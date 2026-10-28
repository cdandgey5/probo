# Probo: rules for every Claude Code session

Probo is an evaluation harness for AI coding agents on mobile (Gradle and
Android) repositories, built as a layer on Harbor. ROADMAP.md is the plan of
record; docs/DESIGN.md holds the decisions; docs/progress.md is the log.

## Read first

1. ROADMAP.md, the Definitions and Run protocol sections, before touching
   anything under `src/probo/grader/`.
2. docs/DESIGN.md. Do not reopen a settled ADR without new evidence; write
   new evidence into docs/ first.
3. docs/progress.md, to see which roadmap package is next and what its done
   check is.

## Working rules

- One roadmap package per session. End by running the package's done check
  and pasting its output into docs/progress.md with the date.
- No API keys in files or chat. No paid agent run without the per-run spend
  cap set (`--ak max_budget_usd=...` for Claude Code).
- Commit at the end of each package with DCO sign-off: `git commit -s`.
- The grader's two known bugs from the prototype have regression tests in
  `tests/test_grade.py` (JUnit 5 names with trailing parentheses, exit
  reasons containing digits). Never remove them.
- `src/probo/grader/grade.py` is copied verbatim into every emitted task
  and runs on the base image's python3: standard library only, no syntax
  newer than Python 3.10, no tomllib.
- Scripts and emitted files are LF. Keep Harbor job output outside OneDrive.
- Harbor is pinned to 0.24.0. Bump checklist: reread Harbor's changelog for
  the separate-verifier, collect-hook and reward-file contracts; run the
  contract tests (`tests/test_task_convert.py`, `tests/test_manifest_report.py`);
  refresh `tests/fixtures/harbor-task-schema-0.24.0.json` from
  `harbor task schema` under the new version's name.

## Commands

```bash
uv sync --all-groups                      # environment, includes harbor and dev tools
uv run ruff format src tests scripts && uv run ruff check src tests scripts
uv run pytest                             # ~1 minute, no JDK needed
uv run probo validate-task tasks/fixtures/pricing-discount
uv run probo convert tasks/fixtures/pricing-discount -o build/harbor-tasks
harbor run -p build/harbor-tasks/pricing-discount -a oracle --dry-run
# With a JDK, an unpacked Gradle 8.14.3 and a warm GRADLE_USER_HOME (see README):
uv run probo grader-selftest build/harbor-tasks/pricing-discount --gradle-dist <dist> --warm-home <home>
uv run probo gate build/harbor-tasks/pricing-discount --gradle-dist <dist> --warm-home <home> --runs 10
```

## Map

- `src/probo/task.py`: schema v0 loading and validation.
- `src/probo/convert.py` and `templates/`: Harbor layout emitter.
- `src/probo/grader/grade.py`: the grader (runs inside the verifier container).
- `src/probo/selftest.py`: grader self-test scenarios and the A/B/C gate on a host JDK.
- `src/probo/manifest.py`, `stats.py`, `report.py`: JSONL flattening, clustered-SE statistics, Markdown reports.
- `src/probo/cli.py`: the `probo` command.
- `tasks/fixtures/pricing-discount`: the pure-Kotlin JVM fixture task.
- `prototype/harbor-gradle-task`: the Phase 0 prototype, frozen; superseded by the converter.
- `docs/`: DESIGN.md, TASK_SCHEMA.md, progress.md, the Harbor verdict, seed-app ranking, MobileDev-Bench research.

## Human-gated items (never do these yourself)

Employer disclosure, WSL2 and Docker Desktop installation, API keys, the
GitHub repository and PyPI name registration, budget approval, the final
seed-app choice. Ask; do not assume they are done.
