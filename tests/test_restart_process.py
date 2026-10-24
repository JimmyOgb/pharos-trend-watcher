"""
Process restart test verifying Requirement 01 & Requirement 03 across separate operating system processes.
Launches separate OS subprocesses to prove durable state persistence and recovery across process death.
"""

import json
from pathlib import Path
import subprocess
import sys
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WATCHER_SCRIPT = _PROJECT_ROOT / "scripts" / "watcher.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(_WATCHER_SCRIPT)] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )


def test_process_restart_preserves_history_and_streak(tmp_path: Path):
    """
    Requirement 01 & 03: Separate OS processes verify that observations survive process death
    and that consecutive streaks accumulate properly across distinct process executions.
    """
    state_file = tmp_path / "proc_restart_state.json"

    # Process 1: First observation
    p1 = run_cli(
        "observe",
        "--value", "100.0",
        "--timestamp", "2026-10-24T10:00:00Z",
        "--id", "p_obs_01",
        "--state-path", str(state_file),
    )
    assert p1.returncode == 0, f"Process 1 failed: {p1.stderr}"
    assert "Status      : ACCEPTED" in p1.stdout
    assert "Streak      : 1 / 3" in p1.stdout
    assert "Triggered   : NO" in p1.stdout

    # Process 2: Second observation (drop to 95.0) in a completely new OS process
    p2 = run_cli(
        "observe",
        "--value", "95.0",
        "--timestamp", "2026-10-24T10:01:00Z",
        "--id", "p_obs_02",
        "--state-path", str(state_file),
    )
    assert p2.returncode == 0, f"Process 2 failed: {p2.stderr}"
    assert "Status      : ACCEPTED" in p2.stdout
    assert "Streak      : 2 / 3" in p2.stdout
    assert "Triggered   : NO" in p2.stdout

    # Process 3: Inspect status from another process
    p3 = run_cli("status", "--json", "--state-path", str(state_file))
    assert p3.returncode == 0
    status_data = json.loads(p3.stdout)
    assert status_data["total_observations"] == 2
    assert status_data["current_streak"] == 2
    assert status_data["is_triggered"] is False

    # Process 4: Third observation (drop to 90.0) in yet another separate process
    p4 = run_cli(
        "observe",
        "--value", "90.0",
        "--timestamp", "2026-10-24T10:02:00Z",
        "--id", "p_obs_03",
        "--state-path", str(state_file),
    )
    assert p4.returncode == 0, f"Process 4 failed: {p4.stderr}"
    assert "Status      : ACCEPTED" in p4.stdout
    assert "Streak      : 3 / 3" in p4.stdout
    assert "Triggered   : YES" in p4.stdout
    assert "Trigger ID  :" in p4.stdout

    # Process 5: Check history via JSON from separate process
    p5 = run_cli("history", "--json", "--state-path", str(state_file))
    assert p5.returncode == 0
    history = json.loads(p5.stdout)
    assert len(history) == 3
    assert [h["id"] for h in history] == ["p_obs_01", "p_obs_02", "p_obs_03"]

    # Process 6: Test duplicate observation rejection across separate processes
    p6 = run_cli(
        "observe",
        "--value", "90.0",
        "--timestamp", "2026-10-24T10:02:00Z",
        "--id", "p_obs_03",
        "--state-path", str(state_file),
    )
    assert p6.returncode == 0
    assert "Status      : DUPLICATE" in p6.stdout

    # Final verification: history count is still 3
    p7 = run_cli("status", "--json", "--state-path", str(state_file))
    final_status = json.loads(p7.stdout)
    assert final_status["total_observations"] == 3
    assert final_status["total_triggers"] == 1
    assert final_status["is_triggered"] is True
