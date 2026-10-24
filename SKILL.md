---
name: pharos-trend-watcher
description: >
  Durable trend detection and monitoring skill for the Pharos blockchain and agentic economy.
  Persists state across runs and processes, acting only once a multi-observation trend condition
  is confirmed over multiple readings (e.g. gas price down 3 checks in a row, or TVL falling across consecutive windows),
  strictly resisting single noisy readings, isolated spikes, or crash artifacts.
version: 0.1.0
requires:
  anyBins:
  - python3
  - python
---

# Pharos Trend Watcher

A SkillEngine-compatible decision engine with durable memory that monitors time-series metrics across separate process executions and acts only once a trend is confirmed over multiple observations.

## Capability Index

| User Need | Capability | Detailed Instructions |
|---|---|---|
| Ingest a metric reading | `python scripts/watcher.py observe --value <FLOAT>` | Record reading with atomic persistence and streak evaluation |
| View active trend status | `python scripts/watcher.py status` | Inspect current active streak, threshold, and trigger confirmation |
| View chronological history | `python scripts/watcher.py history` | Audit stored observations, timestamps, deltas, and trigger records |
| Run single-spike negative test | `python scripts/watcher.py verify-spike` | Verify that an isolated -60% crash does NOT trigger the engine |
| Run end-to-end demo | `python scripts/watcher.py demo` | Execute complete 5-requirement demonstration sequence |
| Output JSON summary | `python scripts/watcher.py status --json` | Stream machine-parseable state and trigger records |

## Agent Guidelines Block

When an autonomous agent monitors volatile on-chain or market metrics (e.g., Pharos gas prices, liquidity vault TVL, or token prices), the agent MUST observe the following rules:

1. **Avoid Premature Action on Single Readings**:
   - Never initiate an automated transaction, swap, or rebalance based on an isolated extreme reading or price flash.
   - Run `python scripts/watcher.py observe --value <V>` at each monitoring check.
2. **Inspect Trigger Confirmation**:
   - Inspect the `.is_triggered` or CLI `Trend Triggered` status.
   - If `Trend Triggered: NO - MONITORING`: Do not fire state-altering transactions. Continue monitoring.
   - If `Trend Triggered: YES - CONFIRMED`: Verify the `Trigger Rationale` and `Trigger Moment` before executing automated workflows.
3. **Handle Process Restarts Safely**:
   - The engine automatically persists observation history and streak progress to durable disk storage. Agents restarting across cron cycles or worker instances automatically resume the existing streak without losing history.
4. **Idempotency Guarantee**:
   - Re-submitting the same observation (same ID or timestamp + value) is automatically deduplicated and will not create duplicate triggers or skew streak calculations.
