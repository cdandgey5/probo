"""Task schema validation and the converter, including the Harbor contract
test: every emitted task.toml must validate against Harbor 0.24.0's task
schema snapshot, and load through Harbor's own task model when Harbor is
installed (it is a dev dependency)."""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import jsonschema
import pytest

from probo.convert import build_instruction, convert_task
from probo.task import load_task, patch_files, patch_stats

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tasks" / "fixtures" / "pricing-discount"
HARBOR_SCHEMA = json.loads(
    (ROOT / "tests" / "fixtures" / "harbor-task-schema-0.24.0.json").read_text("utf-8")
)

try:  # Harbor is a dev dependency; the contract test skips without it.
    from harbor.models.task.task import Task as HarborTask
except Exception:  # noqa: BLE001
    HarborTask = None  # type: ignore[assignment]


def test_fixture_task_is_valid() -> None:
    spec = load_task(FIXTURE)
    assert spec.ok, [str(p) for p in spec.problems]
    assert spec.id == "pricing-discount"
    assert spec.test_tasks == [":test"]
    assert spec.gradle_timeout_sec == 540.0
    assert spec.test_command == "./gradlew test --offline"
    assert patch_files(spec.gold_patch_path.read_text("utf-8")) == [
        "src/main/kotlin/com/example/pricing/DiscountCalculator.kt"
    ]
    assert patch_stats(spec.gold_patch_path.read_text("utf-8")) == {
        "files": 1,
        "insertions": 1,
        "deletions": 1,
    }


def _copy_fixture(tmp_path: Path) -> Path:
    dst = tmp_path / "pricing-discount"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_validation_errors(tmp_path: Path) -> None:
    t = _copy_fixture(tmp_path)
    toml = t / "probo.toml"
    text = toml.read_text("utf-8")
    # Gold patch touching a test file, hidden file missing, overlapping ids,
    # CRLF gradlew, docker_image and repo_dir both set.
    (t / "gold.patch").write_text(
        "diff --git a/src/test/kotlin/T.kt b/src/test/kotlin/T.kt\n--- a/src/test/kotlin/T.kt\n+++ b/src/test/kotlin/T.kt\n@@ -1 +1 @@\n-a\n+b\n",
        encoding="utf-8",
    )
    (
        t / "hidden" / "src" / "test" / "kotlin" / "com" / "example" / "pricing" / "DiscountCalculatorTest.kt"
    ).unlink()
    text = text.replace(
        "p2p = [\n", 'p2p = [\n  "com.example.pricing.DiscountCalculatorTest#fullDiscountYieldsZero",\n'
    )
    text = text.replace('repo_dir = "repo"', 'repo_dir = "repo"\ndocker_image = "ghcr.io/x/y:latest"')
    toml.write_text(text, encoding="utf-8")
    (t / "repo" / "gradlew").write_bytes(b"#!/bin/sh\r\necho hi\r\n")
    spec = load_task(t)
    messages = "\n".join(str(p) for p in spec.problems)
    assert not spec.ok
    assert "gold patch touches a test path" in messages
    assert "missing under hidden/" in messages
    assert "listed in both f2p and p2p" in messages
    assert "CRLF" in messages
    assert "exactly one of docker_image or repo_dir" in messages


def test_schema_errors_are_reported_not_raised(tmp_path: Path) -> None:
    t = _copy_fixture(tmp_path)
    toml = t / "probo.toml"
    toml.write_text(
        toml.read_text("utf-8")
        .replace('kind = "bug_fix"', 'kind = "refactor"')
        .replace("f2p = [", "f2p = [\n  'bad id',"),
        encoding="utf-8",
    )
    spec = load_task(t)
    assert not spec.ok
    assert any("kind" in str(p) for p in spec.errors)
    assert any("f2p" in str(p) for p in spec.errors)


def test_instruction_leak_warning_and_unqualified_task(tmp_path: Path) -> None:
    t = _copy_fixture(tmp_path)
    (t / "instruction.md").write_text("Edit DiscountCalculator.kt so the test passes.\n", encoding="utf-8")
    toml = t / "probo.toml"
    toml.write_text(
        toml.read_text("utf-8").replace('test_tasks = [":test"]', 'test_tasks = ["test"]'), encoding="utf-8"
    )
    spec = load_task(t)
    assert any("test_tasks" in str(p) for p in spec.errors)
    t2 = _copy_fixture(tmp_path / "two")
    (t2 / "instruction.md").write_text("Edit DiscountCalculator.kt so the test passes.\n", encoding="utf-8")
    spec2 = load_task(t2)
    assert spec2.ok
    assert any("names DiscountCalculator.kt" in str(p) for p in spec2.warnings)


def test_convert_emits_harbor_layout(tmp_path: Path) -> None:
    spec = load_task(FIXTURE)
    out = convert_task(spec, tmp_path / "out")
    assert out == tmp_path / "out" / "pricing-discount"
    for rel in (
        "instruction.md",
        "task.toml",
        "environment/Dockerfile",
        "environment/.dockerignore",
        "environment/repo/gradlew",
        "environment/repo/src/main/kotlin/com/example/pricing/DiscountCalculator.kt",
        "solution/solve.sh",
        "solution/gold.patch",
        "tests/test.sh",
        "tests/grade.py",
        "tests/spec.json",
        "tests/hidden/src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt",
        "tests/original/build.gradle.kts",
        "tests/original/gradlew",
        "tests/original/gradle/wrapper/gradle-wrapper.properties",
        "tests/original/src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt",
    ):
        assert (out / rel).is_file(), rel
    assert not (out / "tests" / "original" / "src" / "main").exists()
    # LF everywhere in the scripts.
    for rel in ("tests/test.sh", "solution/solve.sh", "environment/Dockerfile", "tests/grade.py"):
        assert b"\r\n" not in (out / rel).read_bytes(), rel
    assert (out / "tests" / "grade.py").read_text("utf-8") == (
        ROOT / "src" / "probo" / "grader" / "grade.py"
    ).read_text("utf-8")

    spec_json = json.loads((out / "tests" / "spec.json").read_text("utf-8"))
    assert spec_json["test_tasks"] == [":test"]
    assert spec_json["results_dirs"] == ["build/test-results/test"]
    assert spec_json["f2p"] == ["com.example.pricing.DiscountCalculatorTest#fullDiscountYieldsZero"]
    assert spec_json["gradle_timeout_sec"] == 540.0

    instruction = (out / "instruction.md").read_text("utf-8")
    assert "100 percent discount" in instruction
    assert "./gradlew test --offline" in instruction
    assert "Do not edit test sources" in instruction

    dockerfile = (out / "environment" / "Dockerfile").read_text("utf-8")
    assert "FROM eclipse-temurin:17-jdk" in dockerfile
    assert "ls build/test-results/test/TEST-*.xml" in dockerfile
    assert "{" not in dockerfile.replace("${", "").replace("$(", "")  # every placeholder substituted


def test_task_toml_matches_harbor_schema_and_contract(tmp_path: Path) -> None:
    spec = load_task(FIXTURE)
    out = convert_task(spec, tmp_path / "out")
    data = tomllib.loads((out / "task.toml").read_text("utf-8"))
    jsonschema.validate(data, HARBOR_SCHEMA)
    assert data["schema_version"] == "1.4"
    assert data["verifier"]["environment_mode"] == "separate"
    assert data["verifier"]["environment"]["network_mode"] == "no-network"
    assert data["artifacts"] == ["/tmp/harbor-capture"]
    assert data["verifier"]["collect"][0]["command"].startswith("mkdir -p /tmp/harbor-capture")
    assert data["metadata"]["f2p"] == spec.f2p
    assert data["agent"]["timeout_sec"] == 900.0
    assert "user" not in data["agent"]
    if HarborTask is None:
        pytest.skip("harbor not installed")
    task = HarborTask(out)
    assert task.config.verifier.environment_mode.value == "separate"
    assert task.config.verifier.environment.network_mode.value == "no-network"
    assert task.name == "pricing-discount"
    assert "100 percent discount" in task.instruction


def test_convert_image_based_task(tmp_path: Path) -> None:
    t = _copy_fixture(tmp_path)
    toml = t / "probo.toml"
    toml.write_text(
        toml.read_text("utf-8").replace(
            'repo_dir = "repo"', 'docker_image = "ghcr.io/example/pricing@sha256:' + "0" * 64 + '"'
        ),
        encoding="utf-8",
    )
    shutil.rmtree(t / "repo")
    spec = load_task(t)
    assert spec.ok, [str(p) for p in spec.problems]
    out = convert_task(spec, tmp_path / "out")
    assert not (out / "environment" / "Dockerfile").exists()
    assert (out / "environment" / "README.md").is_file()
    assert not (out / "tests" / "original").exists()
    data = tomllib.loads((out / "task.toml").read_text("utf-8"))
    assert data["environment"]["docker_image"].startswith("ghcr.io/example/pricing@sha256:")
    jsonschema.validate(data, HARBOR_SCHEMA)
    # With a checkout supplied, pristine copies are taken from it.
    out2 = convert_task(spec, tmp_path / "out2", repo_for_originals=FIXTURE / "repo")
    assert (out2 / "tests" / "original" / "gradlew").is_file()


def test_interface_contract_and_agent_user(tmp_path: Path) -> None:
    t = _copy_fixture(tmp_path)
    toml = t / "probo.toml"
    toml.write_text(
        toml.read_text("utf-8")
        .replace(
            'test_command = "./gradlew test --offline"',
            'test_command = "./gradlew test --offline"\ninterface_contract = "object DiscountCalculator { fun applyDiscount(priceCents: Long, percent: Int): Long }"',
        )
        .replace('jdk = "17"', 'jdk = "17"\nagent_user = "agent"'),
        encoding="utf-8",
    )
    spec = load_task(t)
    assert spec.ok, [str(p) for p in spec.problems]
    assert "## Interface contract" in build_instruction(spec)
    out = convert_task(spec, tmp_path / "out")
    data = tomllib.loads((out / "task.toml").read_text("utf-8"))
    assert data["agent"]["user"] == "agent"
    jsonschema.validate(data, HARBOR_SCHEMA)
