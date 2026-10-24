"""
History and trigger inspection formatting for Pharos Trend Watcher.

Provides transparent formatting of chronological observations, active rules,
current streak progress, and exact trigger moments for reviewers and agents.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from trend.engine import TrendEngine
from trend.storage import Observation, TriggerRecord


class TrendInspector:
    """Inspector for examining stored observation history and trigger evidence."""

    def __init__(self, engine: TrendEngine):
        self.engine = engine

    def get_summary(self) -> Dict[str, Any]:
        """Generate a structured summary dictionary of engine state."""
        state = self.engine.state
        latest_obs = state.observations[-1] if state.observations else None
        latest_trig = state.triggers[-1] if state.triggers else None

        return {
            "version": state.version,
            "rule_config": state.rule_config.to_dict(),
            "total_observations": len(state.observations),
            "total_triggers": len(state.triggers),
            "current_streak": latest_obs.streak if latest_obs else 0,
            "threshold": state.rule_config.threshold,
            "is_triggered": len(state.triggers) > 0,
            "latest_observation": latest_obs.to_dict() if latest_obs else None,
            "latest_trigger": latest_trig.to_dict() if latest_trig else None,
        }

    def format_status(self) -> str:
        """Format an executive status overview suitable for CLI and logging."""
        cfg = self.engine.config
        state = self.engine.state
        latest_obs = state.observations[-1] if state.observations else None
        latest_trig = state.triggers[-1] if state.triggers else None

        lines = [
            "=" * 60,
            "PHAROS TREND WATCHER — STATUS REPORT",
            "=" * 60,
            f"Metric Name          : {cfg.metric}",
            f"Trend Direction      : {cfg.direction.value}",
            f"Configured Threshold : {cfg.threshold} qualifying observations",
            f"Strict Monotonic     : {cfg.strict_monotonic}",
            f"Max Interval Limit   : {cfg.max_interval_seconds}s",
            "-" * 60,
            f"Total Observations   : {len(state.observations)}",
            f"Current Active Streak: {latest_obs.streak if latest_obs else 0} / {cfg.threshold}",
        ]

        if latest_obs:
            delta_str = f"{latest_obs.delta:+.4f}" if latest_obs.delta is not None else "N/A (baseline)"
            lines.extend([
                f"Latest Reading Value : {latest_obs.value:.4f}",
                f"Latest Reading Delta : {delta_str}",
                f"Latest Timestamp     : {latest_obs.timestamp}",
                f"Latest Obs ID        : {latest_obs.id}",
            ])

        lines.append("-" * 60)
        lines.append(f"Trend Triggered      : {'YES - CONFIRMED' if state.triggers else 'NO - MONITORING'}")
        lines.append(f"Total Trigger Events : {len(state.triggers)}")

        if latest_trig:
            lines.extend([
                f"Latest Trigger Moment: {latest_trig.timestamp}",
                f"Triggering Obs ID    : {latest_trig.triggering_observation_id}",
                f"Triggering Value     : {latest_trig.triggering_value:.4f}",
                f"Trigger Rationale    : {latest_trig.rationale}",
            ])
        lines.append("=" * 60)
        return "\n".join(lines)

    def format_history_table(self) -> str:
        """Format observations in a chronological ASCII table."""
        observations = self.engine.observations
        if not observations:
            return "No observations recorded in durable storage."

        # Map qualifying trigger observation IDs
        triggered_obs_ids = set()
        for trig in self.engine.triggers:
            triggered_obs_ids.add(trig.triggering_observation_id)

        header = (
            f"{'#':<4} | {'Obs ID':<16} | {'Timestamp (UTC)':<24} | "
            f"{'Value':<10} | {'Delta':<10} | {'Streak':<6} | {'Triggered?'}"
        )
        separator = "-" * len(header)
        rows = [header, separator]

        for idx, obs in enumerate(observations, start=1):
            delta_str = f"{obs.delta:+.2f}" if obs.delta is not None else "-"
            is_trig = "YES [CONFIRMED]" if obs.id in triggered_obs_ids else "no"
            rows.append(
                f"{idx:<4} | {obs.id:<16} | {obs.timestamp[:23]:<24} | "
                f"{obs.value:<10.2f} | {delta_str:<10} | {obs.streak:<6} | {is_trig}"
            )

        return "\n".join(rows)

    def format_triggers_table(self) -> str:
        """Format trigger event log into an ASCII table."""
        triggers = self.engine.triggers
        if not triggers:
            return "No trigger events recorded."

        lines = [
            f"{'Trigger ID':<18} | {'Timestamp (UTC)':<24} | {'Trigger Obs ID':<16} | {'Val':<8} | {'Threshold':<9} | {'Rationale'}",
            "-" * 100,
        ]
        for t in triggers:
            lines.append(
                f"{t.trigger_id:<18} | {t.timestamp[:23]:<24} | {t.triggering_observation_id:<16} | {t.triggering_value:<8.2f} | {t.threshold:<9} | {t.rationale}"
            )
        return "\n".join(lines)
