# Changelog

All notable changes to Probo. The format follows Keep a Changelog; the
project is pre-release, so every entry sits under Unreleased until v0.1.0.

## Unreleased

### Added (2026-10-28, package P3-A)

- `probo new-task <pull request URL>`: drafts a task from a merged GitHub
  pull request through `gh api`. Base commit from the merge commit's first
  parent, instruction from the linked issue only, the diff split into
  `gold.patch` (main sources) and `hidden.patch` (tests), Gradle test tasks
  and class filters from the touched modules, Fail-to-Pass candidates from
  the new `@Test` methods, an interface contract from the declarations the
  fix adds that the tests reference, toolchain versions from the wrapper
  and version catalog, and a NOTES.md of what still needs a human.
- docs/TASK_AUTHORING.md: candidate selection, the draft, the hand finish,
  the gate, and how imported tasks fit.

### Added (2026-10-28, package P3-C)

- `probo import-mdb`: imports the Android-native subset of MobileDev-Bench
  from its `data/test.jsonl` into Probo tasks that reference the published
  GHCR instance images. Of 328 Android rows, 230 pass the v0.1 rules (77 from
  Apache-2.0 or MIT sources); every decision is recorded in
  docs/data/mobiledev-bench-import.json. Tasks are generated at import time,
  never checked in (upstream licenses).
- Task schema: `verification.hidden_patch` (a test patch applied at grade
  time, SWE-bench style), `verification.test_filters` (per-task `--tests`
  patterns), `environment.image_with_repo` plus `image_repo_path` (overlay
  on an image that already holds the repository); `jdk` and `gradle` are
  optional until the gate fills them; test IDs may carry parameterized
  display names.
- Grader: applies `tests/hidden.patch` after restoring protected files,
  binds `--tests` filters to their task, honours `PROBO_SKIP_HIDDEN` for
  validation state A; `probo gate` uses it.
- Converter: `Dockerfile.overlay` template for image-with-repo tasks. It
  deletes the gold patch MobileDev-Bench bakes into `/home`, replaces the
  upstream `.git` (whose history contains the fix) with a one-commit
  repository at `/app`, reuses the image's warmed Gradle cache, and builds
  the read-only cache layout.
- docs/mobiledev-bench-images.md: how the upstream images are built and run,
  from the harness source and the registry.

### Added (2026-10-28)

- Project name: Probo (`probo`), free on PyPI; chosen by the author over the first proposal, SeaTrial.
- Task schema v0 (`probo.toml`, JSON Schema in `src/probo/schema/`) with
  `probo validate-task`: schema, gold-patch, hidden-test and leak checks.
- `probo convert`: emits Harbor's task layout (separate key-less verifier,
  no-network grading, diff-capturing collect hook, generated Dockerfile for
  inline repositories, pristine copies of protected files).
- The grader (`src/probo/grader/grade.py`): applies the captured diff onto
  a pristine tree, classifies changed paths, flags tampering and added
  dependencies, restores protected files, overwrites hidden tests, runs only
  the named Gradle test tasks offline with a fresh `GRADLE_USER_HOME` and a
  read-only cache, parses JUnit XML, classifies the Gradle log, and writes
  `reward.json` plus `verdict.json` with exactly one exit reason.
- `probo grader-selftest` (fourteen agent-behaviour scenarios) and
  `probo gate` (validation states A, B, C) on a host JDK without Docker.
- `probo flatten`, `report`, `compare`, `run`, `regrade-infra`: JSONL
  result manifests, Markdown reports with clustered standard errors and the
  minimum detectable difference, paired comparisons, a thin wrapper over
  `harbor run` that records host facts, and the infra-error regrade policy.
- Fixture task `tasks/fixtures/pricing-discount` (pure-Kotlin JVM, hidden
  Fail-to-Pass test).
- Harbor 0.24.0 contract tests: emitted `task.toml` validates against Harbor's
  schema snapshot and loads through Harbor's task model; the sample trial
  result validates against Harbor's `TrialResult`.
- docs/DESIGN.md (nine ADRs and the naming decision), docs/TASK_SCHEMA.md,
  docs/seed-apps.md (GitHub API ranking of twelve candidate apps),
  docs/mobiledev-bench.md (import feasibility: yes), CLAUDE.md, CI workflow.
