"""The ``probo`` command: a thin layer over Harbor plus the task tooling."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from probo import __version__
from probo.convert import convert_task
from probo.manifest import flatten_job, read_jsonl, write_jsonl
from probo.report import render_compare, render_report
from probo.selftest import HostGradle, default_work_dir, run_gate, run_selftest
from probo.task import load_task, patch_stats

HARBOR_PIN = "0.24.0"


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


# ---------------------------------------------------------------------------
# validate-task
# ---------------------------------------------------------------------------


def cmd_validate_task(args: argparse.Namespace) -> int:
    rc = 0
    for d in args.task_dir:
        try:
            spec = load_task(d)
        except (FileNotFoundError, ValueError) as exc:
            print(f"{d}: error: {exc}")
            rc = 1
            continue
        gold = spec.gold_patch_path
        size = patch_stats(gold.read_text("utf-8")) if gold.is_file() else None
        status = "ok" if spec.ok else "invalid"
        print(
            f"{spec.id}: {status}"
            + (
                f" (gold patch: {size['files']} files, +{size['insertions']}/-{size['deletions']})"
                if size
                else ""
            )
        )
        for p in spec.problems:
            print(f"  {p}")
        if not spec.ok:
            rc = 1
    return rc


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


def cmd_convert(args: argparse.Namespace) -> int:
    rc = 0
    for d in args.task_dir:
        spec = load_task(d)
        for p in spec.problems:
            print(f"{spec.id}: {p}")
        if not spec.ok:
            rc = 1
            continue
        out = convert_task(spec, args.out, repo_for_originals=args.repo)
        print(f"{spec.id}: emitted {out}")
    return rc


# ---------------------------------------------------------------------------
# run (over harbor run)
# ---------------------------------------------------------------------------


def _harbor_version() -> str | None:
    exe = shutil.which("harbor")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60
        )
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _host_memory_mb() -> int | None:
    try:
        if hasattr(os, "sysconf") and os.sysconf_names.get("SC_PHYS_PAGES"):
            return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        pass
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return int(status.ullTotalPhys / (1024 * 1024))
        except Exception:  # noqa: BLE001
            return None
    return None


def host_record(command: list[str], job_dir: Path, task_dir: Path | None) -> dict[str, object]:
    rec: dict[str, object] = {
        "schema": "probo-host/1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "probo_version": __version__,
        "harbor_version": _harbor_version(),
        "harbor_pin": HARBOR_PIN,
        "platform": platform.platform(),
        "cpus": os.cpu_count(),
        "memory_mb": _host_memory_mb(),
        "command": command,
        "job_dir": str(job_dir),
        "telemetry": os.environ.get("HARBOR_TELEMETRY", "default (on)"),
        "network_policy_agent": "public (baseline; allowlist pending the nftables check)",
        "network_policy_verifier": "no-network",
    }
    if task_dir is not None:
        spec_path = task_dir / "tests" / "spec.json"
        if spec_path.is_file():
            spec = json.loads(spec_path.read_text("utf-8"))
            for k in ("jdk", "gradle", "agp", "task_id", "pack_version"):
                rec[k] = spec.get(k)
    return rec


def cmd_run(args: argparse.Namespace) -> int:
    harbor = shutil.which("harbor")
    if not harbor:
        _eprint("harbor is not on PATH. Install it with: uv tool install harbor==" + HARBOR_PIN)
        return 2
    task_dir = Path(args.task).resolve()
    if (task_dir / "probo.toml").is_file():
        spec = load_task(task_dir)
        if not spec.ok:
            for p in spec.problems:
                _eprint(str(p))
            return 1
        task_dir = convert_task(spec, args.emit_dir)
        print(f"emitted {task_dir}")
    jobs = Path(args.jobs).resolve()
    job_name = args.job_name or f"{task_dir.name}-{args.agent}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cmd = [
        harbor,
        "run",
        "-p",
        str(task_dir),
        "-a",
        args.agent,
        "-o",
        str(jobs),
        "--job-name",
        job_name,
        "-k",
        str(args.attempts),
        "-n",
        str(args.concurrency),
    ]
    if args.model:
        cmd += ["-m", args.model]
    for kv in args.ak or []:
        cmd += ["--ak", kv]
    if args.dry_run:
        cmd.append("--dry-run")
    cmd += args.harbor_args or []
    print("$ " + " ".join(cmd))
    if args.print_only:
        return 0
    rc = subprocess.call(cmd)
    job_dir = jobs / job_name
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "probo-host.json").write_text(
        json.dumps(host_record(cmd, job_dir, task_dir), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"harbor exit code {rc}; host record written to {job_dir / 'probo-host.json'}")
    return rc


# ---------------------------------------------------------------------------
# flatten / report / compare / regrade-infra
# ---------------------------------------------------------------------------


def cmd_flatten(args: argparse.Namespace) -> int:
    records = []
    for job in args.job_dir:
        recs = flatten_job(job)
        if not recs:
            _eprint(f"{job}: no trial directories with result.json found")
        records.extend(recs)
    write_jsonl(records, args.out)
    print(f"wrote {len(records)} records to {args.out}")
    return 0 if records else 1


def cmd_report(args: argparse.Namespace) -> int:
    records = []
    for p in args.results:
        records.extend(read_jsonl(p))
    text = render_report(records, ", ".join(args.results), reproduce_command=args.reproduce)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a, b = read_jsonl(args.a), read_jsonl(args.b)
    text = render_compare(a, b, args.a, args.b)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_regrade_infra(args: argparse.Namespace) -> int:
    """Rerun only the verifier for trials that ended in infra_error (verifier
    OOM, patch failure). One regrade per the roadmap's rerun policy; the
    manifest's regrade_count comes from the host record."""
    job_dir = Path(args.job_dir).resolve()
    records = flatten_job(job_dir)
    infra = [r for r in records if r.get("exit_reason") == "infra_error"]
    if not infra:
        print("no infra_error trials; nothing to regrade")
        return 0
    for r in infra:
        print(
            f"infra_error: {r['harbor_trial_name']} "
            f"(grader detail: {r.get('exception_type') or 'see verdict.json'})"
        )
    harbor = shutil.which("harbor")
    cmd = [harbor or "harbor", "job", "regrade", str(job_dir), "-p", str(Path(args.task).resolve())]
    print("$ " + " ".join(cmd))
    if args.print_only or not harbor:
        if not harbor:
            _eprint("harbor is not on PATH; printed the command only")
        return 0
    rc = subprocess.call(cmd)
    host_path = job_dir / "probo-host.json"
    host = json.loads(host_path.read_text("utf-8")) if host_path.is_file() else {}
    host["regrade_count"] = int(host.get("regrade_count") or 0) + 1
    host_path.write_text(json.dumps(host, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rc


# ---------------------------------------------------------------------------
# grader-selftest / gate (host JDK, no Docker)
# ---------------------------------------------------------------------------


def _host(args: argparse.Namespace) -> HostGradle:
    work = Path(args.work) if args.work else default_work_dir()
    return HostGradle(Path(args.gradle_dist), Path(args.warm_home), work)


def cmd_grader_selftest(args: argparse.Namespace) -> int:
    results = run_selftest(Path(args.task_dir), _host(args), only=args.only, timeout_sec=args.gradle_timeout)
    if args.json:
        Path(args.json).write_text(
            json.dumps([r.__dict__ for r in results], indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return 0 if results and all(r.passed for r in results) else 1


def cmd_gate(args: argparse.Namespace) -> int:
    ok, runs, problems = run_gate(Path(args.task_dir), _host(args), runs=args.runs)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"ok": ok, "problems": problems, "runs": [r.__dict__ for r in runs]}, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="probo", description="Puts AI coding agents' Android changes to the proof."
    )
    p.add_argument("--version", action="version", version=f"probo {__version__} (harbor pin {HARBOR_PIN})")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "validate-task", help="validate probo.toml, the gold patch and hidden tests (no Gradle)"
    )
    s.add_argument("task_dir", nargs="+")
    s.set_defaults(func=cmd_validate_task)

    s = sub.add_parser("convert", help="emit Harbor's task layout from a task directory")
    s.add_argument("task_dir", nargs="+")
    s.add_argument(
        "-o", "--out", default="build/harbor-tasks", help="output root (default: build/harbor-tasks)"
    )
    s.add_argument(
        "--repo",
        help="checkout of the repository at the base commit, for tests/original on image-based tasks",
    )
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("run", help="run a task through harbor with the project's conventions")
    s.add_argument(
        "task", help="a Probo task directory (converted first) or an emitted Harbor task directory"
    )
    s.add_argument("-a", "--agent", required=True, help="harbor agent name or module:Class")
    s.add_argument("-m", "--model")
    s.add_argument("-k", "--attempts", type=int, default=1)
    s.add_argument("-n", "--concurrency", type=int, default=1)
    s.add_argument(
        "-o",
        "--jobs",
        default=os.environ.get("PROBO_JOBS", "harbor-jobs"),
        help="jobs directory, outside OneDrive",
    )
    s.add_argument("--job-name")
    s.add_argument("--ak", action="append", help="agent kwarg key=value, passed to harbor --ak")
    s.add_argument("--emit-dir", default="build/harbor-tasks")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--print-only", action="store_true", help="print the harbor command and exit")
    s.add_argument("harbor_args", nargs="*", help="extra arguments after -- go to harbor run")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("flatten", help="flatten harbor job directories into one JSONL result set")
    s.add_argument("job_dir", nargs="+")
    s.add_argument("-o", "--out", default="results.jsonl")
    s.set_defaults(func=cmd_flatten)

    s = sub.add_parser("report", help="render a Markdown report from JSONL result sets")
    s.add_argument("results", nargs="+")
    s.add_argument("-o", "--out")
    s.add_argument("--reproduce", help="the command that reproduces the table, printed under it")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("compare", help="paired per-task comparison of two JSONL result sets")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("-o", "--out")
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser(
        "regrade-infra", help="rerun only the verifier for infra_error trials (harbor job regrade)"
    )
    s.add_argument("job_dir")
    s.add_argument("--task", required=True, help="the emitted Harbor task directory")
    s.add_argument("--print-only", action="store_true")
    s.set_defaults(func=cmd_regrade_infra)

    for name, func, help_text in (
        ("grader-selftest", cmd_grader_selftest, "grade synthetic agent outcomes on the host JDK, no Docker"),
        ("gate", cmd_gate, "run validation states A, B and C on the host JDK, no Docker"),
    ):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("task_dir", help="an emitted Harbor task directory with environment/repo")
        s.add_argument("--gradle-dist", required=True, help="unpacked Gradle distribution directory")
        s.add_argument("--warm-home", required=True, help="a GRADLE_USER_HOME that built the repository once")
        s.add_argument("--work", help="scratch directory (default: a fresh temp dir)")
        s.add_argument("--json", help="write results as JSON to this path")
        if name == "grader-selftest":
            s.add_argument("--only", nargs="+", help="scenario names to run")
            s.add_argument("--gradle-timeout", type=float, help="override the spec's gradle_timeout_sec")
        else:
            s.add_argument("--runs", type=int, default=1, help="runs per state (the roadmap's gate uses 10)")
        s.set_defaults(func=func)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
