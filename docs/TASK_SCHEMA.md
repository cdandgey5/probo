# Task schema v0 and the converter

Status: v0, 2026-10-28. The machine-readable schema is
`src/probo/schema/task-v0.schema.json`; `probo validate-task` applies
it plus the semantic checks listed below. This document is the human
reference and the seed of the task authoring guide (roadmap package P3-A).

## A task on disk

```
tasks/<pack>/<task id>/
├── probo.toml       the specification (schema v0)
├── instruction.md      what the agent is told, derived from the issue text
├── gold.patch          the reference fix, applied by Harbor's oracle agent
├── hidden/             files overwritten into the repository before grading,
│   └── <repo path>     mirrored at their repository-relative paths
└── repo/               optional: an inline repository (fixtures only)
```

Real tasks reference a per-repo image instead of an inline repository:
`environment.docker_image = "ghcr.io/<org>/<repo>@sha256:<digest>"` with the
repository at `/app` at the base commit.

## probo.toml

| Section | Field | Meaning |
|---|---|---|
| (root) | `schema_version` | Always `"0"` for this schema. |
| | `id` | Stable task ID, `[a-z0-9-]`, 3 to 64 characters. The directory should carry the same name. |
| | `kind` | `bug_fix` or `small_feature`. Refactors are out (no Fail-to-Pass test). |
| | `difficulty` | Optional label. The measured proxy is the gold patch size, printed by validate-task. |
| | `language` | `kotlin-jvm`, `android-kotlin`, `android-java`, `android-mixed`. |
| | `pack_version` | Semver of the pack the task ships in. |
| `source` | `repo`, `license`, `base_commit` | Upstream repository, SPDX license, pinned commit. |
| | `issue_url`, `pr_url`, `merge_date` | Provenance; merge date drives the contamination split. |
| | `attribution` | One-paragraph task card text. Issue text is user content not covered by the repo license; say so. |
| `environment` | `docker_image`, `repo_dir` or `image_with_repo` | Exactly one. `image_with_repo` is a prebuilt image that already holds the repository (a MobileDev-Bench instance image, say); the converter generates an overlay Dockerfile around it. |
| | `image_repo_path` | Where the repository lives inside `image_with_repo` (default `/app`). |
| | `base_image` | Base for the generated Dockerfile (inline repos only). |
| | `jdk`, `gradle`, `agp` | Toolchain versions, recorded in every result. Optional; validate-task warns when missing. |
| | `cpus`, `memory_mb`, `build_timeout_sec` | Container limits for Harbor. Android builds want 8 to 12 GB. |
| | `agent_user` | Non-root user for the agent phase. Unset until verified on Docker (P0-C). |
| `verification` | `test_tasks` | Fully qualified Gradle task paths, e.g. `:app:testDemoDebugUnitTest`. Only these run. |
| | `results_dirs` | Override of the JUnit XML directories derived from the task paths. |
| | `hidden_tests` | Repository-relative paths overwritten from `hidden/`. Must be test source set paths. |
| | `hidden_patch` | A git-format patch touching only test source sets, applied by the grader onto the restored tree (SWE-bench style). Can be combined with `hidden_tests`. |
| | `test_filters` | Per test task, the `--tests` patterns to pass. Keys must be entries of `test_tasks`; Gradle binds each pattern to the task before it. |
| | `f2p`, `p2p` | Test IDs as `classname#method`, without JUnit 5's trailing `()`. Disjoint. |
| | `agent_timeout_sec`, `verify_timeout_sec` | Harbor phase timeouts. |
| | `gradle_timeout_sec` | The grader's own kill timer; defaults to the verify timeout minus 60 s. |
| | `extra_protected` | Task-level regular expressions whose matches count as build-file tampering. |
| | `test_command` | What the instruction recommends to the agent. |
| | `interface_contract` | Public symbols the hidden tests reference, appended to the instruction. |
| `gold` | `patch` | Path of the gold patch, default `gold.patch`. |

## What validate-task checks without Gradle

Schema conformance, then: exactly one of `docker_image` and `repo_dir`; an
inline repository has `settings.gradle(.kts)` and an LF-only `gradlew` and
no `.git`; the Gradle timeout is shorter than the verify timeout; `f2p` and
`p2p` do not overlap; the instruction exists; every hidden test is listed and
every listed hidden test exists and sits in a test source set; the gold
patch exists, has `diff --git` headers, touches only `main` paths and adds
no dependency; the instruction does not name a file the gold patch touches
(warning, the leak check). The Gradle-backed checks are `probo gate`
(states A, B, C) and `probo grader-selftest`.

## What the converter emits

`probo convert <task> -o <out>` writes `<out>/<id>/` in Harbor's layout:

| Path | Content |
|---|---|
| `instruction.md` | The task instruction, the interface contract when present, and a fixed "Environment and rules" section naming the test command and the protected files. |
| `task.toml` | Harbor schema 1.4. `artifacts = ["/tmp/harbor-capture"]`; `[verifier] environment_mode = "separate"`; `[verifier.environment] network_mode = "no-network"`; a `[[verifier.collect]]` hook that captures the agent's diff; agent and verifier timeouts; `[environment]` limits and `docker_image` when image-based; `[metadata]` with the task ID, pack version, F2P and P2P IDs, test tasks, toolchain versions and source provenance. |
| `environment/Dockerfile`, `environment/repo/` | Inline repositories and image-with-repo tasks (overlay template, no `repo/`): the generated image recipe (base commit, warmed single read-only cache, pinned distribution, offline probes, non-root user). Image-based tasks get a README pointing at the image. |
| `solution/solve.sh`, `solution/gold.patch` | Run by Harbor's oracle agent. |
| `tests/test.sh` | Entry point; runs `grade.py` with python3 or writes a reward 0 / `infra_error` verdict if python3 is missing. |
| `tests/grade.py` | A verbatim copy of `src/probo/grader/grade.py`. |
| `tests/spec.json` | What the grader needs: test tasks, results dirs, F2P, P2P, hidden paths, extra protected patterns, the Gradle timeout, toolchain versions, versions of probo and the grader. |
| `tests/hidden/` | The hidden test files. |
| `tests/hidden.patch` | The hidden test patch, when the task uses one. |
| `tests/original/` | Pristine copies of every test, build and CI file, taken from the inline repository or from `--repo <checkout>`. Optional: the grader restores from git when absent. |

## The grading contract

Inputs the grader reads: the working tree at `/app` (pristine in separate
mode, the agent's in shared mode), `/tmp/harbor-capture/agent.patch` from
the collect hook, `/tests/spec.json`, `/tests/hidden`, `/tests/original`.
Every path is overridable by environment variable (`APP_DIR`, `TESTS_DIR`,
`OUT_DIR`, `CAPTURE_DIR`, `GRADLE_BIN`, `RO_CACHE`, `TMPDIR`,
`GRADLE_TIMEOUT_SEC`) so the same script runs on a developer machine.
`PROBO_SKIP_HIDDEN=1` grades the base tree without the hidden tests or patch
(validation state A).

Outputs in the verifier log directory:

| File | Content |
|---|---|
| `reward.json` | `{"reward": 0 or 1, "f2p": 0 or 1, "p2p": 0 or 1, "tampered": 0 or 1}`. Harbor reads this. |
| `reward.txt` | The reward alone, for tools that expect the text form. |
| `verdict.json` | `exit_reason`, `verifier_mode`, `tampered_files`, `files_by_category`, `diff_stats`, `detail` flags (`dependency_added`, `patch_failed`, `oom`, `timed_out`, `unresolved_dependency`, `suspicious_f2p_pass_without_diff`, `history_rewrite_suspected`, `error`), `gradle` (tasks, exit code, seconds, failed tasks), `tests` (per-test F2P and P2P status, report counts), restored and hidden files, `verify_seconds`, grader and task versions. |
| `test-results.json` | Every test the reports contained, with status. |
| `agent-diff.patch`, `changed-files.txt`, `gradle-test.log`, `git-apply.log` | Evidence. |

Exit reasons, exactly one per run, in precedence order: `infra_error`,
`timeout`, `agent_error` (assigned by the flattener from Harbor's exception
info, never by the grader), `tampered`, `no_diff`, `build_failed`,
`test_compile_failed`, `f2p_failed`, `p2p_failed`, `resolved`. A listed
Pass-to-Pass test missing from the reports counts as not passed.

Tampering categories: test source sets (`src/test*`, `src/androidTest*`,
`sharedTest`, `testFixtures`, Kotlin multiplatform test sets), Gradle build
scripts and any `.gradle(.kts)` file, `settings.gradle(.kts)`,
`gradle.properties`, version catalogs, the wrapper directory, `gradlew`,
`gradlew.bat`, init scripts and `init.d/`, `buildSrc/` and `build-logic/`,
and CI configuration (`.github/`, `.gitlab-ci.yml`, `.circleci/`,
`bitrise.yml`, `Jenkinsfile` and similar). A directory named `gradle`
inside a source set is code, not configuration.

## Result manifest

`probo flatten <job dir>` writes one JSON line per trial with the fields
listed in ROADMAP.md under "Result manifest fields"; `src/probo/manifest.py`
is the reference. Missing values are `null`, never zero; a cost that Harbor
did not report has `cost_source = "missing"`.
