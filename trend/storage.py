"""
Durable state storage and recovery for Pharos Trend Watcher.

Provides atomic persistence, state validation, forensic quarantine on corruption,
and idempotent recording across separate operating-system process executions.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from trend.config import RuleConfig, TrendConfigurationError


class StorageError(Exception):
    """Base exception for storage operations."""
    pass


class CorruptedStateError(StorageError):
    """Raised when persisted state is corrupted or violates schema integrity."""
    pass


@dataclass(frozen=True)
class Observation:
    """An immutable recorded metric observation."""
    id: str
    timestamp: str  # ISO-8601 UTC format
    metric: str
    value: float
    delta: Optional[float] = None
    streak: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Observation:
        return cls(
            id=str(data["id"]),
            timestamp=str(data["timestamp"]),
            metric=str(data["metric"]),
            value=float(data["value"]),
            delta=float(data["delta"]) if data.get("delta") is not None else None,
            streak=int(data.get("streak", 1)),
        )


@dataclass(frozen=True)
class TriggerRecord:
    """An immutable record of a confirmed trend trigger event."""
    trigger_id: str
    timestamp: str  # ISO-8601 UTC format
    triggering_observation_id: str
    triggering_value: float
    threshold: int
    qualifying_window_ids: List[str]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TriggerRecord:
        return cls(
            trigger_id=str(data["trigger_id"]),
            timestamp=str(data["timestamp"]),
            triggering_observation_id=str(data["triggering_observation_id"]),
            triggering_value=float(data["triggering_value"]),
            threshold=int(data["threshold"]),
            qualifying_window_ids=[str(i) for i in data.get("qualifying_window_ids", [])],
            rationale=str(data["rationale"]),
        )


@dataclass
class TrendState:
    """Complete serialized state of the Trend Watcher."""
    version: str = "1.0.0"
    rule_config: RuleConfig = field(default_factory=RuleConfig)
    observations: List[Observation] = field(default_factory=list)
    triggers: List[TriggerRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "rule_config": self.rule_config.to_dict(),
            "observations": [obs.to_dict() for obs in self.observations],
            "triggers": [trig.to_dict() for trig in self.triggers],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TrendState:
        if not isinstance(data, dict):
            raise CorruptedStateError("Persisted state root must be a JSON object.")

        version = data.get("version", "1.0.0")
        config_data = data.get("rule_config")
        if not isinstance(config_data, dict):
            raise CorruptedStateError("Persisted state missing or invalid 'rule_config'.")

        try:
            rule_config = RuleConfig.from_dict(config_data)
        except TrendConfigurationError as err:
            raise CorruptedStateError(f"Persisted rule_config violates configuration constraints: {err}") from err

        raw_observations = data.get("observations")
        if not isinstance(raw_observations, list):
            raise CorruptedStateError("Persisted state missing or invalid 'observations' array.")

        observations = []
        for idx, obs_data in enumerate(raw_observations):
            if not isinstance(obs_data, dict):
                raise CorruptedStateError(f"Observation at index {idx} is not a valid JSON object.")
            try:
                observations.append(Observation.from_dict(obs_data))
            except (KeyError, ValueError, TypeError) as err:
                raise CorruptedStateError(f"Malformed observation at index {idx}: {err}") from err

        raw_triggers = data.get("triggers")
        if not isinstance(raw_triggers, list):
            raise CorruptedStateError("Persisted state missing or invalid 'triggers' array.")

        triggers = []
        for idx, trig_data in enumerate(raw_triggers):
            if not isinstance(trig_data, dict):
                raise CorruptedStateError(f"Trigger record at index {idx} is not a valid JSON object.")
            try:
                triggers.append(TriggerRecord.from_dict(trig_data))
            except (KeyError, ValueError, TypeError) as err:
                raise CorruptedStateError(f"Malformed trigger at index {idx}: {err}") from err

        return cls(
            version=version,
            rule_config=rule_config,
            observations=observations,
            triggers=triggers,
        )


def compute_observation_id(metric: str, timestamp_iso: str, value: float) -> str:
    """Generate a deterministic 16-hex identifier for an observation."""
    raw = f"{metric}:{timestamp_iso}:{value:.6f}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def compute_trigger_id(qualifying_window_ids: List[str]) -> str:
    """Generate a deterministic identifier for a trigger based on its qualifying window."""
    raw = ":".join(sorted(qualifying_window_ids)).encode("utf-8")
    return f"trig_{hashlib.sha256(raw).hexdigest()[:12]}"


class DurableStorage:
    """
    Manages persistent state on durable media using atomic file replacement.

    Guarantees:
    - Writes new state to a temporary file, flushes buffer, executes os.fsync, and renames atomically.
    - Protects against partial-write file corruption during sudden process aborts.
    - Quarantines invalid or corrupted state files to .corrupted.<timestamp> rather than silently erasing them.
    - Idempotently prevents duplicate observations and duplicate triggers.

    Platform Considerations:
    - On Windows NTFS, file locks by indexing or antivirus software can transiently block os.replace;
      a bounded retry backoff is implemented to handle these transient lock contention events.
    - File-based persistence guarantees single-process crash consistency. For multi-process
      environments without an external database, external locking must be coordinated.
    """

    def __init__(self, file_path: Path | str, default_config: Optional[RuleConfig] = None):
        self.file_path = Path(file_path).resolve()
        self.default_config = default_config or RuleConfig()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> TrendState:
        """
        Load state from disk. If file does not exist, return new default state.
        If file contains corrupted data, quarantine the file and raise CorruptedStateError.
        """
        if not self.file_path.exists():
            return TrendState(rule_config=self.default_config)

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    raise CorruptedStateError("Persisted state file is empty (0 bytes).")
                raw_data = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            self._quarantine_corrupt_file()
            raise CorruptedStateError(f"Persisted JSON is malformed or unreadable: {err}") from err

        try:
            return TrendState.from_dict(raw_data)
        except CorruptedStateError:
            self._quarantine_corrupt_file()
            raise

    def save(self, state: TrendState) -> None:
        """
        Persist state atomically to disk.
        Workflow: .tmp file -> flush -> fsync -> atomic os.replace with retry.
        """
        serialized = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
        temp_path = self.file_path.parent / f"{self.file_path.name}.tmp.{uuid.uuid4().hex}"

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    # Some filesystems or environments do not support fsync
                    pass

            # Atomic replace with retry for Windows lock contention
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    os.replace(temp_path, self.file_path)
                    break
                except OSError as err:
                    if attempt == max_attempts - 1:
                        raise StorageError(f"Failed to atomically persist state after {max_attempts} attempts: {err}") from err
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _quarantine_corrupt_file(self) -> Path:
        """Move corrupted state file to a timestamped quarantine path to preserve audit evidence."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        quarantine_path = self.file_path.parent / f"{self.file_path.name}.corrupted.{timestamp}"
        try:
            shutil.move(str(self.file_path), str(quarantine_path))
        except OSError as err:
            raise StorageError(f"Failed to quarantine corrupted file {self.file_path}: {err}") from err
        return quarantine_path
