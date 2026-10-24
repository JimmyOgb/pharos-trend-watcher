#!/usr/bin/env python3
"""
Reviewer-facing Command-Line Interface for Pharos Trend Watcher.

Usage:
  python scripts/watcher.py status [--state-path PATH]
  python scripts/watcher.py history [--state-path PATH]
  python scripts/watcher.py observe --value <FLOAT> [--metric <NAME>] [--timestamp <ISO>] [--id <ID>] [--state-path PATH]
  python scripts/watcher.py verify-spike [--state-path PATH]
  python scripts/watcher.py demo [--state-path PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path so 'trend' package is resolvable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from trend.config import RuleConfig, TrendConfigurationError, TrendDirection
from trend.engine import (
    EngineError,
    InvalidObservationError,
    OutOfOrderObservationError,
    TrendEngine,
)
from trend.inspector import TrendInspector
from trend.storage import (
    CorruptedStateError,
    DurableStorage,
    StorageError,
)

DEFAULT_STATE_PATH = _PROJECT_ROOT / "data" / "trend_state.json"


def get_engine(state_path: Path | str, threshold: int = 3, direction: str = "DOWNWARD") -> TrendEngine:
    config = RuleConfig(
        metric="pharos_gas_price_gwei",
        direction=TrendDirection(direction.upper()),
        threshold=threshold,
        strict_monotonic=True,
    )
    storage = DurableStorage(state_path, default_config=config)
    return TrendEngine(storage=storage)


def cmd_status(args: argparse.Namespace) -> int:
    try:
        engine = get_engine(args.state_path)
        inspector = TrendInspector(engine)
        if args.json:
            print(json.dumps(inspector.get_summary(), indent=2))
        else:
            print(inspector.format_status())
        return 0
    except Exception as err:
        print(f"Error loading status: {err}", file=sys.stderr)
        return 1


def cmd_history(args: argparse.Namespace) -> int:
    try:
        engine = get_engine(args.state_path)
        inspector = TrendInspector(engine)
        if args.json:
            observations = [o.to_dict() for o in engine.observations]
            print(json.dumps(observations, indent=2))
        else:
            print(inspector.format_history_table())
            if engine.triggers:
                print("\nCONFIRMED TRIGGERS:")
                print(inspector.format_triggers_table())
        return 0
    except Exception as err:
        print(f"Error inspecting history: {err}", file=sys.stderr)
        return 1


def cmd_observe(args: argparse.Namespace) -> int:
    try:
        engine = get_engine(args.state_path)
        res = engine.ingest(
            value=args.value,
            timestamp=args.timestamp,
            observation_id=args.id,
        )
        print(f"Status      : {res.status}")
        print(f"Obs ID      : {res.observation.id if res.observation else 'N/A'}")
        print(f"Value       : {res.observation.value if res.observation else args.value}")
        print(f"Streak      : {res.streak} / {engine.config.threshold}")
        print(f"Triggered   : {'YES' if res.triggered else 'NO'}")
        print(f"Message     : {res.message}")
        if res.trigger_record:
            print(f"Trigger ID  : {res.trigger_record.trigger_id}")
            print(f"Rationale   : {res.trigger_record.rationale}")
        return 0
    except (InvalidObservationError, OutOfOrderObservationError, TrendConfigurationError) as err:
        print(f"Validation Error: {err}", file=sys.stderr)
        return 2
    except (StorageError, EngineError) as err:
        print(f"Engine/Storage Error: {err}", file=sys.stderr)
        return 1


def cmd_verify_spike(args: argparse.Namespace) -> int:
    """Execute the deterministic single-spike verification sequence."""
    print("=" * 70)
    print("PHAROS TREND WATCHER — REQUIREMENT 05 SINGLE-SPIKE VERIFICATION")
    print("=" * 70)
    fixture_path = _PROJECT_ROOT / "fixtures" / "spike_scenario.json"
    if not fixture_path.exists():
        print(f"Error: Fixture {fixture_path} not found.", file=sys.stderr)
        return 1

    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture = json.load(f)

    # Use a dedicated isolated test state file if not provided
    test_state_path = args.state_path or (_PROJECT_ROOT / "data" / "spike_test_state.json")
    if Path(test_state_path).exists():
        Path(test_state_path).unlink()

    engine = get_engine(test_state_path, threshold=fixture.get("threshold", 3))

    print(f"Loaded Scenario: {fixture.get('description')}")
    print(f"Configured Threshold: {engine.config.threshold} (Must require >= 3 observations)")
    print("-" * 70)

    header = f"{'Step':<5} | {'Obs ID':<14} | {'Val':<8} | {'Streak':<6} | {'Trig?':<6} | {'Audit Note'}"
    print(header)
    print("-" * 70)

    spike_passed = True
    for r in fixture["readings"]:
        res = engine.ingest(
            value=r["value"],
            timestamp=r["timestamp"],
            observation_id=r["id"],
        )
        trig_str = "YES" if res.triggered else "no"
        print(f"{r['step']:<5} | {r['id']:<14} | {r['value']:<8.2f} | {res.streak:<6} | {trig_str:<6} | {r['note']}")

        # Validate spike reading (Step 3) MUST NOT TRIGGER
        if r["step"] == 3 and res.triggered:
            print("FAILED: Single spike triggered trend prematurely!", file=sys.stderr)
            spike_passed = False

        # Validate step 7 MUST TRIGGER
        if r["step"] == 7 and not res.triggered:
            print("FAILED: Step 7 failed to trigger multi-observation trend!", file=sys.stderr)
            spike_passed = False

    print("-" * 70)
    if spike_passed:
        print("VERDICT: PASS — Single -60.8% spike resisted; 3 consecutive drops triggered.")
        return 0
    else:
        print("VERDICT: FAIL — Spike verification failed.", file=sys.stderr)
        return 1


def cmd_demo(args: argparse.Namespace) -> int:
    """Run an end-to-end interactive demonstration demonstrating all 5 requirements."""
    demo_state_path = args.state_path or (_PROJECT_ROOT / "data" / "demo_state.json")
    if Path(demo_state_path).exists():
        Path(demo_state_path).unlink()

    print("=" * 70)
    print("PHAROS TREND WATCHER — END-TO-END DEMO WALKTHROUGH")
    print("=" * 70)

    # 1. Initialize Engine (Req 01 & 02)
    print("[1/5] Initializing TrendEngine with threshold=3 (strict monotonic downward)...")
    engine = get_engine(demo_state_path, threshold=3)
    print(f"      Active Config: threshold={engine.config.threshold}, metric={engine.config.metric}")

    # 2. Ingest Baseline and Single Spike (Req 05)
    print("\n[2/5] Ingesting baseline (100.0) followed by a massive -60% crash (40.0)...")
    res1 = engine.ingest(100.0, "2026-10-24T12:00:00Z", "demo_obs_01")
    print(f"      Reading 1: 100.0 Gwei -> Streak: {res1.streak}, Triggered: {res1.triggered}")

    res2 = engine.ingest(40.0, "2026-10-24T12:01:00Z", "demo_obs_02")
    print(f"      Reading 2: 40.0 Gwei (Isolated Spike) -> Streak: {res2.streak}, Triggered: {res2.triggered}")
    assert not res2.triggered, "Spike must not trigger!"

    # 3. Simulate Process Restart and State Recovery (Req 01 & 03)
    print("\n[3/5] Simulating process termination and restart from durable disk storage...")
    del engine  # Simulate memory wipe
    restarted_engine = get_engine(demo_state_path, threshold=3)
    print(f"      Recovered observations from disk: {len(restarted_engine.observations)}")
    print(f"      Current active streak preserved : {restarted_engine.observations[-1].streak}")
    assert len(restarted_engine.observations) == 2, "Restart must preserve history!"

    # 4. Ingest Immediate Recovery & Subsequent 3-Drop Genuine Trend (Req 02, 04, 05)
    print("\n[4/5] Ingesting recovery (99.0) followed by 3 sustained downward readings...")
    restarted_engine.ingest(99.0, "2026-10-24T12:02:00Z", "demo_obs_03")  # resets downward streak
    restarted_engine.ingest(95.0, "2026-10-24T12:03:00Z", "demo_obs_04")  # drop 1 (streak=2)
    res_trig = restarted_engine.ingest(90.0, "2026-10-24T12:04:00Z", "demo_obs_05")  # drop 2 (streak=3 -> TRIGGER!)

    print(f"      Reading 5: 90.0 Gwei -> Streak: {res_trig.streak}, Triggered: {res_trig.triggered}")
    assert res_trig.triggered, "3 consecutive readings must trigger!"
    assert res_trig.trigger_record is not None, "Trigger record must be present when triggered"
    print(f"      Trigger ID: {res_trig.trigger_record.trigger_id}")
    print(f"      Exact Moment: {res_trig.trigger_record.timestamp}")

    # 5. Duplicate Detection (Req 03)
    print("\n[5/5] Re-submitting identical observation to verify duplicate detection...")
    dup_res = restarted_engine.ingest(90.0, "2026-10-24T12:04:00Z", "demo_obs_05")
    print(f"      Status: {dup_res.status} ({dup_res.message})")
    assert dup_res.status == "DUPLICATE", "Repeated observation must be detected as DUPLICATE!"

    print("\n" + "=" * 70)
    print("DEMO VERDICT: ALL 5 CRITERIA CONFIRMED ON DURABLE STORAGE.")
    print("=" * 70)
    return 0


def main() -> int:
    # Common parent parser for flags like --state-path
    state_parser = argparse.ArgumentParser(add_help=False)
    state_parser.add_argument(
        "--state-path",
        default=str(DEFAULT_STATE_PATH),
        help=f"Path to durable state JSON file (default: {DEFAULT_STATE_PATH})",
    )

    parser = argparse.ArgumentParser(
        description="Pharos Trend Watcher CLI — Multi-observation trend detection with durable memory.",
        parents=[state_parser],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: status
    p_status = subparsers.add_parser("status", parents=[state_parser], help="Show active configuration and current trend state")
    p_status.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # Subcommand: history
    p_history = subparsers.add_parser("history", parents=[state_parser], help="Show chronological observation and trigger history")
    p_history.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # Subcommand: observe
    p_observe = subparsers.add_parser("observe", parents=[state_parser], help="Ingest a new metric observation")
    p_observe.add_argument("--value", type=float, required=True, help="Numeric metric value")
    p_observe.add_argument("--metric", default="pharos_gas_price_gwei", help="Metric name")
    p_observe.add_argument("--timestamp", default=None, help="ISO-8601 timestamp (default: UTC now)")
    p_observe.add_argument("--id", default=None, help="Explicit unique observation ID")

    # Subcommand: verify-spike
    subparsers.add_parser("verify-spike", parents=[state_parser], help="Run the deterministic Requirement 05 single-spike test")

    # Subcommand: demo
    subparsers.add_parser("demo", parents=[state_parser], help="Run the end-to-end multi-requirement demonstration")

    parsed = parser.parse_args()

    if parsed.command == "status":
        return cmd_status(parsed)
    elif parsed.command == "history":
        return cmd_history(parsed)
    elif parsed.command == "observe":
        return cmd_observe(parsed)
    elif parsed.command == "verify-spike":
        return cmd_verify_spike(parsed)
    elif parsed.command == "demo":
        return cmd_demo(parsed)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
