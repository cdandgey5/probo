"""Unit tests for the grader's pure functions: path classification, dependency
detection, JUnit parsing, Gradle log classification and exit-reason precedence.

The two bugs the Phase 0 prototype found are regression tests here and must
never be removed: JUnit 5 method names with trailing parentheses, and exit
reasons containing digits (``f2p_failed``, ``p2p_failed``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from probo.grader import grade as g

# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,category",
    [
        ("src/main/kotlin/com/example/A.kt", "main"),
        ("app/src/main/java/com/example/A.java", "main"),
        ("app/src/main/res/values/strings.xml", "main"),
        ("app/src/demoDebug/kotlin/Flavour.kt", "main"),
        ("app/src/main/kotlin/com/example/gradle/Plugin.kt", "main"),
        ("src/test/kotlin/ATest.kt", "test"),
        ("app/src/androidTest/java/T.java", "test"),
        ("app/src/testDebug/kotlin/T.kt", "test"),
        ("app/src/androidTestDemo/kotlin/T.kt", "test"),
        ("core/src/commonTest/kotlin/T.kt", "test"),
        ("core/src/jvmTest/kotlin/T.kt", "test"),
        ("lib/src/sharedTest/kotlin/T.kt", "test"),
        ("app/src/testFixtures/kotlin/F.kt", "test"),
        ("app/src/test/resources/fixture.json", "test"),
        ("build.gradle.kts", "build"),
        ("app/build.gradle", "build"),
        ("settings.gradle.kts", "build"),
        ("gradle.properties", "build"),
        ("app/gradle.properties", "build"),
        ("gradle/libs.versions.toml", "build"),
        ("gradle/wrapper/gradle-wrapper.jar", "build"),
        ("gradle/wrapper/gradle-wrapper.properties", "build"),
        ("gradlew", "build"),
        ("gradlew.bat", "build"),
        ("buildSrc/src/main/kotlin/Convention.kt", "build"),
        ("build-logic/convention/src/main/kotlin/X.kt", "build"),
        ("gradle/build-logic/convention/build.gradle.kts", "build"),
        ("init.gradle.kts", "build"),
        ("init.gradle", "build"),
        ("scripts/evil.init.gradle", "build"),
        ("scripts/common.gradle", "build"),
        ("init.d/x.gradle", "build"),
        (".github/workflows/ci.yml", "ci"),
        (".gitlab-ci.yml", "ci"),
        ("Jenkinsfile", "ci"),
        ("bitrise.yml", "ci"),
        (".circleci/config.yml", "ci"),
        ("README.md", "other"),
        ("app/proguard-rules.pro", "other"),
        ("docs/design.md", "other"),
    ],
)
def test_classify_path(path: str, category: str) -> None:
    assert g.classify_path(path) == category


def test_classify_path_extra_protected_and_windows_separators() -> None:
    assert g.classify_path("app\\src\\main\\kotlin\\A.kt") == "main"
    assert g.classify_path("./gradlew") == "build"
    assert g.classify_path("app/schemas/1.json", extra_protected=[r"^app/schemas/"]) == "build"
    assert g.is_protected("app/schemas/1.json", [r"^app/schemas/"])
    assert not g.is_protected("app/src/main/kotlin/A.kt")


# ---------------------------------------------------------------------------
# dependency_added
# ---------------------------------------------------------------------------


def _diff(path: str, added: list[str]) -> str:
    body = "\n".join("+" + line for line in added)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,{len(added) + 1} @@\n context\n{body}\n"


def test_dependency_added_kotlin_dsl() -> None:
    d = _diff("build.gradle.kts", ['    testImplementation("org.assertj:assertj-core:3.27.3")'])
    assert g.find_dependency_additions(d) == ["build.gradle.kts"]


def test_dependency_added_groovy_dsl_and_catalog_reference() -> None:
    d = _diff(
        "app/build.gradle",
        [
            "    implementation 'com.squareup.okhttp3:okhttp:4.12.0'",
            "    debugImplementation libs.leakcanary",
        ],
    )
    assert g.find_dependency_additions(d) == ["app/build.gradle"]


def test_dependency_added_version_catalog() -> None:
    d = _diff(
        "gradle/libs.versions.toml",
        ['okhttp = { module = "com.squareup.okhttp3:okhttp", version = "4.12.0" }'],
    )
    assert g.find_dependency_additions(d) == ["gradle/libs.versions.toml"]
    d2 = _diff("gradle/libs.versions.toml", ['okhttp = "com.squareup.okhttp3:okhttp:4.12.0"'])
    assert g.find_dependency_additions(d2) == ["gradle/libs.versions.toml"]
    # A version bump is not a new dependency.
    d3 = _diff("gradle/libs.versions.toml", ['kotlin = "2.2.0"'])
    assert g.find_dependency_additions(d3) == []


def test_dependency_added_ignores_non_build_files_and_comments() -> None:
    d = _diff("src/main/kotlin/A.kt", ['val implementation = "x"', "implementation(foo)"])
    assert g.find_dependency_additions(d) == []
    d2 = _diff("build.gradle.kts", ['// implementation("not really")', "    jvmToolchain(17)"])
    assert g.find_dependency_additions(d2) == []


def test_dependency_added_multi_file_diff_tracks_current_file() -> None:
    d = _diff("README.md", ['implementation("decoy")']) + _diff("build.gradle.kts", ["    api(libs.coil)"])
    assert g.find_dependency_additions(d) == ["build.gradle.kts"]


# ---------------------------------------------------------------------------
# JUnit XML
# ---------------------------------------------------------------------------

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.example.pricing.DiscountCalculatorTest" tests="6" skipped="1" failures="1" errors="1">
  <testcase name="fullDiscountYieldsZero()" classname="com.example.pricing.DiscountCalculatorTest" time="0.001"/>
  <testcase name="halfDiscountHalvesPrice()" classname="com.example.pricing.DiscountCalculatorTest" time="0.001">
    <failure message="expected 100 but was 99" type="org.opentest4j.AssertionFailedError">trace</failure>
  </testcase>
  <testcase name="explodes()" classname="com.example.pricing.DiscountCalculatorTest" time="0.001">
    <error message="boom" type="java.lang.IllegalStateException">trace</error>
  </testcase>
  <testcase name="later()" classname="com.example.pricing.DiscountCalculatorTest" time="0.0">
    <skipped/>
  </testcase>
  <testcase name="add(int, int)[1]" classname="com.example.pricing.DiscountCalculatorTest" time="0.001"/>
  <testcase name="[2] a=1, b=2" classname="com.example.pricing.DiscountCalculatorTest" time="0.001"/>
</testsuite>
"""


def test_normalize_test_id_regression_parentheses() -> None:
    assert g.normalize_test_id("a.B#c()") == "a.B#c"
    assert g.normalize_test_id("a.B#c") == "a.B#c"
    assert g.normalize_test_id("a.B#add(int, int)[1]") == "a.B#add(int, int)[1]"
    assert g.normalize_test_id("  a.B#c()  ") == "a.B#c"


def test_parse_junit_reports(tmp_path: Path) -> None:
    report = tmp_path / "TEST-com.example.pricing.DiscountCalculatorTest.xml"
    report.write_text(_XML, encoding="utf-8")
    bad = tmp_path / "TEST-broken.xml"
    bad.write_text("<testsuite><testcase", encoding="utf-8")
    status, warnings = g.parse_junit_reports([str(report), str(bad)])
    cls = "com.example.pricing.DiscountCalculatorTest"
    assert status[f"{cls}#fullDiscountYieldsZero"] == "passed"
    assert status[f"{cls}#halfDiscountHalvesPrice"] == "failed"
    assert status[f"{cls}#explodes"] == "error"
    assert status[f"{cls}#later"] == "skipped"
    assert status[f"{cls}#add(int, int)[1]"] == "passed"
    assert status[f"{cls}#[2] a=1, b=2"] == "passed"
    assert len(warnings) == 1 and "TEST-broken.xml" in warnings[0]


def test_expected_statuses_missing_counts_as_not_passed() -> None:
    status = {"a.T#x": "passed"}
    out = g.expected_statuses(status, ["a.T#x()", "a.T#y"])
    assert out == {"a.T#x": "passed", "a.T#y": "missing"}


def test_find_junit_reports(tmp_path: Path) -> None:
    d = tmp_path / "app" / "build" / "test-results" / "testDebugUnitTest"
    d.mkdir(parents=True)
    (d / "TEST-a.xml").write_text("<testsuite/>")
    (d / "binary").mkdir()
    found = g.find_junit_reports(str(tmp_path), ["app/build/test-results/testDebugUnitTest", "missing/dir"])
    assert [Path(p).name for p in found] == ["TEST-a.xml"]


@pytest.mark.parametrize(
    "task,expected",
    [
        (":test", "build/test-results/test"),
        (":app:testDebugUnitTest", "app/build/test-results/testDebugUnitTest"),
        (
            ":feature:settings:testDemoDebugUnitTest",
            "feature/settings/build/test-results/testDemoDebugUnitTest",
        ),
    ],
)
def test_gradle_task_to_results_dir(task: str, expected: str) -> None:
    assert g.gradle_task_to_results_dir(task) == expected


def test_gradle_task_to_results_dir_rejects_unqualified() -> None:
    with pytest.raises(ValueError):
        g.gradle_task_to_results_dir("test")


# ---------------------------------------------------------------------------
# Gradle log classification
# ---------------------------------------------------------------------------


def test_classify_gradle_log_main_compile_failure() -> None:
    log = (
        "> Task :compileKotlin FAILED\n"
        "e: file:///app/src/main/kotlin/X.kt:5:1 Expecting an element\n"
        "FAILURE: Build failed with an exception.\n"
        "* What went wrong:\nExecution failed for task ':compileKotlin'.\n"
    )
    info = g.classify_gradle_log(log)
    assert info["failed_tasks"] == [":compileKotlin"]
    assert info["main_compile_failed"] == [":compileKotlin"]
    assert info["test_compile_failed"] == []
    assert info["oom"] is False


def test_classify_gradle_log_test_compile_failure_android() -> None:
    log = (
        "> Task :app:compileDebugKotlin\n> Task :app:compileDebugUnitTestKotlin FAILED\n"
        "e: file:///app/app/src/test/kotlin/T.kt:3:8 Unresolved reference 'NewApi'\n"
        "Execution failed for task ':app:compileDebugUnitTestKotlin'.\n"
    )
    info = g.classify_gradle_log(log)
    assert info["test_compile_failed"] == [":app:compileDebugUnitTestKotlin"]
    assert info["main_compile_failed"] == []


def test_classify_gradle_log_java_and_kapt_variants() -> None:
    assert g.is_test_compile(":app:compileDebugUnitTestJavaWithJavac")
    assert g.is_test_compile(":compileTestJava")
    assert g.is_compile_like(":app:kaptDebugKotlin") and not g.is_test_compile(":app:kaptDebugKotlin")
    assert not g.is_compile_like(":app:testDebugUnitTest")
    assert not g.is_compile_like(":app:processDebugResources")


def test_classify_gradle_log_oom_and_unresolved() -> None:
    assert g.classify_gradle_log("Gradle build daemon disappeared unexpectedly\n")["oom"] is True
    assert g.classify_gradle_log("java.lang.OutOfMemoryError: Java heap space\n")["oom"] is True
    assert (
        g.classify_gradle_log("Process 'Gradle Test Executor 1' finished with non-zero exit value 137\n")[
            "oom"
        ]
        is True
    )
    info = g.classify_gradle_log(
        "Could not resolve all dependencies for configuration ':testRuntimeClasspath'.\n"
    )
    assert info["unresolved_dependency"] is True
    assert g.classify_gradle_log("BUILD SUCCESSFUL in 40s\n")["unresolved_dependency"] is False


# ---------------------------------------------------------------------------
# Exit reason precedence
# ---------------------------------------------------------------------------

_OK = {"a.T#f": "passed"}
_BAD = {"a.T#f": "failed"}


def _decide(**over: object) -> str:
    kw: dict[str, object] = {
        "infra_error": False,
        "timed_out": False,
        "tampered": False,
        "no_diff": False,
        "main_compile_failed": False,
        "test_compile_failed": False,
        "n_reports": 1,
        "f2p": _OK,
        "p2p": _OK,
    }
    kw.update(over)
    return g.decide_exit_reason(**kw)  # type: ignore[arg-type]


def test_exit_reason_taxonomy_is_closed_and_digits_are_allowed() -> None:
    assert set(g.EXIT_REASONS) == {
        "resolved",
        "test_compile_failed",
        "f2p_failed",
        "p2p_failed",
        "build_failed",
        "no_diff",
        "agent_error",
        "timeout",
        "tampered",
        "infra_error",
    }
    # Regression: the prototype's shell regex [a-z_]* rejected these.
    assert _decide(f2p=_BAD) == "f2p_failed"
    assert _decide(p2p=_BAD) == "p2p_failed"
    assert json.loads(json.dumps({"exit_reason": "f2p_failed"}))["exit_reason"] == "f2p_failed"


def test_exit_reason_precedence() -> None:
    assert _decide() == "resolved"
    assert _decide(infra_error=True, timed_out=True, tampered=True, no_diff=True) == "infra_error"
    assert _decide(timed_out=True, tampered=True, no_diff=True) == "timeout"
    assert _decide(tampered=True, no_diff=True, main_compile_failed=True) == "tampered"
    assert _decide(no_diff=True, main_compile_failed=True, f2p=_BAD) == "no_diff"
    assert _decide(main_compile_failed=True, test_compile_failed=True, f2p=_BAD) == "build_failed"
    assert _decide(n_reports=0) == "build_failed"
    assert _decide(n_reports=0, test_compile_failed=True) == "test_compile_failed"
    assert _decide(test_compile_failed=True, f2p={"a.T#f": "missing"}) == "test_compile_failed"
    assert _decide(f2p={"a.T#f": "missing"}) == "f2p_failed"
    assert _decide(f2p={}) == "f2p_failed"
    assert _decide(p2p={"a.T#g": "skipped"}) == "p2p_failed"
    assert _decide(p2p={}) == "resolved"


# ---------------------------------------------------------------------------
# Verdict serialisation
# ---------------------------------------------------------------------------


def test_verdict_reward_flags(tmp_path: Path) -> None:
    v = g.Verdict("t", "0.0.0")
    v.tests["f2p"] = {"a.T#f": "passed"}
    v.tests["p2p"] = {"a.T#g": "failed"}
    v.tampered_files = ["gradlew"]
    v.exit_reason = "tampered"
    g.write_outputs(str(tmp_path), v, {"a.T#f": "passed"})
    reward = json.loads((tmp_path / "reward.json").read_text())
    assert reward == {"reward": 0, "f2p": 1, "p2p": 0, "tampered": 1}
    assert (tmp_path / "reward.txt").read_text().strip() == "0"
    verdict = json.loads((tmp_path / "verdict.json").read_text())
    assert verdict["schema"] == "probo-verdict/1"
    assert verdict["exit_reason"] == "tampered"
    assert verdict["tampered_files"] == ["gradlew"]
    assert json.loads((tmp_path / "test-results.json").read_text())["status"] == {"a.T#f": "passed"}


def test_remove_build_outputs_only_next_to_gradle_scripts(tmp_path: Path) -> None:
    (tmp_path / "settings.gradle.kts").write_text("")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "x").write_text("")
    (tmp_path / ".gradle").mkdir()
    src_build = tmp_path / "src" / "main" / "kotlin" / "build"
    src_build.mkdir(parents=True)
    (src_build / "Keep.kt").write_text("")
    g.remove_build_outputs(str(tmp_path))
    assert not (tmp_path / "build").exists()
    assert not (tmp_path / ".gradle").exists()
    assert (src_build / "Keep.kt").exists()
