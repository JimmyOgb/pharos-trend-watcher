"""
Configuration and validation for Pharos Trend Watcher.

Defines the mathematical and operational semantics of trend detection:
- Enforces configurable threshold with strict minimum of 3 observations.
- Supports DOWNWARD and UPWARD trend directions.
- Defines behavior for monotonic progressions, flat readings, time deltas, and invalid values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TrendDirection(str, Enum):
    """Direction of the trend to monitor."""
    DOWNWARD = "DOWNWARD"
    UPWARD = "UPWARD"


class TrendConfigurationError(ValueError):
    """Raised when trend configuration fails validation rules."""
    pass


@dataclass(frozen=True)
class RuleConfig:
    """
    Validated configuration for trend evaluation.

    Attributes:
        metric: The name or identifier of the metric being monitored.
        direction: TrendDirection (DOWNWARD or UPWARD). Default: DOWNWARD.
        threshold: Minimum consecutive qualifying observations required to trigger.
                   MUST be >= 3. Default: 3.
        strict_monotonic: If True, unchanged values (V_i == V_{i-1}) break the streak.
                          If False, unchanged values sustain the current streak without incrementing it.
                          Default: True.
        max_interval_seconds: Maximum allowable time delta in seconds between consecutive
                              observations. If exceeded, the streak resets to avoid bridging
                              disconnected epochs. None disables interval checks. Default: 3600.
    """
    metric: str = "pharos_gas_price_gwei"
    direction: TrendDirection = TrendDirection.DOWNWARD
    threshold: int = 3
    strict_monotonic: bool = True
    max_interval_seconds: Optional[int] = 3600

    def __post_init__(self) -> None:
        """Validate all configuration attributes strictly upon initialization."""
        # Validate metric name
        if not self.metric or not isinstance(self.metric, str) or not self.metric.strip():
            raise TrendConfigurationError("Metric name must be a non-empty string.")

        # Validate threshold: MUST BE >= 3
        if not isinstance(self.threshold, int) or isinstance(self.threshold, bool):
            raise TrendConfigurationError(
                f"Threshold must be an integer, got {type(self.threshold).__name__}."
            )
        if self.threshold < 3:
            raise TrendConfigurationError(
                f"Invalid trend threshold ({self.threshold}). "
                "Official requirement 02 mandates at least 3 observations (threshold >= 3)."
            )

        # Validate direction
        if not isinstance(self.direction, TrendDirection):
            try:
                # Attempt conversion from string if passed as raw string
                object.__setattr__(self, "direction", TrendDirection(str(self.direction).upper()))
            except ValueError:
                raise TrendConfigurationError(
                    f"Invalid trend direction '{self.direction}'. Must be DOWNWARD or UPWARD."
                )

        # Validate max_interval_seconds
        if self.max_interval_seconds is not None:
            if not isinstance(self.max_interval_seconds, (int, float)) or self.max_interval_seconds <= 0:
                raise TrendConfigurationError(
                    f"max_interval_seconds must be a positive number, got {self.max_interval_seconds}."
                )

    def to_dict(self) -> dict:
        """Serialize configuration to a JSON-compatible dictionary."""
        return {
            "metric": self.metric,
            "direction": self.direction.value,
            "threshold": self.threshold,
            "strict_monotonic": self.strict_monotonic,
            "max_interval_seconds": self.max_interval_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RuleConfig:
        """Reconstruct RuleConfig from dictionary representation."""
        if not isinstance(data, dict):
            raise TrendConfigurationError("Configuration data must be a dictionary.")
        return cls(
            metric=data.get("metric", "pharos_gas_price_gwei"),
            direction=TrendDirection(data.get("direction", "DOWNWARD")),
            threshold=int(data.get("threshold", 3)),
            strict_monotonic=bool(data.get("strict_monotonic", True)),
            max_interval_seconds=data.get("max_interval_seconds", 3600),
        )
