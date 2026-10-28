"""Flatten a Harbor job directory into one JSONL record per trial.

Sources per trial directory (Harbor 0.24.0 layout, ``harbor/models/trial/paths.py``):

* ``result.json``: Harbor's TrialResult (agent info, agent context with tokens
  and cost, verifier rewards, phase timings, verifier environment mode,
  exception info).
* ``config.json``: the resolved trial config (agent kwargs, model, task path).
* ``verifier/verdict.json``: the grader's verdict (exit reason, tampering,
  per-test results, Gradle timings).
* ``artifacts/manifest.json``: what crossed from the agent container.
* ``probo-host.json`` at the job root, written by ``probo run``: host
  CPU and RAM, harness and Harbor versions, the command line.

Missing values are ``None``, never zero. Fields are the ones ROADMAP.md lists
under "Result manifest fields"; retrofitting them later is painful, so every
one is present in every record even when unknown.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from probo import __version__

MANIFEST_SCHEMA = "probo-manifest/1"

# Harbor exception class names -> exit reason. Anything else is infra_error.
_EXCEPTION_EXIT_REASONS = {
    "AgentTimeoutError": "timeout",
    "VerifierTimeoutError": "timeout",
    "AgentExecutionError": "agent_error",
    "AgentSetupError": "agent_error",
    "AgentUsageLimitError": "agent_error",
    "AgentAuthError": "agent_error",
    "AgentRefusalError": "agent_error",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration(timing: dict[str, Any] | None) -> float | None:
    if not timing:
        return None
    a, b = _parse_ts(timing.get("started_at")), _parse_ts(timing.get("finished_at"))
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def exit_reason_from_exception(exception_info: dict[str, Any] | None) -> str | None:
    if not exception_info:
        return None
    name = str(exception_info.get("exception_type", ""))
    return _EXCEPTION_EXIT_REASONS.get(name, "infra_error")


def iter_trial_dirs(job_dir: Path) -> Iterator[Path]:
    for child in sorted(job_dir.iterdir()):
        if child.is_dir() and (child / "result.json").is_file():
            yield child


def flatten_trial(trial_dir: Path, host: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _read_json(trial_dir / "result.json") or {}
    config = _read_json(trial_dir / "config.json") or {}
    verdict = _read_json(trial_dir / "verifier" / "verdict.json") or {}
    artifacts = _read_json(trial_dir / "artifacts" / "manifest.json")
    host = host or {}

    agent_info = result.get("agent_info") or {}
    model_info = agent_info.get("model_info") or {}
    agent_ctx = result.get("agent_result") or {}
    cfg_agent = (config.get("agent") or {}) if isinstance(config, dict) else {}
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    detail = verdict.get("detail") or {}
    tests = verdict.get("tests") or {}
    gradle = verdict.get("gradle") or {}

    harbor_exit = exit_reason_from_exception(result.get("exception_info"))
    grader_exit = verdict.get("exit_reason")
    # Harbor-level failures (agent timeout, agent crash, sandbox failure) take
    # precedence over whatever the grader could still say, per the Definitions.
    exit_reason = harbor_exit or grader_exit or ("infra_error" if not verdict else None)
    reward = rewards.get("reward")
    if reward is None:
        reward = verdict.get("reward")
    resolved = exit_reason == "resolved" and reward == 1

    cost = agent_ctx.get("cost_usd")
    meta = agent_ctx.get("metadata") or {}
    if cost is None:
        cost_source = "missing"
    elif meta.get("cost_source"):
        cost_source = str(meta["cost_source"])
    else:
        cost_source = "reported"

    return {
        "schema": MANIFEST_SCHEMA,
        "task_id": verdict.get("task_id") or result.get("task_name"),
        "pack_version": verdict.get("pack_version"),
        "harbor_job_id": config.get("job_id") or (result.get("config") or {}).get("job_id"),
        "harbor_trial_id": result.get("id"),
        "harbor_trial_name": result.get("trial_name") or trial_dir.name,
        "task_checksum": result.get("task_checksum"),
        "agent_name": agent_info.get("name") or cfg_agent.get("name"),
        "agent_version": agent_info.get("version"),
        "agent_import_path": cfg_agent.get("import_path"),
        "agent_kwargs": cfg_agent.get("kwargs") or {},
        "model_name": model_info.get("name") or cfg_agent.get("model_name"),
        "model_provider": model_info.get("provider"),
        "prompt_template_hash": None,  # set by the run layer once templates exist
        "probo_version_flatten": __version__,
        "probo_version_run": host.get("probo_version"),
        "grader_version": verdict.get("grader_version"),
        "harbor_version": host.get("harbor_version"),
        "image_digest": host.get("image_digest"),
        "jdk": host.get("jdk") or _spec_field(trial_dir, "jdk"),
        "gradle": host.get("gradle") or _spec_field(trial_dir, "gradle"),
        "agp": host.get("agp") or _spec_field(trial_dir, "agp"),
        "network_policy_agent": host.get("network_policy_agent"),
        "network_policy_verifier": host.get("network_policy_verifier"),
        "verifier_mode_harbor": result.get("verifier_environment_mode"),
        "verifier_mode_grader": verdict.get("verifier_mode"),
        "host_cpus": host.get("cpus"),
        "host_memory_mb": host.get("memory_mb"),
        "host_platform": host.get("platform"),
        "run_started_at": result.get("started_at"),
        "run_finished_at": result.get("finished_at"),
        "environment_setup_sec": _duration(result.get("environment_setup")),
        "agent_setup_sec": _duration(result.get("agent_setup")),
        "agent_execution_sec": _duration(result.get("agent_execution")),
        "verifier_sec": _duration(result.get("verifier")),
        "wall_sec": _duration(
            {"started_at": result.get("started_at"), "finished_at": result.get("finished_at")}
        ),
        "agent_timeout_sec": _spec_field(trial_dir, "agent_timeout_sec"),
        "verify_timeout_sec": _spec_field(trial_dir, "verify_timeout_sec"),
        "attempt_index": None,  # filled by flatten_job
        "retry_count": None,  # Harbor 0.24.0 does not record it
        "regrade_count": host.get("regrade_count"),
        "n_input_tokens": agent_ctx.get("n_input_tokens"),
        "n_cache_tokens": agent_ctx.get("n_cache_tokens"),
        "n_output_tokens": agent_ctx.get("n_output_tokens"),
        "cost_usd": cost,
        "cost_source": cost_source,
        "pricing_table_version": None,
        "diff_files": (verdict.get("diff_stats") or {}).get("files"),
        "diff_insertions": (verdict.get("diff_stats") or {}).get("insertions"),
        "diff_deletions": (verdict.get("diff_stats") or {}).get("deletions"),
        "files_by_category": verdict.get("files_by_category"),
        "reward": reward,
        "rewards": rewards,
        "exit_reason": exit_reason,
        "exit_reason_grader": grader_exit,
        "exit_reason_harbor": harbor_exit,
        "exception_type": (result.get("exception_info") or {}).get("exception_type"),
        "resolved": resolved,
        "tampered": bool(verdict.get("tampered_files")),
        "tampered_files": verdict.get("tampered_files") or [],
        "dependency_added": bool(detail.get("dependency_added")),
        "oom": bool(detail.get("oom")),
        "f2p_results": tests.get("f2p"),
        "p2p_results": tests.get("p2p"),
        "n_junit_reports": tests.get("n_reports"),
        "gradle_exit_code": gradle.get("exit_code"),
        "gradle_sec": gradle.get("seconds"),
        "gradle_failed_tasks": gradle.get("failed_tasks"),
        "verify_sec_grader": verdict.get("verify_seconds"),
        "artifacts": artifacts,
        "trial_dir": str(trial_dir),
    }


def _spec_field(trial_dir: Path, key: str) -> Any:
    """The grader copies nothing of spec.json into the verifier log directory
    except what verdict.json carries; a task-local spec next to the job is
    optional. Returns None when unknown."""
    spec = _read_json(trial_dir / "verifier" / "spec.json")
    if spec:
        return spec.get(key)
    return None


def flatten_job(job_dir: str | Path) -> list[dict[str, Any]]:
    job_dir = Path(job_dir)
    host = _read_json(job_dir / "probo-host.json")
    records = [flatten_trial(t, host) for t in iter_trial_dirs(job_dir)]
    # Attempt index: trials of the same task ordered by start time.
    by_task: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_task.setdefault(str(r["task_id"]), []).append(r)
    for group in by_task.values():
        group.sort(key=lambda r: (r.get("run_started_at") or "", r["harbor_trial_name"]))
        for i, r in enumerate(group):
            r["attempt_index"] = i
    return records


def write_jsonl(records: list[dict[str, Any]], out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
