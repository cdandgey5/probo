"""Import MobileDev-Bench Android tasks (arXiv 2603.24946) as Probo tasks.

Source: the Hugging Face dataset ``MobileDev-Bench/mobiledev-bench``
(``data/test.jsonl``, CC-BY-4.0) and the per-task images the authors publish
on GHCR. See docs/mobiledev-bench.md for the licensing analysis and
docs/mobiledev-bench-images.md for the image layout.

What a row becomes: ``instruction.md`` from ``problem_statement`` (the issue
text; ``hints`` are pull-request comments and are deliberately not used),
``gold.patch`` from ``fix_patch``, ``hidden.patch`` from ``test_patch``,
``probo.toml`` with the Gradle tasks and ``--tests`` filters parsed from
``test_command``, Fail-to-Pass IDs from ``f2p_tests`` plus ``n2p_tests`` and
``s2p_tests`` (tests that are missing or skipped at base and pass after the
fix count as Fail-to-Pass), Pass-to-Pass IDs from ``p2p_tests``, and an
``image_with_repo`` environment pointing at the published instance image.

What is excluded, by the v0.1 rules in ROADMAP.md: rows whose fix patch
touches a build, test or CI file, adds a dependency or edits a dependency
baseline; rows whose test patch touches main sources, build or CI files; rows without a Gradle task or
without a Fail-to-Pass test. Every decision is written to ``manifest.json``.

The imported patches are code from the upstream apps and keep those apps'
licenses; they are redistributed as labelled data, never as part of Probo.
Only Apache-2.0 and MIT sources qualify for the public pack
(``public_pack_ok`` in the manifest).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from probo.grader import grade as grader
from probo.task import patch_files

DATASET = "MobileDev-Bench/mobiledev-bench"
DATASET_URL = "https://huggingface.co/datasets/MobileDev-Bench/mobiledev-bench"
PAPER = "Fakorede, Upadhyay, Siddique and Farooq, MobileDev-Bench, arXiv 2603.24946 (2026)"
DEFAULT_IMAGE_PATTERN = "ghcr.io/mobiledev-bench/mobiledevbench/{org}_mb_{repo}:pr-{number}"
DEFAULT_REPO_PATH = "/home/{repo}"  # the harness clones to /home/<repo>, case preserved
ANDROID_LANGS = {"kotlin": "android-kotlin", "java": "android-java"}

# Paper table 5, as recorded in docs/mobiledev-bench.md. Verify against each
# repository's LICENSE file before redistributing anything derived from it.
UPSTREAM_LICENSES = {
    "thunderbird/thunderbird-android": "Apache-2.0",
    "wordpress-mobile/WordPress-Android": "GPL-2.0",
    "element-hq/element-x-android": "AGPL-3.0",
    "streetcomplete/StreetComplete": "GPL-3.0",
    "tuskyapp/Tusky": "GPL-3.0",
    "commons-app/apps-android-commons": "Apache-2.0",
    "AntennaPod/AntennaPod": "GPL-3.0",
    "openhab/openhab-android": "EPL-2.0",
    "Futsch1/medTimer": "MIT",
    "PaulWoitaschek/Voice": "GPL-3.0",
    "LemmyNet/jerboa": "AGPL-3.0",
    "mjaakko/NeoStumbler": "MIT",
    "JackEblan/Geto": "GPL-3.0",
}
PUBLIC_PACK_LICENSES = {"Apache-2.0", "MIT"}

_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# Dependency-guard baselines (Thunderbird): a fix that touches them changed the
# runtime classpath, which offline grading cannot follow in v0.1.
_DEP_BASELINE_RE = re.compile(r"(^|/)dependencies/[^/]+\.txt$")
_BUG_RE = re.compile(
    r"\b(bug|fix|fixes|crash|crashes|broken|regression|wrong|incorrect|fails?|error)\b", re.I
)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def json_field(value: Any) -> dict[str, Any]:
    """``f2p_tests`` and friends are dicts in a few rows and JSON strings in
    most. Empty or unparsable values are empty."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def split_test_id(key: str) -> str:
    """``pkg.Class.method`` -> ``pkg.Class#method``.

    MobileDev-Bench joins the JUnit classname and the test name with a dot.
    The class part is the longest prefix of dot-separated identifiers; the
    first segment that is not an identifier (display names with spaces or
    parentheses, parameterized ``[1]`` suffixes) starts the test name. When
    every segment is an identifier the last one is the method.
    """
    parts = key.split(".")
    for i in range(1, len(parts)):
        if not _IDENT_RE.match(parts[i]):
            return ".".join(parts[:i]) + "#" + ".".join(parts[i:])
    if len(parts) < 2:
        return key
    return ".".join(parts[:-1]) + "#" + parts[-1]


def parse_test_command(command: str) -> tuple[list[str], dict[str, list[str]]]:
    """``./gradlew :app:testDebugUnitTest --tests "a.B" :lib:test`` ->
    ``([":app:testDebugUnitTest", ":lib:test"], {":app:testDebugUnitTest": ["a.B"]})``.

    Each ``--tests`` pattern attaches to the task that precedes it, which is
    how Gradle binds task options. Other flags are ignored.
    """
    tokens = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', command)
    tasks: list[str] = []
    filters: dict[str, list[str]] = {}
    current: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i].strip("\"'")
        if tok.startswith(":"):
            current = tok
            if tok not in tasks:
                tasks.append(tok)
        elif tok == "--tests" and i + 1 < len(tokens) and current is not None:
            pattern = tokens[i + 1].strip("\"'")
            if pattern not in filters.setdefault(current, []):
                filters[current].append(pattern)
            i += 1
        elif tok.startswith("--tests=") and current is not None:
            pattern = tok.split("=", 1)[1].strip("\"'")
            if pattern not in filters.setdefault(current, []):
                filters[current].append(pattern)
        i += 1
    return tasks, filters


def task_id_for(row: dict[str, Any]) -> str:
    raw = str(row.get("instance_id") or f"{row.get('org')}__{row.get('repo')}-{row.get('number')}")
    # Keep the org/repo separator visible: "Org__repo-12" -> "org--repo-12".
    tid = re.sub(r"[^a-z0-9-]+", "-", raw.lower().replace("__", "--")).strip("-")
    return tid[:64]


def image_ref(row: dict[str, Any], pattern: str = DEFAULT_IMAGE_PATTERN) -> str:
    return pattern.format(org=str(row["org"]).lower(), repo=str(row["repo"]).lower(), number=row["number"])


def repo_slug(row: dict[str, Any]) -> str:
    return f"{row['org']}/{row['repo']}"


def repo_path_for(row: dict[str, Any], pattern: str = DEFAULT_REPO_PATH) -> str:
    return pattern.format(repo=str(row["repo"]), org=str(row["org"]))


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@dataclass
class Decision:
    instance_id: str
    task_id: str
    repo: str
    license: str | None
    public_pack_ok: bool
    importable: bool
    reasons: list[str] = field(default_factory=list)
    test_tasks: list[str] = field(default_factory=list)
    n_f2p: int = 0
    n_p2p: int = 0
    fix_patch_lines: int = 0
    task_dir: str | None = None


def f2p_ids(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for fld in ("f2p_tests", "n2p_tests", "s2p_tests"):
        for k in json_field(row.get(fld)):
            if k not in keys:
                keys.append(k)
    return [split_test_id(k) for k in keys]


def p2p_ids(row: dict[str, Any]) -> list[str]:
    f2p = set(f2p_ids(row))
    out = []
    for k in json_field(row.get("p2p_tests")):
        tid = split_test_id(k)
        if tid not in f2p and tid not in out:
            out.append(tid)
    return out


def assess(row: dict[str, Any]) -> Decision:
    reasons: list[str] = []
    lang = str(row.get("lang") or "")
    if lang not in ANDROID_LANGS:
        reasons.append(f"not_android:{lang}")
    fix = row.get("fix_patch") or ""
    test = row.get("test_patch") or ""
    fix_files = patch_files(fix)
    test_files = patch_files(test)
    if not fix_files:
        reasons.append("empty_fix_patch")
    bad_fix = sorted({grader.classify_path(p) for p in fix_files} - {"main", "other"})
    for cat in bad_fix:
        reasons.append(f"fix_touches_{cat}")
    if grader.find_dependency_additions(fix):
        reasons.append("fix_adds_dependency")
    if any(_DEP_BASELINE_RE.search(p) for p in fix_files):
        reasons.append("fix_touches_dependency_baseline")
    if not test_files:
        reasons.append("empty_test_patch")
    bad_test = sorted({grader.classify_path(p) for p in test_files} - {"test", "other"})
    for cat in bad_test:
        reasons.append(f"test_patch_touches_{cat}")
    tasks, _filters = parse_test_command(str(row.get("test_command") or ""))
    if not tasks:
        reasons.append("no_gradle_task")
    f2p = f2p_ids(row)
    if not f2p:
        reasons.append("no_f2p")
    slug = repo_slug(row)
    lic = UPSTREAM_LICENSES.get(slug)
    return Decision(
        instance_id=str(row.get("instance_id")),
        task_id=task_id_for(row),
        repo=slug,
        license=lic,
        public_pack_ok=lic in PUBLIC_PACK_LICENSES,
        importable=not reasons,
        reasons=reasons,
        test_tasks=tasks,
        n_f2p=len(f2p),
        n_p2p=len(p2p_ids(row)),
        fix_patch_lines=len(fix.splitlines()),
    )


# ---------------------------------------------------------------------------
# Writing a task
# ---------------------------------------------------------------------------


def _kind(row: dict[str, Any]) -> str:
    head = f"{row.get('title') or ''}\n{(row.get('problem_statement') or '')[:300]}"
    return "bug_fix" if _BUG_RE.search(head) else "small_feature"


def _with_offline(command: str) -> str:
    if "--offline" in command:
        return command
    return command.replace("./gradlew", "./gradlew --offline", 1) if "./gradlew" in command else command


def build_spec(
    row: dict[str, Any],
    pack_version: str = "0.0.0",
    image_pattern: str = DEFAULT_IMAGE_PATTERN,
    repo_path: str = DEFAULT_REPO_PATH,
    toolchain: dict[str, str] | None = None,
) -> dict[str, Any]:
    tasks, filters = parse_test_command(str(row.get("test_command") or ""))
    slug = repo_slug(row)
    base = row.get("base") or {}
    sha = str(base.get("sha") if isinstance(base, dict) else base)
    issue_urls = row.get("issue_urls") or []
    if isinstance(issue_urls, str):
        try:
            issue_urls = json.loads(issue_urls)
        except json.JSONDecodeError:
            issue_urls = [issue_urls]
    lic = UPSTREAM_LICENSES.get(slug, "UNKNOWN")
    source: dict[str, Any] = {
        "repo": f"https://github.com/{slug}",
        "license": lic,
        "base_commit": sha,
        "pr_url": str(row.get("pull_url") or ""),
        "attribution": (
            f"Imported from MobileDev-Bench ({PAPER}; dataset {DATASET_URL}, CC-BY-4.0), "
            f"instance {row.get('instance_id')}. The gold and hidden-test patches are code from "
            f"{slug} ({lic}) at commit {sha}; they keep that license and are redistributed as "
            "labelled data, not as part of Probo. The instruction is the linked issue text, "
            "which is user content."
        ),
    }
    if issue_urls:
        source["issue_url"] = str(issue_urls[0])
    environment: dict[str, Any] = {
        "image_with_repo": image_ref(row, image_pattern),
        "image_repo_path": repo_path_for(row, repo_path),
        "cpus": 4,
        "memory_mb": 12288,
        "build_timeout_sec": 3600,
    }
    if toolchain:
        for k in ("jdk", "gradle", "agp"):
            if toolchain.get(k):
                environment[k] = toolchain[k]
    verification: dict[str, Any] = {
        "test_tasks": tasks,
        "hidden_patch": "hidden.patch",
        "f2p": f2p_ids(row),
        "p2p": p2p_ids(row),
        "agent_timeout_sec": 1800,
        "verify_timeout_sec": 1800,
        "gradle_timeout_sec": 1620,
        "test_command": _with_offline(str(row.get("test_command") or "")),
    }
    if filters:
        verification["test_filters"] = filters
    return {
        "schema_version": "0",
        "id": task_id_for(row),
        "kind": _kind(row),
        "language": ANDROID_LANGS.get(str(row.get("lang")), "android-mixed"),
        "pack_version": pack_version,
        "source": source,
        "environment": environment,
        "verification": verification,
        "gold": {"patch": "gold.patch"},
    }


def write_task(
    row: dict[str, Any],
    out_root: Path,
    pack_version: str = "0.0.0",
    image_pattern: str = DEFAULT_IMAGE_PATTERN,
    repo_path: str = DEFAULT_REPO_PATH,
    toolchain: dict[str, str] | None = None,
) -> Path:
    spec = build_spec(row, pack_version, image_pattern, repo_path, toolchain)
    task_dir = Path(out_root) / spec["id"]
    task_dir.mkdir(parents=True, exist_ok=True)
    with (task_dir / "probo.toml").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(tomli_w.dumps(spec))
    instruction = str(row.get("problem_statement") or row.get("title") or "").strip() + "\n"
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8", newline="\n")
    (task_dir / "gold.patch").write_text(_lf(str(row.get("fix_patch") or "")), encoding="utf-8", newline="\n")
    (task_dir / "hidden.patch").write_text(
        _lf(str(row.get("test_patch") or "")), encoding="utf-8", newline="\n"
    )
    return task_dir


def _lf(text: str) -> str:
    text = text.replace("\r\n", "\n")
    return text if text.endswith("\n") else text + "\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def import_rows(
    rows: Iterable[dict[str, Any]],
    out_root: str | Path,
    pack_version: str = "0.0.0",
    image_pattern: str = DEFAULT_IMAGE_PATTERN,
    repo_path: str = DEFAULT_REPO_PATH,
    only_importable: bool = True,
    public_pack_only: bool = False,
    limit: int | None = None,
    toolchains: dict[str, dict[str, str]] | None = None,
) -> list[Decision]:
    """Assess every row, write the tasks that qualify, and write
    ``manifest.json`` with every decision next to them."""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    decisions: list[Decision] = []
    written = 0
    for row in rows:
        if str(row.get("lang") or "") not in ANDROID_LANGS:
            continue
        d = assess(row)
        wanted = (d.importable or not only_importable) and (d.public_pack_ok or not public_pack_only)
        if wanted and (limit is None or written < limit):
            tc = (toolchains or {}).get(d.instance_id)
            d.task_dir = str(write_task(row, out_root, pack_version, image_pattern, repo_path, tc))
            written += 1
        decisions.append(d)
    manifest = {
        "schema": "probo-mdb-import/1",
        "dataset": DATASET,
        "paper": PAPER,
        "image_pattern": image_pattern,
        "repo_path": repo_path,
        "pack_version": pack_version,
        "n_android_rows": len(decisions),
        "n_importable": sum(1 for d in decisions if d.importable),
        "n_written": written,
        "n_public_pack_ok": sum(1 for d in decisions if d.importable and d.public_pack_ok),
        "decisions": [asdict(d) for d in decisions],
    }
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return decisions


def summarize(decisions: list[Decision]) -> str:
    from collections import Counter

    reasons = Counter(r for d in decisions if not d.importable for r in d.reasons)
    per_repo: dict[str, list[int]] = {}
    for d in decisions:
        per_repo.setdefault(d.repo, [0, 0])[0 if d.importable else 1] += 1
    lines = [
        f"Android rows: {len(decisions)}; importable: {sum(1 for d in decisions if d.importable)}; "
        "public-pack licenses among importable: "
        f"{sum(1 for d in decisions if d.importable and d.public_pack_ok)}",
        "exclusion reasons:",
    ]
    lines += [f"  {n:4d}  {r}" for r, n in reasons.most_common()]
    lines.append("per repository (importable / excluded, license):")
    for repo, (ok, no) in sorted(per_repo.items(), key=lambda kv: -kv[1][0]):
        lines.append(f"  {repo:<40} {ok:3d} / {no:3d}  {UPSTREAM_LICENSES.get(repo, '?')}")
    return "\n".join(lines)
