"""
Pharos Trend Watcher package.
"""

from trend.config import RuleConfig, TrendConfigurationError, TrendDirection
from trend.engine import (
    EngineError,
    IngestionResult,
    InvalidObservationError,
    OutOfOrderObservationError,
    TrendEngine,
)
from trend.inspector import TrendInspector
from trend.storage import (
    CorruptedStateError,
    DurableStorage,
    Observation,
    StorageError,
    TrendState,
    TriggerRecord,
    compute_observation_id,
    compute_trigger_id,
)

__all__ = [
    "TrendDirection",
    "TrendConfigurationError",
    "RuleConfig",
    "Observation",
    "TriggerRecord",
    "TrendState",
    "StorageError",
    "CorruptedStateError",
    "DurableStorage",
    "compute_observation_id",
    "compute_trigger_id",
    "EngineError",
    "OutOfOrderObservationError",
    "InvalidObservationError",
    "IngestionResult",
    "TrendEngine",
    "TrendInspector",
]
