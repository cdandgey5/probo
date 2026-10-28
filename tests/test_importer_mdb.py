"""The MobileDev-Bench importer against a synthetic four-row sample
(tests/fixtures/mdb-sample.jsonl): one importable Kotlin row with string-encoded
test lists, one excluded for adding a dependency in a build file, one Java row
with two Gradle tasks, nested-class and parameterized test names, and one
Flutter row that is skipped."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from probo.convert import convert_task
from probo.importers import mobiledev_bench as mdb
from probo.task import load_task

SAMPLE = Path(__file__).with_name("fixtures") / "mdb-sample.jsonl"


def test_split_test_id() -> None:
    assert mdb.split_test_id("com.example.ListTest.old") == "com.example.ListTest#old"
    assert mdb.split_test_id("org.another.ParserTest.check(int)[1]") == "org.another.ParserTest#check(int)[1]"
    assert (
        mdb.split_test_id("org.another.Outer$Inner.should handle spaces (a, b) [2]")
        == "org.another.Outer$Inner#should handle spaces (a, b) [2]"
    )
    assert (
        mdb.split_test_id("com.jerboa.T.should rewrite (^, ^) [17]")
        == "com.jerboa.T#should rewrite (^, ^) [17]"
    )
    assert mdb.split_test_id("NoDots") == "NoDots"


def test_parse_test_command() -> None:
    tasks, filters = mdb.parse_test_command(
        './gradlew :app:testBetaDebugUnitTest --tests "fr.x.ReasonBuilderTest"'
    )
    assert tasks == [":app:testBetaDebugUnitTest"]
    assert filters == {":app:testBetaDebugUnitTest": ["fr.x.ReasonBuilderTest"]}
    tasks, filters = mdb.parse_test_command(
        './gradlew :mail:protocols:smtp:test --tests "a.SmtpTest" :mail:protocols:imap:test --tests "b.ImapTest" --tests "b.ConnTest"'
    )
    assert tasks == [":mail:protocols:smtp:test", ":mail:protocols:imap:test"]
    assert filters == {
        ":mail:protocols:smtp:test": ["a.SmtpTest"],
        ":mail:protocols:imap:test": ["b.ImapTest", "b.ConnTest"],
    }
    assert mdb.parse_test_command("./gradlew test --no-daemon") == ([], {})
    assert mdb.parse_test_command("./gradlew :app:test --tests=x.Y") == (
        [":app:test"],
        {":app:test": ["x.Y"]},
    )


def test_json_field_and_ids() -> None:
    assert mdb.json_field('{"a": 1}') == {"a": 1}
    assert mdb.json_field({"a": 1}) == {"a": 1}
    assert mdb.json_field("") == {} and mdb.json_field(None) == {} and mdb.json_field("not json") == {}
    rows = mdb.load_rows(SAMPLE)
    assert mdb.task_id_for(rows[0]) == "example-org--sample-app-101"
    assert mdb.image_ref(rows[0]) == "ghcr.io/mobiledev-bench/mobiledevbench/example-org_mb_sample-app:pr-101"
    java = rows[2]
    assert mdb.f2p_ids(java) == [
        "org.another.ParserTest#trailingSpace",
        "org.another.ParserTest#check(int)[1]",
        "org.another.Outer$Inner#should handle spaces (a, b) [2]",
        "org.another.ParserTest#skipped",
    ]
    # A test listed both as F2P and P2P stays F2P only.
    assert mdb.p2p_ids(java) == ["org.another.cli.MainTest#runs"]


def test_assess_decisions() -> None:
    rows = mdb.load_rows(SAMPLE)
    d0, d1, d2 = (mdb.assess(r) for r in rows[:3])
    assert d0.importable and d0.reasons == [] and d0.n_f2p == 1 and d0.n_p2p == 1
    assert d0.license is None and d0.public_pack_ok is False  # unknown upstream: never public-pack
    assert not d1.importable
    assert "fix_touches_build" in d1.reasons and "fix_adds_dependency" in d1.reasons
    assert d2.importable and d2.test_tasks == [":core:test", ":cli:testDebugUnitTest"]
    assert d2.task_id == "anotherorg--java-app-7"


def test_import_rows_writes_valid_tasks(tmp_path: Path) -> None:
    rows = mdb.load_rows(SAMPLE)
    decisions = mdb.import_rows(rows, tmp_path / "out", pack_version="0.1.0")
    assert [d.instance_id for d in decisions] == [
        "Example-Org__sample-app-101",
        "Example-Org__sample-app-102",
        "AnotherOrg__java-app-7",
    ]  # the Flutter row is skipped entirely
    assert sum(1 for d in decisions if d.task_dir) == 2
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text("utf-8"))
    assert manifest["n_android_rows"] == 3 and manifest["n_importable"] == 2 and manifest["n_written"] == 2

    task = tmp_path / "out" / "example-org--sample-app-101"
    spec = load_task(task)
    assert spec.ok, [str(p) for p in spec.problems]
    assert any("environment.jdk" in str(w) for w in spec.warnings)
    data = tomllib.loads((task / "probo.toml").read_text("utf-8"))
    assert data["kind"] == "bug_fix" and data["language"] == "android-kotlin"
    assert data["source"]["base_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert data["source"]["issue_url"].endswith("/issues/42")
    assert "CC-BY-4.0" in data["source"]["attribution"]
    assert data["environment"]["image_with_repo"].endswith("example-org_mb_sample-app:pr-101")
    assert data["environment"]["image_repo_path"] == "/home/sample-app"
    assert data["verification"]["test_tasks"] == [":app:testDebugUnitTest"]
    assert data["verification"]["test_filters"] == {":app:testDebugUnitTest": ["com.example.ListTest"]}
    assert data["verification"]["f2p"] == ["com.example.ListTest#emptyListGivesNull"]
    assert data["verification"]["p2p"] == ["com.example.ListTest#old"]
    assert data["verification"]["test_command"].startswith("./gradlew --offline :app:testDebugUnitTest")
    assert (task / "instruction.md").read_text("utf-8").startswith("[Bug]: App crashes")
    assert "I can take this one" not in (task / "instruction.md").read_text("utf-8")
    assert (task / "hidden.patch").read_text("utf-8").startswith("diff --git a/app/src/test/")
    assert spec.test_command == './gradlew --offline :app:testDebugUnitTest --tests "com.example.ListTest"'

    out = convert_task(spec, tmp_path / "harbor")
    dockerfile = (out / "environment" / "Dockerfile").read_text("utf-8")
    assert dockerfile.startswith("# Generated by probo convert")
    assert "FROM ghcr.io/mobiledev-bench/mobiledevbench/example-org_mb_sample-app:pr-101" in dockerfile
    assert "--continue :app:testDebugUnitTest --tests com.example.ListTest" in dockerfile
    assert 'ln -s "/home/sample-app" /app' in dockerfile
    assert "rm -f /home/fix.patch" in dockerfile
    assert "ls app/build/test-results/testDebugUnitTest/TEST-*.xml" in dockerfile
    assert (out / "tests" / "hidden.patch").is_file()
    spec_json = json.loads((out / "tests" / "spec.json").read_text("utf-8"))
    assert spec_json["hidden_patch"] == "hidden.patch"
    assert spec_json["test_filters"] == {":app:testDebugUnitTest": ["com.example.ListTest"]}
    task_toml = tomllib.loads((out / "task.toml").read_text("utf-8"))
    assert "docker_image" not in task_toml["environment"]
    assert task_toml["environment"]["memory_mb"] == 12288

    java_task = tmp_path / "out" / "anotherorg--java-app-7"
    jspec = load_task(java_task)
    assert jspec.ok, [str(p) for p in jspec.problems]
    assert jspec.test_filters == {
        ":core:test": ["org.another.ParserTest"],
        ":cli:testDebugUnitTest": ["org.another.cli.MainTest"],
    }


def test_import_all_and_limit(tmp_path: Path) -> None:
    rows = mdb.load_rows(SAMPLE)
    decisions = mdb.import_rows(rows, tmp_path / "all", only_importable=False, limit=1)
    assert sum(1 for d in decisions if d.task_dir) == 1
    decisions = mdb.import_rows(rows, tmp_path / "pub", public_pack_only=True)
    assert sum(1 for d in decisions if d.task_dir) == 0  # synthetic repos have no known license
    text = mdb.summarize(decisions)
    assert "importable: 2" in text and "fix_adds_dependency" in text
