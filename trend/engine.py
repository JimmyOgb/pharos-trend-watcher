"""
Deterministic trend evaluation engine for Pharos Trend Watcher.

Translates observations into verified multi-observation trends, enforces
strict threshold and monotonicity rules, resists single-spike noise,
and ensures idempotent ingestion and trigger persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from trend.config import RuleConfig, TrendDirection
from trend.storage import (
    DurableStorage,
    Observation,
    TrendState,
    TriggerRecord,
    compute_observation_id,
    compute_trigger_id,
)


class EngineError(Exception):
    """Base exception for Trend Engine errors."""
    pass


class OutOfOrderObservationError(EngineError):
    """Raised when an incoming observation timestamp precedes the latest recorded observation."""
    pass


class InvalidObservationError(EngineError):
    """Raised when observation value or format is invalid."""
    pass


@dataclass(frozen=True)
class IngestionResult:
    """The result of ingesting an observation into the engine."""
    status: str  # "ACCEPTED", "DUPLICATE", "REJECTED"
    observation: Optional[Observation]
    triggered: bool
    trigger_record: Optional[TriggerRecord]
    streak: int
    message: str


class TrendEngine:
    """
    Core deterministic trend engine.

    Responsibilities:
    - Enforces configurable threshold (minimum 3 observations).
    - Tracks consecutive directional streaks (DOWNWARD or UPWARD).
    - Ignores isolated spikes by requiring sustained qualifying readings.
    - Idempotently rejects duplicate observations.
    - Idempotently records trigger events without duplicates upon restarts or replays.
    - Persists state atomically through DurableStorage.
    """

    def __init__(self, storage: DurableStorage, config: Optional[RuleConfig] = None):
        self.storage = storage
        self.state: TrendState = self.storage.load()
        if config is not None:
            # Override or update configuration if explicitly supplied
            self.state.rule_config = config
            self.storage.save(self.state)

    @property
    def config(self) -> RuleConfig:
        return self.state.rule_config

    @property
    def observations(self) -> List[Observation]:
        return self.state.observations

    @property
    def triggers(self) -> List[TriggerRecord]:
        return self.state.triggers

    def ingest(
        self,
        value: float,
        timestamp: Optional[datetime | str] = None,
        observation_id: Optional[str] = None,
    ) -> IngestionResult:
        """
        Ingest a new numeric metric observation.

        Args:
            value: Float metric reading (e.g. gas price in Gwei, TVL in USD).
            timestamp: ISO datetime string or datetime object. Defaults to UTC now.
            observation_id: Optional explicit unique identifier. If omitted, computed deterministically.

        Returns:
            IngestionResult indicating whether the observation was ACCEPTED or DUPLICATE,
            current streak, and whether a trend trigger was confirmed.
        """
        # Validate value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InvalidObservationError(f"Observation value must be a number, got {type(value).__name__}.")
        value_float = float(value)

        # Standardize timestamp
        iso_timestamp = self._normalize_timestamp(timestamp)
        dt_current = datetime.fromisoformat(iso_timestamp)

        # Determine observation ID
        obs_id = observation_id or compute_observation_id(
            self.config.metric, iso_timestamp, value_float
        )

        # 1. Duplicate Detection Check
        existing = next((o for o in self.state.observations if o.id == obs_id), None)
        if existing is not None:
            # Recheck if trigger is already active
            last_trigger = self.state.triggers[-1] if self.state.triggers else None
            return IngestionResult(
                status="DUPLICATE",
                observation=existing,
                triggered=False,
                trigger_record=last_trigger,
                streak=existing.streak,
                message=f"Observation with ID '{obs_id}' has already been processed. Deduplicated.",
            )

        # 2. Chronological Ordering Check
        if self.state.observations:
            last_obs = self.state.observations[-1]
            dt_last = datetime.fromisoformat(last_obs.timestamp)
            if dt_current < dt_last:
                raise OutOfOrderObservationError(
                    f"Observation timestamp ({iso_timestamp}) is earlier than "
                    f"latest recorded observation ({last_obs.timestamp}). Retroactive observations rejected."
                )

        # 3. Calculate Streak and Delta
        streak, delta, reset_reason = self._compute_streak_and_delta(value_float, dt_current)

        new_obs = Observation(
            id=obs_id,
            timestamp=iso_timestamp,
            metric=self.config.metric,
            value=value_float,
            delta=delta,
            streak=streak,
        )

        self.state.observations.append(new_obs)

        # 4. Evaluate Trigger Condition
        triggered, trigger_record = self._evaluate_trigger(new_obs)
        if trigger_record:
            self.state.triggers.append(trigger_record)

        # 5. Persist State Atomically
        self.storage.save(self.state)

        msg = "Observation accepted."
        if reset_reason:
            msg += f" Streak reset ({reset_reason})."
        if triggered:
            msg += f" Trend condition met (threshold={self.config.threshold}). Trigger confirmed."

        return IngestionResult(
            status="ACCEPTED",
            observation=new_obs,
            triggered=triggered,
            trigger_record=trigger_record,
            streak=streak,
            message=msg,
        )

    def _compute_streak_and_delta(
        self, value: float, current_dt: datetime
    ) -> Tuple[int, Optional[float], Optional[str]]:
        """Calculate the new streak and delta relative to the latest observation."""
        if not self.state.observations:
            return 1, None, None

        prev_obs = self.state.observations[-1]
        prev_dt = datetime.fromisoformat(prev_obs.timestamp)
        delta = round(value - prev_obs.value, 8)

        # Check for excessive time interval
        if self.config.max_interval_seconds is not None:
            elapsed_seconds = (current_dt - prev_dt).total_seconds()
            if elapsed_seconds > self.config.max_interval_seconds:
                return (
                    1,
                    delta,
                    f"interval {elapsed_seconds}s exceeded max allowable {self.config.max_interval_seconds}s",
                )

        # Monotonicity evaluation
        if self.config.direction == TrendDirection.DOWNWARD:
            if delta < 0:
                # Value decreased: streak increments
                return prev_obs.streak + 1, delta, None
            elif delta == 0:
                # Flat reading: breaks strictly monotonic trend
                if self.config.strict_monotonic:
                    return 1, delta, "flat reading broke strictly monotonic downward streak"
                else:
                    return prev_obs.streak, delta, None
            else:
                # Upward reversal: resets streak
                return 1, delta, f"upward movement (+{delta}) broke downward streak"
        else:  # UPWARD
            if delta > 0:
                # Value increased: streak increments
                return prev_obs.streak + 1, delta, None
            elif delta == 0:
                if self.config.strict_monotonic:
                    return 1, delta, "flat reading broke strictly monotonic upward streak"
                else:
                    return prev_obs.streak, delta, None
            else:
                # Downward reversal: resets streak
                return 1, delta, f"downward movement ({delta}) broke upward streak"

    def _evaluate_trigger(self, current_obs: Observation) -> Tuple[bool, Optional[TriggerRecord]]:
        """
        Evaluate if the current observation satisfies the trend threshold.
        Triggers at the EXACT moment the streak first reaches threshold (streak == threshold).
        Subsequent observations in an unbroken streak continue the confirmed trend but do not
        re-trigger new events, preserving the exact trigger moment (Requirement 04).
        """
        if current_obs.streak < self.config.threshold:
            return False, None

        # Extract qualifying observation window (the exact threshold observations leading up to this moment)
        window_size = self.config.threshold
        qualifying_window = self.state.observations[-window_size:]
        qualifying_ids = [o.id for o in qualifying_window]
        trig_id = compute_trigger_id(qualifying_ids)

        # Check trigger idempotency: if already recorded for this window, do not duplicate
        already_exists = any(t.trigger_id == trig_id for t in self.state.triggers)
        if already_exists:
            return False, None

        # Only trigger at the exact moment the threshold is first reached
        # If streak > threshold, the trend was already confirmed at streak == threshold
        if current_obs.streak > self.config.threshold:
            return False, None

        # Build human-readable rationale
        values_str = " -> ".join(f"{o.value:.2f}" for o in qualifying_window)
        rationale = (
            f"Confirmed {self.config.direction.value.lower()} trend: "
            f"{window_size} consecutive qualifying observations ({values_str}). "
            f"Triggered by observation '{current_obs.id}'."
        )

        record = TriggerRecord(
            trigger_id=trig_id,
            timestamp=current_obs.timestamp,
            triggering_observation_id=current_obs.id,
            triggering_value=current_obs.value,
            threshold=self.config.threshold,
            qualifying_window_ids=qualifying_ids,
            rationale=rationale,
        )
        return True, record

    @staticmethod
    def _normalize_timestamp(ts: Optional[datetime | str]) -> str:
        """Convert timestamp input into standardized ISO-8601 UTC string."""
        if ts is None:
            return datetime.now(timezone.utc).isoformat()
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.isoformat()
        if isinstance(ts, str):
            # Validate ISO format parsing
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        raise InvalidObservationError(f"Unsupported timestamp format: {ts}")
