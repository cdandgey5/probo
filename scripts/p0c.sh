#!/bin/bash
# Package P0-C from ROADMAP.md: the prototype verification list, run against
# the converter's output for the fixture task, in one go. Needs Docker
# reachable, Python 3.12 with uv, and this repository's environment
# (`uv sync --all-groups`). Runs from Git Bash on Windows or any Linux shell.
#
#   bash scripts/p0c.sh                 # jobs under C:/harbor-jobs (Windows) or ~/harbor-jobs
#   JOBS=/mnt/d/harbor-jobs bash scripts/p0c.sh
#
# The paid Claude Code run is deliberately not here; see the end of the output.
set -uo pipefail
cd "$(dirname "$0")/.."

TASK_SRC="tasks/fixtures/pricing-discount"
TASK="build/harbor-tasks/pricing-discount"
IMAGE="probo-pricing-discount:p0c"
if [ -z "${JOBS:-}" ]; then
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) JOBS="C:/harbor-jobs" ;; *) JOBS="$HOME/harbor-jobs" ;; esac
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="build/p0c-$STAMP"
mkdir -p "$OUT" "$JOBS"
export HARBOR_TELEMETRY="${HARBOR_TELEMETRY:-off}"

say() { printf '\n=== %s ===\n' "$*"; }
record() { printf '%s\n' "$*" | tee -a "$OUT/summary.txt"; }

say "0. Docker and the kernel check (section 4.4 of the prototype verdict)"
docker info > "$OUT/docker-info.txt" 2>&1 || { echo "docker info failed; is Docker Desktop running?"; exit 2; }
record "docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
kernel="$(docker run --rm alpine sh -c 'zcat /proc/config.gz 2>/dev/null | grep NFT_FIB_INET || echo NO-MATCH-OR-NO-CONFIG' 2>&1 | tail -1)"
record "nftables check (G1): $kernel"

say "1. Convert the fixture task"
uv run probo convert "$TASK_SRC" -o build/harbor-tasks | tee -a "$OUT/summary.txt"

say "2. Image build time and size (docker build, outside Harbor, for the record)"
t0=$(date +%s)
docker build -t "$IMAGE" "$TASK/environment" > "$OUT/docker-build.log" 2>&1
rc=$?
t1=$(date +%s)
record "image build: exit $rc, $((t1 - t0)) s, size $(docker image inspect "$IMAGE" --format '{{.Size}}' 2>/dev/null || echo '?') bytes"
[ "$rc" = 0 ] || { echo "image build failed; see $OUT/docker-build.log"; exit 3; }

run_agent() {  # name, then harbor agent args
  local name="$1"; shift
  say "run $name"
  t0=$(date +%s)
  uv run probo run "$TASK" "$@" -o "$JOBS" --job-name "p0c-$name-$STAMP" > "$OUT/run-$name.log" 2>&1
  local rc=$?
  t1=$(date +%s)
  record "harbor run $name: exit $rc, $((t1 - t0)) s, job $JOBS/p0c-$name-$STAMP"
  tail -5 "$OUT/run-$name.log"
}

say "3. Oracle (expect reward 1, resolved, verifier mode separate), three attempts"
run_agent oracle -a oracle -k 3 -n 1
say "4. No-op (expect reward 0, no_diff), three attempts"
run_agent nop -a nop -k 3 -n 1
say "5. Saboteur (expect reward 0, tampered naming the test file)"
run_agent saboteur -a probo.agents.saboteur:Saboteur --ak mode=edit_tests -k 1 -n 1

say "6. Flatten and report"
uv run probo flatten "$JOBS"/p0c-oracle-"$STAMP" "$JOBS"/p0c-nop-"$STAMP" "$JOBS"/p0c-saboteur-"$STAMP" -o "$OUT/results.jsonl" | tee -a "$OUT/summary.txt"
uv run probo report "$OUT/results.jsonl" -o "$OUT/report.md" | tee -a "$OUT/summary.txt"
uv run python - "$OUT/results.jsonl" <<'PY' | tee -a "$OUT/summary.txt"
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
for r in rows:
    print(f"{r['agent_name']:<10} reward={r['reward']} exit={r['exit_reason']:<12} verifier={r['verifier_mode_harbor']} "
          f"tampered={r['tampered_files']} setup={r['environment_setup_sec']}s agent={r['agent_execution_sec']}s verify={r['verifier_sec']}s")
PY

say "7. Regrade the oracle job (expect only the verifier to rerun)"
t0=$(date +%s)
uv run harbor job regrade "$JOBS/p0c-oracle-$STAMP" -p "$TASK" > "$OUT/regrade.log" 2>&1
rc=$?
t1=$(date +%s)
record "harbor job regrade: exit $rc, $((t1 - t0)) s"
tail -5 "$OUT/regrade.log"

say "Done. Summary in $OUT/summary.txt; report in $OUT/report.md"
cat "$OUT/summary.txt"
cat <<EOF

Still manual, from the verdict's list:
  8. Resume: start 'uv run probo run $TASK -a oracle -k 3 -o $JOBS --job-name resume-test',
     kill it mid-way (Ctrl+C), then 'uv run harbor job resume -p $JOBS/resume-test'.
  9. One paid Claude Code run, only with a dedicated low-limit key in ANTHROPIC_API_KEY:
     uv run probo run $TASK -a claude-code -m anthropic/claude-sonnet-5-5 \\
       --ak max_turns=30 --ak max_budget_usd=2 --ak disable_web_search=true -k 1 -o $JOBS --job-name claude-code
     Then flatten the job and check agent_version, cost_usd and the token counts.
Paste summary.txt into docs/progress.md under a P0-C heading.
EOF
