"""Create a draft task from a merged GitHub pull request (roadmap package P3-A).

The draft is what a human then runs through ``probo gate``: it carries the
gold patch, the hidden test patch, the Fail-to-Pass candidates read from
the test patch, the Gradle test tasks and class filters derived from the
touched modules, the interface contract (symbols the gold patch introduces
that the tests reference), source metadata, and a NOTES.md listing what
still needs a human. The instruction comes from the linked issue only,
never from the pull request's title or description (ROADMAP.md, Phase 3).

GitHub access goes through ``gh api`` (the user's own authentication) behind
a small ``Fetcher`` interface so the logic is testable with canned data.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import tomli_w

from probo.grader import grade as grader

PR_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$")
ISSUE_REF_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*"
    r"(?:https://github\.com/([^/\s]+)/([^/\s]+)/issues/(\d+)|#(\d+))",
    re.I,
)
_BUG_RE = re.compile(
    r"\b(bug|fix|fixes|crash|crashes|broken|regression|wrong|incorrect|fails?|error)\b", re.I
)
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_KT_DECL_RE = re.compile(
    r"^\s*(?:(?:public|internal|private|protected|open|abstract|final|data|sealed|inline|suspend|"
    r"override|operator|infix|const|lateinit|enum|annotation|value|expect|actual)\s+)*"
    r"(class|object|interface|fun|val|var)\s+(?:<[^>]+>\s+)?(?:[\w.]+\.)?`?([A-Za-z_][\w ]*?)`?\s*[(<:={]"
)
_JAVA_TYPE_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|abstract|sealed|non-sealed)\s+)*"
    r"(class|interface|enum|record)\s+([A-Za-z_]\w*)"
)
_JAVA_METHOD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|default|native)\s+)+"
    r"[\w<>\[\],.? ]+?\s+([A-Za-z_]\w*)\s*\("
)
_JAVA_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "new",
    "catch",
    "synchronized",
    "else",
    "do",
    "try",
}
_KT_TEST_FUN_RE = re.compile(
    r"^\s*(?:(?:public|internal|private|override|suspend)\s+)*fun\s+(?:`([^`]+)`|([A-Za-z_]\w*))\s*\("
)
_JAVA_TEST_METHOD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final)\s+)*[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\("
)
_TEST_ANNOTATION_RE = re.compile(r"^\s*@(?:org\.junit\.(?:jupiter\.api\.)?)?Test\b")
_LEADING_ANNOTATIONS_RE = re.compile(r"^\s*(?:@[\w.]+(?:\([^)]*\))?\s*)+")
_SOURCE_ROOTS = ("kotlin", "java")


# ---------------------------------------------------------------------------
# GitHub access
# ---------------------------------------------------------------------------


class Fetcher(Protocol):
    def json(self, endpoint: str) -> Any: ...

    def diff(self, endpoint: str) -> str: ...

    def file(self, endpoint: str) -> str | None: ...


class GhFetcher:
    """Reads through the ``gh`` CLI, which carries the user's authentication."""

    def _run(self, endpoint: str, accept: str | None = None) -> str:
        cmd = ["gh", "api"]
        if accept:
            cmd += ["-H", f"Accept: {accept}"]
        cmd.append(endpoint)
        return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8").stdout

    def json(self, endpoint: str) -> Any:
        return json.loads(self._run(endpoint))

    def diff(self, endpoint: str) -> str:
        return self._run(endpoint, accept="application/vnd.github.v3.diff")

    def file(self, endpoint: str) -> str | None:
        try:
            data = self.json(endpoint)
        except subprocess.CalledProcessError:
            return None
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Patch and source analysis
# ---------------------------------------------------------------------------


def split_patch(text: str) -> list[tuple[str, str]]:
    """Split a unified diff into ``(path, chunk)`` pairs at ``diff --git`` headers."""
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    path: str | None = None
    for line in text.splitlines(keepends=True):
        m = _DIFF_HEADER_RE.match(line.rstrip("\r\n"))
        if m:
            if path is not None:
                chunks.append((path, "".join(current)))
            path = m.group(2)
            current = [line]
        elif path is not None:
            current.append(line)
    if path is not None:
        chunks.append((path, "".join(current)))
    return chunks


def added_lines(chunk: str) -> list[str]:
    return [
        ln[1:].rstrip("\r\n") for ln in chunk.splitlines() if ln.startswith("+") and not ln.startswith("+++")
    ]


def module_of(path: str) -> str:
    """``feature/settings/src/test/kotlin/A.kt`` -> ``:feature:settings``; root -> ``""``."""
    parts = path.split("/")
    if "src" not in parts:
        return ""
    idx = parts.index("src")
    return "".join(":" + p for p in parts[:idx])


def class_fqn_of(path: str) -> str | None:
    """``app/src/test/kotlin/com/x/FooTest.kt`` -> ``com.x.FooTest``."""
    parts = path.split("/")
    if "src" not in parts:
        return None
    idx = parts.index("src")
    rest = parts[idx + 2 :]  # after src/<sourceSet>/
    if not rest:
        return None
    if rest[0] in _SOURCE_ROOTS:
        rest = rest[1:]
    if not rest or not rest[-1].endswith((".kt", ".java")):
        return None
    stem = rest[-1].rsplit(".", 1)[0]
    return ".".join([*rest[:-1], stem])


def removed_lines(chunk: str) -> list[str]:
    return [
        ln[1:].rstrip("\r\n") for ln in chunk.splitlines() if ln.startswith("-") and not ln.startswith("---")
    ]


def _declarations(lines: list[str], path: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in lines:
        if path.endswith(".kt"):
            m = _KT_DECL_RE.match(line)
            if m:
                out.append((m.group(2).strip(), line.strip()))
        elif path.endswith(".java"):
            m = _JAVA_TYPE_RE.match(line)
            if m:
                out.append((m.group(2), line.strip()))
                continue
            m = _JAVA_METHOD_RE.match(line)
            if m and m.group(1) not in _JAVA_KEYWORDS:
                out.append((m.group(1), line.strip()))
    return out


def declared_symbols(chunk: str, path: str, new_only: bool = False) -> list[tuple[str, str]]:
    """``(name, declaration line)`` for declarations the chunk adds. With
    ``new_only`` a declaration whose name also appears in a removed line is a
    modification of an existing symbol and is left out."""
    added = _declarations(added_lines(chunk), path)
    if not new_only:
        return added
    existing = {name for name, _d in _declarations(removed_lines(chunk), path)}
    return [(n, d) for n, d in added if n not in existing]


def signature_of(declaration: str) -> str:
    """Trim a declaration to its signature so the contract never carries the
    body of the fix: cut at the first ``=`` or ``{`` outside brackets."""
    depth = 0
    for i, ch in enumerate(declaration):
        if ch in "([<":
            depth += 1
        elif ch in ")]>":
            depth -= 1
        elif depth == 0 and ch in "={":
            return declaration[:i].rstrip()
    return declaration.rstrip()


def interface_contract(gold_chunks: list[tuple[str, str]], test_chunks: list[tuple[str, str]]) -> list[str]:
    """Signatures of declarations the gold patch introduces (not ones it only
    modifies) whose names the test patch references."""
    test_text = "\n".join(line for _p, c in test_chunks for line in added_lines(c))
    contract: list[str] = []
    for path, chunk in gold_chunks:
        for name, decl in declared_symbols(chunk, path, new_only=True):
            if re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", test_text):
                sig = signature_of(decl)
                if sig not in contract:
                    contract.append(sig)
    return contract


def f2p_candidates(test_chunks: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """New ``@Test`` methods added by the test patch, as ``class#method``, plus notes."""
    ids: list[str] = []
    notes: list[str] = []
    for path, chunk in test_chunks:
        fqn = class_fqn_of(path)
        if fqn is None:
            notes.append(f"could not derive a test class name from {path}; add its tests to f2p by hand")
            continue
        armed = False
        for line in added_lines(chunk):
            if _TEST_ANNOTATION_RE.match(line):
                armed = True
                # `@Test fun x()` on one line: drop the annotation and fall through.
                line = _LEADING_ANNOTATIONS_RE.sub("", line)
                if not line.strip():
                    continue
            if not armed:
                continue
            m = _KT_TEST_FUN_RE.match(line) if path.endswith(".kt") else _JAVA_TEST_METHOD_RE.match(line)
            if m:
                name = (m.group(1) or m.group(2)) if path.endswith(".kt") else m.group(1)
                tid = f"{fqn}#{name}"
                if tid not in ids:
                    ids.append(tid)
                armed = False
            elif line.strip() and not line.strip().startswith("@"):
                armed = False
    if not ids:
        notes.append(
            "no new @Test methods found in the test patch; the task needs at least one Fail-to-Pass test"
        )
    return ids, notes


def gradle_version_from_wrapper(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"distributionUrl=.*gradle-(\d+\.\d+(?:\.\d+)?)-", text)
    return m.group(1) if m else None


def agp_version_from_catalog(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(
        r'^\s*(?:agp|android-gradle-plugin|androidGradlePlugin|android-gradlePlugin)\s*=\s*"([^"]+)"',
        text,
        re.M,
    )
    return m.group(1) if m else None


def jdk_from_build_files(texts: list[str | None]) -> str | None:
    for t in texts:
        if not t:
            continue
        m = (
            re.search(r"jvmToolchain\((\d+)\)", t)
            or re.search(r"JavaVersion\.VERSION_(\d+)", t)
            or re.search(r"jvmTarget\s*=\s*[\"']?(\d+)", t)
        )
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# The draft
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    task_dir: Path
    spec: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = PR_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"not a GitHub pull request URL: {url}")
    return m.group(1), m.group(2), int(m.group(3))


def linked_issue(pr: dict[str, Any], owner: str, repo: str) -> tuple[str, str, int] | None:
    body = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
    m = ISSUE_REF_RE.search(body)
    if not m:
        return None
    if m.group(4):
        return owner, repo, int(m.group(4))
    return m.group(1), m.group(2), int(m.group(3))


def draft_task(
    pr_url: str,
    out_root: str | Path,
    fetcher: Fetcher | None = None,
    pack_version: str = "0.0.0",
    force: bool = False,
) -> Draft:
    fetch = fetcher or GhFetcher()
    owner, repo, number = parse_pr_url(pr_url)
    notes: list[str] = []
    problems: list[str] = []
    pr = fetch.json(f"repos/{owner}/{repo}/pulls/{number}")
    repo_info = fetch.json(f"repos/{owner}/{repo}")
    license_id = (repo_info.get("license") or {}).get("spdx_id") or "UNKNOWN"
    if license_id not in ("Apache-2.0", "MIT"):
        notes.append(f"source license is {license_id}: not eligible for the public pack")

    merged_at = pr.get("merged_at")
    merge_sha = pr.get("merge_commit_sha")
    if merged_at and merge_sha:
        merge_commit = fetch.json(f"repos/{owner}/{repo}/commits/{merge_sha}")
        parents = merge_commit.get("parents") or []
        base_sha = parents[0]["sha"] if parents else pr["base"]["sha"]
        diff_text = fetch.diff(f"repos/{owner}/{repo}/commits/{merge_sha}")
    else:
        notes.append(
            "pull request is not merged; using its current base and head instead of the merge commit"
        )
        base_sha = pr["base"]["sha"]
        diff_text = fetch.diff(f"repos/{owner}/{repo}/pulls/{number}")

    chunks = split_patch(diff_text)
    if not chunks:
        problems.append("the pull request diff is empty")
    gold_chunks: list[tuple[str, str]] = []
    test_chunks: list[tuple[str, str]] = []
    for path, chunk in chunks:
        cat = grader.classify_path(path)
        if cat == "main":
            gold_chunks.append((path, chunk))
        elif cat == "test":
            test_chunks.append((path, chunk))
        elif cat == "other":
            gold_chunks.append((path, chunk))
            notes.append(f"gold patch includes a non-source file: {path}")
        else:
            problems.append(f"the fix touches a {cat} file ({path}); v0.1 tasks must not")
    gold_text = "".join(c for _p, c in gold_chunks)
    if grader.find_dependency_additions(diff_text):
        problems.append("the fix adds a dependency; v0.1 tasks must not")
    if not gold_chunks:
        problems.append("no main-source change in the pull request")
    if not test_chunks:
        problems.append("no test-source change in the pull request; a task needs hidden tests")

    # Instruction: the linked issue only.
    issue_ref = linked_issue(pr, owner, repo)
    instruction = ""
    issue_url = ""
    issue_labels: list[str] = []
    if issue_ref:
        io, ir, inum = issue_ref
        issue = fetch.json(f"repos/{io}/{ir}/issues/{inum}")
        issue_url = str(issue.get("html_url") or f"https://github.com/{io}/{ir}/issues/{inum}")
        issue_labels = [str(lb.get("name")) for lb in issue.get("labels") or [] if isinstance(lb, dict)]
        instruction = f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}".strip() + "\n"
    else:
        notes.append(
            "no linked issue found in the pull request body; instruction.md is a placeholder. "
            "Write it from the issue the fix addresses, never from the pull request."
        )
        instruction = "TODO: describe the observable problem from the linked issue, without naming the fix.\n"

    # Verification spec from the touched test files.
    modules = sorted({module_of(p) for p, _c in test_chunks})
    test_tasks: list[str] = []
    test_filters: dict[str, list[str]] = {}
    build_texts: list[str | None] = []
    for mod in modules:
        prefix = mod.replace(":", "/").lstrip("/")
        prefix = prefix + "/" if prefix else ""
        build_text = fetch.file(
            f"repos/{owner}/{repo}/contents/{prefix}build.gradle.kts?ref={base_sha}"
        ) or fetch.file(f"repos/{owner}/{repo}/contents/{prefix}build.gradle?ref={base_sha}")
        build_texts.append(build_text)
        is_android = bool(build_text) and (
            "com.android" in build_text or re.search(r"^\s*android\s*\{", build_text, re.M) is not None
        )
        task = f"{mod}:testDebugUnitTest" if is_android else f"{mod}:test"
        if is_android and build_text and "productFlavors" in build_text:
            notes.append(
                f"module {mod or ':'} has product flavors; "
                "replace testDebugUnitTest with the right variant task"
            )
        if build_text is None:
            notes.append(
                f"could not read the build file of module {mod or ':'}; the test task name is a guess"
            )
        test_tasks.append(task)
        classes = sorted({c for p, _c in test_chunks if module_of(p) == mod for c in [class_fqn_of(p)] if c})
        if classes:
            test_filters[task] = classes
    f2p, f2p_notes = f2p_candidates(test_chunks)
    notes += f2p_notes
    contract = interface_contract(gold_chunks, test_chunks)

    gradle_version = gradle_version_from_wrapper(
        fetch.file(f"repos/{owner}/{repo}/contents/gradle/wrapper/gradle-wrapper.properties?ref={base_sha}")
    )
    agp = agp_version_from_catalog(
        fetch.file(f"repos/{owner}/{repo}/contents/gradle/libs.versions.toml?ref={base_sha}")
    )
    root_build = fetch.file(f"repos/{owner}/{repo}/contents/build.gradle.kts?ref={base_sha}")
    jdk = jdk_from_build_files([*build_texts, root_build])
    if jdk is None:
        notes.append("JDK version not found in build files; defaulting to 17")
        jdk = "17"

    head = f"{pr.get('title') or ''}\n{instruction[:300]}"
    kind = (
        "bug_fix"
        if (_BUG_RE.search(head) or any("bug" in lb.lower() for lb in issue_labels))
        else "small_feature"
    )
    task_id = re.sub(r"[^a-z0-9-]+", "-", f"{owner}--{repo}-{number}".lower()).strip("-")[:64]
    environment: dict[str, Any] = {
        "docker_image": f"pending:{owner}/{repo}@{base_sha}",
        "jdk": jdk,
        "cpus": 4,
        "memory_mb": 12288,
        "build_timeout_sec": 3600,
    }
    if gradle_version:
        environment["gradle"] = gradle_version
    else:
        notes.append("Gradle wrapper version not found; set environment.gradle by hand")
    if agp:
        environment["agp"] = agp
    verification: dict[str, Any] = {
        "test_tasks": test_tasks or [":test"],
        "hidden_patch": "hidden.patch",
        "f2p": f2p or ["TODO.Class#method"],
        "p2p": [],
        "agent_timeout_sec": 1800,
        "verify_timeout_sec": 1800,
        "gradle_timeout_sec": 1620,
    }
    if test_filters:
        verification["test_filters"] = test_filters
    if contract:
        verification["interface_contract"] = "\n".join(contract)
    source: dict[str, Any] = {
        "repo": f"https://github.com/{owner}/{repo}",
        "license": license_id,
        "base_commit": base_sha,
        "pr_url": f"https://github.com/{owner}/{repo}/pull/{number}",
        "attribution": (
            f"Mined from {owner}/{repo} ({license_id}) pull request #{number} at base commit {base_sha}. "
            "The instruction is the linked issue's text, which is user content."
        ),
    }
    if issue_url:
        source["issue_url"] = issue_url
    if merged_at:
        source["merge_date"] = str(merged_at)[:10]
    spec = {
        "schema_version": "0",
        "id": task_id,
        "kind": kind,
        "language": "android-kotlin" if any(p.endswith(".kt") for p, _c in gold_chunks) else "android-java",
        "pack_version": pack_version,
        "source": source,
        "environment": environment,
        "verification": verification,
        "gold": {"patch": "gold.patch"},
    }
    notes.append(
        "p2p is empty: run `probo gate` once the image exists and copy the tests that pass in state A"
    )
    notes.append(
        "environment.docker_image is a placeholder until the per-repo image is built and pinned by digest"
    )

    task_dir = Path(out_root) / task_id
    if task_dir.exists() and not force:
        problems.append(f"{task_dir} exists; pass --force to overwrite")
        return Draft(task_dir, spec, problems, notes)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "probo.toml").write_text(tomli_w.dumps(spec), encoding="utf-8", newline="\n")
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8", newline="\n")
    (task_dir / "gold.patch").write_text(gold_text, encoding="utf-8", newline="\n")
    (task_dir / "hidden.patch").write_text(
        "".join(c for _p, c in test_chunks), encoding="utf-8", newline="\n"
    )
    (task_dir / "NOTES.md").write_text(render_notes(pr_url, problems, notes), encoding="utf-8", newline="\n")
    return Draft(task_dir, spec, problems, notes)


def render_notes(pr_url: str, problems: list[str], notes: list[str]) -> str:
    lines = ["# Draft task notes", "", f"Source: {pr_url}", ""]
    if problems:
        lines += ["## Blocking", ""] + [f"- {p}" for p in problems] + [""]
    lines += ["## Before the gate", ""] + [f"- {n}" for n in notes] + [""]
    lines += [
        "## Then",
        "",
        "- Reread instruction.md a few days later: reject the task if it names the solution,",
        "  references files the fix touches, or is unsolvable without information outside the repo.",
        "- Build the per-repo image, set environment.docker_image by digest, run `probo gate --runs 10`.",
        "- Delete this file when the task enters a pack.",
        "",
    ]
    return "\n".join(lines)
