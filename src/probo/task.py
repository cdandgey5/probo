"""Task specification (schema v0): loading, schema validation and the semantic
checks that need no Gradle run. See docs/TASK_SCHEMA.md."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema

from probo.grader import grade as grader

SPEC_FILENAME = "probo.toml"
INSTRUCTION_FILENAME = "instruction.md"
HIDDEN_DIRNAME = "hidden"


def load_schema() -> dict[str, Any]:
    text = resources.files("probo.schema").joinpath("task-v0.schema.json").read_text("utf-8")
    return json.loads(text)


@dataclass
class Problem:
    level: str  # "error" or "warning"
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.message}"


@dataclass
class TaskSpec:
    """A validated probo.toml plus the files next to it."""

    task_dir: Path
    data: dict[str, Any]
    problems: list[Problem] = field(default_factory=list)

    # -- convenience accessors -------------------------------------------------
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def pack_version(self) -> str:
        return self.data.get("pack_version", "0.0.0")

    @property
    def source(self) -> dict[str, Any]:
        return self.data["source"]

    @property
    def environment(self) -> dict[str, Any]:
        return self.data["environment"]

    @property
    def verification(self) -> dict[str, Any]:
        return self.data["verification"]

    @property
    def instruction_path(self) -> Path:
        return self.task_dir / INSTRUCTION_FILENAME

    @property
    def gold_patch_path(self) -> Path:
        return self.task_dir / self.data.get("gold", {}).get("patch", "gold.patch")

    @property
    def hidden_dir(self) -> Path:
        return self.task_dir / HIDDEN_DIRNAME

    @property
    def repo_dir(self) -> Path | None:
        rel = self.environment.get("repo_dir")
        return (self.task_dir / rel) if rel else None

    @property
    def docker_image(self) -> str | None:
        return self.environment.get("docker_image")

    @property
    def test_tasks(self) -> list[str]:
        return list(self.verification["test_tasks"])

    @property
    def f2p(self) -> list[str]:
        return list(self.verification["f2p"])

    @property
    def p2p(self) -> list[str]:
        return list(self.verification.get("p2p", []))

    @property
    def hidden_tests(self) -> list[str]:
        return list(self.verification.get("hidden_tests", []))

    @property
    def agent_timeout_sec(self) -> float:
        return float(self.verification.get("agent_timeout_sec", 1800))

    @property
    def verify_timeout_sec(self) -> float:
        return float(self.verification.get("verify_timeout_sec", 900))

    @property
    def gradle_timeout_sec(self) -> float:
        explicit = self.verification.get("gradle_timeout_sec")
        if explicit is not None:
            return float(explicit)
        return max(60.0, self.verify_timeout_sec - 60.0)

    @property
    def test_command(self) -> str:
        explicit = self.verification.get("test_command")
        if explicit:
            return explicit
        return "./gradlew --offline " + " ".join(self.test_tasks)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.level == "error"]

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if p.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Patch inspection (no git needed)
# ---------------------------------------------------------------------------

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.M)
_HUNK_ADD_RE = re.compile(r"^\+(?!\+\+)", re.M)
_HUNK_DEL_RE = re.compile(r"^-(?!--)", re.M)


def patch_files(patch_text: str) -> list[str]:
    """Paths touched by a git-format patch, in order of appearance."""
    seen: list[str] = []
    for m in _DIFF_GIT_RE.finditer(patch_text):
        path = m.group(2)
        if path not in seen:
            seen.append(path)
    return seen


def patch_stats(patch_text: str) -> dict[str, int]:
    files = patch_files(patch_text)
    return {
        "files": len(files),
        "insertions": len(_HUNK_ADD_RE.findall(patch_text)),
        "deletions": len(_HUNK_DEL_RE.findall(patch_text)),
    }


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def load_task(task_dir: str | Path) -> TaskSpec:
    """Load and validate a task directory. Never raises for validation
    problems; read ``spec.problems`` / ``spec.ok``. Raises only when the spec
    file is missing or is not valid TOML."""
    task_dir = Path(task_dir).resolve()
    spec_path = task_dir / SPEC_FILENAME
    if not spec_path.is_file():
        raise FileNotFoundError(f"{spec_path} not found")
    with spec_path.open("rb") as fh:
        data = tomllib.load(fh)
    spec = TaskSpec(task_dir=task_dir, data=data)
    _validate_schema(spec)
    if spec.ok:
        _validate_semantics(spec)
    return spec


def _validate_schema(spec: TaskSpec) -> None:
    validator = jsonschema.Draft202012Validator(load_schema())
    for err in sorted(validator.iter_errors(spec.data), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "(root)"
        spec.problems.append(Problem("error", f"{SPEC_FILENAME} {where}: {err.message}"))


def _validate_semantics(spec: TaskSpec) -> None:
    add = spec.problems.append
    env = spec.environment
    ver = spec.verification

    if spec.task_dir.name != spec.id:
        add(Problem("warning", f"task directory name {spec.task_dir.name!r} differs from id {spec.id!r}"))

    # Environment: exactly one of docker_image / repo_dir.
    has_image = bool(env.get("docker_image"))
    has_repo = bool(env.get("repo_dir"))
    if has_image == has_repo:
        add(Problem("error", "environment must set exactly one of docker_image or repo_dir"))
    if has_repo:
        repo = spec.repo_dir
        assert repo is not None
        if not repo.is_dir():
            add(Problem("error", f"repo_dir {repo} does not exist"))
        else:
            if not any((repo / n).is_file() for n in ("settings.gradle", "settings.gradle.kts")):
                add(Problem("error", "repo_dir has no settings.gradle(.kts)"))
            if not (repo / "gradlew").is_file():
                add(Problem("error", "repo_dir has no gradlew"))
            elif b"\r\n" in (repo / "gradlew").read_bytes():
                add(Problem("error", "repo_dir/gradlew has CRLF line endings; the container needs LF"))
            if (repo / ".git").exists():
                add(Problem("error", "repo_dir must not contain .git; the image creates the base commit"))
    if has_image and "@sha256:" not in env["docker_image"]:
        add(Problem("warning", "docker_image is not pinned by digest"))

    # Timeouts.
    if spec.gradle_timeout_sec >= spec.verify_timeout_sec:
        add(Problem("error", "gradle_timeout_sec must be smaller than verify_timeout_sec"))

    # Test IDs.
    f2p, p2p = spec.f2p, spec.p2p
    overlap = sorted(set(f2p) & set(p2p))
    if overlap:
        add(Problem("error", f"tests listed in both f2p and p2p: {overlap}"))
    for tid in f2p + p2p:
        if tid.endswith("()"):
            add(Problem("warning", f"test id {tid!r} carries '()'; the grader normalizes it, drop it"))

    # Instruction.
    if not spec.instruction_path.is_file() or not spec.instruction_path.read_text("utf-8").strip():
        add(Problem("error", f"{INSTRUCTION_FILENAME} is missing or empty"))

    # Hidden tests.
    for rel in spec.hidden_tests:
        src = spec.hidden_dir / rel
        if not src.is_file():
            add(Problem("error", f"hidden test {rel} missing under {HIDDEN_DIRNAME}/"))
        if grader.classify_path(rel) != "test":
            add(Problem("error", f"hidden test path {rel} is not in a test source set"))
    if spec.hidden_dir.is_dir():
        on_disk = sorted(
            p.relative_to(spec.hidden_dir).as_posix() for p in spec.hidden_dir.rglob("*") if p.is_file()
        )
        extra = sorted(set(on_disk) - set(spec.hidden_tests))
        if extra:
            add(Problem("error", f"files under {HIDDEN_DIRNAME}/ not listed in hidden_tests: {extra}"))

    # Gold patch.
    gold = spec.gold_patch_path
    if not gold.is_file():
        add(Problem("error", f"gold patch {gold.name} is missing"))
        return
    text = gold.read_text("utf-8")
    files = patch_files(text)
    if not files:
        add(Problem("error", f"gold patch {gold.name} has no 'diff --git' headers"))
        return
    extra_protected = ver.get("extra_protected", [])
    for path in files:
        cat = grader.classify_path(path, extra_protected)
        if cat != "main":
            add(Problem("error", f"gold patch touches a {cat} path: {path}"))
    deps = grader.find_dependency_additions(text)
    if deps:
        add(Problem("error", f"gold patch adds a dependency in {deps}"))
    # Leak check: the instruction must not name files the fix touches.
    if spec.instruction_path.is_file():
        instruction = spec.instruction_path.read_text("utf-8")
        for path in files:
            base = Path(path).name
            if base in instruction:
                add(Problem("warning", f"instruction names {base}, a file the gold patch touches"))
