# MobileDev-Bench import

The Android-native subset of MobileDev-Bench (Fakorede, Upadhyay, Siddique
and Farooq, arXiv 2603.24946, 2026) is Probo's v0.1 volume source. The tasks
are not checked in: the dataset is CC-BY-4.0, but every gold patch and hidden
test patch is code from one of thirteen upstream apps under its own license
(Apache-2.0, MIT, GPL-2.0, GPL-3.0, AGPL-3.0, EPL-2.0), so Probo generates
the task directories at import time, labels each with its upstream license,
and keeps them out of the repository. docs/mobiledev-bench.md has the
licensing analysis; docs/data/mobiledev-bench-import.json records every
import decision (no code, only metadata).

## Import

```bash
curl -sSL -o /tmp/mdb-test.jsonl https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/resolve/main/data/test.jsonl
uv run probo import-mdb /tmp/mdb-test.jsonl -o build/tasks/mobiledev-bench --pack-version 0.1.0
uv run probo validate-task build/tasks/mobiledev-bench/*
uv run probo convert build/tasks/mobiledev-bench/<task id> -o build/harbor-tasks
```

`--public-pack-only` keeps only Apache-2.0 and MIT sources (Thunderbird,
Wikimedia Commons, medTimer, NeoStumbler). `--all` also writes the rows that
fail the v0.1 import rules, for inspection.

## What the importer does with a row

| Dataset field | Task file or field |
|---|---|
| `problem_statement` (the linked issue) | `instruction.md`. `hints` (pull-request comments) are never used: they can name the fix. |
| `fix_patch` | `gold.patch` |
| `test_patch` | `hidden.patch`, applied by the grader onto the restored tree |
| `test_command` | `verification.test_tasks` and `test_filters` (`--tests` patterns bound to their task); `test_command` with `--offline` added |
| `f2p_tests`, `n2p_tests`, `s2p_tests` | `verification.f2p` as `classname#name` (tests missing or skipped at base that pass after the fix are Fail-to-Pass) |
| `p2p_tests` | `verification.p2p`, minus anything already in `f2p` |
| `base.sha`, `pull_url`, `issue_urls[0]` | `source.base_commit`, `source.pr_url`, `source.issue_url` |
| `org`, `repo`, `number` | `environment.image_with_repo` (the published GHCR instance image) and the task ID `org--repo-number` |

The v0.1 rules exclude a row when its fix patch touches a build, test or CI
file or adds a dependency, when its test patch touches anything outside a test
source set, when the command names no Gradle task, or when it has no
Fail-to-Pass test. The reasons are in the manifest.

## Before an imported task enters a pack

The converter wraps the published instance image in an overlay Dockerfile
(`src/probo/templates/Dockerfile.overlay`) that adds git and python3, makes
the checkout a one-commit repository at `/app`, warms a single read-only
dependency cache and pins the Gradle distribution. That needs Docker, and so
does the validation gate (states A, B, C, ten runs each). Both wait for
roadmap item H2 on the development machine; `environment.jdk` and
`environment.gradle` are filled from the repository at the base commit once
the gate runs.
