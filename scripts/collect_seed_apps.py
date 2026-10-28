#!/usr/bin/env python3
"""Collect seed-app candidate metrics from the GitHub API via the `gh` CLI.

Re-runnable: raw `gh api` responses are cached under ./cache next to this
script; pass --refresh to ignore the cache. No repository is cloned.

Outputs:
  docs/data/seed-apps.json   raw numbers
  docs/seed-apps.md          ranking report
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache"

REPORT_DATE = "2026-10-28"
WINDOW_START = "2025-10-28"  # 12 months before REPORT_DATE
WINDOW_START_ISO = WINDOW_START + "T00:00:00Z"
SAMPLE_PAGES = 3
SAMPLE_PAGE_SIZE = 50
FILES_PER_PR = 100

DEFAULT_JSON = Path(r"C:\Users\natas\OneDrive\Documents\Claude\GenericSkill\docs\data\seed-apps.json")
DEFAULT_MD = Path(r"C:\Users\natas\OneDrive\Documents\Claude\GenericSkill\docs\seed-apps.md")

CANDIDATES = [
    "thunderbird/thunderbird-android",
    "duckduckgo/Android",
    "wikimedia/apps-android-wikipedia",
    "mihonapp/mihon",
    "home-assistant/android",
    "openfoodfacts/openfoodfacts-androidapp",
    "commons-app/apps-android-commons",
    "Automattic/pocket-casts-android",
    "AntennaPod/AntennaPod",
    "bitwarden/android",
    "wordpress-mobile/WordPress-Android",
    "nextcloud/android",
]

QUALIFYING_LICENSES = {"Apache-2.0", "MIT"}

JVM_TEST_RE = re.compile(r"(^|/)src/(test|testDebug|testRelease|test[A-Z][A-Za-z]*)/.*\.(kt|java)$")
ANDROID_TEST_RE = re.compile(r"(^|/)src/androidTest")
ANDROID_TEST_SRC_RE = re.compile(r"(^|/)src/androidTest[A-Za-z]*/.*\.(kt|java)$")
WRAPPER_VERSION_RE = re.compile(r"gradle-(\d+(?:\.\d+)*(?:-[A-Za-z0-9.]+)?)-(?:bin|all)\.zip")
AGP_KEY_RE = re.compile(
    r"^(agp|android[-_]?gradle[-_]?plugin|androidGradlePlugin|android[-_]?gradle|gradle[-_]?android)$", re.I
)

PR_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: %d, orderBy: {field: UPDATED_AT, direction: DESC}, after: $after) {
      pageInfo { endCursor hasNextPage }
      nodes {
        number
        mergedAt
        changedFiles
        files(first: %d) { totalCount nodes { path } }
      }
    }
  }
}
""" % (SAMPLE_PAGE_SIZE, FILES_PER_PR)


class GhError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- gh
def gh_api(args: list[str], *, refresh: bool = False, max_tries: int = 6) -> str:
    """Run `gh api <args>` and return stdout. Caches successes. Retries on rate limits."""
    cmd = ["gh", "api", *args]
    key = hashlib.sha1(json.dumps(cmd).encode("utf-8")).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if not refresh and cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    delay = 60
    last_err = ""
    proc = None
    for attempt in range(1, max_tries + 1):
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(proc.stdout, encoding="utf-8")
            return proc.stdout
        err = (proc.stderr or "") + "\n" + (proc.stdout or "")
        last_err = err.strip()
        low = err.lower()
        rate_limited = (
            "rate limit" in low
            or "secondary" in low
            or "abuse" in low
            or "http 403" in low
            or "http 429" in low
            or "(403)" in low
            or "(429)" in low
        )
        transient = (
            "http 5" in low
            or "(50" in low
            or "timeout" in low
            or "timed out" in low
            or "connection reset" in low
            or "eof" in low
            or "bad gateway" in low
        )
        if rate_limited and attempt < max_tries:
            log(f"    rate limited (attempt {attempt}); sleeping {delay}s ... [{last_err[:120]}]")
            time.sleep(delay)
            delay = min(delay * 2, 600)
            continue
        if transient and attempt < max_tries:
            log(f"    transient error (attempt {attempt}); sleeping 15s ... [{last_err[:120]}]")
            time.sleep(15)
            continue
        break
    rc = proc.returncode if proc is not None else "?"
    raise GhError(last_err[:500] or f"gh exited {rc}")


def gh_json(args: list[str], **kw):
    return json.loads(gh_api(args, **kw))


# ----------------------------------------------------------------- collectors
def collect_repo_meta(owner: str, name: str, refresh: bool) -> dict:
    d = gh_json([f"repos/{owner}/{name}"], refresh=refresh)
    lic = d.get("license") or {}
    return {
        "license_spdx": lic.get("spdx_id"),
        "license_name": lic.get("name"),
        "default_branch": d.get("default_branch"),
        "pushed_at": d.get("pushed_at"),
        "stars": d.get("stargazers_count"),
        "archived": d.get("archived"),
        "fork": d.get("fork"),
    }


def collect_merged_12mo(owner: str, name: str, refresh: bool) -> dict:
    q = f"repo:{owner}/{name} is:pr is:merged merged:>={WINDOW_START}"
    d = gh_json(["-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=1"], refresh=refresh)
    return {
        "query": q,
        "total_count": d.get("total_count"),
        "incomplete_results": d.get("incomplete_results"),
    }


def classify_pr(pr: dict) -> dict:
    files = pr.get("files") or {}
    paths = [n["path"] for n in (files.get("nodes") or []) if n and n.get("path")]
    jvm = [p for p in paths if JVM_TEST_RE.search(p) and not ANDROID_TEST_RE.search(p)]
    atest = [p for p in paths if ANDROID_TEST_SRC_RE.search(p)]
    total_files = files.get("totalCount")
    if total_files is None:
        total_files = pr.get("changedFiles")
    return {
        "number": pr.get("number"),
        "mergedAt": pr.get("mergedAt"),
        "changedFiles": pr.get("changedFiles"),
        "files_listed": len(paths),
        "files_truncated": bool(total_files and total_files > len(paths)),
        "touches_jvm_test": bool(jvm),
        "touches_android_test": bool(atest),
        "only_android_test_files": bool(paths) and len(atest) == len(paths),
        "only_test_changes_are_android_test": bool(atest) and not jvm,
        "jvm_test_files": jvm,
        "android_test_files": atest,
    }


def collect_pr_sample(owner: str, name: str, refresh: bool) -> dict:
    nodes: list[dict] = []
    after = None
    pages_fetched = 0
    for _page in range(SAMPLE_PAGES):
        args = ["graphql", "-f", f"query={PR_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}"]
        if after:
            args += ["-f", f"after={after}"]
        d = gh_json(args, refresh=refresh)
        if d.get("errors"):
            raise GhError("GraphQL errors: " + json.dumps(d["errors"])[:400])
        prs = d["data"]["repository"]["pullRequests"]
        nodes.extend(prs.get("nodes") or [])
        pages_fetched += 1
        pi = prs.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        after = pi.get("endCursor")
        time.sleep(1)

    classified = [classify_pr(pr) for pr in nodes if pr]
    in_window = [c for c in classified if c["mergedAt"] and c["mergedAt"] >= WINDOW_START_ISO]
    n_in = len(in_window)
    n_jvm = sum(1 for c in in_window if c["touches_jvm_test"])
    n_atest_any = sum(1 for c in in_window if c["touches_android_test"])
    n_only_atest_files = sum(1 for c in in_window if c["only_android_test_files"])
    n_only_test_is_atest = sum(1 for c in in_window if c["only_test_changes_are_android_test"])
    n_trunc = sum(1 for c in in_window if c["files_truncated"])
    merged_dates = sorted(c["mergedAt"] for c in in_window)
    return {
        "pages_fetched": pages_fetched,
        "sample_size_fetched": len(classified),
        "sample_size_in_window": n_in,
        "sample_merged_at_min": merged_dates[0] if merged_dates else None,
        "sample_merged_at_max": merged_dates[-1] if merged_dates else None,
        "prs_touching_jvm_tests": n_jvm,
        "fraction_touching_jvm_tests": (n_jvm / n_in) if n_in else None,
        "prs_touching_android_tests": n_atest_any,
        "prs_only_android_test_files": n_only_atest_files,
        "prs_only_test_changes_are_android_test": n_only_test_is_atest,
        "prs_with_truncated_file_list": n_trunc,
        "prs": classified,
    }


def collect_tree(owner: str, name: str, branch: str, refresh: bool) -> dict:
    jq = "{truncated: .truncated, sha: .sha, entries: [.tree[] | {p: .path, t: .type}]}"
    d = gh_json(
        [f"repos/{owner}/{name}/git/trees/{quote(branch, safe='')}?recursive=1", "--jq", jq], refresh=refresh
    )
    entries = d.get("entries") or []
    blobs = {e["p"] for e in entries if e.get("t") == "blob"}
    trees = {e["p"] for e in entries if e.get("t") == "tree"}
    build_files = sorted(p for p in blobs if p.rsplit("/", 1)[-1] in ("build.gradle.kts", "build.gradle"))
    settings_files = sorted(
        p for p in blobs if p.rsplit("/", 1)[-1] in ("settings.gradle.kts", "settings.gradle")
    )
    return {
        "tree_sha": d.get("sha"),
        "tree_truncated": bool(d.get("truncated")),
        "tree_entries": len(entries),
        "gradle_build_files": len(build_files),
        "gradle_build_files_kts": sum(1 for p in build_files if p.endswith(".kts")),
        "gradle_build_files_groovy": sum(1 for p in build_files if p.endswith("build.gradle")),
        "gradle_build_file_paths": build_files,
        "settings_files": settings_files,
        "has_version_catalog": "gradle/libs.versions.toml" in blobs,
        "has_buildSrc": "buildSrc" in trees,
        "has_build_logic": "build-logic" in trees,
        # the same directories anywhere in the tree (e.g. gradle/build-logic/), for honesty about layout
        "buildSrc_dirs": sorted(p for p in trees if p == "buildSrc" or p.endswith("/buildSrc")),
        "build_logic_dirs": sorted(p for p in trees if p == "build-logic" or p.endswith("/build-logic")),
    }


def fetch_file(owner: str, name: str, path: str, branch: str, refresh: bool) -> str | None:
    try:
        d = gh_json([f"repos/{owner}/{name}/contents/{path}?ref={quote(branch, safe='')}"], refresh=refresh)
    except GhError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return None
        raise
    if d.get("encoding") == "base64" and d.get("content"):
        return base64.b64decode(d["content"]).decode("utf-8", errors="replace")
    return None


def collect_wrapper(owner: str, name: str, branch: str, refresh: bool) -> dict:
    txt = fetch_file(owner, name, "gradle/wrapper/gradle-wrapper.properties", branch, refresh)
    if txt is None:
        return {"present": False, "version": None, "distribution_url": None}
    url = None
    for line in txt.splitlines():
        if line.strip().startswith("distributionUrl"):
            url = line.split("=", 1)[1].strip().replace("\\:", ":")
    m = WRAPPER_VERSION_RE.search(url or "")
    return {"present": True, "version": m.group(1) if m else None, "distribution_url": url}


def collect_agp(owner: str, name: str, branch: str, refresh: bool) -> dict:
    txt = fetch_file(owner, name, "gradle/libs.versions.toml", branch, refresh)
    if txt is None:
        return {"catalog_present": False, "version": None, "source": None}
    # 1) line scan as specified: a key that looks like agp / android-gradle-plugin / androidGradlePlugin
    scanned = None
    scanned_key = None
    for line in txt.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*"([^"]+)"', line)
        if m and AGP_KEY_RE.match(m.group(1)):
            scanned, scanned_key = m.group(2), m.group(1)
            break
    # 2) structured fallback: resolve com.android.* plugin / com.android.tools.build:gradle library
    resolved = None
    resolved_src = None
    try:
        data = tomllib.loads(txt)
        versions = data.get("versions") or {}
        if scanned is None:
            for k, v in versions.items():
                if AGP_KEY_RE.match(k) and isinstance(v, str):
                    scanned, scanned_key = v, k
                    break

        def resolve(entry):
            if not isinstance(entry, dict):
                return None
            v = entry.get("version")
            if isinstance(v, str):
                return v
            if isinstance(v, dict) and "ref" in v:
                return versions.get(v["ref"])
            return None

        for k, v in (data.get("plugins") or {}).items():
            if isinstance(v, dict) and str(v.get("id", "")).startswith("com.android."):
                r = resolve(v)
                if r:
                    resolved, resolved_src = r, f"plugins.{k}"
                    break
        if resolved is None:
            for k, v in (data.get("libraries") or {}).items():
                if isinstance(v, dict):
                    mod = v.get("module") or (f"{v.get('group')}:{v.get('name')}" if v.get("group") else "")
                    if mod == "com.android.tools.build:gradle":
                        r = resolve(v)
                        if r:
                            resolved, resolved_src = r, f"libraries.{k}"
                            break
    except Exception as e:  # noqa: BLE001
        resolved_src = f"toml parse failed: {e}"
    version = scanned or resolved
    source = f"versions.{scanned_key}" if scanned else resolved_src
    return {
        "catalog_present": True,
        "version": version,
        "source": source,
        "version_from_key_scan": scanned,
        "version_from_plugin_resolution": resolved,
    }


def collect_repo(full: str, refresh: bool) -> dict:
    owner, name = full.split("/", 1)
    out: dict = {"repo": full, "owner": owner, "name": name, "errors": {}}
    log(f"== {full}")

    def step(key, fn):
        try:
            out[key] = fn()
        except GhError as e:
            log(f"   !! {key} failed: {e}")
            out[key] = None
            out["errors"][key] = str(e)

    step("meta", lambda: collect_repo_meta(owner, name, refresh))
    step("merged_12mo", lambda: collect_merged_12mo(owner, name, refresh))
    time.sleep(2)  # search API allows 30 req/min; stay well under it
    step("sample", lambda: collect_pr_sample(owner, name, refresh))
    branch = (out.get("meta") or {}).get("default_branch") or "HEAD"
    step("tree", lambda: collect_tree(owner, name, branch, refresh))
    step("wrapper", lambda: collect_wrapper(owner, name, branch, refresh))
    step("agp", lambda: collect_agp(owner, name, branch, refresh))

    s = out.get("sample") or {}
    total = (out.get("merged_12mo") or {}).get("total_count")
    frac = s.get("fraction_touching_jvm_tests")
    out["estimated_12mo_prs_touching_jvm_tests"] = (
        round(frac * total, 1) if (frac is not None and total is not None) else None
    )
    lic = (out.get("meta") or {}).get("license_spdx")
    out["passes_license_filter"] = (lic in QUALIFYING_LICENSES) if lic else None
    return out


# -------------------------------------------------------------------- report
def fmt_int(v) -> str:
    return "n/a" if v is None else f"{v:,}"


def fmt_date(v) -> str:
    return "n/a" if not v else str(v)[:10]


def yn(v) -> str:
    return "n/a" if v is None else ("yes" if v else "no")


def build_report(results: list[dict], generated_at: str) -> str:
    rows = sorted(
        results,
        key=lambda r: (
            r.get("estimated_12mo_prs_touching_jvm_tests") is None,
            -(r.get("estimated_12mo_prs_touching_jvm_tests") or 0),
        ),
    )
    n_sample = SAMPLE_PAGES * SAMPLE_PAGE_SIZE
    L: list[str] = []
    L.append("# Seed-app candidates: merged-PR and test-activity ranking")
    L.append("")
    L.append(f"Date: {REPORT_DATE} (data pulled {generated_at})")
    L.append("")
    L.append("## Method")
    L.append("")
    L.append(
        "All numbers come from the GitHub API through the `gh` CLI (script: `scratchpad/seed_apps/collect_seed_apps.py`; "
        "raw numbers in `docs/data/seed-apps.json`); no repository was cloned. For each candidate the `repos` endpoint "
        'supplied the license SPDX id, default branch, last push, stars and archived flag. "Merged PRs 12mo" is '
        f"`total_count` from `search/issues` with `repo:OWNER/NAME is:pr is:merged merged:>={WINDOW_START}`. The "
        f"test-activity sample is the {n_sample} most recently updated merged PRs from GraphQL (`pullRequests(states: "
        f"MERGED, orderBy: UPDATED_AT DESC)`, {SAMPLE_PAGES} pages of {SAMPLE_PAGE_SIZE}, first {FILES_PER_PR} changed "
        f'files per PR); only PRs with `mergedAt >= {WINDOW_START}` are counted, so "sample in window" can be below '
        f'{n_sample}. A PR "touches JVM tests" if at least one changed path matches '
        "`(^|/)src/(test|testDebug|testRelease|test[A-Z][A-Za-z]*)/.*\\.(kt|java)$` and not `(^|/)src/androidTest`. "
        '"androidTest-only" counts PRs whose only test changes are under `src/androidTest*/` (no JVM-test file); the '
        "JSON also records PRs consisting of nothing but androidTest files. The 12-month estimate is (fraction touching "
        "JVM tests in the sample) x (merged PRs 12mo). Gradle modules is the number of `build.gradle(.kts)` files in the "
        "default-branch tree (`git/trees?recursive=1`, root build file included); the wrapper version is parsed from "
        "`gradle/wrapper/gradle-wrapper.properties` and the AGP version from `gradle/libs.versions.toml` (an `agp` / "
        "`android-gradle-plugin` / `androidGradlePlugin` key, falling back to resolving the `com.android.*` plugin entry)."
    )
    L.append("")
    L.append("## Ranking (sorted by estimated 12-month merged PRs touching JVM tests)")
    L.append("")
    hdr = [
        "Repo",
        "License",
        "Stars",
        "Last push",
        "Merged PRs 12mo",
        "Sample in window",
        "Fraction touching JVM tests",
        "Est. 12mo JVM-test PRs",
        "androidTest-only PRs in sample",
        "Gradle modules",
        "Wrapper",
        "AGP",
        "buildSrc / build-logic / catalog",
    ]
    L.append("| " + " | ".join(hdr) + " |")
    L.append("|" + "|".join(["---"] * len(hdr)) + "|")
    for r in rows:
        meta = r.get("meta") or {}
        s = r.get("sample") or {}
        t = r.get("tree") or {}
        w = r.get("wrapper") or {}
        a = r.get("agp") or {}
        m12 = (r.get("merged_12mo") or {}).get("total_count")
        frac = s.get("fraction_touching_jvm_tests")
        n_in = s.get("sample_size_in_window")
        n_jvm = s.get("prs_touching_jvm_tests")
        frac_s = "n/a" if frac is None else f"{frac:.3f} ({n_jvm}/{n_in})"
        sample_s = "API error" if r.get("sample") is None else f"{n_in} of {s.get('sample_size_fetched')}"
        est = r.get("estimated_12mo_prs_touching_jvm_tests")
        est_s = "n/a" if est is None else f"{est:.0f}"
        if r.get("tree") is None:
            mod_s = "API error"
        else:
            mod_s = str(t.get("gradle_build_files"))
            if t.get("tree_truncated"):
                mod_s += " (tree truncated)"
        if r.get("wrapper") is None:
            wrap_s = "API error"
        elif not w.get("present"):
            wrap_s = "no wrapper file"
        else:
            wrap_s = w.get("version") or "unparsed"
        if r.get("agp") is None:
            agp_s = "API error"
        elif not a.get("catalog_present"):
            agp_s = "no catalog"
        else:
            agp_s = a.get("version") or "not in catalog"
        if r.get("tree") is None:
            bl_s = "API error"
        else:
            bs = yn(t.get("has_buildSrc"))
            bl = yn(t.get("has_build_logic"))
            # root-level answer first; note a nested build-logic/buildSrc dir if that is where it lives
            nested_bl = [p for p in t.get("build_logic_dirs", []) if p != "build-logic"]
            nested_bs = [p for p in t.get("buildSrc_dirs", []) if p != "buildSrc"]
            if not t.get("has_build_logic") and nested_bl:
                bl = f"no (nested: {', '.join(nested_bl)})"
            if not t.get("has_buildSrc") and nested_bs:
                bs = f"no (nested: {', '.join(nested_bs)})"
            bl_s = f"{bs} / {bl} / {yn(t.get('has_version_catalog'))}"
        lic = meta.get("license_spdx") or ("API error" if r.get("meta") is None else "n/a")
        atest_only = s.get("prs_only_test_changes_are_android_test")
        L.append(
            "| "
            + " | ".join(
                [
                    f"[{r['repo']}](https://github.com/{r['repo']})",
                    lic,
                    fmt_int(meta.get("stars")),
                    fmt_date(meta.get("pushed_at")),
                    fmt_int(m12),
                    sample_s,
                    frac_s,
                    est_s,
                    "n/a" if atest_only is None else str(atest_only),
                    mod_s,
                    wrap_s,
                    agp_s,
                    bl_s,
                ]
            )
            + " |"
        )
    L.append("")

    L.append("## Reading the table")
    L.append("")
    L.append(
        "Hard license filter: only Apache-2.0 and MIT qualify for the public task pack; MPL-2.0, GPL and AGPL fail it."
    )
    L.append("")
    passing = [r for r in rows if r.get("passes_license_filter") is True]
    failing = [r for r in rows if r.get("passes_license_filter") is False]
    unknown = [r for r in rows if r.get("passes_license_filter") is None]

    def lic_list(rs):
        return ", ".join(f"{r['repo']} ({(r.get('meta') or {}).get('license_spdx')})" for r in rs) or "none"

    L.append("- Pass (Apache-2.0 / MIT): " + lic_list(passing))
    L.append("- Fail the hard license filter: " + lic_list(failing))
    if unknown:
        L.append(
            "- License not determined (API error or no SPDX id): " + ", ".join(r["repo"] for r in unknown)
        )
    archived = [r["repo"] for r in rows if (r.get("meta") or {}).get("archived")]
    L.append("- Archived repositories: " + (", ".join(archived) if archived else "none"))
    short = [
        r for r in rows if r.get("sample") and (r["sample"].get("sample_size_in_window") or 0) < n_sample
    ]
    if short:
        L.append(
            f"- Samples with fewer than {n_sample} PRs in the 12-month window (the sample is ordered by last update, "
            "so older PRs that were recently touched fall outside the window): "
            + ", ".join(
                f"{r['repo']} ({r['sample']['sample_size_in_window']} of {r['sample']['sample_size_fetched']})"
                for r in short
            )
        )
    cov = [r for r in rows if r.get("sample") and r["sample"].get("sample_merged_at_min")]
    if cov:
        L.append(
            "- Merge-date coverage of the in-window sample (a short span means the fraction reflects only the most "
            "recent weeks of activity): "
            + ", ".join(
                f"{r['repo']} ({r['sample']['sample_merged_at_min'][:10]} to {r['sample']['sample_merged_at_max'][:10]})"
                for r in cov
            )
        )
    full = [
        r
        for r in rows
        if r.get("sample")
        and (r.get("merged_12mo") or {}).get("total_count") is not None
        and r["sample"]["sample_size_in_window"] >= r["merged_12mo"]["total_count"]
    ]
    if full:
        L.append(
            "- Sample equals the whole 12-month population (so the estimate is an exact count, not an extrapolation): "
            + ", ".join(
                f"{r['repo']} ({r['sample']['sample_size_in_window']} of {r['merged_12mo']['total_count']})"
                for r in full
            )
        )
    trunc = [r for r in rows if r.get("sample") and r["sample"].get("prs_with_truncated_file_list")]
    if trunc:
        L.append(
            f"- In-window PRs with more than {FILES_PER_PR} changed files (only the first {FILES_PER_PR} paths were "
            "inspected, so a test file could be missed): "
            + ", ".join(f"{r['repo']} ({r['sample']['prs_with_truncated_file_list']})" for r in trunc)
        )
    ttrunc = [r["repo"] for r in rows if r.get("tree") and r["tree"].get("tree_truncated")]
    L.append(
        "- Default-branch trees reported as truncated by the API (module count would be a lower bound): "
        + (", ".join(ttrunc) if ttrunc else "none")
    )
    errs = [
        (r["repo"], "; ".join(f"{k}: {v[:120]}" for k, v in r["errors"].items()))
        for r in rows
        if r.get("errors")
    ]
    if errs:
        L.append("- API calls that failed:")
        for repo, e in errs:
            L.append(f"  - {repo}: {e}")
    else:
        L.append("- API calls that failed: none.")
    L.append(
        "- The androidTest-only column counts sampled in-window PRs whose only test changes are instrumented tests; "
        "the JSON additionally has `prs_touching_android_tests` and `prs_only_android_test_files` per repo."
    )
    L.append(
        "- The estimate is a sample-based extrapolation, not a measured count; with ~150 sampled PRs the sampling "
        "error on the fraction is roughly +/-0.07 at 95% confidence."
    )
    L.append("")
    L.append("## Not measured")
    L.append("")
    L.append(
        "- Cold build time was not measured: it requires cloning each repository and running a full Gradle build, "
        "which this data pull deliberately did not do."
    )
    L.append(
        "- Test runtime, flakiness, and whether the JVM test suites actually pass on the default branch were "
        "likewise not measured."
    )
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    ap.add_argument("--refresh", action="store_true", help="ignore the local response cache")
    ap.add_argument("--only", nargs="*", help="limit to these owner/name repos")
    args = ap.parse_args()

    repos = args.only or CANDIDATES
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = [collect_repo(r, args.refresh) for r in repos]

    payload = {
        "generated_at": generated_at,
        "report_date": REPORT_DATE,
        "window_start": WINDOW_START,
        "sample_pages": SAMPLE_PAGES,
        "sample_page_size": SAMPLE_PAGE_SIZE,
        "files_per_pr": FILES_PER_PR,
        "jvm_test_regex": JVM_TEST_RE.pattern,
        "android_test_exclusion_regex": ANDROID_TEST_RE.pattern,
        "qualifying_licenses": sorted(QUALIFYING_LICENSES),
        "repos": results,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(build_report(results, generated_at), encoding="utf-8")
    log(f"wrote {args.json_out}\nwrote {args.md_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
