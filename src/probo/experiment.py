"""Experiment mode (ROADMAP.md, Phase 5): the same tasks under two
configurations, for example an agent with and without a skill or an MCP
server, compared with paired per-task differences and a stated minimum
detectable difference.

Both arms run through ``harbor run`` with identical tasks, attempts and
concurrency; only the agent, model and adapter kwargs differ. The result is
a comparison report plus a power table that says how many tasks a given
effect would need, computed from the variance this very experiment measured.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from probo import stats
from probo.manifest import flatten_job, write_jsonl
from probo.report import render_compare, scores_by_task

EFFECTS = (0.05, 0.10, 0.15, 0.20, 0.25)


@dataclass
class Arm:
    label: str
    agent: str
    model: str | None = None
    ak: list[str] = field(default_factory=list)

    def describe(self) -> str:
        parts = [self.agent]
        if self.model:
            parts.append(self.model)
        parts += self.ak
        return " ".join(parts)


@dataclass
class ExperimentResult:
    name: str
    commands: list[list[str]]
    job_dirs: list[Path]
    results: list[Path]
    report_path: Path | None
    report: str


def harbor_command(
    harbor: str, tasks: list[Path], arm: Arm, attempts: int, concurrency: int, jobs: Path, job_name: str
) -> list[str]:
    cmd = [harbor, "run"]
    for t in tasks:
        cmd += ["-p", str(t)]
    cmd += [
        "-a",
        arm.agent,
        "-o",
        str(jobs),
        "--job-name",
        job_name,
        "-k",
        str(attempts),
        "-n",
        str(concurrency),
    ]
    if arm.model:
        cmd += ["-m", arm.model]
    for kv in arm.ak:
        cmd += ["--ak", kv]
    return cmd


def power_table(sd_diff: float, effects: tuple[float, ...] = EFFECTS) -> list[tuple[float, int]]:
    """Tasks needed to detect each effect (in pass-rate points, 0 to 1) at
    alpha 0.05 and 80% power, given the standard deviation of per-task
    differences."""
    return [(e, stats.tasks_needed(sd_diff, e)) for e in effects]


def render_power_note(n_tasks: int, sd_diff: float | None) -> str:
    lines = ["## Power", ""]
    if sd_diff is None or not math.isfinite(sd_diff) or sd_diff == 0:
        lines.append(
            "The standard deviation of per-task differences could not be estimated "
            "(fewer than two shared tasks, or no variation), so no power table."
        )
        return "\n".join(lines) + "\n"
    lines.append(
        f"Measured standard deviation of per-task differences: {sd_diff:.3f} over {n_tasks} tasks. "
        "Tasks needed to detect an effect at 80% power (alpha 0.05):"
    )
    lines += ["", "| Effect | Tasks needed |", "|---|---|"]
    for effect, n in power_table(sd_diff):
        lines.append(f"| {100 * effect:.0f} points | {n} |")
    lines += [
        "",
        "Rule of thumb from ROADMAP.md: detecting a 10 to 15 point effect of a skill or "
        "MCP server needs on the order of 50 or more tasks from your own repository; "
        "more tasks beat more attempts.",
    ]
    return "\n".join(lines) + "\n"


def compare_jobs(job_a: Path, job_b: Path, label_a: str, label_b: str, out_dir: Path) -> tuple[Path, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    recs_a, recs_b = flatten_job(job_a), flatten_job(job_b)
    path_a, path_b = out_dir / f"{label_a}.jsonl", out_dir / f"{label_b}.jsonl"
    write_jsonl(recs_a, path_a)
    write_jsonl(recs_b, path_b)
    text = render_compare(recs_a, recs_b, label_a, label_b)
    d = stats.paired_difference(scores_by_task(recs_a), scores_by_task(recs_b))
    sd = d.se * math.sqrt(d.n_tasks) if d.n_tasks >= 2 and math.isfinite(d.se) else None
    text += "\n" + render_power_note(d.n_tasks, sd)
    report = out_dir / "compare.md"
    report.write_text(text, encoding="utf-8", newline="\n")
    return report, text


def run_experiment(
    tasks: list[Path],
    arm_a: Arm,
    arm_b: Arm,
    attempts: int = 3,
    concurrency: int = 1,
    jobs: Path = Path("harbor-jobs"),
    name: str | None = None,
    print_only: bool = False,
    harbor: str | None = None,
) -> ExperimentResult:
    name = name or f"exp-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    harbor_exe = harbor or shutil.which("harbor") or "harbor"
    jobs = Path(jobs).resolve()
    job_dirs = [jobs / f"{name}-{arm_a.label}", jobs / f"{name}-{arm_b.label}"]
    commands = [
        harbor_command(harbor_exe, tasks, arm_a, attempts, concurrency, jobs, job_dirs[0].name),
        harbor_command(harbor_exe, tasks, arm_b, attempts, concurrency, jobs, job_dirs[1].name),
    ]
    header = [
        f"# Experiment {name}",
        "",
        f"A = {arm_a.label}: {arm_a.describe()}",
        f"B = {arm_b.label}: {arm_b.describe()}",
        f"Tasks: {len(tasks)}; attempts per task: {attempts}; "
        "same tasks, timeouts and network for both arms.",
        "",
    ]
    if print_only:
        text = "\n".join(header + ["Commands:", ""] + ["    " + " ".join(c) for c in commands]) + "\n"
        return ExperimentResult(name, commands, job_dirs, [], None, text)
    for cmd in commands:
        rc = subprocess.call(cmd)
        if rc != 0:
            raise RuntimeError(f"harbor exited with {rc}: {' '.join(cmd)}")
    report, text = compare_jobs(job_dirs[0], job_dirs[1], arm_a.label, arm_b.label, jobs / name)
    full = "\n".join(header) + "\n" + text
    report.write_text(full, encoding="utf-8", newline="\n")
    return ExperimentResult(
        name,
        commands,
        job_dirs,
        [jobs / name / f"{arm_a.label}.jsonl", jobs / name / f"{arm_b.label}.jsonl"],
        report,
        full,
    )
