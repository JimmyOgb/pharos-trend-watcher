"""
Tests for deterministic trend evaluation, threshold triggering, reversals, and timestamps.
Verifies Requirement 02, Requirement 04, and edge cases.
"""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from trend.config import RuleConfig, TrendDirection
from trend.engine import (
    OutOfOrderObservationError,
    TrendEngine,
)
from trend.storage import DurableStorage


def test_initial_observation_no_trigger(tmp_path: Path):
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    res = engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z")
    assert res.status == "ACCEPTED"
    assert res.streak == 1
    assert res.triggered is False
    assert res.trigger_record is None
    assert len(engine.observations) == 1
    assert len(engine.triggers) == 0


def test_two_observations_do_not_trigger_three_observation_rule(tmp_path: Path):
    """Requirement 02: 2 qualifying observations must not trigger a 3-observation rule."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    res1 = engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z")
    assert res1.streak == 1
    assert res1.triggered is False

    res2 = engine.ingest(value=95.0, timestamp="2026-10-24T10:01:00Z")
    assert res2.streak == 2
    assert res2.triggered is False
    assert len(engine.triggers) == 0


def test_three_qualifying_observations_trigger_at_exact_threshold(tmp_path: Path):
    """Requirement 02 & 04: Exactly 3 qualifying observations trigger the trend."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z", observation_id="obs_01")
    engine.ingest(value=95.0, timestamp="2026-10-24T10:01:00Z", observation_id="obs_02")
    res3 = engine.ingest(value=90.0, timestamp="2026-10-24T10:02:00Z", observation_id="obs_03")

    assert res3.streak == 3
    assert res3.triggered is True
    assert res3.trigger_record is not None
    assert res3.trigger_record.triggering_observation_id == "obs_03"
    assert res3.trigger_record.triggering_value == 90.0
    assert res3.trigger_record.threshold == 3
    assert res3.trigger_record.qualifying_window_ids == ["obs_01", "obs_02", "obs_03"]
    assert "Confirmed downward trend" in res3.trigger_record.rationale

    # Must be persisted in storage
    reloaded = storage.load()
    assert len(reloaded.triggers) == 1
    assert reloaded.triggers[0].triggering_observation_id == "obs_03"


def test_threshold_greater_than_three_works_correctly(tmp_path: Path):
    """Requirement 02: Configurable threshold greater than 3."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=5))

    values = [100.0, 95.0, 90.0, 85.0]
    for i, v in enumerate(values, start=1):
        res = engine.ingest(value=v, timestamp=f"2026-10-24T10:0{i}:00Z")
        assert res.streak == i
        assert res.triggered is False, f"Reading {i} should not trigger threshold 5"

    # 5th drop reaches threshold 5
    res5 = engine.ingest(value=80.0, timestamp="2026-10-24T10:05:00Z")
    assert res5.streak == 5
    assert res5.triggered is True
    assert len(engine.triggers) == 1


def test_reversal_breaks_streak_and_resets(tmp_path: Path):
    """An upward move in a downward trend resets the active streak."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z")  # streak 1
    engine.ingest(value=95.0, timestamp="2026-10-24T10:01:00Z")   # streak 2
    res_rev = engine.ingest(value=105.0, timestamp="2026-10-24T10:02:00Z")  # reversal!

    assert res_rev.streak == 1
    assert res_rev.triggered is False
    assert "upward movement" in res_rev.message


def test_flat_reading_strict_monotonic_resets_streak(tmp_path: Path):
    """In strict monotonic mode, an unchanged value breaks the downward streak."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3, strict_monotonic=True))

    engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z")  # streak 1
    engine.ingest(value=95.0, timestamp="2026-10-24T10:01:00Z")   # streak 2
    res_flat = engine.ingest(value=95.0, timestamp="2026-10-24T10:02:00Z")  # flat!

    assert res_flat.streak == 1
    assert res_flat.triggered is False
    assert "flat reading" in res_flat.message


def test_out_of_order_timestamp_rejected(tmp_path: Path):
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    engine.ingest(value=100.0, timestamp="2026-10-24T10:10:00Z")
    with pytest.raises(OutOfOrderObservationError) as exc_info:
        engine.ingest(value=95.0, timestamp="2026-10-24T10:05:00Z")
    assert "Retroactive observations rejected" in str(exc_info.value)


def test_excessive_time_gap_resets_streak(tmp_path: Path):
    """If delta between observations exceeds max_interval_seconds, streak resets."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3, max_interval_seconds=600))  # 10 min

    engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z")  # streak 1
    engine.ingest(value=95.0, timestamp="2026-10-24T10:05:00Z")   # streak 2 (5 min later)

    # 3rd reading arrives 2 hours later (> 600s)
    res_gap = engine.ingest(value=90.0, timestamp="2026-10-24T12:05:00Z")
    assert res_gap.streak == 1
    assert res_gap.triggered is False
    assert "exceeded max allowable" in res_gap.message


def test_upward_trend_configuration(tmp_path: Path):
    """Supports upward trend direction."""
    storage = DurableStorage(tmp_path / "state.json")
    engine = TrendEngine(storage, config=RuleConfig(direction=TrendDirection.UPWARD, threshold=3))

    engine.ingest(value=50.0, timestamp="2026-10-24T10:00:00Z")
    engine.ingest(value=60.0, timestamp="2026-10-24T10:01:00Z")
    res = engine.ingest(value=75.0, timestamp="2026-10-24T10:02:00Z")

    assert res.streak == 3
    assert res.triggered is True
    assert res.trigger_record is not None
    assert "Confirmed upward trend" in res.trigger_record.rationale
