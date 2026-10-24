"""
Tests for trend configuration and threshold validation rules.
Verifies Requirement 02: Configurable trend rule requiring at least 3 observations.
"""

import pytest

from trend.config import RuleConfig, TrendConfigurationError, TrendDirection


def test_valid_default_configuration():
    cfg = RuleConfig()
    assert cfg.metric == "pharos_gas_price_gwei"
    assert cfg.direction == TrendDirection.DOWNWARD
    assert cfg.threshold == 3
    assert cfg.strict_monotonic is True
    assert cfg.max_interval_seconds == 3600


def test_valid_custom_configuration():
    cfg = RuleConfig(
        metric="pharos_tvl_usd",
        direction=TrendDirection.UPWARD,
        threshold=5,
        strict_monotonic=False,
        max_interval_seconds=7200,
    )
    assert cfg.metric == "pharos_tvl_usd"
    assert cfg.direction == TrendDirection.UPWARD
    assert cfg.threshold == 5
    assert cfg.strict_monotonic is False
    assert cfg.max_interval_seconds == 7200


@pytest.mark.parametrize("invalid_threshold", [2, 1, 0, -1, -5])
def test_threshold_below_three_rejected(invalid_threshold):
    """Requirement 02: Must reject thresholds below 3."""
    with pytest.raises(TrendConfigurationError) as exc_info:
        RuleConfig(threshold=invalid_threshold)
    assert "at least 3 observations" in str(exc_info.value)
    assert f"({invalid_threshold})" in str(exc_info.value)


@pytest.mark.parametrize("invalid_type", ["three", 3.5, True, False, None, []])
def test_threshold_non_integer_rejected(invalid_type):
    with pytest.raises(TrendConfigurationError) as exc_info:
        RuleConfig(threshold=invalid_type)  # type: ignore
    assert "must be an integer" in str(exc_info.value)


@pytest.mark.parametrize("invalid_metric", ["", "   ", None])
def test_invalid_metric_name_rejected(invalid_metric):
    with pytest.raises(TrendConfigurationError):
        RuleConfig(metric=invalid_metric)  # type: ignore


def test_direction_string_coercion():
    cfg1 = RuleConfig(direction="downward")  # type: ignore
    assert cfg1.direction == TrendDirection.DOWNWARD
    cfg2 = RuleConfig(direction="UPWARD")  # type: ignore
    assert cfg2.direction == TrendDirection.UPWARD

    with pytest.raises(TrendConfigurationError):
        RuleConfig(direction="SIDEWAYS")  # type: ignore


def test_invalid_max_interval_rejected():
    with pytest.raises(TrendConfigurationError):
        RuleConfig(max_interval_seconds=-10)
    with pytest.raises(TrendConfigurationError):
        RuleConfig(max_interval_seconds=0)


def test_config_serialization_roundtrip():
    original = RuleConfig(metric="custom_gas", direction=TrendDirection.DOWNWARD, threshold=4)
    serialized = original.to_dict()
    reconstructed = RuleConfig.from_dict(serialized)
    assert original == reconstructed
