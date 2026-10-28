"""End-to-end runs of ``grade.grade`` against a tiny git repository and a fake
Gradle binary (tests/fake_gradle.py), so the whole flow (patch application,
diff listing, tampering, restore, hidden-test overwrite, build-output removal,
verdict files) is covered in milliseconds without a JDK.

Scenarios mirror ``probo grader-selftest``, which runs the real Gradle."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from probo.grader import grade as g
from probo.grader.grade import rmtree

CLS = "com.example.pricing.DiscountCalculatorTest"
MAIN = "src/main/kotlin/Calc.kt"
TEST = "src/test/kotlin/CalcTest.kt"
BASE_MAIN = (
    "object DiscountCalculator { fun applyDiscount(p: Long, pct: Int) = p - p * pct.coerceIn(0, 99) / 100 }\n"
)
FIXED_MAIN = BASE_MAIN.replace("coerceIn(0, 99)", "coerceIn(0, 100)")
BASE_TEST = "class CalcTest { fun halfDiscountHalvesPrice() {} fun zeroDiscountKeepsPrice() {} }\n"
HIDDEN_TEST = BASE_TEST.replace("}\n", " fun fullDiscountYieldsZero() {} }\n")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def fake_gradle(tmp_path: Path) -> Path:
    d = tmp_path / "fake-gradle" / "bin"
    d.mkdir(parents=True)
    script = Path(__file__).with_name("fake_gradle.py")
    if os.name == "nt":
        bat = d / "gradle.bat"
        bat.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        (d / "gradle").write_text("", encoding="utf-8")  # existence check only
        return d / "gradle"
    sh = d / "gradle"
    sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    sh.chmod(0o755)
    return sh


@pytest.fixture
def pristine(tmp_path: Path) -> Path:
    repo = tmp_path / "pristine"
    for rel, text in {
        "settings.gradle.kts": 'rootProject.name = "calc"\n',
        "build.gradle.kts": 'plugins { kotlin("jvm") version "2.2.0" }\n',
        "gradle.properties": "org.gradle.daemon=false\n",
        "gradlew": "#!/bin/sh\necho wrapper\n",
        MAIN: BASE_MAIN,
        TEST: BASE_TEST,
        ".gitignore": "build/\n.gradle/\n",
    }.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


@pytest.fixture
def tests_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tests"
    (d / "hidden" / "src" / "test" / "kotlin").mkdir(parents=True)
    (d / "hidden" / TEST).write_text(HIDDEN_TEST, encoding="utf-8", newline="\n")
    spec = {
        "task_id": "calc",
        "pack_version": "0.0.0",
        "test_tasks": [":test"],
        "f2p": [f"{CLS}#fullDiscountYieldsZero"],
        "p2p": [f"{CLS}#halfDiscountHalvesPrice", f"{CLS}#zeroDiscountKeepsPrice"],
        "hidden_tests": [TEST],
        "gradle_timeout_sec": 30,
    }
    (d / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return d


class Harness:
    def __init__(self, tmp_path: Path, pristine: Path, tests_dir: Path, fake_gradle: Path):
        self.tmp = tmp_path
        self.pristine = pristine
        self.tests_dir = tests_dir
        self.gradle = fake_gradle
        self.spec = json.loads((tests_dir / "spec.json").read_text())

    def mutate_patch(self, mutate) -> str:  # type: ignore[no-untyped-def]
        scratch = self.tmp / "scratch"
        if scratch.exists():
            rmtree(str(scratch))
        shutil.copytree(self.pristine, scratch)
        mutate(scratch)
        _git(scratch, "add", "-A")
        return _git(scratch, "diff", "--cached", "--binary", "HEAD")

    def grade(
        self, patch: str, shared: bool = False, extra_env: dict[str, str] | None = None
    ) -> tuple[g.Verdict, Path]:
        app = self.tmp / "app"
        if app.exists():
            rmtree(str(app))
        shutil.copytree(self.pristine, app)
        capture = self.tmp / "capture"
        capture.mkdir(exist_ok=True)
        out = self.tmp / "out"
        if out.exists():
            rmtree(str(out))
        if shared and patch.strip():
            (self.tmp / "in.patch").write_text(patch, encoding="utf-8", newline="\n")
            _git(app, "apply", str(self.tmp / "in.patch"))
            (capture / "agent.patch").write_text("", encoding="utf-8")
        else:
            (capture / "agent.patch").write_text(patch, encoding="utf-8", newline="\n")
        env = {
            "APP_DIR": str(app),
            "TESTS_DIR": str(self.tests_dir),
            "OUT_DIR": str(out),
            "CAPTURE_DIR": str(capture),
            "GRADLE_BIN": str(self.gradle),
            "RO_CACHE": str(self.tmp / "ro-cache"),
            "TMPDIR": str(self.tmp),
        }
        env.update(extra_env or {})
        old = {k: os.environ.get(k) for k in ("FAKE_GRADLE_SLEEP", "FAKE_GRADLE_OOM")}
        for k in old:
            os.environ.pop(k, None)
        for k in ("FAKE_GRADLE_SLEEP", "FAKE_GRADLE_OOM"):
            if k in env:
                os.environ[k] = env[k]
        try:
            verdict = g.grade(g.Settings(env), self.spec)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return verdict, app


@pytest.fixture
def h(tmp_path: Path, pristine: Path, tests_dir: Path, fake_gradle: Path) -> Harness:
    return Harness(tmp_path, pristine, tests_dir, fake_gradle)


def _fix(t: Path) -> None:
    (t / MAIN).write_text(FIXED_MAIN, encoding="utf-8", newline="\n")


def test_oracle_is_resolved_and_outputs_written(h: Harness) -> None:
    v, app = h.grade(h.mutate_patch(_fix))
    assert v.exit_reason == "resolved" and v.reward == 1
    assert v.verifier_mode == "separate"
    assert v.hidden_files_written == [TEST]
    assert (app / TEST).read_text() == HIDDEN_TEST
    out = Path(h.tmp / "out")
    assert json.loads((out / "reward.json").read_text()) == {"reward": 1, "f2p": 1, "p2p": 1, "tampered": 0}
    verdict = json.loads((out / "verdict.json").read_text())
    assert verdict["files_by_category"]["main"] == [MAIN]
    assert verdict["diff_stats"]["files"] == 1
    assert (out / "agent-diff.patch").read_text().startswith("diff --git")
    assert (out / "gradle-test.log").read_text().strip()


def test_nop_is_no_diff(h: Harness) -> None:
    v, _ = h.grade("")
    assert v.exit_reason == "no_diff" and v.reward == 0
    assert v.diff_stats["files"] == 0
    assert v.tests["f2p"] == {f"{CLS}#fullDiscountYieldsZero": "failed"}


def test_wrong_fix_is_f2p_failed(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(lambda t: (t / MAIN).write_text(BASE_MAIN + "// touched\n")))
    assert v.exit_reason == "f2p_failed"


def test_tampered_tests_are_restored_and_flagged(h: Harness) -> None:
    def tamper(t: Path) -> None:
        _fix(t)
        (t / TEST).write_text("class CalcTest {}\n")

    v, app = h.grade(h.mutate_patch(tamper))
    assert v.exit_reason == "tampered" and v.reward == 0
    assert v.tampered_files == [TEST]
    assert v.restored_files == [TEST]
    # The hidden test replaced the tampered file before the build ran.
    assert (app / TEST).read_text() == HIDDEN_TEST
    assert v.reward_json()["tampered"] == 1


def test_dependency_added_detail(h: Harness) -> None:
    def add_dep(t: Path) -> None:
        _fix(t)
        with (t / "build.gradle.kts").open("a") as fh:
            fh.write('dependencies { testImplementation("org.assertj:assertj-core:3.27.3") }\n')

    v, app = h.grade(h.mutate_patch(add_dep))
    assert v.exit_reason == "tampered"
    assert v.detail["dependency_added"] is True
    assert v.detail["dependency_added_files"] == ["build.gradle.kts"]
    assert (app / "build.gradle.kts").read_text() == 'plugins { kotlin("jvm") version "2.2.0" }\n'


def test_added_protected_file_is_deleted(h: Harness) -> None:
    def add_init(t: Path) -> None:
        _fix(t)
        (t / "init.gradle.kts").write_text("// evil\n")

    v, app = h.grade(h.mutate_patch(add_init))
    assert v.exit_reason == "tampered"
    assert v.tampered_files == ["init.gradle.kts"]
    assert not (app / "init.gradle.kts").exists()


def test_broken_main_is_build_failed(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(lambda t: (t / MAIN).write_text("BROKEN\n")))
    assert v.exit_reason == "build_failed"
    assert v.gradle["main_compile_failed"] == [":compileKotlin"]


def test_deleted_main_is_test_compile_failed(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(lambda t: (t / MAIN).unlink()))
    assert v.exit_reason == "test_compile_failed"


def test_shared_mode_oracle_and_tamper(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(_fix), shared=True)
    assert v.verifier_mode == "shared" and v.exit_reason == "resolved"
    v2, _ = h.grade(h.mutate_patch(lambda t: (t / TEST).write_text("x\n")), shared=True)
    assert v2.verifier_mode == "shared" and v2.exit_reason == "tampered"


def test_shared_mode_history_rewrite_is_caught_with_originals(h: Harness, tmp_path: Path) -> None:
    orig = h.tests_dir / "original" / "gradlew"
    orig.parent.mkdir(parents=True)
    orig.write_text("#!/bin/sh\necho wrapper\n", encoding="utf-8", newline="\n")

    # The agent edits gradlew and commits, so `git diff HEAD` is clean for it.
    def rewrite(t: Path) -> None:
        _fix(t)

    patch = h.mutate_patch(rewrite)
    app = h.tmp / "app"
    v, app = h.grade(patch, shared=True)
    assert v.exit_reason == "resolved"
    # Now simulate the rewritten history: amend gradlew into the base commit.
    rmtree(str(app))
    shutil.copytree(h.pristine, app)
    (app / "gradlew").write_text("#!/bin/sh\necho evil\n", encoding="utf-8", newline="\n")
    _git(app, "add", "-A")
    _git(app, "commit", "-q", "--amend", "-m", "base")
    (app / MAIN).write_text(FIXED_MAIN, encoding="utf-8", newline="\n")  # dirty tree: shared mode
    env = {
        "APP_DIR": str(app),
        "TESTS_DIR": str(h.tests_dir),
        "OUT_DIR": str(tmp_path / "out2"),
        "CAPTURE_DIR": str(tmp_path / "capture"),
        "GRADLE_BIN": str(h.gradle),
        "RO_CACHE": str(tmp_path / "ro"),
        "TMPDIR": str(tmp_path),
    }
    v2 = g.grade(g.Settings(env), h.spec)
    assert v2.exit_reason == "tampered"
    assert v2.detail["history_rewrite_suspected"] is True
    assert (app / "gradlew").read_text() == "#!/bin/sh\necho wrapper\n"


def test_patch_that_does_not_apply_is_infra_error(h: Harness) -> None:
    v, _ = h.grade("diff --git a/nope b/nope\n--- a/nope\n+++ b/nope\n@@ -1 +1 @@\n-x\n+y\n")
    assert v.exit_reason == "infra_error" and v.detail["patch_failed"] is True
    assert (h.tmp / "out" / "reward.json").is_file()


def test_timeout_kills_gradle(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(_fix), extra_env={"GRADLE_TIMEOUT_SEC": "1", "FAKE_GRADLE_SLEEP": "5"})
    assert v.exit_reason == "timeout" and v.detail["timed_out"] is True


def test_oom_is_infra_error(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(_fix), extra_env={"FAKE_GRADLE_OOM": "1"})
    assert v.exit_reason == "infra_error" and v.detail["oom"] is True


def test_missing_gradle_is_infra_error(h: Harness) -> None:
    v, _ = h.grade(h.mutate_patch(_fix), extra_env={"GRADLE_BIN": str(h.tmp / "nowhere" / "gradle")})
    assert v.exit_reason == "infra_error"
    assert "Gradle binary not found" in str(v.detail["error"])


def test_build_outputs_from_agent_are_removed(h: Harness) -> None:
    def leave_output(t: Path) -> None:
        _fix(t)
        (t / "build" / "test-results" / "test").mkdir(parents=True)
        (t / "build" / "test-results" / "test" / "TEST-stale.xml").write_text("<testsuite/>")
        (t / ".gitignore").write_text("")  # make build/ visible to git

    v, _ = h.grade(h.mutate_patch(leave_output))
    assert v.exit_reason == "resolved"
    assert "build/test-results/test/TEST-stale.xml" in v.files_by_category["other"]
    assert v.tests["n_reports"] == 1
