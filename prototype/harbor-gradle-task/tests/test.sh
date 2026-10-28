#!/bin/bash
# Grader for the pricing task. Harbor copies tests/ to /tests and runs this
# script from the task working directory (/app), either in a fresh separate
# verifier container (the task.toml default) or in the agent's container.
#
# Reward 1 only if: the fail-to-pass test passes, every pass-to-pass test
# passes, and the agent touched no test source, build file or wrapper file.
# Everything else is 0. A reward file is always written.
#
# The paths below are overridable so the same script can be exercised on a
# developer machine without Docker (see commands.md).
set -uo pipefail

APP_DIR="${APP_DIR:-/app}"
TESTS_DIR="${TESTS_DIR:-/tests}"
OUT_DIR="${OUT_DIR:-/logs/verifier}"
CAPTURE_DIR="${CAPTURE_DIR:-/tmp/harbor-capture}"
GRADLE_BIN="${GRADLE_BIN:-/opt/gradle/dist/bin/gradle}"
RO_CACHE="${RO_CACHE:-/opt/gradle/ro-cache}"
PYTHON="${PYTHON:-python3}"
GRADLE_TIMEOUT_SEC="${GRADLE_TIMEOUT_SEC:-540}"
TMP_ROOT="${TMPDIR:-/tmp}"

TARGET_TEST="com.example.pricing.DiscountCalculatorTest#fullDiscountYieldsZero"
ORIG="$TESTS_DIR/original"
# Files the agent must not touch. Checked by content against ORIG and by path
# in the diff; restored from ORIG before the build runs.
PROTECTED_DIRS="src/test gradle"
PROTECTED_FILES="build.gradle.kts settings.gradle.kts gradle.properties gradlew gradlew.bat"

mkdir -p "$OUT_DIR"
reward=0
exit_reason="infra_error"
mode="unknown"
tampered=""
gradle_rc=""
t0=$(date +%s)

finish() {
  local t1
  t1=$(date +%s)
  echo "$reward" > "$OUT_DIR/reward.txt"
  {
    echo "{"
    echo "  \"reward\": $reward,"
    echo "  \"exit_reason\": \"$exit_reason\","
    echo "  \"verifier_mode\": \"$mode\","
    echo "  \"tampered_files\": \"$(echo $tampered)\","
    echo "  \"gradle_exit_code\": \"$gradle_rc\","
    echo "  \"verify_seconds\": $((t1 - t0))"
    echo "}"
  } > "$OUT_DIR/verdict.json"
  echo "verdict: reward=$reward exit_reason=$exit_reason tampered=[$(echo $tampered)] mode=$mode seconds=$((t1 - t0))"
  exit 0
}

cd "$APP_DIR" || finish

# 1. Bring the agent's change into this tree.
#    Shared container: the working tree already holds the agent's edits.
#    Separate container: the tree is pristine; apply the captured patch.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  mode="shared"
else
  mode="separate"
  patch="$CAPTURE_DIR/agent.patch"
  if [ -s "$patch" ]; then
    if ! git apply --whitespace=nowarn "$patch" > "$OUT_DIR/git-apply.log" 2>&1; then
      exit_reason="patch_failed"
      finish
    fi
  fi
fi

# 2. List changed files against the base commit without touching the real index.
tmp_index="$(mktemp "$TMP_ROOT/harbor-index.XXXXXX")"
GIT_INDEX_FILE="$tmp_index" git read-tree HEAD
GIT_INDEX_FILE="$tmp_index" git add -A
GIT_INDEX_FILE="$tmp_index" git diff --cached --name-only HEAD > "$OUT_DIR/changed-files.txt"
GIT_INDEX_FILE="$tmp_index" git diff --cached --binary HEAD > "$OUT_DIR/agent-diff.patch"
rm -f "$tmp_index"

# 3. Tampering: any protected path in the diff, or any content difference
#    between the live protected files and the pristine copies.
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    src/test/*|gradle/*|build.gradle.kts|settings.gradle.kts|gradle.properties|gradlew|gradlew.bat)
      tampered="$tampered $f" ;;
  esac
done < "$OUT_DIR/changed-files.txt"
for d in $PROTECTED_DIRS; do
  if ! diff -r -q "$ORIG/$d" "$d" > /dev/null 2>&1; then
    case " $tampered " in *" $d/"*) ;; *) tampered="$tampered $d/" ;; esac
  fi
done
for f in $PROTECTED_FILES; do
  if ! cmp -s "$ORIG/$f" "$f"; then
    case " $tampered " in *" $f "*) ;; *) tampered="$tampered $f" ;; esac
  fi
done

# 4. Restore every protected file from the pristine copies and drop any build
#    output that came along, so the build below starts from a known state and
#    never executes agent-written build logic or wrapper code.
for d in $PROTECTED_DIRS; do rm -rf "$d"; cp -r "$ORIG/$d" "$d"; done
for f in $PROTECTED_FILES; do cp "$ORIG/$f" "$f"; done
rm -rf build .gradle .kotlin

# 5. Fresh Gradle home, read-only dependency cache, pinned distribution,
#    offline. Nothing the agent wrote under a Gradle home can reach this build.
GRADLE_USER_HOME="$(mktemp -d "$TMP_ROOT/gradle-home.XXXXXX")"
export GRADLE_USER_HOME
export GRADLE_RO_DEP_CACHE="$RO_CACHE"
timeout -k 10 "$GRADLE_TIMEOUT_SEC" "$GRADLE_BIN" --offline --no-daemon --console=plain --no-build-cache \
  -p "$APP_DIR" test > "$OUT_DIR/gradle-test.log" 2>&1
gradle_rc=$?
rm -rf "$GRADLE_USER_HOME"

# 6. Parse JUnit XML. A listed test that is missing counts as not passed.
"$PYTHON" "$TESTS_DIR/parse_junit.py" "$APP_DIR/build/test-results/test" \
  "$TESTS_DIR/expected-tests.txt" "$TARGET_TEST" > "$OUT_DIR/test-results.json" 2> "$OUT_DIR/parse-junit.err"
target_status=$(sed -n 's/.*"target_status": "\([a-z]*\)".*/\1/p' "$OUT_DIR/test-results.json")
p2p_bad=$(sed -n 's/.*"n_p2p_not_passed": \([0-9]*\).*/\1/p' "$OUT_DIR/test-results.json")
reports=$(sed -n 's/.*"reports": \([0-9]*\).*/\1/p' "$OUT_DIR/test-results.json")

# 7. Verdict. Order matters: tampering and infrastructure problems first.
#    Exit 124 is the timeout wrapper; 137 or a killed test JVM means the
#    container's memory limit hit the build, which is infrastructure, not the
#    agent's fault (the roadmap retries those; Harbor leaves that to the layer).
if [ -n "$tampered" ]; then
  exit_reason="tampered"
elif [ "$gradle_rc" = "124" ]; then
  exit_reason="timeout"
elif [ "$gradle_rc" = "137" ] || grep -q "finished with non-zero exit value 137\|OutOfMemoryError\|Gradle build daemon disappeared" "$OUT_DIR/gradle-test.log"; then
  exit_reason="infra_error"
elif [ "${reports:-0}" = "0" ]; then
  if grep -q "compileTestKotlin" "$OUT_DIR/gradle-test.log" && grep -qi "compilation error\|^e: " "$OUT_DIR/gradle-test.log"; then
    exit_reason="test_compile_failed"
  else
    exit_reason="build_failed"
  fi
elif [ "$target_status" != "passed" ]; then
  if [ ! -s "$OUT_DIR/changed-files.txt" ]; then
    exit_reason="no_diff"
  else
    exit_reason="f2p_failed"
  fi
elif [ "${p2p_bad:-0}" != "0" ]; then
  exit_reason="p2p_failed"
else
  exit_reason="resolved"
  reward=1
fi
finish
