"""Emit Harbor's task layout from a Probo task directory.

<out>/<task id>/
├── instruction.md        instruction + interface contract + rules
├── task.toml             separate key-less verifier, no-network, collect hook
├── environment/          generated Dockerfile + repo/ (inline tasks), or a
│                         note pointing at the per-repo image
├── solution/             solve.sh applies gold.patch (Harbor's oracle agent)
└── tests/                test.sh -> grade.py, spec.json, hidden/, original/
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import Any

import tomli_w

from probo import __version__
from probo.grader import grade as grader
from probo.task import TaskSpec

HARBOR_SCHEMA_VERSION = "1.4"
CAPTURE_DIR = "/tmp/harbor-capture"
COLLECT_COMMAND = (
    f"mkdir -p {CAPTURE_DIR} && cd /app && git add -A"
    f" && git diff --cached --binary HEAD > {CAPTURE_DIR}/agent.patch"
    f" && git diff --cached --name-status HEAD > {CAPTURE_DIR}/changed-files.txt; git reset -q"
)
_SKIP_DIRS = {".git", "build", ".gradle", ".kotlin", ".idea"}


def _template(name: str) -> str:
    return resources.files("probo.templates").joinpath(name).read_text("utf-8")


def _grader_source() -> str:
    return resources.files("probo.grader").joinpath("grade.py").read_text("utf-8")


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if executable:
        path.chmod(path.stat().st_mode | 0o111)


def build_instruction(spec: TaskSpec) -> str:
    body = spec.instruction_path.read_text("utf-8").rstrip() + "\n"
    contract = spec.verification.get("interface_contract", "").strip()
    sections = [body]
    if contract:
        sections.append(
            "\n## Interface contract\n\n"
            "The hidden tests reference these symbols; keep their names and signatures.\n\n" + contract + "\n"
        )
    sections.append(
        "\n## Environment and rules\n\n"
        "- The project is in the current directory (`/app`) and builds with Gradle.\n"
        f"- Run the relevant tests with `{spec.test_command}`. Always pass `--offline`: "
        "every dependency is already in the local Gradle cache, and the grading "
        "container has no network.\n"
        "- Change only main source sets (files under `src/main` and similar).\n"
        "- Do not edit test sources, Gradle build scripts, `gradle.properties`, "
        "version catalogs, the Gradle wrapper, init scripts, `buildSrc`/`build-logic` "
        "or CI configuration, and do not add dependencies. The grader restores "
        "those files from pristine copies before it runs the tests and rejects any "
        "submission that touched them.\n"
    )
    return "".join(sections)


def build_task_toml(spec: TaskSpec) -> dict[str, Any]:
    env = spec.environment
    src = spec.source
    metadata: dict[str, Any] = {
        "probo_schema_version": spec.data["schema_version"],
        "probo_version": __version__,
        "pack_version": spec.pack_version,
        "task_id": spec.id,
        "kind": spec.data["kind"],
        "language": spec.data["language"],
        "jdk": env["jdk"],
        "gradle": env["gradle"],
        "f2p": spec.f2p,
        "p2p": spec.p2p,
        "test_tasks": spec.test_tasks,
        "source_repo": src["repo"],
        "source_license": src["license"],
        "base_commit": src["base_commit"],
    }
    for key in ("difficulty",):
        if key in spec.data:
            metadata[key] = spec.data[key]
    for key in ("agp",):
        if env.get(key):
            metadata[key] = env[key]
    for key in ("issue_url", "pr_url", "merge_date"):
        if src.get(key):
            metadata[key] = src[key]

    agent: dict[str, Any] = {"timeout_sec": float(spec.agent_timeout_sec)}
    if env.get("agent_user"):
        agent["user"] = env["agent_user"]

    environment: dict[str, Any] = {
        "build_timeout_sec": float(env.get("build_timeout_sec", 1800)),
        "cpus": int(env.get("cpus", 2)),
        "memory_mb": int(env.get("memory_mb", 4096)),
    }
    if spec.docker_image:
        environment["docker_image"] = spec.docker_image

    return {
        "schema_version": HARBOR_SCHEMA_VERSION,
        # Files the grading container needs from the agent container. Harbor
        # copies them out after the agent phase and restores them at the same
        # path inside the separate verifier sandbox.
        "artifacts": [CAPTURE_DIR],
        "metadata": metadata,
        "agent": agent,
        "verifier": {
            "timeout_sec": float(spec.verify_timeout_sec),
            # Grade in a fresh container built from the same image: the
            # agent's filesystem, environment and API key never reach the grader.
            "environment_mode": "separate",
            # Baseline network policy of the grading container: none.
            "environment": {"network_mode": "no-network"},
            # Runs in the agent container after the agent finishes: only the
            # diff crosses the boundary, applied onto a pristine tree.
            "collect": [{"command": COLLECT_COMMAND, "timeout_sec": 60.0}],
        },
        "environment": environment,
    }


def build_spec_json(spec: TaskSpec) -> dict[str, Any]:
    results_dirs = list(spec.verification.get("results_dirs", [])) or [
        grader.gradle_task_to_results_dir(t) for t in spec.test_tasks
    ]
    env = spec.environment
    return {
        "schema": "probo-spec/1",
        "task_id": spec.id,
        "pack_version": spec.pack_version,
        "kind": spec.data["kind"],
        "language": spec.data["language"],
        "jdk": env["jdk"],
        "gradle": env["gradle"],
        "agp": env.get("agp"),
        "test_tasks": spec.test_tasks,
        "results_dirs": results_dirs,
        "f2p": spec.f2p,
        "p2p": spec.p2p,
        "hidden_tests": spec.hidden_tests,
        "extra_protected": list(spec.verification.get("extra_protected", [])),
        "gradle_timeout_sec": spec.gradle_timeout_sec,
        "agent_timeout_sec": spec.agent_timeout_sec,
        "verify_timeout_sec": spec.verify_timeout_sec,
        "probo_version": __version__,
        "grader_version": grader.GRADER_VERSION,
    }


def build_dockerfile(spec: TaskSpec) -> str:
    env = spec.environment
    results_dirs = build_spec_json(spec)["results_dirs"]
    probe_check = " && ".join(f"ls {d}/TEST-*.xml > /dev/null" for d in results_dirs)
    return _template("Dockerfile.inline").format(
        task_id=spec.id,
        base_image=env.get("base_image", "eclipse-temurin:17-jdk"),
        test_tasks=" ".join(spec.test_tasks),
        probe_check=probe_check,
    )


def protected_files(repo: Path, extra_protected: list[str]) -> list[Path]:
    """Repository files the grader restores: every test, build and CI path."""
    out: list[Path] = []
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if grader.is_protected(rel.as_posix(), extra_protected):
            out.append(rel)
    return out


def convert_task(spec: TaskSpec, out_root: str | Path, repo_for_originals: str | Path | None = None) -> Path:
    """Write the Harbor task directory and return its path.

    ``repo_for_originals``: for image-based tasks, a checkout of the repository
    at the base commit from which ``tests/original`` pristine copies are taken.
    Without it the grader restores protected files from git alone, which is
    enough in separate-verifier mode.
    """
    if not spec.ok:
        raise ValueError("task has validation errors: " + "; ".join(str(e) for e in spec.errors))
    out = Path(out_root).resolve() / spec.id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    _write(out / "instruction.md", build_instruction(spec))
    _write(out / "task.toml", tomli_w.dumps(build_task_toml(spec)))

    env_dir = out / "environment"
    env_dir.mkdir()
    repo_src = spec.repo_dir
    if repo_src is not None:
        _write(env_dir / "Dockerfile", build_dockerfile(spec))
        _write(env_dir / ".dockerignore", "repo/build/\nrepo/.gradle/\nrepo/.kotlin/\nrepo/.git/\n")
        shutil.copytree(repo_src, env_dir / "repo", ignore=shutil.ignore_patterns(*_SKIP_DIRS))
    else:
        _write(
            env_dir / "README.md",
            f"This task runs in the prebuilt image `{spec.docker_image}` (see task.toml). "
            "There is no Dockerfile here on purpose: the image is the source of truth.\n",
        )

    sol = out / "solution"
    _write(sol / "solve.sh", _template("solve.sh"), executable=True)
    shutil.copyfile(spec.gold_patch_path, sol / "gold.patch")

    tests = out / "tests"
    _write(tests / "test.sh", _template("test.sh"), executable=True)
    _write(tests / "grade.py", _grader_source())
    _write(tests / "spec.json", _json_dumps(build_spec_json(spec)))
    for rel in spec.hidden_tests:
        dst = tests / "hidden" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(spec.hidden_dir / rel, dst)
    originals_from = (
        repo_src if repo_src is not None else (Path(repo_for_originals) if repo_for_originals else None)
    )
    if originals_from is not None:
        extra = list(spec.verification.get("extra_protected", []))
        for rel in protected_files(originals_from, extra):
            dst = tests / "original" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(originals_from / rel, dst)
    return out


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, indent=2, sort_keys=True) + "\n"
