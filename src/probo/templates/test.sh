#!/bin/bash
# Probo grader entry point. Harbor copies tests/ to /tests and runs this
# script from the task working directory, in a fresh verifier container by
# default. All logic lives in grade.py; this wrapper only guarantees that a
# reward file exists even if python3 is missing from the image.
set -u
TESTS_DIR="${TESTS_DIR:-/tests}"
OUT_DIR="${OUT_DIR:-/logs/verifier}"
export TESTS_DIR OUT_DIR
mkdir -p "$OUT_DIR"
if command -v python3 > /dev/null 2>&1; then
  exec python3 "$TESTS_DIR/grade.py"
fi
echo 0 > "$OUT_DIR/reward.txt"
printf '{"reward": 0, "f2p": 0, "p2p": 0, "tampered": 0}\n' > "$OUT_DIR/reward.json"
printf '{"schema": "probo-verdict/1", "reward": 0, "exit_reason": "infra_error", "detail": {"error": "python3 not found in the verifier image"}}\n' > "$OUT_DIR/verdict.json"
echo "verdict: reward=0 exit_reason=infra_error (python3 missing)"
exit 0
