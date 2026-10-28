#!/bin/bash
# Exercise tests/test.sh on a developer machine without Docker.
#
# It builds the same situations Harbor would hand the grader (a pristine
# clone of the repo plus a captured agent patch) and checks the reward and
# exit reason for each. Gradle runs with the pinned distribution, a fresh
# GRADLE_USER_HOME per run and a read-only copy of a warm dependency cache,
# exactly as in the container.
#
# usage: validate-grader.sh GRADLE_DIST WARM_HOME [WORK_DIR]
#   GRADLE_DIST  unpacked gradle-8.14.3 directory (contains bin/gradle)
#   WARM_HOME    a GRADLE_USER_HOME that has already built environment/repo once
#   WORK_DIR     scratch directory (default: a fresh temp dir)
# needs: JDK 17+ on PATH, git, python 3 (as `python` or `python3`), bash.
set -uo pipefail

TASK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GRADLE_DIST="${1:?unpacked Gradle distribution directory}"
WARM_HOME="${2:?warm GRADLE_USER_HOME}"
WORK="${3:-$(mktemp -d)}"
mkdir -p "$WORK"

# Gradle is a native Windows process under Git Bash, so hand it mixed-style
# paths (C:/...). cygpath exists on Git Bash and MSYS; elsewhere paths pass
# through unchanged.
winpath() { if command -v cygpath > /dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }
PYTHON_BIN="python3"; command -v python3 > /dev/null 2>&1 || PYTHON_BIN="python"

echo "task dir : $TASK_DIR"
echo "work dir : $WORK"
echo "java     : $(java -version 2>&1 | head -1)"

# Pristine repository at its base commit, as the Dockerfile builds it.
rm -rf "$WORK/pristine"
cp -r "$TASK_DIR/environment/repo" "$WORK/pristine"
( cd "$WORK/pristine" && rm -rf build .gradle .kotlin \
  && git init -q -b main && git config user.email task@example.invalid && git config user.name task \
  && git config core.autocrlf false && git add -A && git commit -q -m base )

# Read-only dependency cache carved out of the warm home, as in the Dockerfile.
rm -rf "$WORK/ro-cache"; mkdir -p "$WORK/ro-cache"
cp -r "$WARM_HOME/caches/modules-2" "$WORK/ro-cache/"
find "$WORK/ro-cache" -name '*.lock' -delete
rm -f "$WORK/ro-cache/modules-2/gc.properties"
mkdir -p "$WORK/tmp"

# Patches for the scenarios.
mkdir -p "$WORK/patches"
cp "$TASK_DIR/solution/fix.patch" "$WORK/patches/oracle.patch"
: > "$WORK/patches/nop.patch"
make_patch() {  # name, then a shell snippet applied inside a scratch clone
  local name="$1"; shift
  rm -rf "$WORK/scratch"; cp -r "$WORK/pristine" "$WORK/scratch"
  ( cd "$WORK/scratch" && eval "$*" && git add -A && git diff --cached --binary HEAD ) > "$WORK/patches/$name.patch"
}
TAMPERED_TEST='package com.example.pricing

import kotlin.test.Test
import kotlin.test.assertTrue

class DiscountCalculatorTest {
    @Test fun halfDiscountHalvesPrice() = assertTrue(true)
    @Test fun fullDiscountYieldsZero() = assertTrue(true)
    @Test fun zeroDiscountKeepsPrice() = assertTrue(true)
    @Test fun negativePercentIsClampedToZero() = assertTrue(true)
    @Test fun negativePriceIsRejected() = assertTrue(true)
}
'
export TAMPERED_TEST
make_patch tamper 'printf "%s" "$TAMPERED_TEST" > src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt'
make_patch tamper_and_fix 'printf "%s" "$TAMPERED_TEST" > src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt && git apply "$TASK_DIR/solution/fix.patch"'
make_patch build_tamper 'git apply "$TASK_DIR/solution/fix.patch" && printf "\ndependencies { testImplementation(\"org.assertj:assertj-core:3.27.3\") }\n" >> build.gradle.kts'
make_patch wrong_fix 'sed -i "s/coerceIn(0, 99)/coerceIn(0, 98)/" src/main/kotlin/com/example/pricing/DiscountCalculator.kt'
make_patch break_build 'printf "\nval oops = \n" >> src/main/kotlin/com/example/pricing/DiscountCalculator.kt'

pass=0; fail=0
run_scenario() {  # name expected_reward expected_reason [shared]
  local name="$1" want_reward="$2" want_reason="$3" shared="${4:-}"
  local work="$WORK/run-$name"
  rm -rf "$work"; cp -r "$WORK/pristine" "$work"
  mkdir -p "$work.capture" "$work.out"
  if [ -n "$shared" ]; then
    # shared mode: the tree itself is dirty, nothing is captured
    ( cd "$work" && git apply "$WORK/patches/$name.patch" )
    : > "$work.capture/agent.patch"
  else
    cp "$WORK/patches/$name.patch" "$work.capture/agent.patch"
  fi
  local t0; t0=$(date +%s)
  APP_DIR="$(winpath "$work")" TESTS_DIR="$(winpath "$TASK_DIR/tests")" OUT_DIR="$(winpath "$work.out")" \
  CAPTURE_DIR="$(winpath "$work.capture")" GRADLE_BIN="$GRADLE_DIST/bin/gradle" RO_CACHE="$(winpath "$WORK/ro-cache")" \
  PYTHON="$PYTHON_BIN" TMPDIR="$(winpath "$WORK/tmp")" \
    bash "$TASK_DIR/tests/test.sh" > "$work.out/test-stdout.txt" 2>&1
  local t1; t1=$(date +%s)
  local reward reason
  reward=$(cat "$work.out/reward.txt" 2>/dev/null || echo "missing")
  reason=$(sed -n 's/.*"exit_reason": "\([a-z0-9_]*\)".*/\1/p' "$work.out/verdict.json" 2>/dev/null)
  local verdict="FAIL"
  if [ "$reward" = "$want_reward" ] && [ "$reason" = "$want_reason" ]; then verdict="PASS"; pass=$((pass+1)); else fail=$((fail+1)); fi
  printf "%-16s %-4s reward=%s (want %s)  exit_reason=%-20s (want %-18s) %3ss\n" "$name" "$verdict" "$reward" "$want_reward" "$reason" "$want_reason" "$((t1-t0))"
  if [ "$verdict" = "FAIL" ]; then tail -5 "$work.out/test-stdout.txt"; tail -15 "$work.out/gradle-test.log" 2>/dev/null; fi
}

echo "--- scenarios (separate-verifier mode unless noted) ---"
run_scenario oracle 1 resolved
run_scenario nop 0 no_diff
run_scenario tamper 0 tampered
run_scenario tamper_and_fix 0 tampered
run_scenario build_tamper 0 tampered
run_scenario wrong_fix 0 f2p_failed
run_scenario break_build 0 build_failed
echo "--- shared-verifier mode (dirty working tree, no capture) ---"
cp "$WORK/patches/oracle.patch" "$WORK/patches/oracle_shared.patch"; run_scenario oracle_shared 1 resolved shared
cp "$WORK/patches/tamper.patch" "$WORK/patches/tamper_shared.patch"; run_scenario tamper_shared 0 tampered shared
echo "--- summary: $pass passed, $fail failed ---"
[ "$fail" = 0 ]
