# Probo

Puts AI coding agents' Android changes to the proof. (Latin *probo*: I test, I prove.)

Probo answers one question for a team that runs a coding agent on its own
Android or Gradle repository: **did the agent's change build, pass the hidden
tests and avoid regressions, how often, and at what cost?** It grades every
change in a fresh, key-less, network-less container, flags any attempt to
edit the tests or the build, and reports pass rates with error bars that
respect the fact that attempts of the same task are not independent.

It is a layer on [Harbor](https://github.com/harbor-framework/harbor), which
runs the agents. Probo adds the mobile parts: a task schema and converter,
the Gradle grader, result flattening, and the statistics. It is not a model
leaderboard and not a GUI-agent benchmark.

**Status: pre-alpha, no benchmark numbers yet.** Everything below the
"Verified" line has run; everything under "Not yet" has not. The plan is in
[ROADMAP.md](ROADMAP.md), the decisions in [docs/DESIGN.md](docs/DESIGN.md).

## What runs, and what does not

Verified on 2026-10-28, without Docker, on a Windows host JDK:

- `probo validate-task` and `probo convert` on the fixture task; the
  emitted `task.toml` validates against Harbor 0.24.0's schema and loads
  through Harbor's own task model (contract tests in CI).
- The grader against fourteen synthetic agent behaviours with real Gradle
  (gold patch, no change, wrong fix, test edits with and without a fix, an
  added dependency, a broken build, a deleted class, a replaced wrapper, an
  init script, a CI edit, a `gradle.properties` edit, and two shared-container
  controls), and the task validation gate (states A, B, C). See
  [docs/progress.md](docs/progress.md) for the output.
- 98 unit tests, including a hand-computed statistics fixture.

Not yet: any Harbor trial in a container (Docker is not installed on the
development machine; this is roadmap item H2), any real agent run, any
Android image, any public number.

## How a run works

1. **Agent stage.** Harbor starts a container from the task image. The
   repository sits at `/app` at its base commit with the remote stripped. The
   agent gets the instruction, which names the test command and the files it
   may not touch. Its API key is scoped to its own process.
2. **Capture.** After the agent finishes, a collect hook writes the diff
   against the base commit. Only that diff leaves the agent container.
3. **Grading.** Harbor starts a fresh container from the same image with no
   network and no keys, and runs the grader: apply the diff onto the pristine
   tree, classify every changed path, restore every test, build and CI file
   from pristine copies, overwrite the hidden tests, remove build outputs,
   run only the named Gradle test tasks offline with the image-pinned Gradle
   binary, a fresh `GRADLE_USER_HOME` and a read-only dependency cache, parse
   the JUnit XML, and write the verdict.
4. **Record.** `probo flatten` turns Harbor's per-trial files into one
   JSON line per run; `probo report` and `probo compare` turn those
   into tables with intervals.

Exactly one exit reason per run, in precedence order:

| Exit reason | Meaning |
|---|---|
| `infra_error` | Image, container or verifier failure, including an out-of-memory kill during grading. Retried once through `probo regrade-infra`; still counted if it persists. |
| `timeout` | The agent or the build hit its limit. |
| `agent_error` | The agent crashed or refused. |
| `tampered` | The diff touched a test source set, a Gradle script, `gradle.properties`, a version catalog, the wrapper, an init script, `buildSrc`/`build-logic`, or CI config. An added dependency is reported as a detail. |
| `no_diff` | The agent changed nothing. |
| `build_failed` | Main sources do not compile, or no test report was produced. |
| `test_compile_failed` | Main compiles; the hidden tests do not (usually a renamed symbol). |
| `f2p_failed` | A Fail-to-Pass test still fails. |
| `p2p_failed` | A previously passing test now fails or is missing. |
| `resolved` | Everything passed with no tampering. Reward 1. |

Tampered and failed runs stay in the denominator. Nothing is dropped.

## Quick start

```bash
uv sync --all-groups
uv run probo validate-task tasks/fixtures/pricing-discount
uv run probo convert tasks/fixtures/pricing-discount -o build/harbor-tasks
```

With Docker and a key, one trial of the oracle (gold patch) and of a real
agent, three attempts each (the telemetry variable is Harbor's opt-out):

```bash
export HARBOR_TELEMETRY=off
uv run probo run build/harbor-tasks/pricing-discount -a oracle -k 3 -o ~/harbor-jobs
uv run probo run build/harbor-tasks/pricing-discount -a claude-code -m anthropic/claude-sonnet-5-5 \
  --ak max_turns=30 --ak max_budget_usd=2 --ak disable_web_search=true -k 3 -o ~/harbor-jobs
uv run probo flatten ~/harbor-jobs/* -o results.jsonl
uv run probo report results.jsonl
```

Without Docker, the grader and the task gate run on a host JDK against an
unpacked Gradle distribution and a warm Gradle home (built once):

```bash
curl -sSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-8.14.3-bin.zip
unzip -q /tmp/gradle.zip -d /tmp/gradle-dist
(cd tasks/fixtures/pricing-discount/repo && GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-dist/gradle-8.14.3/bin/gradle --no-daemon test)
uv run probo grader-selftest build/harbor-tasks/pricing-discount --gradle-dist /tmp/gradle-dist/gradle-8.14.3 --warm-home /tmp/gradle-home
uv run probo gate build/harbor-tasks/pricing-discount --gradle-dist /tmp/gradle-dist/gradle-8.14.3 --warm-home /tmp/gradle-home --runs 10
```

## Reference agents

Two agents ship with Probo and run through Harbor's `module:Class` syntax:

- `probo.agents.saboteur:Saboteur` never fixes anything. It edits or deletes
  the tests, disables the test task from a build script, writes an init
  script, or replaces the wrapper (`--ak mode=...`). Every run must grade
  `tampered`; that is the harness's own regression test.
- `probo.agents.command:CommandAgent` runs any command-line tool already in
  the task image from a template, for example
  `--ak command='my-agent --repo {app_dir} --task-file {instruction_file}'`,
  so a team can evaluate its own agent as a black box.

## Statistics

The headline is pass@1 averaged over attempts, with a 95% interval from
standard errors clustered by task (Miller, *Adding Error Bars to Evals*,
2024): between-task variance dominates, so more tasks beat more attempts.
Every table prints the minimum detectable difference under it. `probo
compare` reports paired per-task differences between two result sets; if the
interval includes zero it says "no detectable difference" rather than letting
two means be eyeballed. Cost is reported as Harbor's adapters report it;
when an adapter reports none (Aider) the cost is `null` and labelled missing,
never zero.

## Tasks and their licenses

- `tasks/fixtures/`: harness fixtures, written for Probo.
- v0.1 volume source: the Android-native subset of
  [MobileDev-Bench](https://github.com/MobileDev-Bench/mobiledev-bench) (MIT
  harness, CC-BY-4.0 dataset, public images). `probo import-mdb` turns its
  `data/test.jsonl` into tasks at import time; 230 of the 328 Android rows
  pass the v0.1 rules. The patches are code from the upstream apps and keep
  those apps' licenses, so they are generated locally, never checked in.
  Details in [tasks/mobiledev-bench/README.md](tasks/mobiledev-bench/README.md)
  and [docs/mobiledev-bench.md](docs/mobiledev-bench.md).
- Planned fresh subset: mined from Apache-2.0 or MIT Android apps ranked by
  merged pull requests that touch JVM unit tests
  ([docs/seed-apps.md](docs/seed-apps.md)).

Task format: [docs/TASK_SCHEMA.md](docs/TASK_SCHEMA.md). Authoring, from a
pull request to the gate: [docs/TASK_AUTHORING.md](docs/TASK_AUTHORING.md)
(`probo new-task <pull request URL>` writes the draft).

## Limitations worth knowing

- Windows works as a host: Harbor's CLI and the grader self-test run from
  PowerShell or Git Bash. Docker Desktop on Windows Home needs the WSL2
  feature (`wsl --install --no-distribution` is enough; no Linux shell or
  distro is required). Keep the Harbor jobs directory outside OneDrive.
- Agent-written code runs in the container that holds the agent's API key.
  Use a dedicated low-limit key per benchmark run and rotate it. Grading is
  key-less and offline, so the key never reaches the verifier.
- Harbor sends anonymous command and job summaries to its telemetry by
  default; `HARBOR_TELEMETRY=off` turns it off.
- No-network and allowlist policies on Docker need the nftables FIB option
  in the daemon kernel. Docker Desktop's WSL2 kernel has to be checked
  first; if it lacks the option, grading moves to a Linux host.
- Only JVM tests (unit tests and Robolectric) are verifiable in v0.1.
  Instrumented and Compose UI tests that need an emulator wait for a later
  phase on Linux hosts with KVM.
- Training-data contamination cannot be ruled out for tasks mined from
  public pull requests; results will be split by merge date against each
  model's stated cutoff.

## Repository map

`src/probo/` the package; `tasks/fixtures/` fixture tasks; `tests/` unit
and contract tests; `docs/` design records, task schema, research and the
progress log; `prototype/` the Phase 0 Harbor prototype, kept as the
reference the verdict document cites; `scripts/` data collection.

## License and acknowledgements

Apache-2.0. Built on Harbor (Apache-2.0). Task semantics follow SWE-bench;
the statistics follow Miller (2024); MobileDev-Bench (Fakorede, Upadhyay,
Siddique, Farooq, 2026) is the planned import source. Contributions are
welcome under the Developer Certificate of Origin, see
[CONTRIBUTING.md](CONTRIBUTING.md).
