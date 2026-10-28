"""Experiment mode, the power calculation and the grader's diff signals."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from probo import stats
from probo.experiment import Arm, harbor_command, power_table, render_power_note, run_experiment
from probo.grader import grade as g
from probo.report import render_compare


def test_tasks_needed_hand_computed() -> None:
    # n = ((1.96 + 0.84) * sd / effect)^2 ; sd 0.5, effect 0.1 -> (14.008)^2 = 196.2 -> 197
    assert stats.tasks_needed(0.5, 0.10) == 197
    assert stats.tasks_needed(0.5, 0.25) == 32
    assert stats.tasks_needed(0.0, 0.10) == 1
    with pytest.raises(ValueError):
        stats.tasks_needed(0.5, 0)
    table = power_table(0.5)
    assert table[0] == (0.05, stats.tasks_needed(0.5, 0.05))
    assert [n for _e, n in table] == sorted([n for _e, n in table], reverse=True)


def test_power_note_and_harbor_command(tmp_path: Path) -> None:
    note = render_power_note(12, 0.4)
    assert "| 10 points |" in note and "50 or more tasks" in note
    assert "could not be estimated" in render_power_note(1, None)
    assert "could not be estimated" in render_power_note(3, float("nan"))
    arm = Arm("treat", "claude-code", "anthropic/claude-sonnet-5-5", ["max_turns=30", "skills=/skills"])
    cmd = harbor_command(
        "harbor", [tmp_path / "t1", tmp_path / "t2"], arm, 3, 2, tmp_path / "jobs", "exp-treat"
    )
    assert cmd[:5] == ["harbor", "run", "-p", str(tmp_path / "t1"), "-p"]
    assert "--job-name" in cmd and "exp-treat" in cmd
    assert cmd[cmd.index("-k") + 1] == "3" and cmd[cmd.index("-n") + 1] == "2"
    assert cmd.count("--ak") == 2 and "-m" in cmd
    assert arm.describe() == "claude-code anthropic/claude-sonnet-5-5 max_turns=30 skills=/skills"


def test_run_experiment_print_only(tmp_path: Path) -> None:
    res = run_experiment(
        [tmp_path / "t1"],
        Arm("baseline", "mini-swe-agent", "openai/gpt-5"),
        Arm("with-skill", "mini-swe-agent", "openai/gpt-5", ["skills=/opt/skills"]),
        attempts=2,
        jobs=tmp_path / "jobs",
        name="exp1",
        print_only=True,
        harbor="harbor",
    )
    assert res.name == "exp1" and len(res.commands) == 2 and res.report_path is None
    assert "A = baseline: mini-swe-agent openai/gpt-5" in res.report
    assert "B = with-skill: mini-swe-agent openai/gpt-5 skills=/opt/skills" in res.report
    assert res.job_dirs[0].name == "exp1-baseline" and res.job_dirs[1].name == "exp1-with-skill"
    assert "--ak skills=/opt/skills" in res.report


def _records(label: str, task_scores: dict[str, list[int]]) -> list[dict]:
    out = []
    for task, scores in task_scores.items():
        for s in scores:
            out.append(
                {
                    "task_id": task,
                    "agent_name": label,
                    "model_name": "m",
                    "resolved": bool(s),
                    "exit_reason": "resolved" if s else "f2p_failed",
                }
            )
    return out


def test_compare_prints_tasks_needed() -> None:
    a = _records("a", {"t1": [1, 1], "t2": [1, 0], "t3": [0, 0], "t4": [1, 1], "t5": [0, 1]})
    b = _records("b", {"t1": [0, 1], "t2": [0, 0], "t3": [0, 0], "t4": [1, 0], "t5": [0, 0]})
    text = render_compare(a, b, "a", "b")
    assert "Tasks needed at 80% power for a difference of 5 pts:" in text
    assert "minimum detectable difference" in text


def test_scan_diff_signals() -> None:
    diff = (
        "diff --git a/app/src/main/AndroidManifest.xml b/app/src/main/AndroidManifest.xml\n"
        "--- a/app/src/main/AndroidManifest.xml\n+++ b/app/src/main/AndroidManifest.xml\n@@ -1,2 +1,4 @@\n"
        ' <manifest>\n+    <uses-permission android:name="android.permission.READ_CONTACTS" />\n'
        '+    <uses-permission-sdk-23 android:name="android.permission.CAMERA"/>\n </manifest>\n'
        "diff --git a/app/src/main/kotlin/K.kt b/app/src/main/kotlin/K.kt\n"
        "--- a/app/src/main/kotlin/K.kt\n+++ b/app/src/main/kotlin/K.kt\n@@ -1 +1,4 @@\n"
        '+val apiKey = "AIza' + "A" * 35 + '"\n'
        '+const val PASSWORD = "hunter2hunter2"\n'
        "+val fine = 1\n"
        '-val removed = "AKIA' + "B" * 16 + '"\n'
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n"
        "+-----BEGIN RSA PRIVATE KEY-----\n"
    )
    signals = g.scan_diff_signals(diff)
    assert signals["permissions_added"] == [
        {"path": "app/src/main/AndroidManifest.xml", "permission": "android.permission.READ_CONTACTS"},
        {"path": "app/src/main/AndroidManifest.xml", "permission": "android.permission.CAMERA"},
    ]
    kinds = [(s["path"], s["kind"]) for s in signals["secrets_found"]]
    assert ("app/src/main/kotlin/K.kt", "google_api_key") in kinds
    assert ("app/src/main/kotlin/K.kt", "secret_assignment") in kinds
    assert ("README.md", "private_key_block") in kinds
    assert all(k != "aws_access_key" for _p, k in kinds)  # removed lines are not scanned
    assert g.scan_diff_signals("") == {"secrets_found": [], "permissions_added": []}
    assert json.dumps(signals)
    assert not math.isnan(len(kinds))
