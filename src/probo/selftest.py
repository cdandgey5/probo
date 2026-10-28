"""Exercise the grader on a developer machine without Docker, and run the
Phase 3 validation gate (states A, B, C) the same way.

Both need an emitted Harbor task whose ``environment/repo`` is inline (the
fixtures), a JDK on PATH, an unpacked Gradle distribution matching the task,
and a warm GRADLE_USER_HOME that has built the repository once. The
situations handed to the grader are built exactly as Harbor would: a pristine
clone of the repository at its base commit plus a captured agent patch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probo.grader import grade as grader
from probo.grader.grade import rmtree

_SKIP = ("build", ".gradle", ".kotlin", ".git")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@dataclass
class HostGradle:
    gradle_dist: Path
    warm_home: Path
    work: Path
    ro_cache: Path = field(init=False)
    tmp: Path = field(init=False)

    def __post_init__(self) -> None:
        self.gradle_dist = Path(self.gradle_dist).resolve()
        self.warm_home = Path(self.warm_home).resolve()
        self.work = Path(self.work).resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.ro_cache = self.work / "ro-cache"
        self.tmp = self.work / "tmp"
        self.tmp.mkdir(exist_ok=True)

    @property
    def gradle_bin(self) -> Path:
        return self.gradle_dist / "bin" / "gradle"

    def prepare_ro_cache(self) -> None:
        """A read-only copy of the warm cache, laid out as in the image."""
        src = self.warm_home / "caches" / "modules-2"
        if not src.is_dir():
            raise FileNotFoundError(f"{src} not found: build the repository once with this GRADLE_USER_HOME")
        if self.ro_cache.exists():
            rmtree(str(self.ro_cache))
        shutil.copytree(src, self.ro_cache / "modules-2")
        for lock in self.ro_cache.rglob("*.lock"):
            lock.unlink()
        gc = self.ro_cache / "modules-2" / "gc.properties"
        if gc.exists():
            gc.unlink()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def make_pristine(repo_src: Path, dst: Path) -> Path:
    """A clone of the repository at its base commit, as the Dockerfile builds it."""
    if dst.exists():
        rmtree(str(dst))
    shutil.copytree(repo_src, dst, ignore=shutil.ignore_patterns(*_SKIP))
    _git(dst, "init", "-q", "-b", "main")
    _git(dst, "config", "user.email", "task@example.invalid")
    _git(dst, "config", "user.name", "task")
    _git(dst, "add", "-A")
    _git(dst, "commit", "-q", "-m", "base")
    return dst


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        rmtree(str(dst))
    shutil.copytree(src, dst, symlinks=True)


def patch_from_mutation(pristine: Path, scratch: Path, mutate: Callable[[Path], None]) -> str:
    """Apply ``mutate`` to a scratch clone and return the diff an agent would
    have produced, captured the way the collect hook captures it."""
    _copy_tree(pristine, scratch)
    mutate(scratch)
    _git(scratch, "add", "-A")
    return _git(scratch, "diff", "--cached", "--binary", "HEAD")


# ---------------------------------------------------------------------------
# Running the grader on one situation
# ---------------------------------------------------------------------------


def run_grader(
    host: HostGradle,
    task_dir: Path,
    pristine: Path,
    patch_text: str,
    name: str,
    shared: bool = False,
    timeout_sec: float | None = None,
    extra_hidden: dict[str, str] | None = None,
    skip_hidden: bool = False,
) -> dict[str, Any]:
    """Grade one situation and return the verdict (plus ``_seconds``)."""
    app = host.work / f"run-{name}"
    _copy_tree(pristine, app)
    capture = host.work / f"run-{name}.capture"
    out = host.work / f"run-{name}.out"
    for d in (capture, out):
        if d.exists():
            rmtree(str(d))
        d.mkdir()
    if shared:
        if patch_text.strip():
            (capture / "incoming.patch").write_text(patch_text, encoding="utf-8", newline="\n")
            _git(app, "apply", "--whitespace=nowarn", str(capture / "incoming.patch"))
            (capture / "incoming.patch").unlink()
        (capture / "agent.patch").write_text("", encoding="utf-8")
    else:
        (capture / "agent.patch").write_text(patch_text, encoding="utf-8", newline="\n")
    tests_dir = task_dir / "tests"
    if extra_hidden is not None:
        tests_dir = host.work / f"run-{name}.tests"
        _copy_tree(task_dir / "tests", tests_dir)
        for rel, content in extra_hidden.items():
            p = tests_dir / "hidden" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env.update(
        {
            "APP_DIR": str(app),
            "TESTS_DIR": str(tests_dir),
            "OUT_DIR": str(out),
            "CAPTURE_DIR": str(capture),
            "GRADLE_BIN": str(host.gradle_bin),
            "RO_CACHE": str(host.ro_cache),
            "TMPDIR": str(host.tmp),
        }
    )
    if timeout_sec is not None:
        env["GRADLE_TIMEOUT_SEC"] = str(timeout_sec)
    if skip_hidden:
        env["PROBO_SKIP_HIDDEN"] = "1"
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(tests_dir / "grade.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    (out / "test-stdout.txt").write_text(proc.stdout, encoding="utf-8")
    verdict_path = out / "verdict.json"
    verdict: dict[str, Any] = json.loads(verdict_path.read_text("utf-8")) if verdict_path.is_file() else {}
    verdict["_seconds"] = round(time.time() - t0, 1)
    verdict["_reward_txt"] = (
        (out / "reward.txt").read_text("utf-8").strip() if (out / "reward.txt").is_file() else None
    )
    verdict["_out_dir"] = str(out)
    return verdict


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    want_reward: int
    want_reason: str
    mutate: Callable[[Path, dict[str, Any]], None]
    shared: bool = False
    want_detail: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def _spec(task_dir: Path) -> dict[str, Any]:
    return json.loads((task_dir / "tests" / "spec.json").read_text("utf-8"))


def _gold(task_dir: Path) -> str:
    return (task_dir / "solution" / "gold.patch").read_text("utf-8")


def _apply_gold(tree: Path, task_dir: Path) -> None:
    (tree / ".gold.patch").write_text(_gold(task_dir), encoding="utf-8", newline="\n")
    _git(tree, "apply", "--whitespace=nowarn", ".gold.patch")
    (tree / ".gold.patch").unlink()


def _first_main_file(task_dir: Path) -> str:
    from probo.task import patch_files

    for p in patch_files(_gold(task_dir)):
        if grader.classify_path(p) == "main":
            return p
    raise RuntimeError("gold patch touches no main file")


def _root_build_file(tree: Path) -> Path:
    for n in ("build.gradle.kts", "build.gradle"):
        if (tree / n).is_file():
            return tree / n
    raise RuntimeError("no root build file")


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def build_scenarios(task_dir: Path) -> list[Scenario]:
    spec = _spec(task_dir)
    hidden = list(spec.get("hidden_tests", []))
    main_file = _first_main_file(task_dir)

    def oracle(t: Path, _s: dict[str, Any]) -> None:
        _apply_gold(t, task_dir)

    def nop(_t: Path, _s: dict[str, Any]) -> None:
        return None

    def comment_only(t: Path, _s: dict[str, Any]) -> None:
        _append(t / main_file, "\n// touched by the agent, no fix\n")

    def tamper_tests(t: Path, _s: dict[str, Any]) -> None:
        for rel in hidden or ["src/test/kotlin/Tampered.kt"]:
            p = t / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("// tests removed by the agent\n", encoding="utf-8", newline="\n")

    def tamper_and_fix(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        tamper_tests(t, s)

    def dependency_added(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        bf = _root_build_file(t)
        if bf.suffix == ".kts":
            _append(bf, '\ndependencies { testImplementation("org.assertj:assertj-core:3.27.3") }\n')
        else:
            _append(bf, "\ndependencies { testImplementation 'org.assertj:assertj-core:3.27.3' }\n")

    def break_build(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        p = t / main_file
        if p.suffix == ".kt":
            _append(p, "\nval oops = \n")
        else:
            _append(p, "\nclass Oops {\n")

    def delete_main(t: Path, _s: dict[str, Any]) -> None:
        (t / main_file).unlink()

    def replace_gradlew(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        _append(t / "gradlew", "\n# replaced by the agent\n")

    def init_script(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        (t / "init.gradle.kts").write_text(
            "allprojects { tasks.withType<Test> { enabled = false } }\n", encoding="utf-8", newline="\n"
        )

    def ci_edit(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        p = t / ".github" / "workflows" / "agent.yml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("name: agent\non: push\njobs: {}\n", encoding="utf-8", newline="\n")

    def properties_edit(t: Path, s: dict[str, Any]) -> None:
        oracle(t, s)
        _append(t / "gradle.properties", "\norg.gradle.jvmargs=-Xmx64m\n")

    return [
        Scenario("oracle", 1, "resolved", oracle),
        Scenario("nop", 0, "no_diff", nop),
        Scenario("comment_only", 0, "f2p_failed", comment_only),
        Scenario("tamper_tests", 0, "tampered", tamper_tests),
        Scenario("tamper_and_fix", 0, "tampered", tamper_and_fix),
        Scenario("dependency_added", 0, "tampered", dependency_added, want_detail={"dependency_added": True}),
        Scenario("break_build", 0, "build_failed", break_build),
        Scenario(
            "delete_main",
            0,
            "test_compile_failed",
            delete_main,
            note="expects the hidden tests to be the only code referencing the deleted file",
        ),
        Scenario("replace_gradlew", 0, "tampered", replace_gradlew),
        Scenario("init_script", 0, "tampered", init_script),
        Scenario("ci_edit", 0, "tampered", ci_edit),
        Scenario("properties_edit", 0, "tampered", properties_edit),
        Scenario("oracle_shared", 1, "resolved", oracle, shared=True),
        Scenario("tamper_shared", 0, "tampered", tamper_tests, shared=True),
    ]


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    reward: Any
    want_reward: int
    reason: Any
    want_reason: str
    seconds: float
    detail_ok: bool
    note: str = ""
    out_dir: str = ""

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        extra = "" if self.detail_ok else " (detail mismatch)"
        return (
            f"{self.name:<18} {mark}  reward={self.reward} (want {self.want_reward})  "
            f"exit_reason={str(self.reason):<20} (want {self.want_reason:<18}) {self.seconds:>6.1f}s{extra}"
        )


def run_selftest(
    task_dir: Path,
    host: HostGradle,
    only: list[str] | None = None,
    timeout_sec: float | None = None,
    log: Callable[[str], None] = print,
) -> list[ScenarioResult]:
    task_dir = Path(task_dir).resolve()
    repo_src = task_dir / "environment" / "repo"
    if not repo_src.is_dir():
        raise FileNotFoundError(f"{repo_src} not found: the self-test needs an inline repository")
    host.prepare_ro_cache()
    pristine = make_pristine(repo_src, host.work / "pristine")
    scratch = host.work / "scratch"
    spec = _spec(task_dir)
    results: list[ScenarioResult] = []
    log(f"task     : {task_dir}")
    log(f"work     : {host.work}")
    log(f"gradle   : {host.gradle_bin}")
    for sc in build_scenarios(task_dir):
        if only and sc.name not in only:
            continue
        patch = patch_from_mutation(pristine, scratch, lambda t, s=sc: s.mutate(t, spec))
        v = run_grader(host, task_dir, pristine, patch, sc.name, shared=sc.shared, timeout_sec=timeout_sec)
        reward = v.get("reward")
        reason = v.get("exit_reason")
        detail = v.get("detail") or {}
        detail_ok = all(detail.get(k) == want for k, want in sc.want_detail.items())
        passed = reward == sc.want_reward and reason == sc.want_reason and detail_ok
        res = ScenarioResult(
            sc.name,
            passed,
            reward,
            sc.want_reward,
            reason,
            sc.want_reason,
            v["_seconds"],
            detail_ok,
            sc.note,
            v["_out_dir"],
        )
        results.append(res)
        log(res.line())
        if not passed:
            err = detail.get("error")
            if err:
                log(f"    error: {err}")
            log(f"    outputs: {res.out_dir}")
    n_pass = sum(1 for r in results if r.passed)
    log(f"--- summary: {n_pass} passed, {len(results) - n_pass} failed ---")
    return results


# ---------------------------------------------------------------------------
# Validation gate: states A, B, C
# ---------------------------------------------------------------------------


@dataclass
class GateRun:
    state: str
    run: int
    exit_reason: str
    f2p: dict[str, str]
    p2p: dict[str, str]
    n_reports: int
    seconds: float
    test_compile_failed: bool


def run_gate(
    task_dir: Path,
    host: HostGradle,
    runs: int = 1,
    log: Callable[[str], None] = print,
) -> tuple[bool, list[GateRun], list[str]]:
    """States, as written out in ROADMAP.md Phase 3:

    * A: base commit with its original tests. P2P tests must pass; the F2P
      tests may be absent (hidden) or failing.
    * B: base commit plus the hidden tests. F2P must not pass. If the test
      sources do not compile here, the task needs an interface contract.
    * C: base commit plus hidden tests plus gold patch. Everything passes.

    Every state runs ``runs`` times; any flake fails the gate.
    """
    task_dir = Path(task_dir).resolve()
    repo_src = task_dir / "environment" / "repo"
    host.prepare_ro_cache()
    pristine = make_pristine(repo_src, host.work / "pristine")
    scratch = host.work / "scratch"
    spec = _spec(task_dir)
    hidden = list(spec.get("hidden_tests", []))
    gold = _gold(task_dir)
    results: list[GateRun] = []
    problems: list[str] = []

    # State A grades the pristine tree with the hidden tests *not* applied
    # (PROBO_SKIP_HIDDEN): neither hidden files nor the hidden patch.
    del hidden

    def record(state: str, i: int, v: dict[str, Any]) -> GateRun:
        tests = v.get("tests") or {}
        g = GateRun(
            state,
            i,
            str(v.get("exit_reason")),
            tests.get("f2p") or {},
            tests.get("p2p") or {},
            int(tests.get("n_reports") or 0),
            float(v.get("_seconds", 0)),
            bool((v.get("gradle") or {}).get("test_compile_failed")),
        )
        results.append(g)
        log(
            f"state {state} run {i}: exit_reason={g.exit_reason} f2p={g.f2p} p2p_not_passed="
            f"{[t for t, s in g.p2p.items() if s != 'passed']} {g.seconds:.1f}s"
        )
        return g

    empty = ""
    for i in range(1, runs + 1):
        # A: base tests. Use the agent's "no diff" situation but with the base
        # test files in place of the hidden ones (deleted files stay deleted).
        a = record("A", i, run_grader(host, task_dir, pristine, empty, f"gate-A-{i}", skip_hidden=True))
        if any(s != "passed" for s in a.p2p.values()):
            problems.append(
                f"state A run {i}: a P2P test does not pass at base: "
                f"{[t for t, s in a.p2p.items() if s != 'passed']}"
            )
        if a.n_reports == 0:
            problems.append(f"state A run {i}: no JUnit reports ({a.exit_reason})")
        # B: base + hidden tests.
        b = record("B", i, run_grader(host, task_dir, pristine, empty, f"gate-B-{i}"))
        if b.test_compile_failed:
            problems.append(
                f"state B run {i}: hidden tests do not compile at base; "
                "the instruction needs an interface contract"
            )
        elif any(s == "passed" for s in b.f2p.values()):
            problems.append(
                f"state B run {i}: an F2P test already passes at base: "
                f"{[t for t, s in b.f2p.items() if s == 'passed']}"
            )
        if b.n_reports == 0 and not b.test_compile_failed:
            problems.append(f"state B run {i}: no JUnit reports ({b.exit_reason})")
        # C: base + hidden tests + gold patch.
        c_patch = patch_from_mutation(pristine, scratch, lambda t: _apply_gold(t, task_dir))
        c = record("C", i, run_grader(host, task_dir, pristine, c_patch, f"gate-C-{i}"))
        if c.exit_reason != "resolved":
            problems.append(f"state C run {i}: gold patch does not resolve the task ({c.exit_reason})")
    del gold
    ok = not problems
    log(f"--- gate: {'PASS' if ok else 'FAIL'} ({runs} run(s) per state) ---")
    for p in problems:
        log("  " + p)
    return ok, results, problems


def default_work_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="probo-selftest."))
