# Changelog

All notable changes to Probo. The format follows Keep a Changelog; the
project is pre-release, so every entry sits under Unreleased until v0.1.0.

## Unreleased

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
