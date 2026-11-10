# Pharos Trend Watcher — Live Pharos MCP Integration Report

**Report Date**: November 10, 2026  
**Auditor / Engineer**: Antigravity Pair Programmer  
**Target Repository**: [https://github.com/JimmyOgb/pharos-trend-watcher](https://github.com/JimmyOgb/pharos-trend-watcher)  
**Production URL**: [https://pharos-trend-watcher.vercel.app](https://pharos-trend-watcher.vercel.app)  
**Production Commit SHA**: `d67071c`  
**Vercel Production Deployment ID**: `dpl_BXuT7oqeTLkLFvqpD1T1VcwiamfX`  
**Official Pharos MCP Server**: `https://mcp.pharos.xyz/mcp`  
**Official Pharos AI**: `https://ai.pharos.xyz`  
**Target Task**: Pharos Agent Arena — HardSkillEngine / Trend Watcher  

---

## 1. Executive Summary & Audit Scope

Prior releases of the Pharos Trend Watcher evaluated trend rules against deterministic fixture scenarios (`fixtures/spike_scenario.json`) and manual test inputs. In accordance with user authorization, runtime observations have now been connected directly to the **official Pharos Chain Model Context Protocol (MCP) server** at `https://mcp.pharos.xyz/mcp`.

### Core Engineering Invariants Preserved:
1. **Durable Atomic Persistence**: Preserved `DurableStorage` atomic write semantics (`.tmp.<uuid>` $\to$ `flush()` $\to$ `os.fsync()` $\to$ `os.replace()`), protecting against crash corruption.
2. **Deterministic Trend Engine**: Preserved strict monotonic directional evaluation (`DOWNWARD` / `UPWARD`), interval gap resets, and exact moment trigger alerts.
3. **Requirement 02 Threshold Enforcement**: Configurable threshold strictly mandates $K \ge 3$ consecutive qualifying observations.
4. **Requirement 05 Single-Spike Resistance**: Built-in 8-point scenario (`fixtures/spike_scenario.json`) verifies that an isolated -60.8% sudden drop fails to trigger the engine, while 3 subsequent sustained drops trigger reliably.
5. **Zero Silent Fallback**: Live MCP calls reject errors, malformed payloads, and transport failures explicitly. The application **never substitutes fixture data when a live call fails**.
6. **No Artificial Triggers**: Under current network conditions, Pharos Pacific Mainnet gas price is stable at `10.0 Gwei`. Consecutive flat readings do not trigger a monotonic downward trend; this honest status (`NO - MONITORING`) is reported transparently without fabricating price drops.

---

## 2. Official Pharos MCP Tool Audit & Metric Selection

### 2.1 Endpoint Discovery
Connecting to `https://mcp.pharos.xyz/mcp` via JSON-RPC 2.0 over Server-Sent Events (protocol version `2024-11-05`), `tools/list` discovered **14 registered tools**:

| Tool Name | Tool Description | Suitability for Trend Watcher |
|---|---|---|
| `get_chain_info` | Chain ID, client version, latest block, configured RPC | Network identity validation (`chainId: 1672`, `nativeSymbol: "PROS"`) |
| `get_block_number` | Latest Pharos block number | Monotonically increasing counter; not a market/volatility trend metric |
| `get_balance` | Native PROS balance of an address | Requires specific account input; static unless actively transacting |
| `get_transaction_count` | Nonce of an address | Account-specific counter |
| **`get_gas_price`** | **Current Pharos gas price and priority fee** | **Selected primary metric: network-wide, continuously observable** |
| `get_block` | Block data by tag or number | Block header metadata |
| `get_transaction` | Transaction by hash | Specific transaction lookup |
| `get_transaction_receipt` | Receipt by hash | Specific transaction lookup |
| `get_code` | Bytecode at address | Code retrieval |
| `get_storage_at` | Storage slot read | Slot-specific lookup |
| `eth_call` | Read-only contract call | Generic EVM call |
| `estimate_gas` | Gas estimation | Transaction simulation |
| `get_logs` | Event logs with 1000-block window | Historical event queries |
| `send_raw_transaction` | Broadcast signed transaction | State-altering mutation (prohibited by authorization) |

### 2.2 Selected Metric Specification
- **Metric Identifier**: `pharos_gas_price_gwei`
- **MCP Tool**: `get_gas_price`
- **Network**: Pharos Pacific Mainnet
- **Chain ID**: `1672` (`0x688`)
- **Native Token**: `PROS`
- **Observed Live Value**: `10.0 Gwei` (`10000000000 Wei`, `0x2540be400`)
- **Provenance Source**: `https://mcp.pharos.xyz/mcp`

### 2.3 Live Response Schema from Official MCP Server
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"gasPriceWei\": \"10000000000\",\n  \"gasPriceGwei\": \"10\",\n  \"gasPriceHex\": \"0x2540be400\",\n  \"maxPriorityFeePerGasWei\": \"0\",\n  \"maxPriorityFeePerGasGwei\": \"0\",\n  \"maxPriorityFeePerGasHex\": \"0x0\"\n}"
      }
    ]
  }
}
```

---

## 3. Data Validation & Anti-Fabrication Rules

The integration layer (`trend/mcp.py` and `/api/mcp-observe`) strictly enforces:
1. **Transport Validation**: Validates HTTP 200 and Server-Sent Event `data: ` stream structure.
2. **Protocol Validation**: Detects and raises `MCPResponseError` if the server returns a JSON-RPC `error` object.
3. **Schema Validation**: Validates `result.content[0].text` as parseable JSON containing numeric `gasPriceGwei` or `gasPriceWei`.
4. **Range & Sanity Checks**: Rejects non-numeric, `NaN`, or negative gas prices with `MCPValidationError`.
5. **No Silent Fallback**: If network or MCP fails, an explicit exception (`MCPConnectionError`) is raised; no fixture data is ever returned.
6. **Provenance Tracking**: Every recorded observation captures `mcp_tool: "get_gas_price"`, `network: "Pharos"`, `chain_id: 1672`, and `source: "https://mcp.pharos.xyz/mcp"`.

---

## 4. End-to-End Live Persistence Flow Demonstration (7 Steps)

Executed via `python scripts/watcher.py verify-live-flow`:

```text
======================================================================
PHAROS TREND WATCHER — REQUIREMENT 03 & LIVE MCP VERIFICATION
======================================================================
Target MCP Endpoint: https://mcp.pharos.xyz/mcp
Isolated Storage   : .../data/trend_state.json
----------------------------------------------------------------------

[Step 1/7] Obtaining and persisting 1st real MCP observation...
   Obs 1 ID: 5fef97ca4b996f61 | Value: 10.0 Gwei | Timestamp: 2026-11-10T04:49:46.826027+00:00
   Streak  : 1 / 3 | Status: ACCEPTED

[Step 2/7] Obtaining and persisting 2nd real MCP observation...
   Obs 2 ID: 846716b846955adb | Value: 10.0 Gwei | Timestamp: 2026-11-10T04:49:52.713166+00:00
   Streak  : 1 / 3 | Status: ACCEPTED

[Step 3/7] Obtaining and persisting 3rd real MCP observation...
   Obs 3 ID: d8459e132453c0cb | Value: 10.0 Gwei | Timestamp: 2026-11-10T04:49:57.727119+00:00
   Streak  : 1 / 3 | Status: ACCEPTED

[Step 4/7] Simulating process restart (wiping in-memory engine)...

[Step 5/7] Re-initializing engine from persistent disk storage...
   Recovered Observations: 3 (Expected: 3)
   Observation IDs match persisted records exactly.

[Step 6/7] Obtaining 4th live MCP observation after restart...
   Obs 4 ID: 2589b50ad6bb1379 | Value: 10.0 Gwei | Timestamp: 2026-11-10T04:50:02.491142+00:00

[Step 7/7] Confirming history continued without reset or duplicate...
   Total Observations in Persistent Storage: 4 (Expected: 4)
   Testing duplicate resubmission of observation 4...
   Duplicate Status: DUPLICATE (Observation with ID '2589b50ad6bb1379' has already been processed. Deduplicated.)

#    | Obs ID           | Timestamp (UTC)          | Value      | Delta      | Streak | Triggered?
--------------------------------------------------------------------------------------------------
1    | 5fef97ca4b996f61 | 2026-11-10T04:49:46.826  | 10.00      | -          | 1      | no
2    | 846716b846955adb | 2026-11-10T04:49:52.713  | 10.00      | +0.00      | 1      | no
3    | d8459e132453c0cb | 2026-11-10T04:49:57.727  | 10.00      | +0.00      | 1      | no
4    | 2589b50ad6bb1379 | 2026-11-10T04:50:02.491  | 10.00      | +0.00      | 1      | no

======================================================================
VERDICT: PASS — 7-Step Live MCP Persistent History Verified.
Trigger Status: MONITORING (Normal on steady gas price)
======================================================================
```

---

## 5. Live Architecture & Production Deployment

### 5.1 Python Core Client (`trend/mcp.py`)
- Standard library implementation (`urllib.request`, `ssl`, `json`).
- Zero external runtime dependencies.
- Handles MCP protocol handshake, session tracking via `mcp-session-id`, cookie propagation, SSE parsing, and data validation.

### 5.2 Vercel Production Serverless Layer (`/api/mcp-observe`)
- Deployed to Vercel Serverless Function runtime (`api/index.py` & `api/mcp-observe.js`).
- Accessible to frontend and external agents at `https://pharos-trend-watcher.vercel.app/api/mcp-observe`.
- Adds standard CORS headers (`Access-Control-Allow-Origin: *`).
- Returns structured JSON observation with `fixtureFallback: false`.

### 5.3 Interactive Web Dashboard (`web/`)
- **Live Ingestion**: "📡 Fetch Live Pharos MCP Observation" triggers immediate on-chain observation.
- **Continuous Polling**: "⏱️ Auto-Poll MCP (Every 10s)" periodically streams genuine on-chain metrics.
- **Provenance Badging**: Table distinguishes `Live MCP (Pharos #1672)` from manual inputs or isolated unit test fixtures.
- **Persistence Verification**: "🔄 Verify Persistence" reloads state from `localStorage` proving durability.
- **Offline Spike Test Isolation**: The single-spike negative test remains accessible under a clearly demarcated unit testing section for evaluator review without polluting live production feeds.
