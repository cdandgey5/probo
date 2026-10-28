# Commands that reproduce every run

All paths are relative to the project root
(`C:\Users\natas\OneDrive\Documents\Claude\GenericSkill`) unless stated.
Harbor 0.24.0 is installed as a uv tool on this machine (`harbor --version`).

Status on 2026-10-17: the Docker-backed runs in sections 3 to 6 have **not**
been executed, because Docker is not installed on this PC (see
`docs/harbor-prototype-verdict.md`, section 1). Sections 1 and 2 were run and
their output is recorded in the verdict; section 7 lists commands for later.

## 0. Prerequisites

```powershell
docker info                     # daemon reachable
python --version                # 3.12 or newer (Harbor needs >= 3.12)
uv --version
uv tool install harbor          # once; `uv tool upgrade harbor` later
harbor --version                # 0.24.0 at the time of writing
```

Keep Harbor's job output outside OneDrive (bind mounts and file locks are
slow and flaky there). The examples below write to `C:\harbor-jobs`.

## 1. Validate the task without Docker (done)

Loads `task.toml`, the instruction and the script paths through Harbor's own
task model, then resolves the job config. `--dry-run` stops at the Docker
preflight on a machine without Docker.

```powershell
harbor run -p prototype\harbor-gradle-task -a oracle --dry-run
harbor run -p prototype\harbor-gradle-task -a oracle -k 3 -n 1 --job-name probe --print-config
```

## 2. Validate the grader on the host JDK, no Docker (done)

Runs `tests/test.sh` against nine synthetic agent outcomes (gold patch, empty
diff, tampered tests, tampered tests plus fix, tampered build file, wrong fix,
broken build, plus two shared-container variants) using the same fresh
`GRADLE_USER_HOME`, read-only dependency cache and pinned distribution the
container uses. Needs a JDK on `PATH`, Git Bash, an unpacked Gradle 8.14.3 and
a warm Gradle home that has built the project once.

```bash
# one-time: fetch and unpack Gradle 8.14.3 into a scratch directory
curl -L -o /tmp/gradle-8.14.3-bin.zip https://services.gradle.org/distributions/gradle-8.14.3-bin.zip
echo "bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531 */tmp/gradle-8.14.3-bin.zip" | sha256sum -c
unzip -q /tmp/gradle-8.14.3-bin.zip -d /tmp/gradle-dist
```

```bash
# one-time: warm a Gradle home by building the project once (downloads dependencies)
cd prototype/harbor-gradle-task/environment/repo
GRADLE_USER_HOME=/tmp/gradle-home-warm /tmp/gradle-dist/gradle-8.14.3/bin/gradle --no-daemon --console=plain test
```

```bash
# the validation itself; prints PASS/FAIL per scenario and a summary line
bash prototype/harbor-gradle-task/local/validate-grader.sh /tmp/gradle-dist/gradle-8.14.3 /tmp/gradle-home-warm /tmp/validate
```

## 3. Build the image and measure it (not run yet)

Harbor builds the image itself on the first trial (content-addressed tag
`hb__<hash>`, reused until the context changes; `--force-build` rebuilds).
To measure build time and size independently:

```powershell
Measure-Command { docker build -t harbor-gradle-task:local prototype\harbor-gradle-task\environment }
docker image inspect harbor-gradle-task:local --format '{{.Size}}'
```

## 4. Oracle and no-op runs (not run yet)

```powershell
harbor run -p prototype\harbor-gradle-task -a oracle -o C:\harbor-jobs --job-name oracle -n 1
harbor run -p prototype\harbor-gradle-task -a nop    -o C:\harbor-jobs --job-name nop    -n 1
```

Expected: oracle reward 1 with `exit_reason` `resolved`; nop reward 0 with
`exit_reason` `no_diff`. Three repetitions of either: add `-k 3`.

Where to look, per trial directory under `C:\harbor-jobs\<job-name>\<trial>\`:

| File | Content |
|---|---|
| `result.json` | reward, `agent_info.version`, `agent_result` (tokens, `cost_usd`), timing per phase, `verifier_environment_mode`, `exception_info` |
| `verifier/reward.txt` | the reward the grader wrote |
| `verifier/verdict.json` | exit reason, tampered files, Gradle exit code, verify seconds (written by `tests/test.sh`) |
| `verifier/test-results.json` | per-test status parsed from JUnit XML |
| `verifier/gradle-test.log`, `verifier/agent-diff.patch`, `verifier/changed-files.txt` | build log and the diff the grader applied |
| `artifacts/tmp/harbor-capture/agent.patch` | the diff captured in the agent container by the collect hook |
| `agent/` | agent logs (`oracle.txt` for the oracle; Claude Code session logs and `trajectory.json` for Claude Code) |
| `config.json`, `trial.log` | resolved trial config and Harbor's log |

Exit codes and timings to record: the `harbor run` exit code, and from
`result.json` the `environment_setup`, `agent_execution` and `verifier`
`started_at`/`finished_at` pairs.

## 5. Tampering agent (not run yet)

A custom agent that rewrites the test file so every test trivially passes and
does not fix the bug. The module must be importable by the Harbor process,
hence `PYTHONPATH`.

```powershell
$env:PYTHONPATH = "prototype\harbor-gradle-task"
harbor run -p prototype\harbor-gradle-task -a agents.tamper_agent:TamperAgent -o C:\harbor-jobs --job-name tamper -n 1
```

Expected: reward 0, `exit_reason` `tampered`,
`tampered_files` naming `src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt`.

## 6. One paid Claude Code run (not run yet; only with a key set)

At most one run. The kwargs are Harbor agent options that map to Claude
Code's own flags (`harbor agent schema claude-code` lists them): `max_turns`,
`max_budget_usd` (a string), `disable_web_search` (default false, so set it),
`version` (pin the CLI version Harbor installs; omit for latest) and
`permission_mode` (default `bypassPermissions`). Harbor reads the key from
`ANTHROPIC_API_KEY` (also `ANTHROPIC_AUTH_TOKEN` or `CLAUDE_CODE_OAUTH_TOKEN`)
and passes it only to the agent phase.

```powershell
$env:ANTHROPIC_API_KEY = "<key>"
harbor run -p prototype\harbor-gradle-task -a claude-code -m anthropic/claude-sonnet-5-5 `
  --ak max_turns=30 --ak max_budget_usd=2 --ak disable_web_search=true `
  -o C:\harbor-jobs --job-name claude-code -n 1
```

Expected: reward 1, `exit_reason` `resolved`, and `result.json` carrying
`agent_info.version` (from `claude --version` inside the container) and
`agent_result.cost_usd` (from the final `total_cost_usd` line of Claude Code's
stream-json output, falling back to a LiteLLM estimate).

## 7. Other Harbor commands worth knowing

```powershell
harbor job resume -p C:\harbor-jobs\oracle          # continue a crashed or interrupted job
harbor job regrade C:\harbor-jobs\oracle -p prototype\harbor-gradle-task   # rerun only the verifier on recorded trials
harbor view C:\harbor-jobs                           # browser UI for trajectories, verifier logs, artifacts
harbor task start-env -p prototype\harbor-gradle-task -e docker -a -i      # interactive shell in the task image
harbor agent schema claude-code                      # kwargs the adapter accepts
harbor agent list                                    # built-in agent names
harbor task schema                                   # task.toml JSON schema
harbor job schema                                    # job config JSON schema
```

Not in 0.24.0 although the docs describe them: `harbor lint` and
`harbor agent auth`. The docs track the main branch.
