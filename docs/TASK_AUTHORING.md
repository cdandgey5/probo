# Task authoring guide

How a merged pull request becomes a Probo task, and the gate it must pass
before it enters a pack. The schema itself is in TASK_SCHEMA.md; the
rules behind the gate are in ROADMAP.md (Definitions, Phase 3).

## 1. Pick a candidate

A good candidate is a merged pull request in an Apache-2.0 or MIT Android or
Gradle repository that fixes an issue someone described in words, changes
main sources only, adds or changes JVM unit tests (Robolectric is fine,
instrumented tests are not), and adds no dependency. Expect to screen four
candidates for every task that survives the gate.

Rejected at once: pull requests that edit build scripts, `gradle.properties`,
version catalogs, the wrapper, `buildSrc`/`build-logic` or CI; pull requests
whose tests only exist as `androidTest`; refactors with no failing test;
pull requests without a linked issue (the instruction must come from an
issue, never from the pull request's title or description, which usually
names the fix).

## 2. Draft it

```bash
uv run probo new-task https://github.com/<owner>/<repo>/pull/<n> -o tasks/drafts
```

The command reads the pull request, its merge commit, the linked issue and
the build files at the base commit through `gh api` (your own GitHub login).
It writes:

| File | Content |
|---|---|
| `probo.toml` | Source metadata (repository, license, base commit, pull request, issue, merge date), the Gradle test tasks of the touched modules with `--tests` filters for the touched test classes, Fail-to-Pass candidates (every new `@Test` method in the test patch), the interface contract (declarations the fix adds that the tests reference), toolchain versions read from the wrapper and the version catalog, Android-sized limits. |
| `instruction.md` | The linked issue's title and body, verbatim. A placeholder if no issue is linked. |
| `gold.patch` | The main-source part of the merge commit's diff (non-source files such as changelogs are included and listed in the notes). |
| `hidden.patch` | The test-source part of the diff. |
| `NOTES.md` | Blocking problems, everything that still needs a human, and the checklist below. |

The base commit is the first parent of the merge commit, not the pull
request's recorded base, which is often stale. If the pull request is not
merged the draft says so and uses the branch instead.

## 3. Finish it by hand

Read `NOTES.md`. The usual items:

- **Variant.** Android modules with product flavors need the right unit-test
  task (for example `:app:testDemoDebugUnitTest`); the draft guesses
  `testDebugUnitTest`.
- **Instruction.** Reread it a few days later. Reject the task if it names
  the solution, references files the fix touches (`validate-task` warns), or
  cannot be solved without information outside the repository. Issue text is
  user content; the task card says so.
- **Interface contract.** Keep it only when the hidden tests reference
  symbols the fix introduces; prefer tasks whose tests use pre-existing APIs.
- **Image.** Build the per-repo image, push it to GHCR and set
  `environment.docker_image` by digest.
- **License.** Only Apache-2.0 and MIT sources enter the public pack.

Then:

```bash
uv run probo validate-task tasks/drafts/<task id>
```

## 4. The gate

With Docker (or, for pure JVM modules, a host JDK and a warm Gradle home):

```bash
uv run probo convert tasks/drafts/<task id> -o build/harbor-tasks
uv run probo gate build/harbor-tasks/<task id> --runs 10 --gradle-dist <dist> --warm-home <home>
```

State A (base commit, original tests) defines Pass-to-Pass: copy the tests
that pass into `p2p`. State B (base plus hidden tests) must fail every
Fail-to-Pass test; if the test sources do not compile, the instruction needs
an interface contract. State C (base plus hidden tests plus gold patch) must
pass everything. Ten runs per state; a test that flakes once is dropped from
`p2p` or the task is dropped. Then the oracle must resolve the task ten of
ten times through Harbor and the no-op agent must exit `no_diff` ten of ten.

Record the measured verification time and set `verify_timeout_sec` with
headroom. Move the task from `tasks/drafts` into its pack, delete
`NOTES.md`, and add a line to the pack changelog.

## 5. Imported tasks

`probo import-mdb` produces the same layout from MobileDev-Bench rows
(tasks/mobiledev-bench/README.md). They skip step 2 but not steps 3 and 4:
the gate decides whether they enter a pack, and `environment.jdk` and
`gradle` are filled from the checkout when it runs.
