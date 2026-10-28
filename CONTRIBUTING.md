# Contributing to Probo

Thank you for considering it. Probo is pre-alpha; the roadmap in
ROADMAP.md says what is being built in which order, and docs/progress.md says
where things stand.

## Developer Certificate of Origin

Every commit must be signed off (`git commit -s`), which adds a
`Signed-off-by: Name <email>` line certifying the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Commits without it are not merged. This keeps provenance clean for a project
that may later be adopted inside companies.

## Setup

```bash
uv sync --all-groups
uv run ruff format src tests scripts && uv run ruff check src tests scripts
uv run pytest
```

The unit tests need Python 3.12, git and nothing else. The Gradle-backed
checks (`probo grader-selftest`, `probo gate`) need a JDK 17 or newer,
an unpacked Gradle distribution matching the task, and a warm
`GRADLE_USER_HOME`; the README shows the commands. Docker and Harbor are
needed only to run agents.

## What to contribute

- **Tasks.** Read docs/TASK_SCHEMA.md. A task pull request must pass
  `probo validate-task`, and the Gradle gate (states A, B, C, ten runs
  each) must pass before the task enters a pack. Only Apache-2.0 and MIT
  source repositories qualify for the public pack. Instructions come from the
  issue text, never from the pull request that fixed it.
- **Adapters and graders.** Harbor owns the agent adapters; Probo adds
  mobile-specific graders. Propose a grader with the exit reason it adds and
  the fixture scenario that proves it.
- **Bugs in the grader.** The grader is a measuring instrument. A fix comes
  with a regression test in `tests/test_grade.py` or a scenario in
  `src/probo/selftest.py`.

## Style

Python 3.12, ruff for formatting and linting (110 columns), type hints on
public functions, docstrings that say what and why. `grade.py` is the
exception: it must run on the base image's python3 (3.10) and stays standard
library only.
