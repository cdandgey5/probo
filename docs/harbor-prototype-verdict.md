# Harbor prototype verdict

Date: 2026-10-17. Harbor version studied: 0.24.0 (PyPI release installed with
`uv tool install harbor`; repository `harbor-framework/harbor`, last push the
same day). Task prototype: `prototype/harbor-gradle-task/`. Commands:
`prototype/harbor-gradle-task/commands.md`.

## Bottom line

**Recommendation: build on Harbor.** Its current release already has the
three things the roadmap's Base framework ADR said to check for, and one more
the roadmap scheduled for v0.2:

1. The verifier can run in a **separate, key-less, network-less container**
   built from the same image (`[verifier] environment_mode = "separate"` plus
   `[verifier.environment] network_mode = "no-network"`). Only declared
   artifacts cross from the agent sandbox to the grader.
2. `tests/test.sh` is an ordinary shell script run inside that container, so a
   **fresh `GRADLE_USER_HOME`**, a read-only dependency cache, test-source
   reset and hidden-test overwrite are all under the task author's control.
   The prototype's grader does all of them and was exercised locally.
3. The **Claude Code, Codex, OpenHands and mini-swe-agent adapters report
   tokens and cost**; every adapter records the agent's version. Aider reports
   neither tokens nor cost (its adapter leaves the context empty), which the
   roadmap already allows for ("missing, never zero": Harbor uses `None`).
4. Harbor's egress-control sidecar gives **allowlisted agent networking** per
   phase, which is the v0.2 "egress proxy allowlisted to model endpoints".

Also free on Harbor: N attempts per task (`-k`), bounded parallelism (`-n`),
retries with an exclude list (`-r`), resume of a crashed job
(`harbor job resume`), regrading recorded trials with a new verifier
(`harbor job regrade`, which needs exactly the separate-verifier setup above),
a trajectory viewer, cloud sandboxes, and an oracle and a no-op agent.

**The verdict is provisional.** Docker is not installed on this PC (section
1), so no container was built and no Harbor trial ran. The evidence is Harbor's
installed source code, its documentation, Harbor's own task model loading the
prototype task, a `--dry-run` that reaches the Docker preflight, and the
grader script passing nine synthetic scenarios on the host JDK. Section 8 lists
what still has to be confirmed once Docker exists; none of it looks like a
blocker, but one item (nftables support in Docker Desktop's kernel) could force
a change of sandbox backend.

License: **Apache-2.0**, read from the repository's `LICENSE` file (the full
Apache 2.0 text), the GitHub API license field and PyPI's
`license_expression`. The roadmap's note that third-party listings say MIT
was right to distrust them.

## 1. Prerequisites: what is missing, how to set it up

Checked with commands on 2026-10-17:

| Requirement | Found |
|---|---|
| Docker daemon (`docker info`) | **Missing.** `docker` is not on `PATH` in PowerShell or Git Bash, Docker Desktop is not under `C:\Program Files\Docker`, the engine pipe `\\.\pipe\docker_engine` does not exist, no docker service or process. |
| WSL2 | **Missing.** `wsl --status` reports it is not installed. |
| Podman, Rancher Desktop | Missing. |
| Python 3.11+ | Python 3.12.10 (Harbor needs 3.12 or newer). |
| uv or pipx | uv 0.13.1. pipx absent, not needed. |
| Harbor | Installed by this session: `uv tool install harbor` gave 0.24.0 in 12 s, user-scoped under `%APPDATA%\uv\tools`. |
| Other | git 2.44, Oracle JDK 21 on `PATH`, winget available. |
| Machine | Windows 11 Home 10.0.26200, i9-13900HX (24 cores), 32 GB RAM, hypervisor already present (virtualization is on), about 75 GB free on `C:`. |
| `ANTHROPIC_API_KEY` | Not set, so no paid run was attempted. |

Nothing system-wide was installed by this session. Setup for the user, in
order:

1. **Enable WSL2** from an administrator PowerShell: `wsl --install`, then
   reboot. Windows Home has no Hyper-V backend, so WSL2 is the only backend
   Docker Desktop can use here. The hypervisor is already active, so this
   should not need a firmware change.
2. **Install Docker Desktop for Windows** with the WSL2 backend (the
   installer's default). Licensing: Docker Personal is free for personal use
   and for companies under 250 employees and 10 million USD revenue; this side
   project qualifies. For the employer-adoption question the roadmap already
   plans a Podman check; Harbor has a `podman` backend (`-e podman`) that
   shares the Docker code path.
3. **Disk.** Docker's WSL2 disk image lives on `C:` and grows. 75 GB free is
   enough for this prototype (about 1 GB image) but not comfortable for the
   roadmap's 5 to 15 GB per-repo Android images. Plan on freeing space or
   moving the WSL disk before Phase 1.
4. **Verify**, then run the kernel check Harbor's Docker backend depends on
   for `no-network` and `allowlist` tasks (section 4.4):

   ```powershell
   docker info
   docker run --rm alpine sh -c "zcat /proc/config.gz | grep NFT_FIB_INET"
   ```

   It must print `CONFIG_NFT_FIB_INET=y` or `=m`, or `/proc/config.gz` must be
   absent (then Harbor proceeds optimistically). If it prints nothing, Harbor
   refuses this task with "network_mode='no-network' is not supported by
   docker environment" and the fallback is a Linux host or a cloud sandbox.
5. **Where to run Harbor.** Harbor's CLI runs on Windows (it is installed and
   validated the task here) and talks to Docker Desktop. Jobs write bind
   mounts under the jobs directory, so keep that outside OneDrive
   (`-o C:\harbor-jobs`). The cleaner setup, and what the roadmap already
   prescribes, is to run Harbor from inside the WSL2 Ubuntu distribution with
   the project in the Linux filesystem: `uv tool install harbor` there, native
   paths, fast mounts, no line-ending risk.
6. Then run `commands.md` sections 3 to 6.

## 2. What was done and what worked

- Read ROADMAP.md (Definitions, Run protocol, Phase 0 ADR), Harbor's docs
  (tasks, configuration, verifier, separate verifier, environment, artifacts,
  network policies, environment variables, jobs, configs, regrade, error
  classification, custom agents, agent auth, telemetry, installation,
  tutorials) and the installed 0.24.0 source for every claim below.
- Authored `prototype/harbor-gradle-task/` in Harbor's layout: a pure-Kotlin
  JVM Gradle project (Gradle 8.14.3 wrapper, Kotlin 2.2.0, JUnit 5 through
  `kotlin("test")`), one red test at base (`fullDiscountYieldsZero`), four
  green tests, a one-line gold patch applied by `solution/solve.sh`, a
  Dockerfile on `eclipse-temurin:17-jdk` that pre-fetches the wrapper
  distribution and all dependencies and proves the offline path at build
  time, and a grader (`tests/test.sh` plus `tests/parse_junit.py`) that
  applies the captured diff, flags tampering, restores test and build files
  from pristine copies, runs Gradle offline with a fresh `GRADLE_USER_HOME`
  and a read-only cache, parses the JUnit XML, and writes the reward with an
  exit reason.
- Harbor's task model loads the task: separate verifier mode resolves, the
  verifier baseline is `no-network`, artifacts and the collect hook parse,
  `solve.sh` and `test.sh` are discovered. `harbor run --dry-run` validates
  the job config and stops at "Docker is not installed".
- Baseline build on the host JDK 21: compiles, 5 tests, exactly one failing.
- Grader validation on the host (`local/validate-grader.sh`), nine scenarios
  built the way Harbor would hand them to the grader. Results are in section
  2.1 below.
- A custom cheating agent (`agents/tamper_agent.py`) is ready for the
  Harbor-run tampering variant.

Not done: image build, image size, any Harbor trial, the paid run.

### 2.1 Local grader validation results

Host: Windows 11, Git Bash, Oracle JDK 21 (the image uses JDK 17), Gradle
8.14.3 distribution unpacked in the session scratchpad, fresh
`GRADLE_USER_HOME` per scenario, `GRADLE_RO_DEP_CACHE` pointing at a
read-only copy of a warm cache, `--offline`.

Final pass (`local/validate-grader.sh`, log `validate-grader-3.log`): 9 of 9
scenarios returned the expected reward and exit reason.

| Scenario (what the "agent" did) | Verifier mode | Reward | Exit reason | Grader time |
|---|---|---|---|---|
| gold patch (oracle) | separate | 1 | resolved | 51 s |
| empty diff (no-op) | separate | 0 | no_diff | 55 s |
| rewrote the test file to pass trivially, no fix | separate | 0 | tampered (`src/test/.../DiscountCalculatorTest.kt`) | 51 s |
| rewrote the test file and applied the fix | separate | 0 | tampered | 60 s |
| fix plus an added dependency in `build.gradle.kts` | separate | 0 | tampered (`build.gradle.kts`) | 57 s |
| wrong fix (clamp to 98) | separate | 0 | f2p_failed | 48 s |
| broke compilation of main sources | separate | 0 | build_failed | 42 s |
| gold patch applied directly in the tree | shared | 1 | resolved | 39 s |
| tampered test file directly in the tree | shared | 0 | tampered | 37 s |

Grader time is the whole `test.sh` run on the host, dominated by a cold Gradle
start with a fresh home (no daemon, Kotlin compiled in-process). This is the
first data point for the roadmap's "measured oracle verification time": about
45 s for a one-module Kotlin project, before any Android plugin.

Two grader bugs surfaced and were fixed during this validation, which is
exactly why the roadmap wants fixture branches: Gradle writes JUnit 5 method
names with trailing parentheses (`fullDiscountYieldsZero()`), so the
expected-test list must be normalized; and a shell regex rejected exit
reasons containing digits (`f2p_failed`).

## 3. Answers to the step-2 questions

Line references are into the installed package
`…\uv\tools\harbor\Lib\site-packages\harbor\`.

### 3.1 Task directory layout

```
task/
├── instruction.md          # given to the agent (plus --extra-instruction text)
├── task.toml               # schema_version "1.4"; [metadata] [agent] [verifier]
│                           # [verifier.environment] [[verifier.collect]]
│                           # [solution] [environment] and top-level artifacts
├── environment/
│   ├── Dockerfile          # build context is environment/; or docker-compose.yaml;
│   └── …                   # or [environment].docker_image for a prebuilt image
├── solution/
│   ├── solve.sh            # run by the oracle agent from the task workdir
│   └── …                   # whole directory is uploaded to /solution
└── tests/
    ├── test.sh             # uploaded with the whole tests/ dir to /tests
    └── …                   # (or tests/Dockerfile for a dedicated verifier image)
```

Container conventions (`models/trial/paths.py:39-48`): `/logs/agent`,
`/logs/verifier`, `/logs/artifacts`, `/tests`, `/solution`; the working
directory is the image's `WORKDIR` (`/app` by convention, overridable with
`[environment].workdir`). On the Docker backend `/logs/agent` and
`/logs/verifier` are bind mounts from the trial directory on the host
(`trial/trial.py:1895-1908`); `/app` comes from the image, never from a
host mount, which satisfies the roadmap's "never bind-mount the working tree".

Multi-step tasks (`steps/<name>/…`) exist and are not needed here.

### 3.2 How tests/test.sh writes the reward

Harbor uploads `tests/` to `/tests`, `chmod +x`'s the script and executes it
directly (shebang required, LF endings required) from the task workdir, with
stdout redirected to `/logs/verifier/test-stdout.txt`
(`verifier/verifier.py:175-232`). The script must write either
`/logs/verifier/reward.txt` (one finite number) or `/logs/verifier/reward.json`
(an object of labeled finite numbers); if both exist JSON wins
(`verifier/verifier.py:257-266`). A missing or empty file or a non-numeric
value is a verifier error (`RewardFileNotFoundError`, `RewardFileEmptyError`,
`VerifierOutputParseError`), which Harbor does not retry by default. There is
no slot for a string exit reason; the prototype writes it to
`/logs/verifier/verdict.json`, which Harbor syncs to the host but does not
interpret. For Phase 1, emit `reward.json` with numeric flags
(`{"reward": 1, "f2p": 1, "p2p": 1, "tampered": 0}`) so the viewer and job
stats carry them, and keep the exit reason in `verdict.json`.

### 3.3 Same container or separate, and API keys during verification

Default is **shared**: after the agent phase, `tests/` is uploaded into the
agent's container and `test.sh` runs there. With
`[verifier] environment_mode = "separate"` (or any `[verifier.environment]`
section) Harbor starts a **fresh container** from the same image, or from a
dedicated verifier image (`[verifier.environment].docker_image` or
`tests/Dockerfile`), empties `/logs/verifier`, uploads the declared artifacts
to their original paths, uploads `tests/`, and runs the script
(`trial/trial.py:898-967`; `models/task/config.py:555-616`). The agent's
filesystem changes do not carry over.

API keys: agents receive their key as an environment variable **scoped to
the agent's exec calls**, not written into the container's environment
(`trial/trial.py:600-631` wraps only the agent phase in
`scoped_exec_env`; `environments/base.py:471-483` states the overlay is kept
off the verifier). The verifier gets only `[verifier.env]`, `--verifier-env`
and job-level `verifier.env`, resolved from the host with `${VAR}` syntax
(`verifier/verifier.py:189-203`). In separate mode nothing but artifacts
crosses. Residual exposure in the agent container is what the roadmap already
describes: agent-written code runs where the key is in the agent process's
environment and could copy it to disk; the fix is the dedicated low-limit key
and the separate grader, both available here. `trial/trial.py:1118-1125`
scrubs agent and verifier env values from the saved job files.

### 3.4 Fresh GRADLE_USER_HOME and a read-only cache for test.sh

Yes for the home, with a caveat for the mount. `test.sh` is a shell script
with full control of its environment, so the prototype sets
`GRADLE_USER_HOME` to a `mktemp -d` directory and points
`GRADLE_RO_DEP_CACHE` at a read-only copy of the warmed `modules-2` cache
baked into the image, runs the image-pinned distribution binary
`/opt/gradle/dist/bin/gradle` instead of the project's `gradlew` (which an
agent could replace), and passes `--offline`. Verified locally (section 2.1).

The caveat: Harbor's job-level `environment.mounts` (bind, volume or image
mounts, with `read_only: true`) apply to the **agent environment only**
(`models/trial/config.py:215-217`); the separate verifier container gets
only the `/logs/verifier` bind (`trial/trial.py:1021-1032`). So a read-only
host-mounted cache is not available to a separate verifier. Baking the cache
into the image layer achieves the same isolation (a fresh container cannot
have been modified by the agent) at the cost of image size, which the
roadmap's "image is the source of truth" already accepts.

### 3.5 Oracle and no-op agents

- `oracle` (`agents/oracle.py:81-156`): uploads the whole `solution/` directory
  to `/solution`, `chmod +x`'s `solve.sh`, runs it from the task workdir with
  `[solution].env`, writes stdout to `/logs/agent/oracle.txt`, and records a
  non-zero exit in `agent/exit-code.txt`. Version string `1.0.0`. Needs no
  model and no key.
- `nop` (`agents/nop.py`): `setup` and `run` do nothing. Version `1.0.0`.
  This is the roadmap's "null agent" and should make the grader report
  `no_diff`.

### 3.6 Which adapters expose cost, tokens and version

From `agents/installed/*.py`. "Version" means the adapter runs the tool's
version command during setup (`agents/installed/base.py:1093-1099`) and the
result lands in `result.json` under `agent_info.version`; the version to
install can also be pinned with `--ak version=…`.

| Adapter (`-a`) | Tokens | Cost (`cost_usd`) | Version | Notes |
|---|---|---|---|---|
| `claude-code` | yes | yes | yes | Cost comes from the final `total_cost_usd` line of `--output-format=stream-json` (`claude_code.py:1001-1031`); if absent, a LiteLLM estimate marked `cost_source: litellm_estimate` (`:1036-1099`). Keys: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`. Kwargs include `max_turns`, `max_budget_usd`, `disable_web_search`, `permission_mode`, `version`. |
| `codex` | yes | yes | yes | From the Codex session JSONL converted to a trajectory. |
| `openhands`, `openhands-sdk` | yes | yes | yes | |
| `mini-swe-agent` | yes | yes | yes | Key env `MSWEA_API_KEY`. The roadmap's controlled reference is already integrated. |
| `gemini-cli`, `cursor-cli`, `goose`, `opencode`, `swe-agent` | yes | yes | yes | |
| `copilot-cli` | yes | **no** | yes | |
| `aider` | **no** | **no** | yes | `populate_context_post_run` is `pass` (`aider.py:98-99`); `AgentContext` stays `None`, which is what the roadmap's manifest should record as missing. Reconstruct from Aider's own cost output if needed. |

Missing values are `None`, never zero (`models/agent/context.py`); the
trial-level totals in `result.json` keep that distinction.

### 3.7 License as stated in the repository

Apache License 2.0. `LICENSE` in `harbor-framework/harbor` (branch `main`) is
the standard Apache 2.0 text (11,357 bytes); GitHub reports `Apache-2.0`; the
PyPI metadata for 0.24.0 carries `license_expression = Apache-2.0`. The
`laude-institute/harbor` URL redirects to `harbor-framework/harbor`.

## 4. Fit against the roadmap's run protocol

| Roadmap requirement | Harbor mechanism | Status |
|---|---|---|
| Agent stage from a per-repo image, shallow clone at base commit, remote removed | Task author's Dockerfile; prototype makes `/app` a one-commit repo with no remote | verified locally (Dockerfile logic), unbuilt |
| Never bind-mount the working tree from Windows | Only `/logs/agent`, `/logs/verifier`, `/logs/artifacts` are binds; `/app` is in the image | source |
| Instruction text with contract and test command | `instruction.md`; `--extra-instruction` for per-run additions | source, docs |
| API key as env var during the agent stage only | Scoped exec env overlay (3.3) | source |
| Network for the model API; web tools off | Baseline `public` or `allowlist` of model hosts per phase; `claude-code --ak disable_web_search=true` | source; allowlist unverified on Docker Desktop |
| Agent timeout | `[agent].timeout_sec`; `AgentTimeoutError` is not retried and the verifier still grades the attempt | source |
| Capture diff | `[[verifier.collect]]` hook runs in the agent container after the agent phase; output declared as an `artifacts` entry | source; round trip unverified |
| Capture agent stdout/stderr, version | `/logs/agent/*` synced; `agent_info.version` | source |
| Capture cost and tokens, missing never zero | `agent_result` with `None` defaults (3.6) | source |
| Grading in a fresh container, no keys, no network | Separate verifier with `no-network` baseline (3.3, 4.4) | source; needs nftables check |
| Fresh `GRADLE_USER_HOME`, warmed cache read-only | In `test.sh` with an in-image read-only cache (3.4) | verified locally |
| Apply agent diff, reset test sources, overwrite hidden tests | In `test.sh`: `git apply` onto the pristine tree, restore from `/tests/original` | verified locally |
| Build, run only named test tasks, parse JUnit XML, missing P2P counts as failed | In `test.sh` and `parse_junit.py`; expected-test list | verified locally |
| Verdict and exit reason | reward file plus `verdict.json` (3.2) | verified locally |
| Verification timeout | `[verifier].timeout_sec`; `VerifierTimeoutError`, not retried | source |
| One manifest per run, JSONL result set | `result.json` per trial with timing per phase, config, agent info, verifier mode; job-level `result.json`. No JSONL: the mobile layer flattens `result.json` + `verifier/verdict.json` into the roadmap's manifest fields | source |
| N repetitions, bounded parallelism | `-k` attempts, `-n` concurrent trials, per-agent caps | source, `--print-config` |
| Resume after crash | `harbor job resume -p <job dir>`; requires the identical config; completed trials are kept | source `job.py:258-381` |
| Infra errors retried once | `-r 1`. In 0.24.0 retry is "everything except an exclude list" (agent/verifier timeouts, missing or bad reward, usage limit, refusal, auth, model not found) (`models/job/config.py:291-322`). Sandbox build or start failures and transient API errors are retried. **Gap:** an out-of-memory kill inside the verifier produces a valid reward 0, which Harbor will not retry; the grader reports `infra_error`, and the layer must rerun it, which `harbor job regrade` can do without a new agent run. The docs' `failure_cause` and `reward_valid` fields are not in 0.24.0 yet. | source |
| Memory limits 8 to 12 GB per container | `[environment].cpus`, `memory_mb` become compose resource limits; `--override-memory-mb` per job | source |
| Security: unprivileged containers, no socket | Agent runs as root by default; set `[agent].user` with a non-root image user. Harbor's lint (not in 0.24.0) flags root agents and shared verifiers | source |

### 4.4 How no-network works on the Docker backend, and why it needs checking

Static `network_mode: none` is used by several cloud backends but not by the
Docker backend. On Docker any non-public policy, static or per-phase, enables
an egress-control sidecar (`gogost/gost` with `NET_ADMIN` and `NET_RAW`); the
task container shares its network namespace and the sidecar applies
`deny-all`, `allow-all` or an allowlist with nftables
(`environments/docker/docker.py:207-216`, `:1443-1468`,
`docker-compose-egress-control.yaml`). The backend enables this only if a
probe container finds `CONFIG_NFT_FIB_INET` in the daemon kernel's
`/proc/config.gz` (`:126-130`); without it the Docker environment reports no
`disable_internet` capability and Harbor rejects the task at validation
rather than running it with a weaker policy (`environments/base.py:826-848`).
Docker Desktop's WSL2 kernel is Microsoft's; whether it exposes this option
is the one thing that could push grading to another backend (cloud sandbox,
Linux host) and must be checked right after installation (section 1, step 4).

## 5. Friction points

1. **Docs run ahead of the release.** `harbor lint`, `harbor agent auth`,
   `failure_cause`/`reward_valid` in `result.json` are documented but absent in
   0.24.0. Pin the Harbor version in the project and re-read the changelog on
   each bump; the project moves fast (deprecations seen in the source:
   `allow_internet`, `mounts_json`, automatic `/logs/artifacts` collection).
2. **Exit reason has no first-class field.** Reward files are numeric. Use
   `reward.json` numeric flags plus a sidecar `verdict.json` (3.2).
3. **No read-only mount into the separate verifier.** Bake the cache into the
   image (3.4).
4. **Separate verifier transfer is by artifacts.** Declaring `/app` would tar
   a whole Android repo out and back in per trial. The prototype captures only
   the diff with a collect hook and applies it onto the pristine tree, which
   is also what the roadmap specifies. The hook runs with the agent
   container's own `git`, so a hostile agent could tamper with it; the result
   is still just a diff applied to a pristine tree in a key-less container,
   so the exposure is bounded. A host-side diff of a downloaded tree is the
   stricter alternative if ever needed.
5. **Docker no-network depends on nftables in the daemon kernel** (4.4).
6. **Gradle JUnit XML naming**: JUnit 5 method names carry `()`; parameterized
   and dynamic tests carry display names. The parser normalizes the former;
   the roadmap's parser tests must cover the latter.
7. **Root agent by default.** Fine for the prototype; Phase 1 images should
   add a non-root user and set `[agent].user`.
8. **Trial directory layout is undocumented**; it is in
   `models/trial/paths.py` (`config.json`, `result.json`, `trial.log`,
   `agent/`, `verifier/`, `artifacts/manifest.json`, `lock.json`).
9. **Telemetry is on by default** (command and job summaries to PostHog, no
   paths, prompts or env). Opt out with `HARBOR_TELEMETRY=off`; document this
   in the project's README.
10. **Windows host specifics.** The Harbor CLI works on Windows, but the
    generated `gradlew` and any script written by Windows tooling must be LF;
    the Dockerfile `chmod +x`'s `gradlew`; keep jobs out of OneDrive. Running
    everything inside WSL2 removes this class of problems.
11. **Custom agents need `PYTHONPATH`**: Harbor imports `module:Class` with
    plain `importlib`, so the task directory must be importable.

## 6. Image build time and size

Not measured (no Docker). Estimate for `prototype/harbor-gradle-task`:
`eclipse-temurin:17-jdk` is about 450 MB, the Gradle 8.14.3 distribution
140 MB unpacked plus the 137 MB zip Gradle keeps, the Kotlin 2.2.0 compiler
and plugin with JUnit 5 roughly 250 to 350 MB in `modules-2`, duplicated once
more as the read-only copy, plus git and python3 about 60 MB. Expect **1.3 to
1.6 GB** and a first build of **4 to 8 minutes**, dominated by downloads;
rebuilds are cached per content hash. The duplicate cache copy exists because
the agent's own `./gradlew` uses the warm home while the grader uses the
read-only copy. Setting `GRADLE_RO_DEP_CACHE` image-wide and moving
`modules-2` out of the warm home (Gradle resolves from the read-only cache
for both) removes the duplicate, saves about 300 MB, and is the first thing
to do in Phase 1; deleting the kept distribution zip saves another 137 MB.

For the Android images the roadmap plans, add: command-line tools, platform
tools, one platform and one build-tools version (1.5 to 2.5 GB), AGP and
AndroidX dependencies for a real app (1 to 4 GB), Robolectric `android-all`
jars pre-fetched per API level (100 to 150 MB each, and they must be in the
cache because grading is offline), and a warmed configuration cache. That is
the roadmap's 5 to 15 GB per repo, with 15 to 45 minute first builds. Harbor's
`[environment].docker_image` lets those be pulled from GHCR by digest instead
of built per machine, which is also the roadmap's plan.

## 7. Recommendation and the pruned Phase 1 list

**Build on Harbor 0.24.x**, pinned, with the task layout exactly as in the
prototype. Reasons: every item in the roadmap's ADR check passes on paper and
the grader logic is validated; the runner, oracle, null agent, adapters with
cost capture, repetitions, concurrency, retries, resume, regrade, network
allowlisting, viewer and cloud backends come free; the mobile layer stays
what the roadmap says is the product (images, graders, task schema,
statistics, experiment mode). The standalone path would re-implement the
first list and still want Harbor's layout for interoperability.

Conditions under which to revisit: the nftables check fails on Docker
Desktop and no Linux host is available; or a Harbor release breaks the
separate-verifier or collect-hook contract and the project cannot stay on a
pinned version.

Phase 1 work on Harbor (replaces the two lists in ROADMAP.md):

- Base and per-repo images (JDK 17 and 21; Android SDK; warmed caches;
  Robolectric jars; non-root user; `GRADLE_RO_DEP_CACHE` layout from the
  prototype's Dockerfile).
- Task schema v0 and a converter to Harbor layout: `task.toml` (separate
  verifier, no-network, collect hook, artifacts, timeouts, metadata with
  F2P/P2P IDs and the verification spec), `instruction.md`,
  `tests/original/` pristine copies, hidden test files, `solution/fix.patch`.
- The grader, generalized from `tests/test.sh`: module paths and test tasks
  from the verification spec, tampering categories from the Definitions
  (test sources, build scripts, buildSrc and build-logic, properties,
  version catalogs, wrapper, init scripts, CI), `dependency_added`
  detection, `reward.json` flags plus `verdict.json`, per-test results.
- Manifest enrichment: read `result.json`, `verifier/verdict.json` and
  `artifacts/manifest.json` into the roadmap's JSONL manifest fields
  (image digests, toolchain versions, network policy, host spec, pricing
  table version, exit reason).
- Thin CLI over `harbor run` for `run`, `report`, `compare`,
  `validate-task`, and the infra-error rerun policy via `harbor job regrade`.
- Statistics and reports as planned.

Dropped from the standalone list: the runner, agent and grading container
orchestration, oracle and null agents, adapters, parallelism, resume,
retries, trajectory viewer.

## 8. Still to verify once Docker exists (in this order)

1. `docker run --rm alpine sh -c "zcat /proc/config.gz | grep NFT_FIB_INET"`
   prints a `y` or `m` line. If not, try `-e podman` on the same WSL2 kernel
   (same answer expected) and then plan on a Linux host or cloud sandbox for
   grading.
2. `docker build` time and size of the prototype image (`commands.md` §3).
3. `harbor run … -a oracle` gives reward 1 with `verifier/verdict.json`
   `exit_reason` `resolved` and `verifier_mode` `separate`;
   `result.json` has `verifier_environment_mode: separate`;
   `artifacts/tmp/harbor-capture/agent.patch` holds the gold diff.
4. `-a nop` gives reward 0, `no_diff`.
5. `-a agents.tamper_agent:TamperAgent` gives reward 0, `tampered`, naming the
   test file.
6. Record `harbor run` exit codes and the `environment_setup`,
   `agent_execution` and `verifier` timings from `result.json`.
7. With a key: one `claude-code` run; confirm `agent_info.version`,
   `agent_result.cost_usd`, token counts, and that the model could still reach
   the API under the `public` baseline.
8. Kill a job mid-way and `harbor job resume` it.
9. `harbor job regrade` on the oracle job reruns only the verifier.

## 9. Evidence index

- Harbor docs: `docs.harborframework.com` pages `tasks/overview`,
  `tasks/configuration`, `tasks/verifier`, `tasks/separate-verifier`,
  `tasks/environment`, `tasks/artifacts`, `tasks/network-policies`,
  `tasks/solution`, `tasks/lint`, `jobs/run-a-job`, `jobs/configs`,
  `jobs/environment-variables`, `jobs/error-classification`, `jobs/regrade`,
  `jobs/custom-verifiers`, `agents/pre-integrated-agents`,
  `agents/custom-agents`, `agents/agent-auth-resolution`,
  `telemetry/telemetry`, `getting-started/installation`,
  `tutorials/create-a-task`.
- Source: `harbor` 0.24.0 as installed by `uv tool install harbor`, files
  cited inline above.
- Repository: `https://github.com/harbor-framework/harbor` (LICENSE,
  default branch `main`).
- Local artifacts in the session scratchpad (not part of the project): Gradle
  8.14.3 distribution, warm Gradle home, validation work directories and logs
  `validate-grader-2.log`.
