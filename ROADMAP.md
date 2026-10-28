# Roadmap: Probo, an evaluation harness for AI-generated mobile code changes

Status: draft v2.3, 2026-10-28. v2 followed two review passes; v2.1 folded in the Phase 0 Harbor prototype findings (docs/harbor-prototype-verdict.md); v2.2 added the execution packages for running the plan from a separate Claude Code chat; v2.3 records the autonomous build session of 2026-10-28 (name, package P0-B, the Docker-independent parts of Phase 1). Changes are listed in the review log at the end. Effort assumption: 10 to 15 hours per week. Phase durations are ranges at that pace, not calendar promises.

**Where things stand (2026-10-28).** The project is named Probo (`probo`; docs/DESIGN.md, naming decision). Package P0-B is done: docs/DESIGN.md, task schema v0 with validator and converter, docs/seed-apps.md, docs/mobiledev-bench.md (checkpoint G2: yes), CLAUDE.md, git with DCO. The Docker-independent parts of P1-B and P1-D are also done and verified on the host JDK: the generalized grader with fourteen self-test scenarios, the A/B/C gate runner, manifest flattening, the statistics module, the report and compare commands, and the thin CLI over `harbor run`. Still blocked on H2 (WSL2 and Docker Desktop, not installed): P0-C, every container run, every Android image. Human-gated and open: H1 disclosure, H2, H3 keys, H4 (GitHub repository push; the name and license are chosen), H5 budget, H6 seed-app pick (ranking in docs/seed-apps.md). Package log: docs/progress.md.

## Goal and non-goals

**Goal.** A tool a team runs on its own mobile repo and its own agent setup to answer: did the agent's change build, pass hidden tests, and avoid regressions, and how often, at what cost? The mobile layer (images, graders, task schema, statistics, experiment mode) is the product. The public task pack and results table are the demo.

**Primary user.** A team that already runs a coding agent on a mobile repo and wants a number it can trust. Readers of the public results are secondary.

**Non-goals for v0.x.**
- Not a model leaderboard. Fixed benchmarks exist already: SWE-bench Mobile (iOS, Swift and Objective-C, hosted and closed) and MobileDev-Bench (Android native, React Native, Flutter; 407 tasks; harness and containers released). This project complements them; it does not compete on task count.
- Not a GUI-agent benchmark. AndroidWorld and iOSWorld (arXiv 2606.09764) cover that.
- Not an agent, and not a runner. Harbor is the runner (decided, see Phase 0). The harness runs other people's agents as black boxes, including the work framework later.

## Definitions

Fixed before any code is written, because every grader, report, and claim depends on them.

- **Task.** A repository at a pinned base commit; an instruction; a hidden test patch; a gold patch; the Fail-to-Pass (F2P) test IDs; the Pass-to-Pass (P2P) test IDs; an executable verification spec (Gradle module paths, variant such as demoDebug, exact test task names, JDK version, AGP and Gradle versions, setup hooks); an agent timeout; a verification timeout; source metadata (repo, license, issue URL, PR URL, merge date); kind (bug fix or small feature); and a difficulty proxy (gold patch size). A task has a stable ID; the pack has a semver and a changelog for dropped or fixed tasks. On disk a task is emitted in Harbor's layout: instruction.md, task.toml, environment/, solution/, tests/.
- **Resolved.** The build succeeds, the test sources compile, every F2P test passes, every P2P test passes, and the run carries no tampering flag. Anything else is not resolved.
- **Exit reason.** Exactly one per run: resolved, test_compile_failed, f2p_failed, p2p_failed, build_failed, no_diff, agent_error, timeout, tampered, infra_error. Precedence when several apply: infra_error, then timeout and agent_error, then tampered, then no_diff, then build_failed, then test_compile_failed, then f2p_failed, then p2p_failed. (agent_error comes from Harbor's exception record and is assigned by the result flattener; the grader never sees a crashed agent, only its diff.) An agent-added dependency is a build-file edit, so in v0.1 it exits tampered with a dependency_added detail flag; dependency_added becomes its own exit reason in v0.2 when the dependency mirror allows dependency edits. Harbor's reward file is numeric, so the grader writes reward.json with numeric flags (reward, f2p, p2p, tampered) for Harbor's own stats and viewer, and the string exit reason plus per-test results in verdict.json next to it. Infra errors (image pull failure, container crash, out-of-memory kill, API outage) are retried once; if they persist they count as not resolved in the headline and appear as their own count. Nothing is ever dropped from the denominator.
- **Tampering.** The agent's diff touches any test source set, Gradle build script (including buildSrc and build-logic convention plugins), gradle.properties, a version catalog, the Gradle wrapper, Gradle init scripts, or CI configuration. Tasks are selected so the gold patch touches none of these, so a tampered run counts as not resolved and is also reported as its own count with the files touched.
- **Verifiable in v0.1.** Tests that run on the JVM: unit test tasks and Robolectric. Instrumented tests (androidTest) and Compose UI tests that need an emulator are out of scope until Phase 5. This is a task selection criterion, and it will cut yield hard, because many UI-facing Android PRs ship instrumented tests or none.
- **Interface contract.** The part of the instruction that names the public symbols the hidden tests reference (class names, function signatures, resource IDs), derived mechanically from the test patch. Without it, a behaviourally correct fix that picks different names fails to compile the test sources and is reported as a failure. Tasks whose hidden tests use only pre-existing APIs are preferred and need no contract.

## Run protocol

Each step names the Harbor mechanism that implements it, as verified against Harbor 0.24.0 source and docs by the prototype. Items marked "unverified" await a Docker install (see Phase 0 deliverables).

1. **Agent stage.** Harbor starts a container from the per-repo image. The working directory /app comes from the image, never from a host bind mount; only the log directories are bind-mounted. The repository inside the image is a shallow clone at the base commit with the remote removed and no unreachable refs, so the agent cannot fetch the upstream fix. The agent receives instruction.md, including the interface contract and the recommended test command for the touched module, so it does not burn its budget building every variant. Its API key is injected only into the agent's own exec calls, not into the container environment, and Harbor scrubs key values from saved job files. Network: baseline public in the first runs; per-phase allowlist of model endpoints once the nftables check below passes (unverified on Docker Desktop). Agent web tools are disabled where the adapter allows (the Claude Code adapter has a kwarg for it) and otherwise recorded as a condition. The agent timeout is task.toml's agent timeout; on timeout Harbor still grades whatever the agent left.
2. **Capture.** A verifier collect hook runs in the agent container after the agent phase and produces the diff against the base commit, excluding build outputs, as a declared artifact. Only that diff crosses to the grader. The hook runs with the agent container's own git, so a hostile agent could tamper with it; the result is still only a diff applied to a pristine tree in a key-less container, so the exposure is bounded. Agent stdout and stderr, the agent's version output, tokens, and cost land in Harbor's per-trial result.json. Missing cost is None, never zero: Claude Code, Codex, OpenHands, and mini-swe-agent report tokens and cost; Aider reports neither, so its cost is reconstructed from its own output or a versioned pricing table and labelled as an estimate.
3. **Grading stage.** task.toml sets the verifier to a separate container with no network. Harbor starts a fresh container from the same image, uploads tests/ and the declared artifacts, and runs tests/test.sh with no agent keys present. The script: creates a fresh GRADLE_USER_HOME with mktemp; points GRADLE_RO_DEP_CACHE at the warmed dependency cache baked into the image (host mounts do not reach the separate verifier, so the cache must live in the image); runs the image-pinned Gradle distribution binary rather than the project's gradlew, which an agent could replace; applies the agent diff onto the pristine tree; restores every test source set and build file from pristine copies under tests/original; overwrites, rather than patches, every file the hidden test patch touches; builds; runs only the test tasks named in the verification spec with --offline; parses JUnit XML from build/test-results, normalizing JUnit 5 method names that carry trailing parentheses; counts a missing P2P test as failed; writes reward.json and verdict.json. The verification timeout is task.toml's verifier timeout.
4. **Record.** The mobile layer flattens Harbor's result.json (phase timings, agent info, verifier mode, cost), verifier/verdict.json, and artifacts/manifest.json into one JSONL manifest line per run with the fields listed under Features.

**Memory limits and the OOM gap.** Gradle and Kotlin daemons under a tight limit die with out-of-memory kills that look like build failures. Set container memory to 8 to 12 GB through task.toml's environment limits, and set org.gradle.jvmargs and kotlin.daemon.jvmargs in the image. Harbor 0.24.0 retries sandbox and transient API failures with its retry flag, but a verifier that is OOM-killed still produces a valid reward of 0, which Harbor will not retry. The grader therefore detects the kill (Gradle exit status 137 or a daemon disappearing before any JUnit XML is written) and writes infra_error to verdict.json; the mobile layer's rerun policy then calls Harbor's regrade command, which reruns only the verifier on the recorded agent output without a new paid agent run. One regrade; if it still fails, the run counts as not resolved with exit reason infra_error.

**Security.** Agent-written code, including Gradle scripts, executes inside the agent container. The key is scoped to the agent process but that process runs the agent's code, so a malicious change could still copy it. Mitigations: a dedicated low-limit key per benchmark run, rotated afterwards; a non-root user in the images with the agent user set in task.toml (Harbor runs agents as root by default); no Docker socket and no host paths; key-less, offline grading. Harbor sends anonymous command and job summaries to its telemetry by default; the project README documents the environment variable that turns it off. State the key limitation in the README.

## Phase 0: study and design (1 to 2 weeks)

### Projects to study

| Project | Take from it | Do not copy |
|---|---|---|
| Harbor 0.24.x (harborframework.com, Apache-2.0 confirmed from the repository LICENSE on 2026-10-17; third-party listings saying MIT were wrong) | Task layout: instruction.md, task.toml, environment/, tests/test.sh, solution/solve.sh, reward written to the verifier log directory. Ships an oracle agent (runs solve.sh) and a no-op agent. Adapters with cost and version capture for Claude Code, Codex CLI, OpenHands, mini-swe-agent and others; Aider without cost. Separate key-less verifier mode, per-phase network policies through an egress sidecar, attempts, concurrency, retries, resume, regrade, trajectory viewer, cloud sandbox backends. Its docs run ahead of its releases (lint, agent auth, and failure-cause fields are documented but absent in 0.24.0), so pin the version and read the changelog on every bump. | Its generality. Your value is the mobile layer. |
| SWE-bench harness, SWE-bench Multimodal, SWE-bench-java | F2P and P2P semantics and the validation states written out below. How compiled-language variants handle test compilation. | Python-only assumptions about test runners. |
| MobileDev-Bench (arXiv 2603.24946) | 407 tasks from 19 apps across Android native, React Native, Flutter, with harness and containers released. Locate the code release via the paper's full text; check task and container licenses. If usable, this is the v0.1 volume source (see Task sourcing ADR). Also their method for restoring repos to a compiling state. | Being a fixed dataset. |
| SWE-bench Mobile (arXiv 2602.09540) | Findings to cite, with the caveat that it is iOS-only and hosted: same model varied up to 6x across agents, best agent reached 12%, short defensive-programming prompts beat complex ones by 7.4 points. | Hosted, closed benchmark model. |
| SWE-smith | Synthesizing tasks by breaking working code. Cheap way to scale task count in v0.3. | Using synthetic tasks for headline numbers. |
| mini-swe-agent | A tiny agent loop you fully control, usable with any model, as the controlled reference. Already integrated in Harbor. | Making it the only agent. |
| inspect-ai (UK AISI) | Scorer abstraction, eval log format, log viewer. No longer a base candidate; still worth reading for log design. | Its solver abstraction. |
| Anthropic, "Adding Error Bars to Evals" (Miller, 2024) | Clustered standard errors by task; paired differences for comparing configurations; why between-task variance dominates and more tasks beat more reps. | Nothing. Read it twice. |
| Tau-bench | pass^k as a consistency idea. Not usable at three reps (see Metrics ADR). | |
| reactivecircus/android-emulator-runner | Running an emulator in GitHub Actions on Linux runners with KVM. Phase 5 only. | |
| Maestro | UI flow files as a verifier for emulator-based tasks. Phase 5 only. | |

### Strategy decisions recorded as ADRs

| Decision | Options | Decision | Why |
|---|---|---|---|
| Base framework | Harbor; inspect-ai extension; standalone | **Build on Harbor 0.24.x, pinned.** Decided on 2026-10-17 by the prototype, provisionally: Docker was not installed, so the evidence is Harbor's source, docs, its task model loading the prototype task, a dry run reaching the Docker preflight, and the grader passing synthetic scenarios on the host JDK. Revisit only if the nftables check fails on Docker Desktop and no Linux host or cloud sandbox is available, or if a Harbor release breaks the separate-verifier or collect-hook contract and the project cannot stay pinned. | Every item in the fit check passes on paper: separate key-less verifier, script-controlled GRADLE_USER_HOME, cost and version capture, allowlisted networking, attempts, concurrency, retries, resume, regrade, oracle and no-op agents. The standalone path would rebuild all of that and still want Harbor's layout. |
| Task sourcing | Import MobileDev-Bench; mine PRs; synthesize; hand-write | If MobileDev-Bench's release and licenses allow, import its Android-native subset as the v0.1 volume source and hand-mine a small fresh subset of post-cutoff tasks from the seed apps. If not, hand-mine 10 to 15 tasks and say so. Synthesis in v0.3. | A 20-task hand-mined pack next to a 407-task one is not a differentiator; the harness, experiment mode, and statistics are. |
| Grading | Hidden tests + deterministic checks; LLM judge; rubric | Deterministic for every headline number. LLM judge only as a labelled secondary signal, never in the summary table. | Reviewers trust tests. A judged number invites "the judge is biased". |
| Agent integration | Black-box CLI adapter; harness-owned agent loop | Black-box through Harbor's adapters, plus mini-swe-agent as one controlled reference and a custom Harbor agent class for the generic command template. | The point is to evaluate real tools, including the work framework. |
| Environment | Container per run with layered images; shared VM | Base image per JDK (17 and 21) with Android SDK and cmdline-tools; per-repo image with the repo cloned in, Gradle wrapper distribution, warmed dependency cache laid out once as a read-only dependency cache (no duplicate copy, kept distribution zip deleted), Robolectric android-all jars pre-fetched, toolchain auto-provisioning disabled, a non-root user; per-task overlay. Images published to GHCR, referenced from task.toml by digest, with a stated size budget (expect 5 to 15 GB per repo and 15 to 45 minute first builds). | Cold Gradle builds are the main cost and flake source. The image, not the network, is the source of truth for a task, and the separate verifier can only see what is in the image. |
| New dependencies | Allow network during grading; forbid; local mirror or cache proxy | v0.1: exclude tasks whose gold patch adds a dependency; grade offline; an agent-added dependency is a build-file edit and exits tampered with a dependency_added detail, reported separately. v0.2: a local Maven mirror or cache proxy baked into the image so legitimate additions resolve offline, and dependency_added promoted to its own exit reason. | Offline grading is worth more than coverage of dependency-adding fixes in the first release. |
| Network policy | Open; API-only allowlist; open with git remote stripped | Always: remote stripped, no unreachable refs, agent web tools disabled where possible and otherwise declared as a condition. Agent phase: Harbor's per-phase allowlist of model endpoints once the nftables check passes; public baseline until then, recorded as a condition. Verifier phase: no network. | Open network lets an agent fetch the merged fix or search for the issue. Harbor's egress sidecar provides the allowlist the plan previously scheduled as v0.2 work. |
| Metrics | pass@1; pass@k; pass^k; cost-normalized | Headline: pass@1 averaged over reps with a 95% interval from analytic standard errors clustered by task (Miller). Secondary: per-task consistency histogram (tasks resolved 0, 1, 2, 3 of 3), cost per resolved task, median wall time, exit-reason breakdown. No pass^3. One CI method. | Matches what SWE-bench readers expect, adds cost and failure-mode angles they lack. |
| Language | Python with uv; TypeScript | Python 3.12 or newer (Harbor's floor). | Harbor, SWE-bench, and the stats tooling are all Python. |

### Phase 0 deliverables

- Written disclosure to your manager and a check of the employer's open-source and moonlighting policy. This comes first, before any code, because the project is explicitly aimed at later adoption at work. Use DCO sign-off from the first commit so provenance is clean.
- **Windows setup**, in this order, none of it done yet. The machine is Windows 11 Home with 24 cores, 32 GB RAM, and about 75 GB free on C:, which is enough for two or three parallel Android builds and not enough disk for several per-repo images.
  1. Enable WSL2 from an administrator PowerShell and reboot. Windows Home has no Hyper-V, so WSL2 is the only backend Docker Desktop can use here.
  2. Install Docker Desktop with the WSL2 backend. Docker Personal is free for this side project; the Podman backend check stays in v0.1 for employer adoption.
  3. Free disk or move the WSL virtual disk off C: before Phase 1.
  4. Run the kernel check Harbor's Docker backend needs for no-network and allowlist policies: a probe container must find the nftables FIB option in the daemon kernel's config. If it is missing, Harbor refuses no-network tasks rather than weakening them, and grading moves to a Linux host or a cloud sandbox.
  5. Run Harbor from inside the WSL2 Ubuntu distribution with the project in the Linux filesystem. Keep the Harbor jobs directory and the repo out of OneDrive. All scripts LF.
- **Complete the prototype's verification list** (section 8 of the verdict): image build time and size; oracle run gives reward 1 with exit reason resolved and verifier mode separate; no-op run gives reward 0 with no_diff; the tampering agent gives reward 0 with tampered naming the test file; one Claude Code run with cost and version captured; kill a job and resume it; regrade the oracle job and confirm only the verifier reruns. Already done on the host JDK without Docker: the grader passed nine of nine scenarios (oracle resolved, no-op no_diff, three tampering variants tampered, wrong fix f2p_failed, broken main sources build_failed, plus two shared-verifier controls), about 45 seconds per grading run for a one-module Kotlin project before any Android plugin. That is the first data point for oracle verification time.
- docs/DESIGN.md with the nine ADRs above, each with the option rejected and why; the Base framework ADR cites the verdict. **Done 2026-10-28.**
- Task schema v0 matching the Definitions section, including the executable verification spec and gold patch, and the converter design to Harbor's layout. **Done 2026-10-28:** `src/probo/schema/task-v0.schema.json`, docs/TASK_SCHEMA.md, `probo validate-task`, `probo convert`.
- MobileDev-Bench release located and its licenses checked; the Task sourcing ADR resolved on that evidence. **Done 2026-10-28, G2 = yes:** MIT harness, CC-BY-4.0 dataset, public GHCR images per task; 328 Android-native tasks of 407, of which 309 are graded by `*UnitTest` Gradle tasks; 208 of the 328 come from copyleft upstream apps, so imported patches stay labelled data with upstream notices (docs/mobiledev-bench.md).
- Two seed apps chosen by one criterion: number of merged PRs in the last 12 months that touch JVM unit tests, then license (Apache-2.0 or MIT), activity, and cold build time under ten minutes. **Ranked 2026-10-28** (docs/seed-apps.md, GitHub API, no clones): among Apache-2.0 apps the estimated 12-month count of merged PRs touching JVM tests is DuckDuckGo Android 1,726 (203 Gradle modules), Home Assistant Android 265 (10 modules), Thunderbird for Android 239 (161 modules, already the largest source in MobileDev-Bench), Wikipedia Android 138 (3 modules), Wikimedia Commons 47, Open Food Facts 1, Mihon 0. Pocket Casts (MPL-2.0), Bitwarden, WordPress, Nextcloud and AntennaPod (GPL) fail the license filter. Claude's ranking for H6: Home Assistant Android first (volume with a small module count, so the cold build is likely to fit the ten-minute budget), DuckDuckGo second if its cold build does, Thunderbird as the alternate. Cold build time is unmeasured; it needs a clone and a build, which waits for H2. Dropped earlier: Tivi (discontinued November 2024), Element Android (relicensed to AGPL-3.0), Now in Android (dependency-bump PR stream).
- Measured oracle verification time per seed app. This sets per-task verification timeouts. Open; needs H2.
- Project name checked on PyPI and GitHub; license chosen; repo created. **Done 2026-10-28 except the push:** Probo, Apache-2.0, local git with DCO; the GitHub repository is H4.

## Features

| Feature | v0.1 (MVP) | v0.2 | Later |
|---|---|---|---|
| Task schema as defined above, with validator, stable IDs, pack semver and changelog; converter that emits Harbor's task layout (task.toml with separate verifier, no-network verifier, collect hook, artifacts, timeouts, metadata carrying F2P and P2P IDs and the verification spec) | x | | |
| Base images per JDK with Android SDK; per-repo images with repo, wrapper, single read-only dependency cache, Robolectric jars, non-root user; published to GHCR, referenced by digest | x | | |
| Grader (tests/test.sh plus a JUnit XML parser), generalized from the prototype: fresh GRADLE_USER_HOME, in-image read-only cache, pinned Gradle binary, diff applied onto the pristine tree, test and build files restored, hidden tests overwritten, only named test tasks run, tampering categories from the Definitions, dependency_added detection, OOM detection, reward.json flags plus verdict.json | x | | |
| Exit-reason taxonomy, tampering flag, infra rerun policy through Harbor regrade | x | | |
| Reference agents: Harbor's oracle and no-op; saboteur as a custom Harbor agent (prototype has one) | x | | |
| Agent adapters: Harbor's Claude Code, Codex CLI, Aider, mini-swe-agent; a custom agent class for the generic command template; tool versions pinned through adapter kwargs or the image, auto-update disabled | x | | |
| Cost and token capture from Harbor's result.json; Aider reconstructed and labelled estimate; versioned pricing table | x | | |
| Attempts, bounded concurrency, agent and verification timeouts, retries, resume after crash: Harbor flags and the resume command | x | | |
| Manifest flattening (result.json, verdict.json, artifacts manifest) into JSONL; report with clustered-SE intervals, exit-reason breakdown, conditions table | x | | |
| CLI over Harbor: run, validate-task, new-task (from a PR URL, with interface-contract extraction), compare (two result sets, paired differences with CI), report, regrade-infra | x | | |
| Per-phase network allowlist of model endpoints through Harbor's egress sidecar (configuration, conditional on the nftables check) | x | | |
| MobileDev-Bench import adapter (if the Task sourcing ADR lands on import) | x | | |
| Task authoring guide and a CI job that runs validate-task and a Harbor dry run on task pull requests | x | | |
| Podman backend check through Harbor's podman environment | x | | |
| Telemetry opt-out and the key limitation documented in the README | x | | |
| Experiment mode: same tasks, two configs (with and without a skill or MCP server), paired CI, with a stated minimum detectable difference for the task count used | | x | |
| Local Maven mirror or cache proxy in the image so agent-added dependencies resolve during offline grading | | x | |
| Graders: Android Lint and detekt delta; secrets scan; manifest permission diff; debug APK size delta | | x | |
| GitHub Action: runs the harness self-tests and an opt-in paired comparison that reports an interval; never a hard pass-rate gate | | x | |
| Flutter and React Native base images and task packs | | | x |
| Emulator graders via Maestro flows; screenshot diff (Linux hosts with KVM only) | | | x |
| iOS on macOS runners | | | x |
| Task synthesis (SWE-smith style) | | | x |
| Web dashboard for browsing result sets | | | x |

Result manifest fields (write these from day one; retrofitting is painful): task id and pack version; Harbor job and trial ids; agent name, version output, flags and adapter kwargs; model id as reported; prompt-template hash; harness and Harbor versions; image digests; Gradle, AGP and JDK versions; network policy per phase; verifier mode; host CPU and RAM; environment setup, agent, and verifier phase timings; agent and verification timeouts; attempt index; retry and regrade counts; cost and tokens or missing, with cost source (reported or estimate) and pricing-table version; diff stats; files touched by category (main, test, build, ci); each grader's output; F2P and P2P per-test results; exit reason; tampering details; build and test durations.

## Development phases

### Phase 1: mobile layer on Harbor (2 to 3 weeks)

Build, in this order:
- Base and per-repo images: JDK 17 and 21, Android SDK, warmed caches in the single read-only layout from the prototype's Dockerfile, Robolectric jars, non-root user.
- Task schema v0 and the converter to Harbor's layout, including tests/original pristine copies, hidden test files, and solution/fix.patch applied by solve.sh.
- The grader, generalized from the prototype's tests/test.sh and JUnit parser: module paths and test tasks from the verification spec; tampering categories from the Definitions; dependency_added and OOM detection; reward.json flags plus verdict.json with per-test results.
- Manifest flattening into the JSONL fields above.
- Thin CLI over Harbor for run, report, validate-task, and the regrade-based infra rerun.

Dropped because Harbor provides them: the runner, container orchestration, oracle and no-op agents, adapters, attempts, concurrency, retries, resume, trajectory viewer.

Exit criteria:
- On the fixture tasks and on one hand-authored task from a seed app, through Harbor: oracle is resolved ten of ten; no-op exits no_diff ten of ten; validate-task's state B (below) exits f2p_failed or test_compile_failed ten of ten.
- CI is green on the fixture repos using the published base image and a Harbor dry run of each emitted task.

### Phase 2: real agents and metrics (1 to 2 weeks)

Build: adapter configuration and version pinning for Claude Code, Codex CLI, Aider, mini-swe-agent; the custom generic-command agent; the saboteur agent; cost capture and the Aider estimate path; clustered-SE intervals; the compare command; conditions table with per-agent flags, prompt-template hash, network policy, and the test command given; Podman check; per-run spend cap through the Claude Code adapter's budget kwarg where available.

Exit criteria:
- One real agent runs five tasks times three attempts unattended through Harbor and produces a report with intervals and an exit-reason breakdown.
- Saboteur runs are flagged on 100% of runs and counted as not resolved.
- compare on two result sets prints paired per-task differences with an interval.
- A killed job resumes; a regrade reruns only the verifier.

### Phase 3: task pack v0 (3 to 4 weeks)

Build: new-task from a PR URL (fetch the PR and its linked issue; split the test patch from the code patch; derive the verification spec; extract the interface contract; run the validation states; record source metadata; emit the Harbor layout). Write docs/TASK_AUTHORING.md. If importing MobileDev-Bench, build the adapter and run its Android-native subset through the same validation gate. Hand-mine the fresh subset: expect yield under 30% once the JVM-only, no-dependency, no-build-file, and leak filters apply, so screen 60 or more candidates for 15 tasks. Set each task's verification timeout from measured oracle time with headroom. Write a one-paragraph task card with attribution for each; note that issue text is user content not covered by the repo license.

Validation states, written out:
- State A: base commit with original tests. Run the touched modules' test tasks. Tests that pass here define P2P.
- State B: base commit plus hidden test patch. F2P tests must not pass. If the test sources do not compile here because they reference new symbols, record that and require an interface contract in the instruction.
- State C: base commit plus hidden test patch plus gold patch. Every F2P and every P2P test must pass.

Gate: states B and C run ten times each per task (compute only, no API cost). Any test that flakes even once is removed from P2P or the task is dropped. The gold patch touches only main source sets and adds no dependency. All F2P and P2P tests are JVM tests.

Instruction rules: the instruction comes from the linked issue text, never from the PR title or description, which usually names the fix. A few days after writing it, reread it and reject the task if the instruction names the solution, references files the fix touches, or is unsolvable without information outside the repo.

Exit criteria: every kept task passes the gate; task cards and the authoring guide exist; the task-PR CI job runs validate-task and a Harbor dry run.

### Phase 4: first benchmark and release (2 to 3 weeks)

See "Benchmark numbers" below. Then: README with results table above the fold and a demo GIF, raw JSONL published, v0.1.0 tagged and on PyPI, CONTRIBUTING.md with DCO, issue templates, one short write-up with three to five findings.

### Phase 5: differentiators (v0.2 onward)

In this order: experiment mode; dependency mirror in the image; lint, secrets, manifest and APK graders; GitHub Action; Flutter and React Native; emulator graders; iOS. Dogfooding on the work repo starts here, after v0.1.0 is public and with written permission.

Emulator note for planning: an Android emulator inside Docker needs KVM. Docker Desktop on Windows does not provide it reliably (nested virtualization under WSL2). Emulator graders run on Linux hosts, including GitHub's Linux runners.

Total to v0.1.0 at 10 to 15 hours per week: roughly 9 to 14 weeks. If that is too long, cut the hand-mined subset to 10 tasks and the agent list to two commercial agents plus mini-swe-agent before cutting anything in the run protocol or the validation gate.

## Testing the harness itself

The harness is a measuring instrument. Test it like one.

- **Fixture repos.** Two tiny projects under fixtures/: one pure-Kotlin JVM Gradle project (fast, runs on every push; the prototype's project is the seed) and one minimal Android library module (exercises the SDK image, runs on merges and nightly). v0.1 branches: passes, compile error, failing test, test-sources-do-not-compile, dependency added, test file edited, build script edited, init script written, gradlew replaced. v0.2 adds: lint regression, secret committed. Graders run against every branch in CI and must return the expected verdict and exit reason. CI pulls the published base image rather than building it.
- **Unit tests.** JUnit XML parser against saved report samples, including JUnit 5 method names with trailing parentheses, parameterized and dynamic tests with display names, and skipped tests (the prototype's validation already caught the parentheses case and a shell regex that rejected exit reasons containing digits; both are now regression tests). Console log parser for build failures and OOM signatures against saved Gradle logs. Schema validation for the task schema, reward.json, and verdict.json. pass@1 and clustered-SE math against a hand-computed fixture. Interface-contract extraction against saved test patches. Manifest flattening against a saved Harbor trial directory.
- **Harbor contract.** Every emitted task passes Harbor's task-model load and a dry run in CI. A pinned-version bump checklist rereads Harbor's changelog for the separate-verifier, collect-hook, and reward-file contracts before upgrading.
- **Reference-agent contracts.** Oracle must be resolved on every task in the pack. No-op must exit no_diff on every task, and state B must fail on every task. Saboteur must be flagged on every run. These run nightly as a CI matrix, one task per job, because GitHub-hosted runners have about 14 GB of free disk and per-repo images are large.
- **Determinism.** Grade the same diff twice; verdicts, exit reasons, and per-test results must be identical. Timestamps and durations are excluded from the comparison.
- **Adapter contracts.** Harbor owns the adapters; the project tests its manifest flattening against saved result.json samples from each adapter, including Aider's missing cost. One nightly job runs each real adapter on one task with a real key.
- **Limits.** A sleep-forever agent must be killed at the agent timeout and still be graded. A hanging verification must be killed at the verification timeout. An OOM-killed verifier must produce infra_error, not build_failed, and one regrade must follow.
- **Isolation.** A fixture agent that writes a Gradle init script, edits gradle.properties, replaces gradlew, or adds a convention plugin must not affect the grading stage and must be flagged as tampering.

## Benchmark numbers

Plan the numbers before Phase 4 so nothing in the design blocks them.

**Design.**
- Headline: pass@1 averaged over attempts, with a 95% interval from standard errors clustered by task. Secondary: consistency histogram, cost per resolved task, median wall time, tampering count, exit-reason breakdown.
- Headline meaning, stated in the README: "agent products as shipped, with the model pinned and named". Claude Code and Codex CLI are model-plus-scaffold bundles. A second block holds the model constant across Aider and mini-swe-agent so differences there reflect the scaffold. Report the model in every table cell.
- Agents: Claude Code, Codex CLI, Aider, mini-swe-agent. Pin agent versions through the adapters or images and model IDs in the config; record the run date.
- Attempts: three per task and agent. Spend any extra budget on more tasks, not more attempts; between-task variance dominates.
- Tasks: 20 or more in the first public run. With 20 tasks at 10 to 30% success, expect a 95% half-width of roughly 15 to 20 points, and a paired comparison between two agents to detect only differences of about 25 points or more. Compute the actual minimum detectable difference from the measured variance and print it under the table. For experiment mode, tell users that detecting a 10 to 15 point effect of a skill or MCP server needs on the order of 50 or more tasks from their own repo.
- Conditions equalized: repository state, instruction text including the test command, network policy, agent timeout, no extra skills or MCP servers in the baseline. Conditions that cannot be equalized and go in the conditions table: each agent's built-in tools, its permission or approval flags, its web-tool status, the prompt-template hash, and whether cost was reported or estimated.

**Validation gate before any public number.** Every task passes the Phase 3 gate. Any task that fails it later is fixed or dropped, and the drop appears in the pack changelog.

**Budget and compute.** Four agents times 20 tasks times three attempts is 240 runs, plus a pilot of 20 and the private set of 60, about 320 runs. Per-run cost with frontier models on multi-module Android repos is commonly 3 to 20 USD for the commercial agents, so plan on 800 to 2,000 USD and let the pilot correct it. Cap per-run spend where the adapter supports it. Compute: about 160 to 210 container-hours at up to 40 minutes per run including grading. This machine (24 cores, 32 GB) runs two or three containers in parallel and needs one to two weeks of wall time; a rented Linux box with 16 vCPUs and 64 GB, or Harbor's cloud sandbox backends, does it in a weekend. Record the hardware in the manifest; iterations inside a fixed timeout depend on it.

**Statistics.** Compare agents and configurations with paired per-task differences and a clustered interval, never by eyeballing two means. If the interval on the difference includes zero, say "no detectable difference". Publish the raw JSONL so anyone can recompute.

**Tampering and infra.** Tampered runs count as not resolved and are reported with the files they touched. Infra errors are retried once (Harbor retry for sandbox and API failures, regrade for verifier OOM), then counted as not resolved with their own exit reason. Runs that resolved the task but also touched build files are interesting edge cases; list them in the write-up.

**Contamination and targeting.** Record each task's PR merge date and report results split by whether it falls before or after each model's stated cutoff. Do not make recency a hard filter, or the pack becomes too small to mean anything. State that training-data contamination cannot be ruled out for tasks from public PRs. Separately, keep a private set of five tasks that pass the same gate; it guards against agents tuned on the public pack, carries no statistical weight on its own, and is reported as a sanity check only.

**Reporting.** A summary table with the minimum detectable difference under it, a task-by-agent heatmap, a cost-versus-pass-rate scatter, an exit-reason breakdown per agent, the conditions table, and a findings section with three to five sentences a reader will repeat. The command that reproduces the table goes directly under it.

## Publishing checklist for v0.1.0

- Results table, minimum detectable difference, and GIF in the first screen of the README.
- One-command install from PyPI; one-command run of a single task, with the image size it pulls and the pinned Harbor version stated.
- CI badge, tests, tagged release, CHANGELOG, license, DCO.
- docs/DESIGN.md with the ADRs; docs/TASK_AUTHORING.md; the key limitation, the telemetry opt-out, and the headline meaning stated.
- Raw results and the pack version published; reproduce command documented.
- Short write-up posted; link from README.
- Issue templates for "propose a task" and "add an adapter".

## Risks

| Risk | Mitigation |
|---|---|
| Hidden tests do not compile against a correct fix | Interface contract in the instruction; prefer tests on pre-existing APIs; test_compile_failed as its own exit reason. |
| Docker Desktop's WSL2 kernel lacks the nftables option Harbor needs for no-network and allowlist policies | Check immediately after install; fall back to a Linux host or cloud sandbox for grading; the task files do not change. |
| Harbor release churn and docs ahead of releases | Pin 0.24.x; bump checklist rereads the changelog for the three contracts the layer depends on; Harbor contract test in CI. |
| Verifier OOM scored as a valid zero | Grader detects the kill and writes infra_error; one regrade; counted as not resolved if it persists. |
| Gradle cold builds are slow and flaky | Layered images with a warmed cache; offline grading; only the touched test tasks; measure cold build time before accepting a seed app. |
| Dependencies of pinned commits disappear | Bake them into the per-repo image and publish it. The image is the source of truth, and the separate verifier can see nothing else. |
| Disk: about 75 GB free on C: against 5 to 15 GB per repo image | Free space or move the WSL disk before Phase 1; pull images by digest rather than building locally. |
| Task yield is low under the JVM-only and no-build-file filters | Screen 60 or more candidates; import MobileDev-Bench for volume if its licenses allow. |
| Agent fetches the upstream fix or searches for the issue | Remote stripped, no unreachable refs, web tools disabled or declared; per-phase allowlist once available. |
| Agent-written code runs in the container that has the scoped key | Dedicated low-limit keys, rotation, non-root agent user, key-less grading. Documented limitation. |
| Tampering reaches the verifier through Gradle config or a replaced wrapper | Fresh GRADLE_USER_HOME, in-image read-only cache, pinned Gradle binary, build and test files restored, hidden-test overwrite, tampering categories include init scripts and convention plugins. |
| Working from Windows: slow bind mounts, OneDrive file locks, no reliable KVM, CRLF | Run Harbor inside WSL2 with the project and jobs directory in the Linux filesystem; LF everywhere; emulator work on Linux hosts only. |
| Employer adoption blocked by Docker Desktop licensing | Harbor's Podman backend checked in v0.1. |
| Agent CLIs change output or auto-update mid-benchmark | Versions pinned through adapters or images, auto-update disabled, flattening tests with saved samples, one nightly real run. |
| First benchmark costs or takes more than expected | Mandatory pilot; per-run spend cap; rented Linux compute for the full run; budget stated in the write-up. |
| Statistics too weak to support claims | Minimum detectable difference printed under every table; more tasks before more attempts; no hard PR gate. |
| Task source licenses and provenance | Apache-2.0 or MIT apps only for the public pack; attribution in each task card; pack semver and changelog. |
| Instruction leaks the fix | Issue text only; delayed reread check in Phase 3. |
| Scope creep toward emulators and iOS | Nothing in Phase 5 starts before v0.1.0 ships. |
| Employer IP boundary | Disclosure and policy check before Phase 1; own time and machine; no work code, tasks, or prompts; dogfood only after public release. |

## Running this plan from a separate Claude Code chat

The phases above describe what to build. This section turns them into work a fresh Claude Code session can execute one package at a time, and separates out the steps only a human can do.

**Handoff.** Claude's memory for this folder is keyed to the folder path and will not follow a move, so the handoff is the files: ROADMAP.md, CLAUDE.md, docs/progress.md, docs/DESIGN.md, docs/harbor-prototype-verdict.md. CLAUDE.md exists since 2026-10-28 and loads the rules below automatically. Open the new chat inside the WSL2 Ubuntu distribution with the project in the Linux filesystem, not in OneDrive, once H2 is done. First message of the new chat: read ROADMAP.md in full, then docs/progress.md, then do the next open package.

### Human-gated items (Claude cannot do these)

- **H1.** Employer disclosure in writing and the open-source and moonlighting policy check. Before any code.
- **H2.** Enable WSL2 from an administrator shell and reboot; install Docker Desktop with the WSL2 backend; free disk or move the WSL virtual disk off C:; move the project into the WSL2 filesystem. As of 2026-10-28 none of this is done.
- **H3.** API keys: dedicated low-limit keys set in the environment of the shell that runs Claude Code and Harbor. Never pasted into a chat or a file.
- **H4.** Project name, license (Apache-2.0 recommended, matching Harbor), GitHub repository.
- **H5.** Budget approval for the pilot and the full run, and the rented-Linux-box decision.
- **H6.** Final seed-app choice. Claude ranks; you pick.

### Go/no-go checkpoints

- **G1, after H2.** The nftables kernel check passes on Docker Desktop. If not, grading moves to a Linux host or cloud sandbox before P1 starts; task files do not change.
- **G2, after P0-B.** MobileDev-Bench release and licenses are usable. Decides whether P3-C exists and how many tasks P3-B must mine.
- **G3, after P1-C.** The first Android per-repo image builds in under 45 minutes and 15 GB, and the oracle resolves a real seed-app task through Harbor. If not, change seed app before anything else.
- **G4, after P2-B.** Measured cost per run from the pilot confirms or cuts the agent list and task count before task mining starts.

### Session-sized packages, each with a done check

| Package | Needs | Work | Done when | Status (2026-10-28) |
|---|---|---|---|---|
| P0-A | human | H1, H2, H4 | Docker reachable from WSL2; G1 recorded; repo exists | Open: H1, H2 and the GitHub push are the user's |
| P0-B | nothing | Rank seed apps by merged PRs touching JVM tests in the last 12 months via the GitHub API; locate MobileDev-Bench's release and licenses; write docs/DESIGN.md with the nine ADRs; task schema v0 as a JSON schema plus converter design; check name availability; write CLAUDE.md; initialize git with DCO | Files exist; ranking table cites PR counts; G2 recorded | **Done** (docs/progress.md) |
| P0-C | Docker, keys | The prototype's verification list (verdict section 8): image build, oracle, no-op, tamper runs through Harbor, resume, regrade, one paid Claude Code run | Every item recorded with timings in the verdict | Blocked on H2; run it against `build/harbor-tasks/pricing-discount` (the converter's output), not the frozen prototype |
| P1-A | Docker | Base images for JDK 17 and 21 with Android SDK; push to GHCR; CI pulls by digest | Fixture Android module builds inside the image in CI | Blocked on H2 |
| P1-B | P1-A | Converter to Harbor layout; grader generalized from the prototype; fixtures with all v0.1 branches; CI matrix | Every fixture branch returns its expected exit reason; every emitted task passes a Harbor dry run | **Done for the JVM fixture** without Docker: converter, grader, fourteen scenarios as `probo grader-selftest`, CI job on the host JDK. Open: the Android fixture module and the Harbor dry run in CI (needs P1-A) |
| P1-C | P1-B, H6 | First per-repo image for seed app one; one hand-authored task | Oracle ten of ten, no-op ten of ten, state B ten of ten through Harbor; G3 recorded | Blocked on H2 and H6; `probo gate` implements the state A/B/C runs |
| P1-D | P1-C | Manifest flattening; thin CLI for run, report, validate-task, regrade-infra | A Harbor job produces the JSONL manifest and a rendered report | **Done against a saved sample trial layout** validated by Harbor's TrialResult model. Open: the same against a real Harbor job (needs P0-C) |
| P2-A | P1-D, keys | Adapter configuration and pinning; saboteur agent; cost capture including the Aider estimate; conditions table | One agent, one task, three attempts; saboteur flagged every time | Blocked on H2 and H3; the conditions table renderer exists |
| P2-B | P2-A, H5 | Pilot: one agent, five tasks, one attempt; statistics module with clustered SE and minimum detectable difference; compare command | Pilot report with cost per run and MDD; G4 recorded | Statistics module and `probo compare` **done** with a hand-computed fixture; the pilot is blocked on H2, H3, H5 |
| P3-A | P1-D | new-task from a PR URL with interface-contract extraction; docs/TASK_AUTHORING.md | A real PR becomes a task that passes the gate | **Draft half done**: `probo new-task` verified live on a commons-app pull request; docs/TASK_AUTHORING.md written. The gate half needs the per-repo image (H2) |
| P3-B | P3-A | Mining sprints: screen candidates, gate, task cards; repeat | 15 fresh tasks pass the gate, or the candidate pool is exhausted and the count is recorded | Open |
| P3-C | G2 yes | MobileDev-Bench import adapter; its Android-native subset through the gate | Imported tasks pass the gate; failures logged in the pack changelog | **Adapter done** (`probo import-mdb`: 230 of 328 Android rows pass the v0.1 rules, 77 from Apache-2.0 or MIT sources, all 230 validate). The gate on the imported tasks needs H2; images are 3.8 to 4.8 GiB compressed each, so plan disk per repository (docs/mobiledev-bench-images.md) |
| P4-A | P3, H5 | Full benchmark run on the chosen hardware | Raw JSONL for every run; conditions table complete | Open |
| P4-B | P4-A | README with table, MDD, GIF; write-up; v0.1.0 on PyPI; CONTRIBUTING; issue templates | Release tagged; install and single-task run work from a clean machine | CONTRIBUTING.md and a status README exist; the rest is open |

Expect 15 to 25 sessions for the fourteen packages. P0-B, P3-C's adapter and P3-A's draft command are done; the reference agents (P2-A code) and experiment mode (Phase 5) can still be built without Docker; everything else from P0-C onward waits on H2.

### Rules for every session (go into CLAUDE.md)

- Read the Definitions and Run protocol sections before touching the grader. Do not reopen a settled ADR without new evidence; write new evidence into docs/.
- One package per session. End by running the package's done check and pasting its output into docs/progress.md with the date.
- No keys in files or chat. No paid agent run without the per-run spend cap set.
- Commit at the end of each package with DCO sign-off once the repo exists.
- The grader's two known bugs (JUnit 5 parentheses, digits in exit reasons) have regression tests; never remove them.

## Review log

### v2.2 to v2.3 (2026-10-28, autonomous build session)

- Name: Probo. Availability evidence and rejected names in docs/DESIGN.md.
- P0-B completed in full (docs/progress.md). G2 resolved to yes on the evidence in docs/mobiledev-bench.md; the Task sourcing ADR is now settled on import plus a fresh hand-mined subset. Seed apps ranked with GitHub API data in docs/seed-apps.md; the roadmap's earlier leading candidates were half right: DuckDuckGo leads by far, Thunderbird is third and already MobileDev-Bench's largest source, Mihon has no JVM-test PRs at all, and Home Assistant Android, not previously listed, is second.
- The Docker-independent parts of Phase 1 were built and verified on the host JDK, so P1-B and P1-D are partly done ahead of P1-A; the package table now carries a Status column. The thin-slice rule stands: P0-C runs the converter's output through Harbor before any Android image is built.
- Grader taxonomy clarified: `no_diff` sits after `tampered` and before `build_failed` in the precedence (it was listed as an exit reason but absent from the precedence line); `agent_error` is assigned by the result flattener from Harbor's exception info, never by the grader; a `gradle` directory inside a source set is code, not configuration.
- Machine check: WSL2 and Docker still not installed on 2026-10-28; Harbor 0.24.0 and JDK 21 present; Gradle 8.14.3 fetched to a scratch directory for the host-JDK runs.

### v2.1 to v2.2 (2026-10-28)

- Added "Running this plan from a separate Claude Code chat": human-gated items, go/no-go checkpoints, fourteen session-sized packages with done checks, and the rules that go into CLAUDE.md. Machine check on 2026-10-28: WSL2 and Docker still not installed; folder unchanged since 2026-10-17.
- Pilot cost measurement moved earlier, to P2-B, so the budget is known before task mining.
- Thin-slice rule made explicit: the JVM prototype runs end to end through Harbor (P0-C) before any Android image is built.

### v2 to v2.1 (2026-10-17, Harbor prototype findings folded in)

Source: docs/harbor-prototype-verdict.md and prototype/harbor-gradle-task/, produced by the Phase 0 prototype session against Harbor 0.24.0. Docker was not installed on the machine, so the verdict is provisional; its grader passed nine of nine local scenarios on the host JDK.
- Exit-reason precedence fixed: tampered takes precedence over every test outcome, and because any added dependency is a build-file edit, dependency_added cannot be its own exit reason in v0.1. It is now a detail flag inside tampered, promoted to an exit reason in v0.2 when the dependency mirror lands. The prototype's scenario table surfaced this: the fix-plus-dependency case exited tampered.

- Base framework ADR resolved: build on Harbor 0.24.x, pinned, with explicit revisit conditions. The standalone Phase 1 work list is removed; Phase 1 and 2 durations shrink and the total drops to 9 to 14 weeks.
- Harbor's license corrected to Apache-2.0 from the repository itself; third-party listings saying MIT were wrong.
- Exit reasons: Harbor's reward file is numeric, so the grader writes reward.json with numeric flags plus verdict.json carrying the string exit reason and per-test results; the mobile layer flattens Harbor's result.json, verdict.json, and artifacts manifest into the JSONL manifest.
- Cache baking: the separate verifier receives no host mounts, so the warmed dependency cache lives in the image as a single read-only cache (no duplicate copy, distribution zip deleted), and the grader runs the image-pinned Gradle binary instead of the project's gradlew.
- OOM gap: a verifier OOM yields a valid reward of 0 that Harbor does not retry; the grader detects the kill, writes infra_error, and the layer reruns through Harbor's regrade command once.
- Windows prerequisites added as Phase 0 deliverables: WSL2 (Windows Home has no Hyper-V), Docker Desktop on WSL2, the nftables kernel check that no-network and allowlist policies depend on, disk space (about 75 GB free against 5 to 15 GB per image), running Harbor inside WSL2 with project and jobs out of OneDrive, LF endings.
- Network policy ADR updated: Harbor's per-phase egress allowlist covers the v0.2 egress proxy, so it becomes v0.1 configuration conditional on the kernel check.
- Null agent semantics corrected: Harbor's no-op agent produces no diff, so it exits no_diff; the F2P-must-fail check is state B of validate-task, not the no-op run.
- Diff capture through a collect hook with bounded exposure documented; API key scoped to the agent's exec calls and scrubbed from job files; agents run as root by default, so images get a non-root user; telemetry opt-out documented.
- Adapter facts: Claude Code, Codex, OpenHands, mini-swe-agent report tokens and cost; Aider reports neither, so its cost is an estimate labelled as such; per-run spend cap available through the Claude Code adapter.
- Two grader bugs the prototype found become regression tests: JUnit 5 method names with trailing parentheses, and a shell regex rejecting exit reasons containing digits. Fixture branches gain init-script and replaced-gradlew cases.
- Harbor contract test (task-model load and dry run) added to CI, and a pinned-version bump checklist.
- Python floor set to 3.12, Harbor's requirement.
- Risks added: nftables on Docker Desktop, Harbor release churn, verifier OOM, disk space.

### v1 to v2 (2026-10-17, two review passes)

Two passes: my own, then an independent read by a second reviewer who had not seen my notes. Items marked (independent) came only from the second pass.

Errors fixed:
- new-task and compare were in v0.2 but needed in Phase 3 and Phase 4. Moved to v0.1.
- mini-swe-agent appeared in the ADRs and benchmark design but not in the features, Phase 2, or the budget (independent). Added; budget recomputed for four agents.
- The task schema had no gold patch and no executable verification spec, so the oracle and the gate could not run (independent). Added.
- Tampered runs were excluded from the denominator, which rewards tampering (independent). They now count as not resolved.
- Refactor tasks cannot fail the null agent because they have no Fail-to-Pass test (independent). Dropped from v0.1 kinds.
- Two CI methods were named; the paper has no numeric worked example to test against (independent). One method, clustered standard errors, tested against a hand-computed fixture.
- pass^3 at three reps is a single bit per task and near zero at realistic rates (independent). Replaced with a consistency histogram.
- Three oracle runs only catch flake rates above about 30% (independent). Gate raised to ten runs per state; any flaking test removed.
- The GitHub Action pass-rate gate on a PR cannot detect a real drop at affordable task counts (independent). Replaced with self-tests plus an opt-in paired comparison.
- Fixture branches required lint and secrets graders that do not exist until v0.2 (independent). Split into v0.1 and v0.2 branches.
- A public leaderboard in Later contradicted the non-goals (independent). Removed.
- The private task set was described as a contamination control; it guards against targeting, not training data (independent). Reworded.
- Non-goals treated SWE-bench Mobile as a public Android comparator; it is iOS-only and hosted (independent). Corrected.
- MobileDev-Bench was understated and its import deferred to v0.2 while 20 tasks were hand-mined next to its 407 (independent). Import is now the recommended v0.1 volume source, conditional on its release and licenses.
- The three validation states were misdescribed and did not account for test patches that fail to compile at base (independent). Written out precisely; P2P derived from state A.
- Harbor's license was asserted as MIT; only third-party listings said so (independent). Marked for confirmation, and confirmed Apache-2.0 in v2.1.
- Seed apps: Tivi discontinued November 2024; Element Android relicensed and in maintenance; Now in Android is a poor PR source (independent for the last two). Replaced with a selection criterion and new leading candidates.
- The determinism test required byte-identical output, which timestamps make impossible. Now compares verdicts only.
- The manifest listed a seed field; agent CLIs do not take seeds. Removed.
- "Same tool access for every agent" cannot be met. Replaced with equalizable conditions plus a conditions table including permission flags and prompt hash.
- Contamination guidance used post-cutoff commits as a filter, which would empty the pack. Changed to merge-date split.
- Phase 1 referenced a real task before the task tooling existed and omitted the per-repo image layer (independent for the layer). Fixed.
- Budget of 0.50 to 5 USD per run and "a few hundred dollars" was too low; compute time was absent (independent for compute). Replaced with 3 to 20 USD per run, 800 to 2,000 USD total, and container-hours with a hardware recommendation.
- Phase durations were two to three times too short for the scope (independent). Replaced with ranges at a stated hours-per-week, with a scope-cut order.
- Crucible could not be verified by either reviewer. Removed. iOSWorld now carries its arXiv ID.

Gaps filled:
- Hidden-test compile coupling, the largest technical risk: interface contract, preference for pre-existing APIs, test_compile_failed exit reason (independent).
- Definitions of task, resolved, exit reasons, tampering, verifiable tests, and interface contract.
- A run protocol with agent stage, capture, key-less offline grading stage, fresh GRADLE_USER_HOME, hidden-file overwrite, missing P2P counts as failed (verifier isolation details independent).
- Network and information-leak policy: remote stripping, web tools, egress allowlist (independent).
- Security of running agent-written code with an API key present.
- Infra-failure policy with retry once and no denominator exclusion (independent for OOM classification).
- JVM-only verification, Robolectric jars and wrapper distribution pre-fetched, toolchain auto-provisioning disabled, only touched test tasks run (independent for toolchains and task scoping).
- Gradle offline policy for agent-added dependencies with a dependency_added exit reason, and a mirror in v0.2.
- Scaffold-versus-model separation and a stated headline meaning (independent for the headline meaning).
- Minimum detectable difference printed under every table; more tasks before more reps; experiment-mode power note (independent).
- Yield planning: screen 60 or more candidates for 15 tasks (independent).
- Image distribution: GHCR, digests, size budget, one-task-per-job matrix for runner disk limits (independent).
- Manifest fields: agent flags, prompt hash, pack version, network policy, host spec, toolchain versions, retry count, pricing-table version, agent version output; auto-update disabled (independent).
- Task-pack versioning and provenance; issue text as user content (independent).
- Employer sequencing: disclosure before Phase 1, DCO from the first commit, dogfood after public release (independent).
- Podman compatibility for employer adoption (independent).
- Windows specifics: WSL2 filesystem, move out of OneDrive, no reliable KVM in Docker Desktop.
