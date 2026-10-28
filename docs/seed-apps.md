# Seed-app candidates: merged-PR and test-activity ranking

Date: 2026-10-28 (data pulled 2026-10-28T12:07:45Z)

## Method

All numbers come from the GitHub API through the `gh` CLI (script: `scratchpad/seed_apps/collect_seed_apps.py`; raw numbers in `docs/data/seed-apps.json`); no repository was cloned. For each candidate the `repos` endpoint supplied the license SPDX id, default branch, last push, stars and archived flag. "Merged PRs 12mo" is `total_count` from `search/issues` with `repo:OWNER/NAME is:pr is:merged merged:>=2025-10-28`. The test-activity sample is the 150 most recently updated merged PRs from GraphQL (`pullRequests(states: MERGED, orderBy: UPDATED_AT DESC)`, 3 pages of 50, first 100 changed files per PR); only PRs with `mergedAt >= 2025-10-28` are counted, so "sample in window" can be below 150. A PR "touches JVM tests" if at least one changed path matches `(^|/)src/(test|testDebug|testRelease|test[A-Z][A-Za-z]*)/.*\.(kt|java)$` and not `(^|/)src/androidTest`. "androidTest-only" counts PRs whose only test changes are under `src/androidTest*/` (no JVM-test file); the JSON also records PRs consisting of nothing but androidTest files. The 12-month estimate is (fraction touching JVM tests in the sample) x (merged PRs 12mo). Gradle modules is the number of `build.gradle(.kts)` files in the default-branch tree (`git/trees?recursive=1`, root build file included); the wrapper version is parsed from `gradle/wrapper/gradle-wrapper.properties` and the AGP version from `gradle/libs.versions.toml` (an `agp` / `android-gradle-plugin` / `androidGradlePlugin` key, falling back to resolving the `com.android.*` plugin entry).

## Ranking (sorted by estimated 12-month merged PRs touching JVM tests)

| Repo | License | Stars | Last push | Merged PRs 12mo | Sample in window | Fraction touching JVM tests | Est. 12mo JVM-test PRs | androidTest-only PRs in sample | Gradle modules | Wrapper | AGP | buildSrc / build-logic / catalog |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [duckduckgo/Android](https://github.com/duckduckgo/Android) | Apache-2.0 | 4,879 | 2026-10-28 | 2,634 | 148 of 150 | 0.655 (97/148) | 1726 | 2 | 203 | 9.8.0 | no catalog | yes / no / no |
| [Automattic/pocket-casts-android](https://github.com/Automattic/pocket-casts-android) | MPL-2.0 | 2,850 | 2026-10-28 | 1,363 | 150 of 150 | 0.547 (82/150) | 745 | 2 | 48 | 9.8.1 | 9.4.1 | no / no / yes |
| [bitwarden/android](https://github.com/bitwarden/android) | GPL-3.0 | 9,553 | 2026-10-27 | 1,028 | 149 of 150 | 0.503 (75/149) | 517 | 0 | 11 | 9.8.0 | 9.4.1 | no / no / yes |
| [wordpress-mobile/WordPress-Android](https://github.com/wordpress-mobile/WordPress-Android) | GPL-2.0 | 3,152 | 2026-10-28 | 878 | 150 of 150 | 0.460 (69/150) | 404 | 3 | 13 | 9.5.0 | 9.3.1 | no / no / yes |
| [home-assistant/android](https://github.com/home-assistant/android) | Apache-2.0 | 4,003 | 2026-10-28 | 1,060 | 148 of 150 | 0.250 (37/148) | 265 | 0 | 10 | 9.8.2 | 9.4.1 | no / yes / yes |
| [thunderbird/thunderbird-android](https://github.com/thunderbird/thunderbird-android) | Apache-2.0 | 14,151 | 2026-10-28 | 802 | 104 of 150 | 0.298 (31/104) | 239 | 0 | 161 | 9.7.0 | 9.2.1 | no / no / yes |
| [wikimedia/apps-android-wikipedia](https://github.com/wikimedia/apps-android-wikipedia) | Apache-2.0 | 3,049 | 2026-10-28 | 934 | 149 of 150 | 0.148 (22/149) | 138 | 1 | 3 | 9.8.2 | 9.4.1 | no / no / yes |
| [nextcloud/android](https://github.com/nextcloud/android) | GPL-2.0 | 5,652 | 2026-10-28 | 1,298 | 150 of 150 | 0.073 (11/150) | 95 | 24 | 3 | 9.8.2 | 9.4.1 | no / no / yes |
| [commons-app/apps-android-commons](https://github.com/commons-app/apps-android-commons) | Apache-2.0 | 1,191 | 2026-10-27 | 148 | 139 of 150 | 0.317 (44/139) | 47 | 2 | 2 | 8.13 | 8.13.0 | no / no / yes |
| [AntennaPod/AntennaPod](https://github.com/AntennaPod/AntennaPod) | GPL-3.0 | 8,248 | 2026-10-25 | 306 | 148 of 150 | 0.088 (13/148) | 27 | 2 | 38 | 9.3.1 | 9.0.1 | no / no / yes |
| [openfoodfacts/openfoodfacts-androidapp](https://github.com/openfoodfacts/openfoodfacts-androidapp) | Apache-2.0 | 806 | 2026-10-26 | 75 | 75 of 150 | 0.013 (1/75) | 1 | 0 | 2 | 7.6.1 | 7.4.2 | no / no / yes |
| [mihonapp/mihon](https://github.com/mihonapp/mihon) | Apache-2.0 | 24,792 | 2026-10-26 | 593 | 149 of 150 | 0.000 (0/149) | 0 | 0 | 19 | 9.8.2 | 9.4.1 | no / no (nested: gradle/build-logic) / yes |

## Reading the table

Hard license filter: only Apache-2.0 and MIT qualify for the public task pack; MPL-2.0, GPL and AGPL fail it.

- Pass (Apache-2.0 / MIT): duckduckgo/Android (Apache-2.0), home-assistant/android (Apache-2.0), thunderbird/thunderbird-android (Apache-2.0), wikimedia/apps-android-wikipedia (Apache-2.0), commons-app/apps-android-commons (Apache-2.0), openfoodfacts/openfoodfacts-androidapp (Apache-2.0), mihonapp/mihon (Apache-2.0)
- Fail the hard license filter: Automattic/pocket-casts-android (MPL-2.0), bitwarden/android (GPL-3.0), wordpress-mobile/WordPress-Android (GPL-2.0), nextcloud/android (GPL-2.0), AntennaPod/AntennaPod (GPL-3.0)
- Archived repositories: none
- Samples with fewer than 150 PRs in the 12-month window (the sample is ordered by last update, so older PRs that were recently touched fall outside the window): duckduckgo/Android (148 of 150), bitwarden/android (149 of 150), home-assistant/android (148 of 150), thunderbird/thunderbird-android (104 of 150), wikimedia/apps-android-wikipedia (149 of 150), commons-app/apps-android-commons (139 of 150), AntennaPod/AntennaPod (148 of 150), openfoodfacts/openfoodfacts-androidapp (75 of 150), mihonapp/mihon (149 of 150)
- Merge-date coverage of the in-window sample (a short span means the fraction reflects only the most recent weeks of activity): duckduckgo/Android (2026-10-14 to 2026-10-28), Automattic/pocket-casts-android (2026-09-28 to 2026-10-28), bitwarden/android (2026-03-27 to 2026-10-27), wordpress-mobile/WordPress-Android (2026-08-31 to 2026-10-28), home-assistant/android (2026-07-29 to 2026-10-28), thunderbird/thunderbird-android (2026-09-16 to 2026-10-26), wikimedia/apps-android-wikipedia (2026-09-17 to 2026-10-27), nextcloud/android (2026-07-22 to 2026-10-28), commons-app/apps-android-commons (2025-11-30 to 2026-10-27), AntennaPod/AntennaPod (2026-05-14 to 2026-10-11), openfoodfacts/openfoodfacts-androidapp (2026-06-15 to 2026-09-22), mihonapp/mihon (2025-11-07 to 2026-10-26)
- Sample equals the whole 12-month population (so the estimate is an exact count, not an extrapolation): openfoodfacts/openfoodfacts-androidapp (75 of 75)
- In-window PRs with more than 100 changed files (only the first 100 paths were inspected, so a test file could be missed): duckduckgo/Android (5), wordpress-mobile/WordPress-Android (2), thunderbird/thunderbird-android (3), nextcloud/android (1), mihonapp/mihon (4)
- Default-branch trees reported as truncated by the API (module count would be a lower bound): none
- API calls that failed: none.
- The androidTest-only column counts sampled in-window PRs whose only test changes are instrumented tests; the JSON additionally has `prs_touching_android_tests` and `prs_only_android_test_files` per repo.
- The estimate is a sample-based extrapolation, not a measured count; with ~150 sampled PRs the sampling error on the fraction is roughly +/-0.07 at 95% confidence.

## Not measured

- Cold build time was not measured: it requires cloning each repository and running a full Gradle build, which this data pull deliberately did not do.
- Test runtime, flakiness, and whether the JVM test suites actually pass on the default branch were likewise not measured.
