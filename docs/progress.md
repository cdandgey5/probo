# Progress log

One entry per roadmap package, with the package's done check and its output,
dated. Newest first. The package table in ROADMAP.md carries the summary.

## 2026-10-28 (later): P3-C, MobileDev-Bench import adapter

Done check: imported tasks pass the gate; failures logged in the pack
changelog. The adapter and the schema work are done; the gate needs Docker
(the images are linux/amd64, 3.8 to 4.8 GiB compressed each), so the
Gradle-backed half of the check is open until H2.

What ran:

```
probo import-mdb data/test.jsonl -o build/tasks/mobiledev-bench --pack-version 0.1.0
Android rows: 328; importable: 230; public-pack licenses among importable: 77
exclusion reasons: 73 fix_touches_build, 55 fix_adds_dependency,
  51 test_patch_touches_main, 5 test_patch_touches_build, 4 fix_touches_dependency_baseline
per repository (importable / excluded): WordPress-Android 71/13 (GPL-2.0),
  thunderbird-android 65/35 (Apache-2.0), element-x-android 31/37 (AGPL-3.0),
  StreetComplete 15/3, Tusky 11/1, AntennaPod 9/0, apps-android-commons 8/2
  (Apache-2.0), openhab-android 8/0 (EPL-2.0), jerboa 4/0, Voice 3/1,
  medTimer 2/6 (MIT), NeoStumbler 2/0 (MIT), Geto 1/0
probo validate-task build/tasks/mobiledev-bench/*/   -> 230 ok, 0 invalid
```

Warnings worth acting on before any of these enter a pack: `environment.jdk`
and `gradle` are unset on all 230 (the gate fills them from the checkout);
38 gold patches also touch non-source files (changelog fragments, SVG assets,
a lint config), allowed but listed; 4 StreetComplete instructions name a file
the gold patch touches (the leak check), to be reread by hand.

Unit tests: 108 passed. The emitted overlay Dockerfile for
`tuskyapp--tusky-2713` starts `FROM ghcr.io/mobiledev-bench/mobiledevbench/tuskyapp_mb_tusky:pr-2713`,
links `/home/Tusky` to `/app`, deletes `/home/fix.patch`, and runs
`:app:testBlueDebugUnitTest --tests com.keylesspalace.tusky.FilterTest`
offline in both probes. Not built: no Docker.

## 2026-10-28: naming, P0-B, and the Docker-independent parts of P1-B, P1-D, P2-B

Session type: autonomous build from the roadmap (v2.2 to v2.3). Machine:
Windows 11 Home, no Docker or WSL2 (re-checked), Harbor 0.24.0, JDK 21,
Gradle 8.14.3 fetched to a scratch directory and a Gradle home warmed by
building the fixture once.

### Name (H4, the part Claude can do)

Probo, `probo`, chosen by the author over the session's first proposal,
SeaTrial. Checks on 2026-10-28: `https://pypi.org/pypi/probo/json` returned
404 (free); `cdandgey5/probo` did not exist. Neighbours: the GitHub user
`probo` exists, `getprobo/probo` is an unrelated compliance project, and
GitHub search for the word is dominated by Probot. Candidate list and the
rejected names in docs/DESIGN.md. The repository `cdandgey5/probo` was
created and pushed at the end of the session.

### P0-B: done

Done check: files exist; ranking table cites PR counts; G2 recorded.

- docs/DESIGN.md: nine ADRs with rejected options, plus the naming record.
- Task schema v0: `src/probo/schema/task-v0.schema.json`, docs/TASK_SCHEMA.md,
  `probo validate-task`, `probo convert`.
- docs/seed-apps.md with docs/data/seed-apps.json (1.1 MB of raw API data)
  and `scripts/collect_seed_apps.py`: twelve candidates, merged PRs in the
  last 12 months from the search API, a 150-PR GraphQL sample per repository
  for the fraction touching JVM unit tests. Apache-2.0 leaders by estimated
  12-month JVM-test PRs: DuckDuckGo Android 1,726; Home Assistant Android 265;
  Thunderbird 239; Wikipedia 138; Commons 47; Open Food Facts 1; Mihon 0.
- docs/mobiledev-bench.md: **G2 = yes.** Harness MIT, dataset CC-BY-4.0,
  images public on GHCR, 328 Android-native tasks, 309 graded by `*UnitTest`
  tasks, 208 from copyleft upstream apps (kept as labelled data).
- CLAUDE.md written; git initialized with a repo-local identity and DCO
  sign-off on the first commit.

### P1-B: done for the JVM fixture, without Docker

Done check: every fixture branch returns its expected exit reason; every
emitted task passes a Harbor dry run.

`probo grader-selftest build/harbor-tasks/pricing-discount` with Gradle
8.14.3 on JDK 21 (fourteen scenarios, separate-verifier mode unless noted):

```
oracle             PASS  reward=1 (want 1)  exit_reason=resolved             (want resolved          )   50.9s
nop                PASS  reward=0 (want 0)  exit_reason=no_diff              (want no_diff           )   48.6s
comment_only       PASS  reward=0 (want 0)  exit_reason=f2p_failed           (want f2p_failed        )   47.7s
tamper_tests       PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   49.1s
tamper_and_fix     PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   50.4s
dependency_added   PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   50.1s
break_build        PASS  reward=0 (want 0)  exit_reason=build_failed         (want build_failed      )   38.6s
delete_main        PASS  reward=0 (want 0)  exit_reason=test_compile_failed  (want test_compile_failed)   37.9s
replace_gradlew    PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   44.0s
init_script        PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   43.1s
ci_edit            PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   44.5s
properties_edit    PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   45.6s
oracle_shared      PASS  reward=1 (want 1)  exit_reason=resolved             (want resolved          )   44.7s
tamper_shared      PASS  reward=0 (want 0)  exit_reason=tampered             (want tampered          )   45.6s
--- summary: 14 passed, 0 failed ---
```

The `dependency_added` scenario also checks the detail flag; PASS means it
was set. Grading time on the host is 38 to 51 seconds per run for the
one-module Kotlin project, consistent with the prototype's 45 seconds.

Harbor dry run: `harbor run -p build/harbor-tasks/pricing-discount -a oracle --dry-run`
loads the task and stops at "Docker is not installed or not on PATH", as the
prototype did. The task-model contract is covered in CI without Docker:
`tests/test_task_convert.py` validates the emitted `task.toml` against
Harbor's schema snapshot and loads it through `harbor.models.task.task.Task`.

Open for P1-B: the Android fixture module (needs the base image, P1-A) and a
Harbor dry run on a runner with Docker.

### Validation gate (the Phase 3 gate, run early on the fixture)

`probo gate build/harbor-tasks/pricing-discount --runs 2`:

```
state A run 1: exit_reason=no_diff f2p={...fullDiscountYieldsZero: 'missing'} p2p_not_passed=[] 48.6s
state B run 1: exit_reason=no_diff f2p={...fullDiscountYieldsZero: 'failed'}  p2p_not_passed=[] 48.6s
state C run 1: exit_reason=resolved f2p={...fullDiscountYieldsZero: 'passed'} p2p_not_passed=[] 48.4s
state A run 2: exit_reason=no_diff f2p={...fullDiscountYieldsZero: 'missing'} p2p_not_passed=[] 48.4s
state B run 2: exit_reason=no_diff f2p={...fullDiscountYieldsZero: 'failed'}  p2p_not_passed=[] 50.9s
state C run 2: exit_reason=resolved f2p={...fullDiscountYieldsZero: 'passed'} p2p_not_passed=[] 50.1s
--- gate: PASS (2 run(s) per state) ---
```

The roadmap's gate uses ten runs per state; the CI job runs one, and the
command takes `--runs 10` for a task entering a pack.

### P1-D: done against a saved Harbor trial layout

Done check: a Harbor job produces the JSONL manifest and a rendered report.

Without Docker there is no real job yet, so `tests/test_manifest_report.py`
builds a four-trial job directory in Harbor 0.24.0's layout (two Claude Code
trials, one resolved and one tampered with an estimated cost; two Aider
trials, one failed with no cost and one agent timeout with no verdict),
validates every `result.json` against Harbor's `TrialResult` model, flattens
it, and renders the report and the comparison. Open: the same against a real
job after P0-C.

### P2-B: statistics module and compare, done; pilot open

`src/probo/stats.py` with the hand-computed fixture in
`tests/test_stats.py` (four tasks, three attempts: mean 0.5, clustered SE
sqrt(5)/12; paired difference 1/12 with SE 0.1596, interval including zero,
MDD 0.447). The pilot needs H2, H3 and H5.

### Unit tests and lint

`uv run ruff check src tests scripts`: all checks passed.
`uv run pytest`: 98 passed in about 70 seconds.

### Next

- Without Docker: P3-C, the MobileDev-Bench import adapter (dataset rows to
  `probo.toml` tasks referencing the published GHCR images).
- After H2 (WSL2 and Docker Desktop): the nftables check (G1), then P0-C
  against `build/harbor-tasks/pricing-discount`: image build time and size,
  oracle, no-op and tamper trials through Harbor, resume, regrade, one paid
  Claude Code run with the spend cap.
- The user's items: H1 disclosure, H2, H3 keys, H4 push, H5 budget, H6
  seed-app pick (Claude's ranking: Home Assistant Android, then DuckDuckGo,
  with Thunderbird as the alternate).
