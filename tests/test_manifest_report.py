"""Manifest flattening against a saved Harbor trial layout, and the report and
compare renderers. The sample result.json is validated against Harbor's
TrialResult model when Harbor is installed, so the fixture cannot drift from
the real layout unnoticed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from probo.manifest import exit_reason_from_exception, flatten_job, flatten_trial, read_jsonl, write_jsonl
from probo.report import render_compare, render_report

try:
    from harbor.models.trial.result import TrialResult
except Exception:  # noqa: BLE001
    TrialResult = None  # type: ignore[assignment,misc]

JOB_ID = "11111111-1111-1111-1111-111111111111"


def _config(agent: str, model: str | None, kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "task": {"path": "/tasks/pricing-discount"},
        "trial_name": "",
        "trials_dir": "trials",
        "agent": {"name": agent, "model_name": model, "kwargs": kwargs or {}},
        "environment": {"type": "docker"},
        "verifier": {},
        "job_id": JOB_ID,
    }


def _result(
    trial: str,
    agent: str,
    model: str | None,
    reward: int | None,
    cost: float | None,
    tokens: int | None,
    started: str,
    exception: dict[str, Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    cost_source: str | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] | None = None
    if cost is not None or tokens is not None:
        ctx = {"n_input_tokens": tokens, "n_cache_tokens": 0, "n_output_tokens": 12, "cost_usd": cost}
        if cost_source:
            ctx["metadata"] = {"cost_source": cost_source}
    return {
        "id": "22222222-2222-2222-2222-22222222222" + trial[-1],
        "task_name": "pricing-discount",
        "trial_name": trial,
        "trial_uri": f"file:///jobs/x/{trial}",
        "task_id": {"path": "/tasks/pricing-discount"},
        "task_checksum": "deadbeef",
        "config": _config(agent, model, kwargs),
        "agent_info": {
            "name": agent,
            "version": "1.2.3",
            "model_info": {"name": model, "provider": "anthropic"} if model else None,
        },
        "agent_result": ctx,
        "verifier_result": {"rewards": {"reward": reward, "f2p": reward, "p2p": 1, "tampered": 0}}
        if reward is not None
        else None,
        "verifier_environment_mode": "separate",
        "exception_info": exception,
        "started_at": started,
        "finished_at": started.replace("T10:00:00", "T10:12:00"),
        "environment_setup": {
            "started_at": started,
            "finished_at": started.replace("T10:00:00", "T10:00:30"),
        },
        "agent_execution": {
            "started_at": started.replace("T10:00:00", "T10:00:30"),
            "finished_at": started.replace("T10:00:00", "T10:10:30"),
        },
        "verifier": {
            "started_at": started.replace("T10:00:00", "T10:10:30"),
            "finished_at": started.replace("T10:00:00", "T10:12:00"),
        },
    }


def _verdict(
    exit_reason: str, reward: int, tampered: list[str] | None = None, dep: bool = False
) -> dict[str, Any]:
    return {
        "schema": "probo-verdict/1",
        "grader_version": "0.1.0",
        "task_id": "pricing-discount",
        "pack_version": "0.0.0",
        "reward": reward,
        "exit_reason": exit_reason,
        "verifier_mode": "separate",
        "tampered_files": tampered or [],
        "files_by_category": {
            "main": ["src/main/kotlin/A.kt"],
            "test": tampered or [],
            "build": [],
            "ci": [],
            "other": [],
        },
        "diff_stats": {"files": 1 + len(tampered or []), "insertions": 3, "deletions": 1},
        "detail": {"dependency_added": dep, "oom": False},
        "gradle": {"exit_code": 0, "seconds": 41, "failed_tasks": []},
        "tests": {
            "n_reports": 1,
            "f2p": {"a.T#f": "passed" if reward else "failed"},
            "p2p": {"a.T#g": "passed"},
        },
        "verify_seconds": 45,
    }


@pytest.fixture
def job(tmp_path: Path) -> Path:
    job = tmp_path / "job"
    trials = {
        "pricing-discount__a1": (
            _result(
                "pricing-discount__a1",
                "claude-code",
                "anthropic/claude-sonnet-5-5",
                1,
                0.42,
                1000,
                "2026-10-28T10:00:00+00:00",
                kwargs={"max_turns": 30},
            ),
            _verdict("resolved", 1),
        ),
        "pricing-discount__a2": (
            _result(
                "pricing-discount__a2",
                "claude-code",
                "anthropic/claude-sonnet-5-5",
                0,
                0.5,
                1200,
                "2026-10-28T11:00:00+00:00",
                kwargs={"max_turns": 30},
                cost_source="litellm_estimate",
            ),
            _verdict("tampered", 0, tampered=["src/test/kotlin/T.kt"], dep=True),
        ),
        "pricing-discount__b1": (
            _result(
                "pricing-discount__b1", "aider", "openai/gpt-5", 0, None, None, "2026-10-28T12:00:00+00:00"
            ),
            _verdict("f2p_failed", 0),
        ),
        "pricing-discount__b2": (
            _result(
                "pricing-discount__b2",
                "aider",
                "openai/gpt-5",
                None,
                None,
                None,
                "2026-10-28T13:00:00+00:00",
                exception={
                    "exception_type": "AgentTimeoutError",
                    "exception_message": "timed out",
                    "exception_traceback": "",
                    "occurred_at": "2026-10-28T13:30:00+00:00",
                },
            ),
            None,
        ),
    }
    for name, (result, verdict) in trials.items():
        d = job / name
        (d / "verifier").mkdir(parents=True)
        (d / "artifacts").mkdir()
        (d / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (d / "config.json").write_text(json.dumps(result["config"]), encoding="utf-8")
        (d / "artifacts" / "manifest.json").write_text(
            json.dumps(
                [
                    {
                        "source": "/tmp/harbor-capture",
                        "destination": "tmp/harbor-capture",
                        "type": "directory",
                        "status": "ok",
                    }
                ]
            ),
            encoding="utf-8",
        )
        if verdict:
            (d / "verifier" / "verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
            (d / "verifier" / "reward.json").write_text(
                json.dumps({"reward": verdict["reward"]}), encoding="utf-8"
            )
    (job / "probo-host.json").write_text(
        json.dumps(
            {
                "probo_version": "0.1.0.dev0",
                "harbor_version": "0.24.0",
                "cpus": 24,
                "memory_mb": 32768,
                "platform": "Linux",
                "jdk": "17",
                "gradle": "8.14.3",
                "network_policy_agent": "public",
                "network_policy_verifier": "no-network",
            }
        ),
        encoding="utf-8",
    )
    (job / "result.json").write_text("{}", encoding="utf-8")  # job-level file, not a trial
    return job


def test_sample_result_matches_harbor_model(job: Path) -> None:
    if TrialResult is None:
        pytest.skip("harbor not installed")
    for d in sorted(job.iterdir()):
        if d.is_dir():
            TrialResult.model_validate_json((d / "result.json").read_text("utf-8"))


def test_flatten_job(job: Path) -> None:
    records = flatten_job(job)
    assert len(records) == 4
    by_name = {r["harbor_trial_name"]: r for r in records}
    a1 = by_name["pricing-discount__a1"]
    assert a1["schema"] == "probo-manifest/1"
    assert a1["task_id"] == "pricing-discount"
    assert a1["agent_name"] == "claude-code" and a1["agent_version"] == "1.2.3"
    assert a1["model_name"] == "anthropic/claude-sonnet-5-5"
    assert a1["agent_kwargs"] == {"max_turns": 30}
    assert a1["cost_usd"] == 0.42 and a1["cost_source"] == "reported"
    assert a1["resolved"] is True and a1["exit_reason"] == "resolved"
    assert a1["attempt_index"] == 0
    assert a1["agent_execution_sec"] == 600.0 and a1["verifier_sec"] == 90.0 and a1["wall_sec"] == 720.0
    assert a1["host_cpus"] == 24 and a1["harbor_version"] == "0.24.0" and a1["jdk"] == "17"
    assert a1["harbor_job_id"] == JOB_ID
    assert a1["artifacts"][0]["status"] == "ok"
    a2 = by_name["pricing-discount__a2"]
    assert a2["attempt_index"] == 1
    assert a2["tampered"] is True and a2["tampered_files"] == ["src/test/kotlin/T.kt"]
    assert a2["dependency_added"] is True and a2["resolved"] is False
    assert a2["cost_source"] == "litellm_estimate"
    b1 = by_name["pricing-discount__b1"]
    assert b1["cost_usd"] is None and b1["cost_source"] == "missing" and b1["n_input_tokens"] is None
    assert b1["exit_reason"] == "f2p_failed"
    b2 = by_name["pricing-discount__b2"]
    assert b2["exit_reason"] == "timeout" and b2["exit_reason_harbor"] == "timeout"
    assert b2["exit_reason_grader"] is None and b2["reward"] is None and b2["resolved"] is False


def test_exit_reason_from_exception() -> None:
    assert exit_reason_from_exception(None) is None
    assert exit_reason_from_exception({"exception_type": "AgentTimeoutError"}) == "timeout"
    assert exit_reason_from_exception({"exception_type": "VerifierTimeoutError"}) == "timeout"
    assert exit_reason_from_exception({"exception_type": "SandboxBuildFailedError"}) == "infra_error"
    assert exit_reason_from_exception({"exception_type": "RewardFileNotFoundError"}) == "infra_error"


def test_flatten_trial_without_verdict_is_infra_error(tmp_path: Path) -> None:
    d = tmp_path / "t"
    d.mkdir()
    (d / "result.json").write_text(json.dumps({"task_name": "x", "trial_name": "x__1"}), encoding="utf-8")
    r = flatten_trial(d)
    assert r["exit_reason"] == "infra_error" and r["resolved"] is False and r["task_id"] == "x"


def test_jsonl_roundtrip_and_report(job: Path, tmp_path: Path) -> None:
    records = flatten_job(job)
    out = tmp_path / "r.jsonl"
    write_jsonl(records, out)
    back = read_jsonl(out)
    assert len(back) == 4 and back[0]["schema"] == "probo-manifest/1"
    text = render_report(back, "r.jsonl", reproduce_command="probo report r.jsonl")
    assert "| claude-code / anthropic/claude-sonnet-5-5 | 1 | 2 | 50.0% |" in text
    assert "| aider / openai/gpt-5 | 1 | 2 | 0.0% |" in text
    assert "1 runs without cost" in text or "2 runs without cost" in text
    # Columns are sorted by configuration name: aider, then claude-code.
    assert "| tampered | 0 | 1 |" in text
    assert "| timeout | 1 | 0 |" in text
    assert "probo report r.jsonl" in text
    assert "max_turns=30" in text
    assert "## Conditions" in text


def test_compare(job: Path) -> None:
    records = flatten_job(job)
    a = [r for r in records if r["agent_name"] == "claude-code"]
    b = [r for r in records if r["agent_name"] == "aider"]
    text = render_compare(a, b, "a", "b")
    assert "Only one shared task" in text
    same = render_compare(a, a, "a", "a")
    assert "Only one shared task" in same
    # With several tasks, identical sets show no detectable difference.
    many = []
    for i in range(6):
        for r in a:
            rr = dict(r)
            rr["task_id"] = f"t{i}"
            many.append(rr)
    text2 = render_compare(many, many, "x", "y")
    assert "no detectable difference" in text2
    assert "| t0 | 50.0% | 50.0% | 0.0 pts |" in text2
