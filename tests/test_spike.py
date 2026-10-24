"""
Tests verifying Requirement 05: A single spike does NOT trigger the trend.

Executes the official 8-point reproducible negative test scenario through the
real production TrendEngine and verifies that an isolated extreme anomaly is ignored.
"""

import json
from pathlib import Path
import pytest

from trend.config import RuleConfig
from trend.engine import TrendEngine
from trend.storage import DurableStorage


def test_single_spike_does_not_trigger_using_fixture(tmp_path: Path):
    """
    Requirement 05: Demonstrates that a single spike does not trigger it.
    Uses fixtures/spike_scenario.json through genuine production TrendEngine.
    """
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "spike_scenario.json"
    assert fixture_path.exists(), "Spike scenario fixture must exist."

    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture = json.load(f)

    storage = DurableStorage(tmp_path / "spike_state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=fixture.get("threshold", 3)))

    for step in fixture["readings"]:
        res = engine.ingest(
            value=step["value"],
            timestamp=step["timestamp"],
            observation_id=step["id"],
        )

        assert res.streak == step["expected_streak"], (
            f"Step {step['step']} ({step['note']}) expected streak {step['expected_streak']}, got {res.streak}"
        )
        assert res.triggered == step["expected_triggered"], (
            f"Step {step['step']} ({step['note']}) expected triggered={step['expected_triggered']}, got {res.triggered}"
        )

        # Explicit assertion for the extreme single spike (Step 3: 40.0 Gwei from 102.0 Gwei)
        if step["step"] == 3:
            assert res.triggered is False, "CRITICAL: Single spike triggered trend prematurely!"
            assert res.streak == 2  # 1st drop from 102.0 to 40.0, streak is 2, below threshold of 3
            assert len(engine.triggers) == 0

        # Explicit assertion for the immediate bounce-back recovery (Step 4: 99.0 Gwei)
        if step["step"] == 4:
            assert res.triggered is False
            assert res.streak == 1  # Upward reversal reset the streak
            assert len(engine.triggers) == 0

        # Explicit assertion for the genuine multi-observation trend (Step 7: 88.0 Gwei)
        if step["step"] == 7:
            assert res.triggered is True
            assert res.trigger_record is not None
            assert res.trigger_record.triggering_observation_id == "obs_spike_07"
            assert res.trigger_record.triggering_value == 88.0
            assert len(engine.triggers) == 1


def test_isolated_massive_crash_isolated_step(tmp_path: Path):
    """Independent isolated test: single -90% drop does not trigger threshold=3."""
    storage = DurableStorage(tmp_path / "isolated_spike.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    # Baseline
    r1 = engine.ingest(value=1000.0, timestamp="2026-10-24T10:00:00Z")
    assert r1.streak == 1
    assert r1.triggered is False

    # Single massive 90% crash
    r2 = engine.ingest(value=100.0, timestamp="2026-10-24T10:01:00Z")
    assert r2.streak == 2  # Only 2 points total (baseline + 1 drop), threshold requires 3
    assert r2.triggered is False
    assert len(engine.triggers) == 0

    # Immediate bounce back
    r3 = engine.ingest(value=950.0, timestamp="2026-10-24T10:02:00Z")
    assert r3.streak == 1  # Streak reset by reversal
    assert r3.triggered is False
    assert len(engine.triggers) == 0
