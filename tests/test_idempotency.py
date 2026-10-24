"""
Tests for duplicate detection, observation deduplication, and trigger idempotency.
Verifies Requirement 03.
"""

from pathlib import Path
import pytest

from trend.config import RuleConfig
from trend.engine import TrendEngine
from trend.storage import (
    DurableStorage,
    compute_observation_id,
    compute_trigger_id,
)


def test_reprocessing_observation_does_not_duplicate_history(tmp_path: Path):
    """Requirement 03: Re-processing identical observation must be idempotent."""
    storage = DurableStorage(tmp_path / "idemp_state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    res1 = engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z", observation_id="obs_fixed_01")
    assert res1.status == "ACCEPTED"
    assert len(engine.observations) == 1

    # Ingest the exact same observation again
    res2 = engine.ingest(value=100.0, timestamp="2026-10-24T10:00:00Z", observation_id="obs_fixed_01")
    assert res2.status == "DUPLICATE"
    assert "already been processed" in res2.message
    # Observation history length must strictly remain 1
    assert len(engine.observations) == 1

    # Reload from disk: durable state must not have duplicated the entry
    reloaded_state = storage.load()
    assert len(reloaded_state.observations) == 1


def test_re_executing_after_trigger_does_not_duplicate_trigger_record(tmp_path: Path):
    """Triggering window must not produce duplicate trigger records."""
    storage = DurableStorage(tmp_path / "trig_idemp_state.json")
    engine = TrendEngine(storage, config=RuleConfig(threshold=3))

    engine.ingest(100.0, "2026-10-24T10:00:00Z", "obs_01")
    engine.ingest(95.0, "2026-10-24T10:01:00Z", "obs_02")
    res3 = engine.ingest(90.0, "2026-10-24T10:02:00Z", "obs_03")

    assert res3.triggered is True
    assert len(engine.triggers) == 1

    # Ingesting continuation reading or reprocessing obs_03
    dup_obs3 = engine.ingest(90.0, "2026-10-24T10:02:00Z", "obs_03")
    assert dup_obs3.status == "DUPLICATE"
    assert len(engine.triggers) == 1  # Trigger count remains strictly 1

    # Ingesting continuation reading in the same unbroken trend does NOT create a duplicate trigger
    res4 = engine.ingest(85.0, "2026-10-24T10:03:00Z", "obs_04")
    assert res4.streak == 4
    assert res4.triggered is False
    assert len(engine.triggers) == 1  # Trend was already confirmed; preserved exact trigger moment

    # If a reversal occurs, resetting the streak, and a NEW 3-drop sequence occurs later:
    engine.ingest(100.0, "2026-10-24T10:04:00Z", "obs_rev")  # Reversal resets streak to 1
    engine.ingest(95.0, "2026-10-24T10:05:00Z", "obs_05")   # Streak 2
    res_new_trig = engine.ingest(90.0, "2026-10-24T10:06:00Z", "obs_06")  # Streak 3 -> New Trigger!

    assert res_new_trig.triggered is True
    assert len(engine.triggers) == 2
    assert engine.triggers[0].trigger_id != engine.triggers[1].trigger_id


def test_deterministic_observation_ids():
    id1 = compute_observation_id("pharos_gas_price_gwei", "2026-10-24T10:00:00Z", 100.0)
    id2 = compute_observation_id("pharos_gas_price_gwei", "2026-10-24T10:00:00Z", 100.0)
    id3 = compute_observation_id("pharos_gas_price_gwei", "2026-10-24T10:00:00Z", 100.0001)

    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 16


def test_deterministic_trigger_ids():
    w1 = ["obs_01", "obs_02", "obs_03"]
    w2 = ["obs_03", "obs_01", "obs_02"]  # Permuted
    w3 = ["obs_02", "obs_03", "obs_04"]

    assert compute_trigger_id(w1) == compute_trigger_id(w2)
    assert compute_trigger_id(w1) != compute_trigger_id(w3)
