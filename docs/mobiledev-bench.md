# MobileDev-Bench as a task source: import feasibility

Date: 2026-10-28
Scope: can MobileDev-Bench (arXiv 2603.24946) be legally and practically imported as a task source into an Apache-2.0 evaluation harness for AI coding agents on Android/Gradle repositories?

Each fact below is marked **found** (with the URL it was read from) or **not found**. Quotes are verbatim and under 15 words. Counts marked "API" were obtained from the Hugging Face datasets-server query API against the published dataset, without downloading it.

## Bottom line

Yes, importable. The release is public and complete: harness code on GitHub under the **MIT License**, the task dataset on Hugging Face tagged **cc-by-4.0**, and per-PR Docker images on GHCR that pull anonymously. Of the 407 tasks, **328 are Android-native (319 Kotlin + 9 Java)**, all run through `./gradlew`, and **309 of those 328 invoke a Gradle `*UnitTest` task** (JVM local unit tests); zero task commands contain `connected` or `androidTest`, and the paper states that emulator-requiring instrumentation tests were excluded. The remaining 19 Android tasks use some other Gradle invocation that I could not enumerate through the API (likely but unverified JVM-only). The one legal caveat is not the benchmark's own licenses but the upstream apps: the `fix_patch`/`test_patch` diffs and the container contents are code from 19 apps under GPLv2/GPLv3/AGPLv3/Apache-2.0/MIT/EPL-2.0, so an Apache-2.0 harness should keep imported patches as clearly labeled data with upstream license notices rather than treat them as Apache-2.0 source.

## 1. The paper

| Item | Status | Value |
|---|---|---|
| arXiv ID | found | 2603.24946 is correct. https://arxiv.org/abs/2603.24946 |
| Title | found | "MobileDev-Bench: A Benchmark for Issue Resolution in Mobile Application Development" (https://arxiv.org/abs/2603.24946) |
| Authors | found | Moshood A. Fakorede, Krishna Upadhyay, A. B. Siddique, Umar Farooq (https://arxiv.org/abs/2603.24946) |
| Affiliation | found (partial) | Project page links to Louisiana State University (https://mobiledev-bench.github.io/). Other affiliations not verified on the paper page. |
| Dates | found | v1 "Thu, 26 Mar 2026 02:31:03 UTC"; v2 "Fri, 8 May 2026 03:25:28 UTC" (https://arxiv.org/abs/2603.24946v2) |
| Comments field | found | "30 pages, 14 figures, 12 tables." No code link in the comments field. (https://arxiv.org/abs/2603.24946) |
| Paper license | found | arXiv HTML header shows "License: CC BY 4.0" (covers the paper text, not the dataset). https://arxiv.org/html/2603.24946v2 |
| Release claim in abstract | found | "We release MobileDev-Bench with task instances, an evaluation harness, and containerized environments" (https://arxiv.org/abs/2603.24946v2) |
| Version differences | found | v1 reported 384 tasks from 18 repos; v2 reports 407 tasks from 19 repos (https://arxiv.org/html/2603.24946v1, https://arxiv.org/html/2603.24946v2). A search-engine snippet claimed the HF card says "415"; the HF page contains no "415" and shows 407 (https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench). |
| Other venues | found | A NeurIPS-format PDF is hosted at https://mobiledev-bench.github.io/static/pdfs/MobileDev_Bench_NeurIPS.pdf (30 pages). |

## 2. Code and data release

| Component | Status | URL |
|---|---|---|
| Project page | found | https://mobiledev-bench.github.io/ |
| Harness code (GitHub) | found | https://github.com/MobileDev-Bench/mobiledev-bench |
| Task dataset (Hugging Face) | found | https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench (single `test` split, file `data/test.jsonl`, 407 rows in the viewer) |
| Container images (GHCR) | found | https://github.com/orgs/MobileDev-Bench/packages (19 public container packages, one per source repo, tags `pr-<number>`) |
| Image naming | found | Pull script builds `ghcr.io/${GHCR_USERNAME}/${repo_name}:${tag}` with default user `mobiledev-bench`; list file uses `mobiledevbench/{org}_mb_{repo}:pr-{number}` (https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/scripts/pull_images_from_ghcr.sh, https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/scripts/images.txt). Example shown on a package page: `docker pull ghcr.io/mobiledev-bench/mobiledevbench/thunderbird_mb_thunderbird-android:pr-9150` (https://github.com/orgs/MobileDev-Bench/packages/container/package/mobiledevbench%2Fthunderbird_mb_thunderbird-android) |
| Image visibility | found | Package page shows visibility "Public"; pull script has no `docker login` step. |
| Image count | found | `scripts/images.txt` has approximately 407 lines (one per task), per the fetch tool's count; exact count not re-verified. |
| Dataset last update | found | HF commit log: "Anonymize for double-blind submission" (Sep 26), "Update citation" (Sep 22), several README updates in May; year not shown on the page (https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/commits/main) |
| Harness requirements | found | Python 3.10+, `uv`, Docker; `.env` with `OPENROUTER_API_KEY` and `GITHUB_TOKENS` (https://github.com/MobileDev-Bench/mobiledev-bench) |
| Citation | found | README says the citation is "_to be updated_" (https://github.com/MobileDev-Bench/mobiledev-bench) |

## 3. Licenses

| Asset | Status | License, exactly as stated | Source |
|---|---|---|---|
| Harness code | found | LICENSE file begins "MIT License" / "Copyright (c) 2026 MobileDev-Bench"; GitHub sidebar shows "MIT license" | https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/LICENSE, https://github.com/MobileDev-Bench/mobiledev-bench |
| Task dataset | found | Dataset card YAML: `license: cc-by-4.0`. No other license text on the card. | https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/raw/main/README.md |
| Container images | not found | No license, README, or terms shown on the GHCR org or package pages. Package description is "An optimized docker image includes Android, Kotlin, Flutter sdk." (inherited from the base image). | https://github.com/orgs/MobileDev-Bench/packages |
| Base image for Android containers | found | Harness Dockerfile dependency is `mingc/android-build-box:1.29.0`; that project's GitHub sidebar shows "MIT license". | https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/mobiledev_bench/harness/repos/kotlin/thunderbird/thunderbirdandroid.py, https://github.com/mingchen/docker-android-build-box |
| Benchmark license stated in paper | not found | The paper has no license statement for the dataset, harness, or containers; only the arXiv CC BY 4.0 header for the paper. | https://arxiv.org/html/2603.24946v2 |

### Source apps and their licenses (paper Table 5, "Summary and licenses for all GitHub repositories")

Found at https://arxiv.org/html/2603.24946v2 (Table 2 for counts, Table 5 for licenses). Per-repo task counts below were independently confirmed from the dataset's `repo` column (API, https://datasets-server.huggingface.co/statistics?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test). Verify each license against the repo's own LICENSE file before redistributing anything derived from it.

| Platform | Repo (org/name) | Tasks | License per Table 5 |
|---|---|---|---|
| Android | thunderbird/thunderbird-android | 100 | Apache 2.0 |
| Android | wordpress-mobile/WordPress-Android | 84 | GPLv2 |
| Android | element-hq/element-x-android | 68 | AGPLv3 |
| Android | streetcomplete/StreetComplete | 18 | GPLv3 |
| Android | tuskyapp/Tusky | 12 | GPLv3 |
| Android | commons-app/apps-android-commons | 10 | Apache 2.0 |
| Android (Java) | AntennaPod/AntennaPod | 9 | GPLv3 |
| Android | openhab/openhab-android | 8 | EPL 2.0 |
| Android | Futsch1/medTimer | 8 | MIT |
| Android | PaulWoitaschek/Voice | 4 | GPLv3 |
| Android | LemmyNet/jerboa | 4 | AGPLv3 |
| Android | mjaakko/NeoStumbler | 2 | MIT |
| Android | JackEblan/Geto | 1 | GPLv3 |
| Flutter | zulip/zulip-flutter | 51 | Apache 2.0 |
| Flutter | PalisadoesFoundation/talawa | 12 | GPLv3 |
| React Native | NMF-earth/nmf-app | 11 | GPLv3 |
| React Native | Expensify/App | 2 | MIT |
| React Native | RocketChat/Rocket.Chat.ReactNative | 2 | MIT |
| React Native | artsy/eigen | 1 | MIT |

Totals: Android-native 328 across 13 repos; Flutter 63 across 2; React Native 16 across 4; 19 repos, 407 tasks.

The dataset card lists the same 19 repos but "does not list per-repo licenses" (https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/blob/main/README.md). The paper does not say whether the apps' licenses apply to the benchmark data.

## 4. Task format

| Item | Status | Detail | Source |
|---|---|---|---|
| Dataset fields | found | `instance_id, org, repo, number, state, title, body, base, resolved_issues, lang, problem_statement, hints, pull_url, issue_urls, fix_patch, test_patch, test_command, fixed_tests, f2p_tests, p2p_tests, s2p_tests, n2p_tests, run_result, test_patch_result, fix_patch_result` | https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/blob/main/README.md |
| Pinned base commit | found | `base` is "JSON object with base branch label, ref, and SHA"; observed value has keys `label`, `ref`, `sha` (40-hex SHA). | card README; API row at https://datasets-server.huggingface.co/filter?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&where=%22test_command%22%20LIKE%20%27%25UnitTest%25%27&offset=0&length=1 |
| Gold patch | found | `fix_patch` field (the project page calls it "fix patch"). | card README; https://mobiledev-bench.github.io/ |
| Hidden test patch | found | `test_patch` field. | card README |
| Fail-to-Pass / Pass-to-Pass IDs | found | `f2p_tests` = "JSON list of Fail-to-Pass test names"; `p2p_tests`, `s2p_tests` (Skip-to-Pass), `n2p_tests` (None-to-Pass). In the observed row these are JSON objects keyed by test name (e.g. `fr.free.nrw.commons.delete.ReasonBuilderTest.forceLoginWhenAccountIsNull`) with per-stage statuses `run`/`test`/`fix`; `p2p_tests` was `{}`. | card README; API row above |
| Test command | found | `test_command` = "Shell command to execute the relevant test suite". Example: `./gradlew :app:testBetaDebugUnitTest --tests "fr.free.nrw.commons.delete.ReasonBuilderTest"` | card README; API row above |
| Dockerfiles | found | Not checked in as files. Generated in code: per-repo Python classes under `mobiledev_bench/harness/repos/{dart,java,kotlin,typescript}/<org>/<repo>.py` emit `FROM {image_name}` / `FROM {name}:{tag}`; base tag `base`, instance tag `pr-{number}`; Android base dependency `mingc/android-build-box:1.29.0`; JDK chosen by `detect_jdk.sh` (8/11/17/21, default 17). | https://github.com/MobileDev-Bench/mobiledev-bench/tree/main/mobiledev_bench/harness/repos, https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/mobiledev_bench/harness/repos/kotlin/thunderbird/thunderbirdandroid.py |
| Execution scripts | found | `run.sh`, `test-run.sh`, `fix-run.sh` run `{test_cmd} --no-daemon --stacktrace --continue --parallel || true` after `./gradlew clean`; default `test_cmd` is `./gradlew clean test --max-workers 8` when the task has none. Results parsed from JUnit XML `<testcase>` elements into `ClassName.testName`. | thunderbirdandroid.py (URL above) |
| Harness modes | found | `--mode` one of `evaluation`, `instance`, `instance_only`, `image`; `--use_remote_images true` pulls from GHCR; `--ghcr_username` defaults to `mobiledev-bench`; per-instance `report.json`, aggregate `final_report.json`. | https://github.com/MobileDev-Bench/mobiledev-bench, https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/mobiledev_bench/harness/README.md |
| Platform split | found | `lang` column: kotlin 319, java 9, dart 63, typescript 16 (API statistics). Paper Table 10: Android Native 80.6%, Flutter 15.5%, React Native 3.9%, i.e. 328 / 63 / 16. | https://datasets-server.huggingface.co/statistics?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test, https://arxiv.org/html/2603.24946v2 |
| Difficulty tiers | found | Easy 138, Medium 139, Hard 130. | card README |
| Android test runner per paper | found | "we run instance-specific test commands derived from the PR's CI configuration"; "we execute module-specific Gradle tasks (e.g., :feature:login:testDebugUnitTest) rather than the top-level test task."; "We default to the Debug build variant." The paper does not name Robolectric. | https://arxiv.org/html/2603.24946v2 |
| Emulator / instrumented tests | found | "Android instrumentation tests that require emulators are excluded due to reproducibility concerns." | https://arxiv.org/html/2603.24946v2 (also present in the NeurIPS PDF text) |
| React Native / Flutter runners | found | RN: "we verify Node.js compatibility and run tests via npm or yarn."; Flutter: "we confirm Flutter SDK compatibility and execute the test framework." | https://arxiv.org/html/2603.24946v2 |

## 5. Android-native tasks verifiable with JVM-only tests

Counts obtained with the datasets-server `filter` endpoint (`num_rows_total`), without downloading the dataset:

| Query on `test_command` | Rows | Status |
|---|---|---|
| contains `gradlew` | 328 | found (equals all 319 Kotlin + 9 Java rows) |
| contains `UnitTest` (any lang) | 309 | found |
| `lang='kotlin'` and contains `UnitTest` | 300 | found |
| `lang='java'` and contains `UnitTest` | 9 | found (example: `./gradlew :net:download:service:testFreeDebugUnitTest --tests ...`, AntennaPod) |
| `repo='element-x-android'` and contains `UnitTest` | 68 of 68 | found |
| contains `connected` | 0 | found |
| contains `androidTest` | 0 | found |

Query URL pattern: `https://datasets-server.huggingface.co/filter?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&where=<clause>&offset=0&length=1`.

Result: **at least 309 of the 328 Android-native tasks are verified by Gradle local-unit-test tasks (`test<Variant>UnitTest`), which run on the JVM with no emulator.** The other 19 (all Kotlin) use a Gradle command without a `*UnitTest` task name in it. Probes for `jvmTest`, `allTests`, and bare `:test ` returned HTTP 500 from the datasets-server repeatedly, and the API rejects `NOT LIKE`, so the exact tasks for those 19 are **not determinable without downloading `data/test.jsonl`**. Since no command contains `connected` or `androidTest` and the paper excludes emulator tests, they are probably JVM-only too, but that is unverified.

Robolectric: a full-text search for "robolectric" matches 47 rows, but in the sampled row the hit was in `fix_patch` build files, not in `test_command` (https://datasets-server.huggingface.co/search?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&query=robolectric&offset=0&length=1). Whether a given task's unit tests run under Robolectric is not determinable from the API; Robolectric tests still execute in the JVM via the same `*UnitTest` tasks.

## 6. Restrictions on redistribution or derivative benchmarks

| Source | Status | Finding |
|---|---|---|
| Harness repo (README, LICENSE) | found | MIT only; no additional terms. https://github.com/MobileDev-Bench/mobiledev-bench |
| Dataset card | found | `license: cc-by-4.0`; the card "contains no sentences" on licensing, attribution, redistribution, or derivatives beyond the tag; no gating or terms-acceptance notice. https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/raw/main/README.md |
| Paper (arXiv v2) | found | No redistribution or derivative-benchmark terms. Appendix J ethics text asks for "human oversight when deploying model-generated patches" in sensitive components; Appendix I notes iOS was excluded because Xcode's license restricts non-Apple hardware. https://arxiv.org/html/2603.24946v2 |
| NeurIPS PDF | found | Keyword scan of decompressed page streams found no benchmark license or redistribution statement; only Table 5 app licenses and the selection criterion "an open-source license". URLs in the PDF: the HF dataset and https://github.com/multi-swe-bench/MagentLess (cited as the retrieval baseline). https://mobiledev-bench.github.io/static/pdfs/MobileDev_Bench_NeurIPS.pdf |
| GHCR images | not found | No terms shown. https://github.com/orgs/MobileDev-Bench/packages |

### Practical and legal notes (analysis, not found facts)

- The MIT harness code is compatible with inclusion in an Apache-2.0 project (keep the MIT notice).
- CC-BY-4.0 on the dataset requires attribution to the MobileDev-Bench authors and a link to the license; derivative benchmarks are permitted by CC-BY-4.0.
- The dataset's `fix_patch` and `test_patch` contents, and the source trees inside the GHCR images, are code from the 19 upstream apps. The CC-BY-4.0 tag cannot relicense that code; 9 of the 13 Android repos (WordPress-Android, element-x-android, StreetComplete, Tusky, AntennaPod, openhab-android, Voice, jerboa, Geto; 208 of the 328 Android tasks) are under copyleft or weak-copyleft licenses (GPLv2, GPLv3, AGPLv3, EPL-2.0). Treat imported patches as data files with per-repo license notices, or fetch them at run time from Hugging Face instead of vendoring them.
- The harness design (base commit + `test_command` + F2P/P2P names + per-PR GHCR image) maps directly onto a SWE-bench-style importer; the harness's `repos/kotlin/<org>/<repo>.py` classes are the reference for how each repo's Gradle invocation and JDK selection were set up.

## Sources

- https://arxiv.org/abs/2603.24946
- https://arxiv.org/abs/2603.24946v2
- https://arxiv.org/html/2603.24946v1
- https://arxiv.org/html/2603.24946v2
- https://mobiledev-bench.github.io/
- https://mobiledev-bench.github.io/static/pdfs/MobileDev_Bench_NeurIPS.pdf
- https://github.com/MobileDev-Bench/mobiledev-bench
- https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/LICENSE
- https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/scripts/pull_images_from_ghcr.sh
- https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/scripts/images.txt
- https://github.com/MobileDev-Bench/mobiledev-bench/tree/main/mobiledev_bench/harness
- https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/mobiledev_bench/harness/README.md
- https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/mobiledev_bench/harness/image.py
- https://github.com/MobileDev-Bench/mobiledev-bench/tree/main/mobiledev_bench/harness/repos
- https://github.com/MobileDev-Bench/mobiledev-bench/tree/main/mobiledev_bench/harness/repos/kotlin
- https://github.com/MobileDev-Bench/mobiledev-bench/tree/main/mobiledev_bench/harness/repos/java
- https://raw.githubusercontent.com/MobileDev-Bench/mobiledev-bench/main/mobiledev_bench/harness/repos/kotlin/thunderbird/thunderbirdandroid.py
- https://github.com/orgs/MobileDev-Bench/packages
- https://github.com/orgs/MobileDev-Bench/packages/container/package/mobiledevbench%2Fthunderbird_mb_thunderbird-android
- https://github.com/mingchen/docker-android-build-box
- https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench
- https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/raw/main/README.md
- https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/blob/main/README.md
- https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench/commits/main
- https://datasets-server.huggingface.co/size?dataset=MobileDev-Bench/mobiledev-bench
- https://datasets-server.huggingface.co/statistics?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test
- https://datasets-server.huggingface.co/filter?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&where=%22test_command%22%20LIKE%20%27%25UnitTest%25%27&offset=0&length=1
- https://datasets-server.huggingface.co/filter?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&where=%22test_command%22%20LIKE%20%27%25gradlew%25%27&offset=0&length=1
- https://datasets-server.huggingface.co/filter?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&where=%22test_command%22%20LIKE%20%27%25connected%25%27&offset=0&length=1
- https://datasets-server.huggingface.co/filter?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&where=%22test_command%22%20LIKE%20%27%25androidTest%25%27&offset=0&length=1
- https://datasets-server.huggingface.co/search?dataset=MobileDev-Bench/mobiledev-bench&config=default&split=test&query=robolectric&offset=0&length=1
