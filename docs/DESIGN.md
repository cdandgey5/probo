# Design: architecture decision records

Status: v1, 2026-10-28. These are the nine strategy decisions from ROADMAP.md
("Strategy decisions recorded as ADRs"), each with the options that were
rejected and why, plus the naming decision. Do not reopen a settled ADR
without new evidence; write new evidence into this directory first.

How to read a record: Context is the question, Decision is what Probo
does, Rejected lists the other options with the reason each lost, Evidence
points at the document that justifies the decision.

## ADR 1: Base framework

**Context.** The harness needs a runner: containers per run, agent adapters,
attempts, concurrency, retries, resume, a verifier stage, result files.

**Decision.** Build on Harbor 0.24.x, pinned (`harbor==0.24.0` in
`pyproject.toml`). Probo is the mobile layer on top: task schema and
converter, the Gradle grader, result flattening, statistics. Decided on
2026-10-17 by the Phase 0 prototype, provisionally, because Docker was not
installed; confirmed on 2026-10-28 by the Harbor contract tests in
`tests/test_task_convert.py` (every emitted `task.toml` validates against
Harbor's schema and loads through Harbor's own `Task` model).

**Rejected.**
- *Standalone runner.* Would re-implement container orchestration, adapters
  with cost capture, attempts, retries, resume, regrade and a viewer, and
  would still want Harbor's layout for interoperability.
- *inspect-ai extension.* Its solver abstraction is the wrong shape for
  black-box CLI agents; its log format is worth reading, nothing more.

**Revisit when.** The nftables check fails on Docker Desktop and no Linux host
or cloud sandbox is available; or a Harbor release breaks the
separate-verifier, collect-hook or reward-file contract and the project
cannot stay pinned. The pinned-version bump checklist is in CLAUDE.md.

**Evidence.** docs/harbor-prototype-verdict.md.

## ADR 2: Task sourcing

**Context.** Where do the tasks come from: a hand-mined pack, an existing
dataset, synthesis, or hand-written tasks?

**Decision.** Import MobileDev-Bench's Android-native subset as the v0.1
volume source (checkpoint G2: yes, resolved 2026-10-28), and hand-mine a
small fresh subset from the seed apps for post-cutoff coverage. Imported
patches are kept as data files with per-repo license notices, never
relicensed; 208 of the 328 Android tasks come from copyleft repositories,
and the public Probo pack itself takes only Apache-2.0 and MIT sources.
Synthesis (SWE-smith style) waits for v0.3.

**Rejected.**
- *Hand-mine only.* A 15-task pack next to a 407-task one is not a
  differentiator; the harness, experiment mode and statistics are.
- *Synthesis first.* Synthetic tasks must never carry headline numbers.

**Evidence.** docs/mobiledev-bench.md (MIT harness, CC-BY-4.0 dataset,
public GHCR images, 309 of 328 Android-native tasks graded by `*UnitTest`
Gradle tasks). docs/seed-apps.md for the fresh subset's sources.

## ADR 3: Grading

**Context.** Hidden tests, an LLM judge, or a rubric?

**Decision.** Deterministic for every headline number: the build succeeds,
the test sources compile, every Fail-to-Pass test passes, every
Pass-to-Pass test passes, no tampering. An LLM judge may appear later only
as a labelled secondary signal, never in the summary table.

**Rejected.** *LLM judge or rubric as a headline.* Reviewers trust tests; a
judged number invites "the judge is biased" and cannot be reproduced.

**Evidence.** `src/probo/grader/grade.py`, the exit-reason precedence in
`decide_exit_reason`, tested in `tests/test_grade.py` and
`tests/test_grade_e2e.py`.

## ADR 4: Agent integration

**Context.** Run agents as black boxes through adapters, or own the agent loop?

**Decision.** Black-box through Harbor's adapters (Claude Code, Codex CLI,
Aider, mini-swe-agent and others), mini-swe-agent as the controlled
reference, and custom Harbor agent classes for the saboteur and for a
generic command template. The point is to evaluate real tools as shipped.

**Rejected.** *Harness-owned agent loop.* It would measure Probo's own
agent, not the tools teams actually run.

**Evidence.** docs/harbor-prototype-verdict.md, section 3.6 (which adapters
report tokens, cost and version).

## ADR 5: Environment

**Context.** How is the repository, the JDK, the Android SDK and the Gradle
cache delivered to a run, reproducibly and offline?

**Decision.** Container per run from layered images: a base image per JDK
with the Android SDK; a per-repo image with the repository at the base
commit (one local commit, no remote), the wrapper distribution, a single
read-only dependency cache (`GRADLE_RO_DEP_CACHE`, no duplicate copy,
distribution zip deleted), Robolectric jars, toolchain auto-provisioning
off, a non-root user; a per-task overlay. Images are published to GHCR and
referenced by digest. The image, not the network, is the source of truth
for a task, because a separate verifier container can see nothing else.
The converter generates this Dockerfile for inline (fixture) repositories
from `src/probo/templates/Dockerfile.inline`.

**Rejected.** *Shared VM.* Cold Gradle builds are the main cost and flake
source, and a shared VM lets one run's state leak into the next.

**Evidence.** docs/harbor-prototype-verdict.md, sections 3.4 and 6.

## ADR 6: New dependencies

**Context.** An agent's fix may add a dependency that offline grading
cannot resolve.

**Decision.** v0.1: tasks whose gold patch adds a dependency are excluded;
grading is offline; an agent-added dependency is a build-file edit, so it
exits `tampered` with the `dependency_added` detail flag and is reported
separately. v0.2: a local Maven mirror or cache proxy baked into the image
so legitimate additions resolve offline, and `dependency_added` promoted to
its own exit reason.

**Rejected.** *Network during grading.* Offline grading is worth more than
coverage of dependency-adding fixes in the first release.

**Evidence.** `find_dependency_additions` in the grader; the
`dependency_added` self-test scenario.

## ADR 7: Network policy

**Context.** An agent with open network can fetch the merged upstream fix
or search for the issue.

**Decision.** Always: git remote stripped, no unreachable refs, agent web
tools disabled where the adapter allows and otherwise declared as a
condition. Agent phase: Harbor's per-phase allowlist of model endpoints once
the nftables kernel check passes on this machine's Docker; public baseline
until then, recorded as a condition in every result. Verifier phase: no
network (`[verifier.environment] network_mode = "no-network"`).

**Rejected.** *Open network.* Information leak. *API-only from day one.*
Depends on a kernel option Docker Desktop's WSL2 kernel may lack
(docs/harbor-prototype-verdict.md, section 4.4).

## ADR 8: Metrics

**Context.** Which number goes in the headline and which interval goes
under it?

**Decision.** Headline: pass@1 averaged over attempts with a 95% interval
from standard errors clustered by task (Miller, "Adding Error Bars to
Evals", 2024). Secondary: per-task consistency histogram, cost per resolved
task, median wall time, exit-reason breakdown. Comparisons use paired
per-task differences with a clustered interval; if the interval includes
zero the report says "no detectable difference". The minimum detectable
difference is printed under every table. No pass^k.

**Rejected.** *pass^3.* One bit per task, near zero at realistic rates.
*Two interval methods.* One method, tested against a hand-computed fixture.

**Evidence.** `src/probo/stats.py` (formulas in the module docstring),
`tests/test_stats.py`.

## ADR 9: Language

**Decision.** Python 3.12 or newer with uv. Harbor's floor is 3.12; SWE-bench
and the statistics tooling are Python. The grader script that runs inside
the verifier image is kept compatible with the base image's python3
(3.10 on Ubuntu 22.04) and uses only the standard library.

**Rejected.** *TypeScript.* Nothing in the ecosystem to reuse.

## Naming decision (2026-10-28)

**Decision.** The project is **Probo** (`probo` on PyPI and as the import,
CLI and repository name), chosen by the author on 2026-10-28 over the
session's first proposal, SeaTrial. Latin *probo*: I test, I prove, I
approve, which is what the harness does to an agent's change.

**Availability, checked 2026-10-28.** `probo` returned 404 on
`pypi.org/pypi/probo/json`; no repository `cdandgey5/probo` existed. Known
neighbours, recorded so nobody is surprised later: the GitHub user `probo`
exists; `getprobo/probo` is an unrelated compliance-automation project
(about 1,500 stars); a GitHub search for the word mostly returns Probot (the
GitHub Apps framework) repositories, so searches should use a qualifier such
as "probo harness" or "probo eval". The PyPI name is the one that has to be
unique, and it is free.

**Rejected.** SeaTrial (free on PyPI and GitHub; the author preferred a
shorter name). Single words all taken on PyPI: drydock, soundings, slipway,
bollard, mooring, berth, keel, fathom, plimsoll, loadline, shakedown,
tidemark, waterline, seamark, evenkeel, freeboard, harbormaster, caliper.
Available but rejected: dockyard (a software consultancy's name), tidegauge,
hullcheck, leadline, pilotage (obscure), droidbench and gradlebench ("bench"
says leaderboard, which is a non-goal; "droid" is a trademark).
