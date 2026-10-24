"""
Tests for CLI commands, exit codes, and formatting.
"""

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


def test_cli_help():
    res = run_cli("--help")
    assert res.returncode == 0
    assert "Pharos Trend Watcher CLI" in res.stdout


def test_cli_observe_validation_error(tmp_path: Path):
    """Validation errors return exit code 2."""
    state_file = tmp_path / "cli_state.json"
    res = run_cli("observe", "--value", "not_a_number", "--state-path", str(state_file))
    assert res.returncode == 2


def test_cli_status_formatted(tmp_path: Path):
    state_file = tmp_path / "cli_state.json"
    run_cli("observe", "--value", "100.0", "--state-path", str(state_file))
    res = run_cli("status", "--state-path", str(state_file))
    assert res.returncode == 0
    assert "PHAROS TREND WATCHER — STATUS REPORT" in res.stdout
    assert "pharos_gas_price_gwei" in res.stdout


def test_cli_history_formatted(tmp_path: Path):
    state_file = tmp_path / "cli_state.json"
    run_cli("observe", "--value", "100.0", "--state-path", str(state_file))
    res = run_cli("history", "--state-path", str(state_file))
    assert res.returncode == 0
    assert "Obs ID" in res.stdout
    assert "100.00" in res.stdout


def test_cli_verify_spike_command(tmp_path: Path):
    """Requirement 05: CLI verify-spike passes with code 0."""
    state_file = tmp_path / "cli_spike_state.json"
    res = run_cli("verify-spike", "--state-path", str(state_file))
    assert res.returncode == 0
    assert "VERDICT: PASS — Single -60.8% spike resisted" in res.stdout


def test_cli_demo_command(tmp_path: Path):
    """CLI demo passes with code 0."""
    state_file = tmp_path / "cli_demo_state.json"
    res = run_cli("demo", "--state-path", str(state_file))
    assert res.returncode == 0
    assert "DEMO VERDICT: ALL 5 CRITERIA CONFIRMED" in res.stdout
