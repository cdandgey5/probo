"""Markdown reports from flattened JSONL results."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from probo import stats
from probo.grader.grade import EXIT_REASONS

Records = list[dict[str, Any]]


def _config_key(r: dict[str, Any]) -> str:
    agent = r.get("agent_name") or "?"
    model = r.get("model_name") or "?"
    return f"{agent} / {model}"


def group_by_config(records: Records) -> dict[str, Records]:
    out: dict[str, Records] = defaultdict(list)
    for r in records:
        out[_config_key(r)].append(r)
    return dict(out)


def scores_by_task(records: Records) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in records:
        out[str(r.get("task_id"))].append(1.0 if r.get("resolved") else 0.0)
    return dict(out)


def _pct(x: float | None) -> str:
    if x is None or x != x:  # NaN
        return "n/a"
    return f"{100 * x:.1f}%"


def _pts(x: float | None) -> str:
    if x is None or x != x:
        return "n/a"
    return f"{100 * x:.1f} pts"


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.2f}"


def _secs(x: float | None) -> str:
    return "n/a" if x is None else f"{x / 60:.1f} min"


def summary_table(records: Records) -> str:
    lines = [
        "| Agent / model | Tasks | Attempts | pass@1 | 95% CI | MDD (single set) | "
        "Cost per resolved | Median wall | Tampered | Infra |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, recs in sorted(group_by_config(records).items()):
        sbt = scores_by_task(recs)
        pr = stats.pass_rate(sbt)
        costs = [r.get("cost_usd") for r in recs]
        resolved = [bool(r.get("resolved")) for r in recs]
        cpr, missing = stats.cost_per_resolved(costs, resolved)
        cost_label = _money(cpr) + (f" ({missing} runs without cost)" if missing else "")
        wall = stats.median([r.get("wall_sec") for r in recs if r.get("wall_sec") is not None])
        tampered = sum(1 for r in recs if r.get("tampered"))
        infra = sum(1 for r in recs if r.get("exit_reason") == "infra_error")
        lines.append(
            f"| {key} | {pr.n_tasks} | {pr.n_scores} | {_pct(pr.mean)} | "
            f"{_pct(pr.ci_low)} to {_pct(pr.ci_high)} | {_pts(pr.mdd_single)} | {cost_label} | "
            f"{_secs(wall)} | {tampered} | {infra} |"
        )
    return "\n".join(lines)


def exit_reason_table(records: Records) -> str:
    configs = sorted(group_by_config(records).items())
    header = "| Exit reason | " + " | ".join(k for k, _ in configs) + " |"
    sep = "|---|" + "---|" * len(configs)
    counters = [Counter(str(r.get("exit_reason")) for r in recs) for _, recs in configs]
    rows = [header, sep]
    for reason in EXIT_REASONS:
        rows.append(f"| {reason} | " + " | ".join(str(c.get(reason, 0)) for c in counters) + " |")
    other = [sum(v for k, v in c.items() if k not in EXIT_REASONS) for c in counters]
    if any(other):
        rows.append("| (other) | " + " | ".join(str(o) for o in other) + " |")
    return "\n".join(rows)


def consistency_table(records: Records) -> str:
    rows = ["| Agent / model | " + "resolved k of n attempts" + " |", "|---|---|"]
    for key, recs in sorted(group_by_config(records).items()):
        hist = stats.consistency_histogram(scores_by_task(recs))
        cells = ", ".join(f"{i}: {n} tasks" for i, n in hist.items())
        rows.append(f"| {key} | {cells} |")
    return "\n".join(rows)


def conditions_table(records: Records) -> str:
    rows = [
        "| Agent / model | Agent version | Adapter kwargs | Network (agent / verifier) | Verifier mode | "
        "Agent timeout | Verify timeout | Cost source | Harbor | Host |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, recs in sorted(group_by_config(records).items()):
        r = recs[0]
        kwargs = r.get("agent_kwargs") or {}
        kw = ", ".join(f"{k}={v}" for k, v in sorted(kwargs.items())) or "none"
        net = f"{r.get('network_policy_agent') or '?'} / {r.get('network_policy_verifier') or '?'}"
        sources = sorted({str(x.get("cost_source")) for x in recs})
        host = f"{r.get('host_cpus') or '?'} cpus, {r.get('host_memory_mb') or '?'} MB"
        rows.append(
            f"| {key} | {r.get('agent_version') or '?'} | {kw} | {net} | "
            f"{r.get('verifier_mode_harbor') or r.get('verifier_mode_grader') or '?'} | "
            f"{r.get('agent_timeout_sec') or '?'} s | {r.get('verify_timeout_sec') or '?'} s | "
            f"{', '.join(sources)} | {r.get('harbor_version') or '?'} | {host} |"
        )
    return "\n".join(rows)


def task_heatmap(records: Records) -> str:
    configs = sorted(group_by_config(records).keys())
    tasks = sorted({str(r.get("task_id")) for r in records})
    means: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in records:
        means[(str(r.get("task_id")), _config_key(r))].append(1.0 if r.get("resolved") else 0.0)
    rows = ["| Task | " + " | ".join(configs) + " |", "|---|" + "---|" * len(configs)]
    for t in tasks:
        cells = []
        for c in configs:
            s = means.get((t, c))
            cells.append("-" if not s else f"{int(sum(s))}/{len(s)}")
        rows.append(f"| {t} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_report(records: Records, source: str, reproduce_command: str | None = None) -> str:
    n_tasks = len({r.get("task_id") for r in records})
    parts = [
        "# Probo report",
        "",
        f"Source: `{source}`. {len(records)} runs over {n_tasks} tasks.",
        "",
        "Headline: pass@1 averaged over attempts, 95% interval from standard errors "
        "clustered by task (Miller, 2024). Tampered and infrastructure-failed runs count "
        "as not resolved; nothing is dropped from the denominator. The MDD column is the "
        "smallest difference against a second configuration on the same tasks that this "
        "task count could detect at 80% power, assuming no pairing benefit; a paired "
        "`probo compare` prints the real one.",
        "",
        "## Summary",
        "",
        summary_table(records),
        "",
    ]
    if reproduce_command:
        parts += ["Reproduce:", "", "```bash", reproduce_command, "```", ""]
    parts += [
        "## Exit reasons",
        "",
        exit_reason_table(records),
        "",
        "## Consistency (tasks resolved k of n attempts)",
        "",
        consistency_table(records),
        "",
        "## Task by configuration (resolved attempts / attempts)",
        "",
        task_heatmap(records),
        "",
        "## Conditions",
        "",
        conditions_table(records),
        "",
    ]
    return "\n".join(parts)


def render_compare(a: Records, b: Records, label_a: str, label_b: str) -> str:
    sa, sb = scores_by_task(a), scores_by_task(b)
    pa, pb = stats.pass_rate(sa), stats.pass_rate(sb)
    d = stats.paired_difference(sa, sb)
    ma, mb = stats.task_means(sa), stats.task_means(sb)
    common = sorted(set(ma) & set(mb))
    only_a = sorted(set(ma) - set(mb))
    only_b = sorted(set(mb) - set(ma))
    lines = [
        "# Probo comparison",
        "",
        f"A = `{label_a}`: pass@1 {_pct(pa.mean)} ({_pct(pa.ci_low)} to {_pct(pa.ci_high)}) "
        f"over {pa.n_tasks} tasks.",
        f"B = `{label_b}`: pass@1 {_pct(pb.mean)} ({_pct(pb.ci_low)} to {_pct(pb.ci_high)}) "
        f"over {pb.n_tasks} tasks.",
        "",
        f"Paired difference A - B on the {d.n_tasks} shared tasks: {_pts(d.mean)}, "
        f"95% interval {_pts(d.ci_low)} to {_pts(d.ci_high)}, minimum detectable difference {_pts(d.mdd)}.",
        "",
    ]
    if d.n_tasks == 0:
        lines.append("No shared tasks: nothing to compare.")
    elif d.se != d.se:  # NaN
        lines.append("Only one shared task: no interval can be computed.")
    elif d.detectable:
        lines.append("**Verdict: a detectable difference** (the interval excludes zero).")
    else:
        lines.append("**Verdict: no detectable difference** (the interval includes zero).")
    if d.n_tasks >= 2 and d.se == d.se and d.se > 0:
        sd = d.se * (d.n_tasks**0.5)
        need = ", ".join(f"{int(100 * e)} pts: {stats.tasks_needed(sd, e)}" for e in (0.05, 0.10, 0.15, 0.20))
        lines += ["", f"Tasks needed at 80% power for a difference of {need} (from the measured variance)."]
    if only_a or only_b:
        lines += ["", f"Tasks only in A: {only_a or 'none'}. Tasks only in B: {only_b or 'none'}."]
    lines += ["", "| Task | A | B | A - B |", "|---|---|---|---|"]
    for t in common:
        lines.append(f"| {t} | {_pct(ma[t])} | {_pct(mb[t])} | {_pts(ma[t] - mb[t])} |")
    return "\n".join(lines) + "\n"
