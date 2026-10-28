"""``probo new-task`` against a canned GitHub pull request."""

from __future__ import annotations

import base64
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from probo import newtask
from probo.task import load_task

OWNER, REPO, NUM = "acme", "shop-android", 77
MERGE = "f" * 40
BASE = "0" * 40

DIFF = """diff --git a/app/src/main/kotlin/com/acme/shop/Discount.kt b/app/src/main/kotlin/com/acme/shop/Discount.kt
index 1111111..2222222 100644
--- a/app/src/main/kotlin/com/acme/shop/Discount.kt
+++ b/app/src/main/kotlin/com/acme/shop/Discount.kt
@@ -1,4 +1,8 @@
 package com.acme.shop

-fun apply(price: Long, pct: Int) = price - price * pct.coerceIn(0, 99) / 100
+fun apply(price: Long, pct: Int) = price - price * pct.coerceIn(0, 100) / 100
+
+class DiscountPolicy(val max: Int) {
+    fun clamp(pct: Int): Int = pct.coerceIn(0, max)
+}
diff --git a/app/src/test/kotlin/com/acme/shop/DiscountTest.kt b/app/src/test/kotlin/com/acme/shop/DiscountTest.kt
index 3333333..4444444 100644
--- a/app/src/test/kotlin/com/acme/shop/DiscountTest.kt
+++ b/app/src/test/kotlin/com/acme/shop/DiscountTest.kt
@@ -4,4 +4,14 @@ class DiscountTest {
     @Test
     fun half() = assertEquals(100L, apply(200L, 50))
+
+    @Test
+    fun fullDiscountYieldsZero() = assertEquals(0L, apply(200L, 100))
+
+    @Test
+    fun `policy clamps above max`() {
+        assertEquals(50, DiscountPolicy(50).clamp(80))
+    }
+
+    private fun helper() = 1
 }
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 5555555..6666666 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,2 +1,3 @@
 # Changelog
+- Full discounts now yield zero (#41)
"""


class FakeFetcher:
    def __init__(self, files: dict[str, str], pr_overrides: dict[str, Any] | None = None):
        self.files = files
        self.calls: list[str] = []
        self.pr: dict[str, Any] = {
            "number": NUM,
            "title": "Fix full discount",
            "body": "Full discount returned 2 cents.\n\nFixes #41",
            "merged_at": "2026-09-15T10:00:00Z",
            "merge_commit_sha": MERGE,
            "base": {"sha": "9" * 40},
        }
        self.pr.update(pr_overrides or {})

    def json(self, endpoint: str) -> Any:
        self.calls.append(endpoint)
        if endpoint == f"repos/{OWNER}/{REPO}/pulls/{NUM}":
            return self.pr
        if endpoint == f"repos/{OWNER}/{REPO}":
            return {"license": {"spdx_id": "Apache-2.0"}}
        if endpoint == f"repos/{OWNER}/{REPO}/commits/{MERGE}":
            return {"sha": MERGE, "parents": [{"sha": BASE}, {"sha": "a" * 40}]}
        if endpoint == f"repos/{OWNER}/{REPO}/issues/41":
            return {
                "html_url": f"https://github.com/{OWNER}/{REPO}/issues/41",
                "title": "[Bug] A 100 percent discount leaves 2 cents",
                "body": "Applying a full discount to 200 cents gives 2 instead of 0.",
                "labels": [{"name": "bug"}],
            }
        if "/contents/" in endpoint:
            path = endpoint.split("/contents/", 1)[1].split("?", 1)[0]
            if path in self.files:
                return {"encoding": "base64", "content": base64.b64encode(self.files[path].encode()).decode()}
            raise FileNotFoundError(endpoint)
        raise KeyError(endpoint)

    def diff(self, endpoint: str) -> str:
        self.calls.append(endpoint)
        return DIFF

    def file(self, endpoint: str) -> str | None:
        try:
            data = self.json(endpoint)
        except FileNotFoundError:
            return None
        return base64.b64decode(data["content"]).decode()


@pytest.fixture
def files() -> dict[str, str]:
    return {
        "app/build.gradle.kts": 'plugins { alias(libs.plugins.android.application) }\nandroid {\n  namespace = "com.acme.shop"\n}\nkotlin { jvmToolchain(17) }\n',
        "gradle/wrapper/gradle-wrapper.properties": "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.14.3-bin.zip\n",
        "gradle/libs.versions.toml": '[versions]\nagp = "8.13.0"\nkotlin = "2.2.0"\n',
        "build.gradle.kts": "plugins {}\n",
    }


def test_parse_pr_url() -> None:
    assert newtask.parse_pr_url("https://github.com/acme/shop/pull/7") == ("acme", "shop", 7)
    with pytest.raises(ValueError):
        newtask.parse_pr_url("https://github.com/acme/shop/issues/7")


def test_split_patch_and_helpers() -> None:
    chunks = newtask.split_patch(DIFF)
    assert [p for p, _c in chunks] == [
        "app/src/main/kotlin/com/acme/shop/Discount.kt",
        "app/src/test/kotlin/com/acme/shop/DiscountTest.kt",
        "CHANGELOG.md",
    ]
    assert "".join(c for _p, c in chunks) == DIFF
    assert newtask.module_of("app/src/test/kotlin/A.kt") == ":app"
    assert newtask.module_of("feature/settings/src/test/kotlin/A.kt") == ":feature:settings"
    assert newtask.module_of("src/test/kotlin/A.kt") == ""
    assert (
        newtask.class_fqn_of("app/src/test/kotlin/com/acme/shop/DiscountTest.kt")
        == "com.acme.shop.DiscountTest"
    )
    assert newtask.class_fqn_of("core/src/test/java/org/x/PTest.java") == "org.x.PTest"
    assert newtask.class_fqn_of("app/src/test/resources/data.json") is None
    assert (
        newtask.gradle_version_from_wrapper("distributionUrl=https\\://x/gradle-8.14.3-bin.zip") == "8.14.3"
    )
    assert newtask.agp_version_from_catalog('[versions]\nagp = "8.13.0"\n') == "8.13.0"
    assert newtask.jdk_from_build_files([None, "kotlin { jvmToolchain(21) }"]) == "21"
    assert newtask.jdk_from_build_files(["sourceCompatibility = JavaVersion.VERSION_11"]) == "11"


def test_f2p_and_contract_extraction() -> None:
    chunks = newtask.split_patch(DIFF)
    gold = [c for c in chunks if c[0].endswith("Discount.kt")]
    tests = [c for c in chunks if c[0].endswith("DiscountTest.kt")]
    ids, notes = newtask.f2p_candidates(tests)
    assert ids == [
        "com.acme.shop.DiscountTest#fullDiscountYieldsZero",
        "com.acme.shop.DiscountTest#policy clamps above max",
    ]
    assert notes == []
    contract = newtask.interface_contract(gold, tests)
    # `apply` existed before (it appears in a removed line): a modification, not a new symbol.
    # Signatures only: the contract must never carry the body of the fix.
    assert contract == ["class DiscountPolicy(val max: Int)", "fun clamp(pct: Int): Int"]
    assert newtask.signature_of("fun f(a: Int = 1): Int = a + 1") == "fun f(a: Int = 1): Int"
    assert newtask.signature_of("public static boolean ok(String s) { return true; }") == (
        "public static boolean ok(String s)"
    )
    assert newtask.signature_of("class A : Base()") == "class A : Base()"


def test_java_declarations() -> None:
    chunk = (
        "diff --git a/core/src/main/java/org/x/Parser.java b/core/src/main/java/org/x/Parser.java\n"
        "--- a/core/src/main/java/org/x/Parser.java\n+++ b/core/src/main/java/org/x/Parser.java\n"
        "@@ -1,2 +1,6 @@\n public class Parser {\n+  public static boolean ok(String s) { return true; }\n"
        "+  private void helper() {}\n+  if (x) {\n+  record Token(String text) {}\n }\n"
    )
    names = [n for n, _d in newtask.declared_symbols(chunk, "core/src/main/java/org/x/Parser.java")]
    assert names == ["ok", "helper", "Token"]
    test_chunk = (
        "diff --git a/core/src/test/java/org/x/ParserTest.java b/core/src/test/java/org/x/ParserTest.java\n"
        "--- a/core/src/test/java/org/x/ParserTest.java\n+++ b/core/src/test/java/org/x/ParserTest.java\n"
        '@@ -1,2 +1,5 @@\n class ParserTest {\n+  @Test\n+  void trailingSpace() { assertTrue(Parser.ok("a ")); }\n+  @Test void tokens() { new Token("x"); }\n }\n'
    )
    ids, _ = newtask.f2p_candidates([("core/src/test/java/org/x/ParserTest.java", test_chunk)])
    assert ids == ["org.x.ParserTest#trailingSpace", "org.x.ParserTest#tokens"]


def test_draft_task_end_to_end(tmp_path: Path, files: dict[str, str]) -> None:
    fetcher = FakeFetcher(files)
    draft = newtask.draft_task(
        f"https://github.com/{OWNER}/{REPO}/pull/{NUM}", tmp_path, fetcher, pack_version="0.1.0"
    )
    assert draft.ok, draft.problems
    task = draft.task_dir
    assert task == tmp_path / "acme--shop-android-77"
    data = tomllib.loads((task / "probo.toml").read_text("utf-8"))
    assert data["kind"] == "bug_fix" and data["language"] == "android-kotlin"
    assert data["source"]["base_commit"] == BASE  # first parent of the merge commit, not the stale PR base
    assert data["source"]["merge_date"] == "2026-09-15"
    assert data["source"]["issue_url"].endswith("/issues/41")
    assert data["source"]["license"] == "Apache-2.0"
    assert data["environment"]["docker_image"].startswith("pending:acme/shop-android@")
    assert data["environment"]["jdk"] == "17" and data["environment"]["gradle"] == "8.14.3"
    assert data["environment"]["agp"] == "8.13.0"
    assert data["verification"]["test_tasks"] == [":app:testDebugUnitTest"]
    assert data["verification"]["test_filters"] == {":app:testDebugUnitTest": ["com.acme.shop.DiscountTest"]}
    assert data["verification"]["f2p"] == [
        "com.acme.shop.DiscountTest#fullDiscountYieldsZero",
        "com.acme.shop.DiscountTest#policy clamps above max",
    ]
    assert data["verification"]["p2p"] == []
    assert "class DiscountPolicy(val max: Int)" in data["verification"]["interface_contract"]
    instruction = (task / "instruction.md").read_text("utf-8")
    assert instruction.startswith("[Bug] A 100 percent discount leaves 2 cents")
    assert "Fixes #41" not in instruction  # never the pull request text
    gold = (task / "gold.patch").read_text("utf-8")
    assert "Discount.kt" in gold and "CHANGELOG.md" in gold and "DiscountTest.kt" not in gold
    hidden = (task / "hidden.patch").read_text("utf-8")
    assert "DiscountTest.kt" in hidden and "Discount.kt b/" not in hidden
    notes = (task / "NOTES.md").read_text("utf-8")
    assert "non-source file: CHANGELOG.md" in notes and "p2p is empty" in notes
    # The draft validates (with warnings) and converts.
    spec = load_task(task)
    assert spec.ok, [str(p) for p in spec.problems]
    assert any("not pinned by digest" in str(w) for w in spec.warnings)
    assert f"repos/{OWNER}/{REPO}/commits/{MERGE}" in fetcher.calls


def test_draft_task_rejects_build_file_changes_and_missing_issue(
    tmp_path: Path, files: dict[str, str]
) -> None:
    bad_diff = DIFF + (
        "diff --git a/app/build.gradle.kts b/app/build.gradle.kts\n--- a/app/build.gradle.kts\n+++ b/app/build.gradle.kts\n"
        '@@ -1,2 +1,3 @@\n plugins {}\n+dependencies { implementation("x:y:1") }\n'
    )

    class BadFetcher(FakeFetcher):
        def diff(self, endpoint: str) -> str:
            return bad_diff

    fetcher = BadFetcher(
        files, pr_overrides={"body": "no issue link here", "merged_at": None, "merge_commit_sha": None}
    )
    draft = newtask.draft_task(f"https://github.com/{OWNER}/{REPO}/pull/{NUM}", tmp_path, fetcher)
    assert not draft.ok
    assert any("touches a build file" in p for p in draft.problems)
    assert any("adds a dependency" in p for p in draft.problems)
    assert any("no linked issue" in n for n in draft.notes)
    assert any("not merged" in n for n in draft.notes)
    assert (draft.task_dir / "instruction.md").read_text("utf-8").startswith("TODO")
    assert "## Blocking" in (draft.task_dir / "NOTES.md").read_text("utf-8")
    # Refuses to overwrite without --force.
    again = newtask.draft_task(f"https://github.com/{OWNER}/{REPO}/pull/{NUM}", tmp_path, fetcher)
    assert any("exists" in p for p in again.problems)
    forced = newtask.draft_task(
        f"https://github.com/{OWNER}/{REPO}/pull/{NUM}", tmp_path, fetcher, force=True
    )
    assert not any("exists" in p for p in forced.problems)


def test_notes_render() -> None:
    text = newtask.render_notes("https://x/pull/1", ["blocked"], ["note"])
    assert "## Blocking" in text and "- blocked" in text and "- note" in text
    assert json.dumps(text)  # plain text, serialisable
