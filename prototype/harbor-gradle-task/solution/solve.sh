#!/bin/bash
# Oracle solution: apply the gold patch to the repository.
# Harbor copies solution/ to /solution and runs this from the task workdir.
set -euo pipefail
cd "${APP_DIR:-/app}"
git apply --verbose "${SOLUTION_DIR:-/solution}/fix.patch"
