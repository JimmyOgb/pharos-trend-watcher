"""
Tests for durable storage, atomic persistence, schema validation, and quarantine on corruption.
Verifies Requirement 01 & Requirement 03.
"""

import json
from pathlib import Path
import pytest

from trend.config import RuleConfig
from trend.storage import (
    CorruptedStateError,
    DurableStorage,
    Observation,
    TrendState,
    TriggerRecord,
)


def test_atomic_write_creates_valid_state(tmp_path: Path):
    state_file = tmp_path / "trend_state.json"
    storage = DurableStorage(state_file)

    initial_state = storage.load()
    assert len(initial_state.observations) == 0
    assert len(initial_state.triggers) == 0

    obs = Observation(
        id="obs_001",
        timestamp="2026-10-24T10:00:00+00:00",
        metric="pharos_gas_price_gwei",
        value=100.0,
        delta=None,
        streak=1,
    )
    initial_state.observations.append(obs)
    storage.save(initial_state)

    # State file must exist and have content
    assert state_file.exists()
    assert state_file.stat().st_size > 0

    # Ensure no temporary files were leaked
    temp_files = list(tmp_path.glob("*.tmp.*"))
    assert len(temp_files) == 0

    # Reload from fresh storage instance
    new_storage = DurableStorage(state_file)
    reloaded_state = new_storage.load()
    assert len(reloaded_state.observations) == 1
    assert reloaded_state.observations[0].id == "obs_001"
    assert reloaded_state.observations[0].value == 100.0


def test_corrupted_state_quarantined_not_erased(tmp_path: Path):
    """Corrupted state must be quarantined to .corrupted.<timestamp>, not silently overwritten."""
    state_file = tmp_path / "trend_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        f.write("{ INVALID MALFORMED JSON DATA !!!")

    storage = DurableStorage(state_file)
    with pytest.raises(CorruptedStateError) as exc_info:
        storage.load()

    assert "malformed or unreadable" in str(exc_info.value)
    # The original file path should have been moved/quarantined
    assert not state_file.exists()
    quarantined = list(tmp_path.glob("trend_state.json.corrupted.*"))
    assert len(quarantined) == 1
    with open(quarantined[0], "r", encoding="utf-8") as f:
        assert "{ INVALID MALFORMED JSON DATA !!!" in f.read()


def test_invalid_schema_quarantined(tmp_path: Path):
    state_file = tmp_path / "trend_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"version": "1.0.0", "observations": "NOT_A_LIST"}, f)

    storage = DurableStorage(state_file)
    with pytest.raises(CorruptedStateError):
        storage.load()

    quarantined = list(tmp_path.glob("trend_state.json.corrupted.*"))
    assert len(quarantined) == 1


def test_missing_file_initializes_empty_state(tmp_path: Path):
    state_file = tmp_path / "non_existent_state.json"
    storage = DurableStorage(state_file)
    state = storage.load()
    assert state.version == "1.0.0"
    assert len(state.observations) == 0
    assert len(state.triggers) == 0


def test_trigger_record_persistence(tmp_path: Path):
    state_file = tmp_path / "trend_state.json"
    storage = DurableStorage(state_file)
    state = storage.load()

    trig = TriggerRecord(
        trigger_id="trig_abc123",
        timestamp="2026-10-24T10:05:00+00:00",
        triggering_observation_id="obs_003",
        triggering_value=85.0,
        threshold=3,
        qualifying_window_ids=["obs_001", "obs_002", "obs_003"],
        rationale="3 consecutive drops confirmed",
    )
    state.triggers.append(trig)
    storage.save(state)

    reloaded = storage.load()
    assert len(reloaded.triggers) == 1
    assert reloaded.triggers[0].trigger_id == "trig_abc123"
    assert reloaded.triggers[0].qualifying_window_ids == ["obs_001", "obs_002", "obs_003"]
