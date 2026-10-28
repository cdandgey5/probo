#!/usr/bin/env python3
"""Probo grader. Runs inside Harbor's verifier container, or on a developer
machine through ``probo grader-selftest`` and ``probo gate``.

Harbor copies the task's ``tests/`` directory to ``/tests`` and runs
``tests/test.sh`` from the task working directory. ``test.sh`` executes this
file. The container is either a fresh one built from the task image (the
default: ``[verifier] environment_mode = "separate"``) or the agent's own
container (``shared``, used only as a control).

What it does, in order (see ROADMAP.md, "Run protocol", step 3):

1. Bring the agent's change in: in separate mode apply the captured diff onto
   the pristine tree; in shared mode the tree already carries it.
2. List the changed files against the base commit with a throwaway index.
3. Classify every changed path (main, test, build, ci, other). Any test,
   build or ci path is tampering. A build-file edit that adds a dependency
   also sets the ``dependency_added`` detail.
4. Restore every protected file from the base commit (and from the pristine
   copies under ``tests/original`` when the task ships them), overwrite the
   hidden test files, drop build outputs.
5. Run only the named Gradle test tasks with the image-pinned Gradle binary,
   a fresh GRADLE_USER_HOME, the read-only dependency cache and ``--offline``.
6. Parse the JUnit XML, classify the Gradle log, decide exactly one exit
   reason, and write ``reward.json`` (numeric flags for Harbor) plus
   ``verdict.json`` (the exit reason and everything else) to the verifier
   log directory.

The script always exits 0 and always writes a reward file, so Harbor never
sees a verifier error for a graded run; infrastructure problems are reported
as the ``infra_error`` exit reason instead.

This file must stay stdlib-only and compatible with the python3 of the base
image (3.10 on Ubuntu 22.04), so no match statements, no ``X | Y`` at runtime,
no tomllib. Configuration comes from ``tests/spec.json``, written by the
converter, and from the environment variables listed in ``Settings``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Tuple

GRADER_VERSION = "0.1.0"

# Exactly one per run. Order is precedence when several apply.
EXIT_REASONS = (
    "infra_error",
    "timeout",
    "agent_error",  # assigned by the result flattener from Harbor's exception info
    "tampered",
    "no_diff",
    "build_failed",
    "test_compile_failed",
    "f2p_failed",
    "p2p_failed",
    "resolved",
)

# ---------------------------------------------------------------------------
# Path classification (ROADMAP.md, Definitions: Tampering)
# ---------------------------------------------------------------------------

# Test source sets: src/test, src/androidTest, flavour and build-type variants
# (src/testDebug, src/androidTestDemo), Kotlin multiplatform (src/commonTest,
# src/jvmTest, src/androidUnitTest, src/androidInstrumentedTest), sharedTest
# and testFixtures.
_TEST_DIR_RE = re.compile(
    r"(^|/)src/("
    r"test|androidTest|sharedTest|testFixtures|commonTest|jvmTest|androidUnitTest|"
    r"androidInstrumentedTest|test[A-Z][A-Za-z0-9]*|androidTest[A-Z][A-Za-z0-9]*|"
    r"[a-z][A-Za-z0-9]*Test"
    r")/"
)
_MAIN_DIR_RE = re.compile(r"(^|/)src/[A-Za-z0-9]+/")
# Gradle build scripts, settings, properties, wrapper, version catalogs, init scripts.
_BUILD_FILE_RE = re.compile(
    r"(^|/)("
    r"build\.gradle(\.kts)?|settings\.gradle(\.kts)?|gradle\.properties|"
    r"gradlew|gradlew\.bat|[^/]*\.versions\.toml|init\.gradle(\.kts)?|"
    r"[^/]*\.init\.gradle(\.kts)?"
    r")$"
)
_GRADLE_SCRIPT_RE = re.compile(r"\.gradle(\.kts)?$")
# Convention plugins anywhere; the wrapper and init.d directories outside src/.
_CONVENTION_DIR_RE = re.compile(r"(^|/)(buildSrc|build-logic)/")
_BUILD_DIR_NAMES = ("gradle", "init.d")
_CI_RE = re.compile(
    r"^(\.github/|\.gitlab-ci\.yml$|\.gitlab/|\.circleci/|\.travis\.yml$|bitrise\.yml$|"
    r"Jenkinsfile$|\.buildkite/|azure-pipelines\.ya?ml$|\.cirrus\.yml$|codemagic\.ya?ml$|"
    r"\.drone\.yml$|\.woodpecker\.ya?ml$|cloudbuild\.ya?ml$)"
)

CATEGORIES = ("main", "test", "build", "ci", "other")
TAMPER_CATEGORIES = ("test", "build", "ci")


def classify_path(path: str, extra_protected: Iterable[str] = ()) -> str:
    """Return the category of a repository-relative path.

    Order matters: ci first (``.github/`` holds YAML, not Gradle files), then
    test, then build, then main, then other. ``extra_protected`` are task-level
    regular expressions whose matches count as ``build`` (tampering).
    """
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if _CI_RE.search(p):
        return "ci"
    if _TEST_DIR_RE.search(p):
        return "test"
    if _CONVENTION_DIR_RE.search(p):
        return "build"
    if _BUILD_FILE_RE.search(p) or _GRADLE_SCRIPT_RE.search(p):
        return "build"
    # gradle/ (wrapper, catalogs, init scripts) and init.d/ directories count
    # only outside source sets: a package named `gradle` under src/main is code.
    parts = p.split("/")
    src_idx = parts.index("src") if "src" in parts else len(parts)
    if any(c in _BUILD_DIR_NAMES for c in parts[:src_idx][:-1]):
        return "build"
    for pattern in extra_protected:
        if re.search(pattern, p):
            return "build"
    if _MAIN_DIR_RE.search(p):
        return "main"
    return "other"


def is_protected(path: str, extra_protected: Iterable[str] = ()) -> bool:
    return classify_path(path, extra_protected) in TAMPER_CATEGORIES


# ---------------------------------------------------------------------------
# Diff inspection: dependency_added detail
# ---------------------------------------------------------------------------

_DEP_CONFIGS = (
    "implementation|api|compileOnly|compileOnlyApi|runtimeOnly|kapt|ksp|annotationProcessor|"
    "classpath|testFixturesImplementation|testFixturesApi|coreLibraryDesugaring|"
    "lintChecks|lintPublish|[a-z][A-Za-z0-9]*(Implementation|Api|CompileOnly|RuntimeOnly|"
    "Kapt|Ksp|AnnotationProcessor)"
)
# A configuration call anywhere on an added line (after comments are
# stripped), so a one-line `dependencies { implementation("x") }` counts too.
_DEP_LINE_RE = re.compile(r"(?:^|[\s{;(])\"?(" + _DEP_CONFIGS + r")\"?\s*[\(\s\"'`]")
_LINE_COMMENT_RE = re.compile(r"//.*$")
# A new entry under [libraries] or [plugins] of a version catalog.
_CATALOG_ENTRY_RE = re.compile(
    r"^\+\s*[A-Za-z0-9_.\-]+\s*=\s*(\{[^}]*\b(module|group|name|id)\s*=|\"[^\"]*:[^\"]*\")"
)
_DIFF_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_DIFF_DEV_NULL = "/dev/null"


def find_dependency_additions(diff_text: str) -> List[str]:
    """Return the build files whose added lines declare a dependency.

    A heuristic detail flag, not a parser: it catches the common Groovy and
    Kotlin DSL forms (``implementation("g:a:v")``, ``testImplementation libs.x``)
    and new entries in ``*.versions.toml``. Only files in the ``build``
    category are inspected.
    """
    hits: List[str] = []
    current: Optional[str] = None
    current_is_build = False
    current_is_catalog = False
    for line in diff_text.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            current = m.group(1).strip()
            if current == _DIFF_DEV_NULL:
                current = None
                current_is_build = False
                current_is_catalog = False
                continue
            current_is_build = classify_path(current) == "build"
            current_is_catalog = current.endswith(".versions.toml")
            continue
        if not current or not current_is_build or line.startswith("+++"):
            continue
        if not line.startswith("+"):
            continue
        if current_is_catalog:
            if _CATALOG_ENTRY_RE.match(line) and current not in hits:
                hits.append(current)
        else:
            code = _LINE_COMMENT_RE.sub("", line[1:])
            if _DEP_LINE_RE.search(code) and current not in hits:
                hits.append(current)
    return hits


# ---------------------------------------------------------------------------
# JUnit XML
# ---------------------------------------------------------------------------


def normalize_test_id(test_id: str) -> str:
    """Gradle writes JUnit 5 method names with trailing parentheses
    (``fullDiscountYieldsZero()``); task metadata lists them without. Only a
    bare ``()`` suffix is stripped: parameterized names such as
    ``add(int, int)[1]`` keep their text."""
    t = test_id.strip()
    if t.endswith("()"):
        t = t[:-2]
    return t


def parse_junit_reports(report_paths: Iterable[str]) -> Tuple[Dict[str, str], List[str]]:
    """Parse Gradle JUnit XML reports into ``{classname#name: status}``.

    Status is one of passed, failed, error, skipped. Returns the status map and
    a list of warnings for reports that could not be parsed.
    """
    status: Dict[str, str] = {}
    warnings: List[str] = []
    for report in report_paths:
        try:
            root = ET.parse(report).getroot()
        except (ET.ParseError, OSError) as exc:
            warnings.append("could not parse %s: %s" % (report, exc))
            continue
        for case in root.iter("testcase"):
            key = normalize_test_id("%s#%s" % (case.get("classname", ""), case.get("name", "")))
            if case.find("failure") is not None:
                status[key] = "failed"
            elif case.find("error") is not None:
                status[key] = "error"
            elif case.find("skipped") is not None:
                status[key] = "skipped"
            else:
                status[key] = "passed"
    return status, warnings


def find_junit_reports(app_dir: str, results_dirs: Iterable[str]) -> List[str]:
    found: List[str] = []
    for rel in results_dirs:
        d = os.path.join(app_dir, rel)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("TEST-") and name.endswith(".xml"):
                found.append(os.path.join(d, name))
    return found


def gradle_task_to_results_dir(task_path: str) -> str:
    """``:app:testDebugUnitTest`` -> ``app/build/test-results/testDebugUnitTest``.

    ``:test`` (root project) -> ``build/test-results/test``.
    """
    if not task_path.startswith(":"):
        raise ValueError("Gradle task paths must be fully qualified, e.g. ':test': %r" % task_path)
    parts = task_path.split(":")[1:]
    task_name = parts[-1]
    module = "/".join(parts[:-1])
    if not task_name:
        raise ValueError("empty task name in %r" % task_path)
    prefix = module + "/" if module else ""
    return "%sbuild/test-results/%s" % (prefix, task_name)


def expected_statuses(status: Dict[str, str], expected: Iterable[str]) -> Dict[str, str]:
    """Status per expected test ID; a listed test missing from the reports is
    ``missing``, which counts as not passed."""
    out: Dict[str, str] = {}
    for tid in expected:
        key = normalize_test_id(tid)
        out[key] = status.get(key, "missing")
    return out


# ---------------------------------------------------------------------------
# Gradle log classification
# ---------------------------------------------------------------------------

_FAILED_TASK_RE = re.compile(r"Execution failed for task '([^']+)'|^> Task (\S+) FAILED", re.M)
_OOM_RE = re.compile(
    r"OutOfMemoryError|Gradle build daemon disappeared|finished with non-zero exit value 137|"
    r"Could not reserve enough space for object heap|GC overhead limit exceeded|"
    r"Daemon.*killed|The Daemon will expire immediately since the JVM garbage collector",
)
_UNRESOLVED_RE = re.compile(r"Could not resolve all (dependencies|files|artifacts)|Could not resolve ")


def _task_name(task_path: str) -> str:
    return task_path.rsplit(":", 1)[-1]


def is_compile_like(task_path: str) -> bool:
    name = _task_name(task_path)
    return bool(re.match(r"(compile|kapt|ksp|kaptGenerateStubs)", name))


def is_test_compile(task_path: str) -> bool:
    return is_compile_like(task_path) and "Test" in _task_name(task_path)


def classify_gradle_log(log_text: str) -> Dict[str, object]:
    """Extract failed task paths and the signatures the verdict depends on."""
    failed: List[str] = []
    for m in _FAILED_TASK_RE.finditer(log_text):
        name = m.group(1) or m.group(2)
        if name and name not in failed:
            failed.append(name)
    main_compile_failed = [t for t in failed if is_compile_like(t) and not is_test_compile(t)]
    test_compile_failed = [t for t in failed if is_test_compile(t)]
    return {
        "failed_tasks": failed,
        "main_compile_failed": main_compile_failed,
        "test_compile_failed": test_compile_failed,
        "oom": bool(_OOM_RE.search(log_text)),
        "unresolved_dependency": bool(_UNRESOLVED_RE.search(log_text)),
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def decide_exit_reason(
    infra_error: bool,
    timed_out: bool,
    tampered: bool,
    no_diff: bool,
    main_compile_failed: bool,
    test_compile_failed: bool,
    n_reports: int,
    f2p: Dict[str, str],
    p2p: Dict[str, str],
) -> str:
    """Exactly one exit reason, by the precedence in ROADMAP.md, Definitions."""
    if infra_error:
        return "infra_error"
    if timed_out:
        return "timeout"
    if tampered:
        return "tampered"
    if no_diff:
        return "no_diff"
    if main_compile_failed or (n_reports == 0 and not test_compile_failed):
        return "build_failed"
    if test_compile_failed:
        return "test_compile_failed"
    if not f2p or any(s != "passed" for s in f2p.values()):
        return "f2p_failed"
    if any(s != "passed" for s in p2p.values()):
        return "p2p_failed"
    return "resolved"


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class Settings:
    """Paths and limits. Every value can be overridden by an environment
    variable so the same script runs on a developer machine."""

    def __init__(self, env: Optional[Dict[str, str]] = None):
        e = env if env is not None else os.environ
        self.app_dir = e.get("APP_DIR", "/app")
        self.tests_dir = e.get("TESTS_DIR", "/tests")
        self.out_dir = e.get("OUT_DIR", "/logs/verifier")
        self.capture_dir = e.get("CAPTURE_DIR", "/tmp/harbor-capture")
        self.gradle_bin = e.get("GRADLE_BIN", "/opt/gradle/dist/bin/gradle")
        self.ro_cache = e.get("RO_CACHE", "/opt/gradle/ro-cache")
        self.tmp_root = e.get("TMPDIR", tempfile.gettempdir())
        self.gradle_timeout_sec = e.get("GRADLE_TIMEOUT_SEC")  # None: from spec
        # Validation state A: grade the base tree without the hidden tests.
        self.skip_hidden = e.get("PROBO_SKIP_HIDDEN", "") not in ("", "0", "false")


def load_spec(tests_dir: str) -> Dict[str, object]:
    with open(os.path.join(tests_dir, "spec.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


class Git:
    """git with hooks disabled and no line-ending conversion, so an agent's
    hook or config in a shared container cannot run during grading."""

    def __init__(self, cwd: str, hooks_dir: str):
        self.cwd = cwd
        self.base = [
            "git",
            "-c",
            "core.hooksPath=" + hooks_dir,
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.safecrlf=false",
        ]

    def run(
        self, *args: str, env: Optional[Dict[str, str]] = None, check: bool = False
    ) -> subprocess.CompletedProcess:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(
            self.base + list(args),
            cwd=self.cwd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
        )

    def out(self, *args: str, env: Optional[Dict[str, str]] = None) -> str:
        return self.run(*args, env=env, check=True).stdout


def _on_rm_error(func, path, _exc_info):  # type: ignore[no-untyped-def]
    """Clear the read-only bit and retry: git object files are read-only, and
    on Windows that makes shutil.rmtree fail."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except OSError:
        pass


def rmtree(path: str) -> None:
    shutil.rmtree(path, onerror=_on_rm_error)


def _rm(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        rmtree(path)
    elif os.path.lexists(path):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.remove(path)


_GRADLE_SCRIPT_NAMES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")


def remove_build_outputs(app_dir: str) -> None:
    """Delete ``build``, ``.gradle`` and ``.kotlin`` directories next to every
    Gradle script, so nothing an agent left in them reaches the verifier."""
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        if any(f in _GRADLE_SCRIPT_NAMES for f in files):
            for d in ("build", ".gradle", ".kotlin"):
                if d in dirs:
                    _rm(os.path.join(root, d))
                    dirs.remove(d)


def copy_tree_over(src: str, dst: str) -> List[str]:
    copied: List[str] = []
    for root, _dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        for f in files:
            rel = os.path.normpath(os.path.join(rel_root, f)) if rel_root != "." else f
            target = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            shutil.copy2(os.path.join(root, f), target)
            copied.append(rel.replace("\\", "/"))
    return copied


def run_with_timeout(
    cmd: List[str], cwd: str, env: Dict[str, str], log_path: str, timeout_sec: float
) -> Tuple[int, bool]:
    """Run ``cmd``, stream output to ``log_path``, kill the whole process tree
    on timeout. Returns (return code, timed out)."""
    timed_out = False
    with open(log_path, "wb") as log:
        kwargs = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        try:
            rc = proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
            try:
                rc = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                rc = -9
    return rc, timed_out


def gradle_task_args(test_tasks: List[str], test_filters: Dict[str, List[str]]) -> List[str]:
    """``:app:testDebugUnitTest --tests a.B --tests a.C :lib:test``: Gradle binds
    each ``--tests`` to the task that precedes it, so filters are emitted
    right after their task."""
    args: List[str] = []
    for task in test_tasks:
        args.append(task)
        for pattern in test_filters.get(task, []) or []:
            args += ["--tests", str(pattern)]
    return args


def gradle_command(gradle_bin: str) -> List[str]:
    """On Windows the distribution's ``bin/gradle`` is a shell script; use the
    batch file next to it."""
    if os.name == "nt" and not gradle_bin.lower().endswith(".bat"):
        bat = gradle_bin + ".bat"
        if os.path.exists(bat):
            return [bat]
    return [gradle_bin]


class Verdict:
    def __init__(self, task_id: str, pack_version: str):
        self.task_id = task_id
        self.pack_version = pack_version
        self.reward = 0
        self.exit_reason = "infra_error"
        self.verifier_mode = "unknown"
        self.tampered_files: List[str] = []
        self.files_by_category: Dict[str, List[str]] = {c: [] for c in CATEGORIES}
        self.diff_stats: Dict[str, int] = {"files": 0, "insertions": 0, "deletions": 0}
        self.detail: Dict[str, object] = {
            "dependency_added": False,
            "dependency_added_files": [],
            "patch_failed": False,
            "oom": False,
            "timed_out": False,
            "unresolved_dependency": False,
            "suspicious_f2p_pass_without_diff": False,
            "history_rewrite_suspected": False,
            "error": None,
        }
        self.gradle: Dict[str, object] = {
            "tasks": [],
            "exit_code": None,
            "seconds": None,
            "failed_tasks": [],
            "main_compile_failed": [],
            "test_compile_failed": [],
        }
        self.tests: Dict[str, object] = {
            "n_reports": 0,
            "n_tests_seen": 0,
            "f2p": {},
            "p2p": {},
            "warnings": [],
        }
        self.restored_files: List[str] = []
        self.hidden_files_written: List[str] = []
        self.verify_seconds: Optional[int] = None

    def f2p_passed(self) -> bool:
        f2p = self.tests["f2p"]
        return bool(f2p) and all(s == "passed" for s in f2p.values())  # type: ignore[union-attr]

    def p2p_passed(self) -> bool:
        p2p = self.tests["p2p"]
        return all(s == "passed" for s in p2p.values())  # type: ignore[union-attr]

    def to_json(self) -> Dict[str, object]:
        return {
            "schema": "probo-verdict/1",
            "grader_version": GRADER_VERSION,
            "task_id": self.task_id,
            "pack_version": self.pack_version,
            "reward": self.reward,
            "exit_reason": self.exit_reason,
            "f2p_passed": self.f2p_passed(),
            "p2p_passed": self.p2p_passed(),
            "verifier_mode": self.verifier_mode,
            "tampered_files": self.tampered_files,
            "files_by_category": self.files_by_category,
            "diff_stats": self.diff_stats,
            "detail": self.detail,
            "gradle": self.gradle,
            "tests": self.tests,
            "restored_files": self.restored_files,
            "hidden_files_written": self.hidden_files_written,
            "verify_seconds": self.verify_seconds,
        }

    def reward_json(self) -> Dict[str, int]:
        return {
            "reward": int(self.reward),
            "f2p": int(self.f2p_passed()),
            "p2p": int(self.p2p_passed()),
            "tampered": int(bool(self.tampered_files)),
        }


def write_outputs(out_dir: str, verdict: Verdict, status_map: Dict[str, str]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "reward.json"), "w", encoding="utf-8") as fh:
        json.dump(verdict.reward_json(), fh)
    with open(os.path.join(out_dir, "reward.txt"), "w", encoding="utf-8") as fh:
        fh.write("%d\n" % verdict.reward)
    with open(os.path.join(out_dir, "verdict.json"), "w", encoding="utf-8") as fh:
        json.dump(verdict.to_json(), fh, indent=2, sort_keys=True)
    with open(os.path.join(out_dir, "test-results.json"), "w", encoding="utf-8") as fh:
        json.dump({"status": status_map}, fh, indent=2, sort_keys=True)


def _same_file(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def grade(settings: Settings, spec: Dict[str, object]) -> Verdict:
    t0 = time.time()
    app = settings.app_dir
    out = settings.out_dir
    tests_dir = settings.tests_dir
    os.makedirs(out, exist_ok=True)
    extra_protected = [str(p) for p in spec.get("extra_protected", [])]  # type: ignore[union-attr]
    verdict = Verdict(str(spec.get("task_id", "")), str(spec.get("pack_version", "")))
    status_map: Dict[str, str] = {}
    hooks_dir = tempfile.mkdtemp(prefix="probo-nohooks.", dir=settings.tmp_root)
    git = Git(app, hooks_dir)

    try:
        if not os.path.isdir(os.path.join(app, ".git")):
            raise RuntimeError("%s is not a git repository" % app)

        # 1. Bring the agent's change into this tree.
        dirty = git.out("status", "--porcelain", "--untracked-files=all").strip()
        if dirty:
            verdict.verifier_mode = "shared"
        else:
            verdict.verifier_mode = "separate"
            patch = os.path.join(settings.capture_dir, "agent.patch")
            if os.path.isfile(patch) and os.path.getsize(patch) > 0:
                r = git.run("apply", "--whitespace=nowarn", patch)
                with open(os.path.join(out, "git-apply.log"), "w", encoding="utf-8") as fh:
                    fh.write(r.stdout + r.stderr)
                if r.returncode != 0:
                    verdict.detail["patch_failed"] = True
                    verdict.detail["error"] = "captured patch did not apply onto the pristine tree"
                    verdict.exit_reason = "infra_error"
                    return verdict

        # 2. Changed files against the base commit, through a throwaway index.
        fd, tmp_index = tempfile.mkstemp(prefix="probo-index.", dir=settings.tmp_root)
        os.close(fd)
        os.remove(tmp_index)
        idx_env = {"GIT_INDEX_FILE": tmp_index}
        git.out("read-tree", "HEAD", env=idx_env)
        git.out("add", "-A", env=idx_env)
        name_status = git.out("diff", "--cached", "--name-status", "--no-renames", "HEAD", env=idx_env)
        diff_text = git.out("diff", "--cached", "--binary", "--no-renames", "HEAD", env=idx_env)
        numstat = git.out("diff", "--cached", "--numstat", "--no-renames", "HEAD", env=idx_env)
        try:
            os.remove(tmp_index)
        except OSError:
            pass
        with open(os.path.join(out, "agent-diff.patch"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(diff_text)
        changed: List[Tuple[str, str]] = []
        for line in name_status.splitlines():
            if not line.strip():
                continue
            st, _, path = line.partition("\t")
            changed.append((st.strip(), path.strip()))
        with open(os.path.join(out, "changed-files.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join("%s\n" % p for _s, p in changed))
        ins = dele = 0
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                ins += int(parts[0]) if parts[0].isdigit() else 0
                dele += int(parts[1]) if parts[1].isdigit() else 0
        verdict.diff_stats = {"files": len(changed), "insertions": ins, "deletions": dele}

        # 3. Classify and detect tampering.
        for _st, path in changed:
            cat = classify_path(path, extra_protected)
            verdict.files_by_category[cat].append(path)
            if cat in TAMPER_CATEGORIES:
                verdict.tampered_files.append(path)
        dep_files = find_dependency_additions(diff_text)
        verdict.detail["dependency_added"] = bool(dep_files)
        verdict.detail["dependency_added_files"] = dep_files

        # In a shared container the agent may also have rewritten history, so
        # compare the live protected files with the pristine copies when the
        # task ships them.
        original = os.path.join(tests_dir, "original")
        if verdict.verifier_mode == "shared" and os.path.isdir(original):
            for root, _dirs, files in os.walk(original):
                for f in files:
                    src = os.path.join(root, f)
                    rel = os.path.relpath(src, original).replace("\\", "/")
                    live = os.path.join(app, rel)
                    if not os.path.isfile(live) or not _same_file(live, src):
                        if rel not in verdict.tampered_files:
                            verdict.tampered_files.append(rel)
                            verdict.detail["history_rewrite_suspected"] = True

        # 4. Restore protected files, overwrite hidden tests, drop build output.
        for _st, path in changed:
            if not is_protected(path, extra_protected):
                continue
            exists_in_head = git.run("cat-file", "-e", "HEAD:" + path).returncode == 0
            if exists_in_head:
                git.out("checkout", "HEAD", "--", path)
            else:
                _rm(os.path.join(app, path))
            verdict.restored_files.append(path)
        if os.path.isdir(original):
            for rel in copy_tree_over(original, app):
                if rel not in verdict.restored_files:
                    verdict.restored_files.append(rel)
        hidden = os.path.join(tests_dir, "hidden")
        hidden_patch = os.path.join(tests_dir, str(spec.get("hidden_patch") or "hidden.patch"))
        if settings.skip_hidden:
            verdict.detail["hidden_skipped"] = True
        else:
            if os.path.isdir(hidden):
                verdict.hidden_files_written = copy_tree_over(hidden, app)
            if os.path.isfile(hidden_patch) and os.path.getsize(hidden_patch) > 0:
                r = git.run("apply", "--whitespace=nowarn", hidden_patch)
                with open(os.path.join(out, "hidden-apply.log"), "w", encoding="utf-8") as fh:
                    fh.write(r.stdout + r.stderr)
                if r.returncode != 0:
                    verdict.detail["hidden_patch_failed"] = True
                    verdict.detail["error"] = "hidden test patch did not apply onto the restored tree"
                    verdict.exit_reason = "infra_error"
                    return verdict
                verdict.detail["hidden_patch_applied"] = True
        remove_build_outputs(app)

        # 5. Build and test, offline, with nothing of the agent's reachable.
        test_tasks = [str(t) for t in spec.get("test_tasks", [])]  # type: ignore[union-attr]
        if not test_tasks:
            raise RuntimeError("spec.json lists no test_tasks")
        test_filters = spec.get("test_filters") or {}
        results_dirs = [str(d) for d in spec.get("results_dirs", [])] or [  # type: ignore[union-attr]
            gradle_task_to_results_dir(t) for t in test_tasks
        ]
        timeout = float(settings.gradle_timeout_sec or spec.get("gradle_timeout_sec", 540))
        if not os.path.exists(settings.gradle_bin) and not os.path.exists(settings.gradle_bin + ".bat"):
            raise RuntimeError("Gradle binary not found: %s" % settings.gradle_bin)
        gradle_home = tempfile.mkdtemp(prefix="gradle-home.", dir=settings.tmp_root)
        env = dict(os.environ)
        env["GRADLE_USER_HOME"] = gradle_home
        env["GRADLE_RO_DEP_CACHE"] = settings.ro_cache
        env.pop("GRADLE_OPTS", None)
        env.pop("JAVA_TOOL_OPTIONS", None)
        task_args = gradle_task_args(test_tasks, test_filters)  # type: ignore[arg-type]
        cmd = (
            gradle_command(settings.gradle_bin)
            + [
                "--offline",
                "--no-daemon",
                "--console=plain",
                "--no-build-cache",
                "--continue",
                "-p",
                app,
            ]
            + task_args
        )
        verdict.gradle["tasks"] = test_tasks
        verdict.gradle["task_args"] = task_args
        log_path = os.path.join(out, "gradle-test.log")
        g0 = time.time()
        rc, timed_out = run_with_timeout(cmd, app, env, log_path, timeout)
        verdict.gradle["seconds"] = int(time.time() - g0)
        verdict.gradle["exit_code"] = rc
        verdict.detail["timed_out"] = timed_out
        rmtree(gradle_home)
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            log_text = fh.read()
        log_info = classify_gradle_log(log_text)
        verdict.gradle["failed_tasks"] = log_info["failed_tasks"]
        verdict.gradle["main_compile_failed"] = log_info["main_compile_failed"]
        verdict.gradle["test_compile_failed"] = log_info["test_compile_failed"]
        verdict.detail["oom"] = bool(log_info["oom"]) or rc == 137
        verdict.detail["unresolved_dependency"] = bool(log_info["unresolved_dependency"])

        # 6. Parse results and decide.
        reports = find_junit_reports(app, results_dirs)
        status_map, warnings = parse_junit_reports(reports)
        f2p = expected_statuses(status_map, [str(t) for t in spec.get("f2p", [])])  # type: ignore[union-attr]
        p2p = expected_statuses(status_map, [str(t) for t in spec.get("p2p", [])])  # type: ignore[union-attr]
        verdict.tests = {
            "n_reports": len(reports),
            "n_tests_seen": len(status_map),
            "f2p": f2p,
            "p2p": p2p,
            "warnings": warnings,
        }
        no_diff = len(changed) == 0
        infra = bool(verdict.detail["oom"]) and len(reports) == 0
        verdict.exit_reason = decide_exit_reason(
            infra_error=infra,
            timed_out=timed_out,
            tampered=bool(verdict.tampered_files),
            no_diff=no_diff,
            main_compile_failed=bool(log_info["main_compile_failed"]),
            test_compile_failed=bool(log_info["test_compile_failed"]),
            n_reports=len(reports),
            f2p=f2p,
            p2p=p2p,
        )
        if no_diff and f2p and all(s == "passed" for s in f2p.values()):
            verdict.detail["suspicious_f2p_pass_without_diff"] = True
        verdict.reward = 1 if verdict.exit_reason == "resolved" else 0
        return verdict
    except Exception as exc:  # noqa: BLE001 - every failure must become a graded infra_error
        verdict.exit_reason = "infra_error"
        verdict.reward = 0
        verdict.detail["error"] = "%s: %s" % (type(exc).__name__, exc)
        return verdict
    finally:
        verdict.verify_seconds = int(time.time() - t0)
        rmtree(hooks_dir)
        write_outputs(out, verdict, status_map)
        print(
            "verdict: reward=%d exit_reason=%s tampered=%s mode=%s seconds=%s"
            % (
                verdict.reward,
                verdict.exit_reason,
                verdict.tampered_files,
                verdict.verifier_mode,
                verdict.verify_seconds,
            )
        )


def main(argv: Optional[List[str]] = None) -> int:
    settings = Settings()
    try:
        spec = load_spec(settings.tests_dir)
    except Exception as exc:  # noqa: BLE001
        os.makedirs(settings.out_dir, exist_ok=True)
        v = Verdict("", "")
        v.detail["error"] = "could not load spec.json: %s" % exc
        write_outputs(settings.out_dir, v, {})
        print("verdict: reward=0 exit_reason=infra_error (no spec)")
        return 0
    grade(settings, spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
