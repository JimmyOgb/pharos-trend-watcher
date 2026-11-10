"""
Official Pharos Chain MCP Client for Pharos Trend Watcher.

Integrates with the official Pharos Chain MCP endpoint (https://mcp.pharos.xyz/mcp)
to retrieve genuine, live on-chain metrics (such as current gas price) via JSON-RPC
over SSE protocol.

Strict Integrity Rules:
- Never substitutes fixture data when a live call fails.
- Rejects malformed values, negative gas prices, or MCP error responses.
- Preserves full tool and network provenance (chain ID 1672, network Pharos).
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

DEFAULT_MCP_ENDPOINT = "https://mcp.pharos.xyz/mcp"
DEFAULT_USER_AGENT = "Pharos-Trend-Watcher/1.0.0"
PHAROS_CHAIN_ID = 1672
PHAROS_NETWORK_NAME = "Pharos"


class MCPError(Exception):
    """Base exception for Model Context Protocol client errors."""
    pass


class MCPConnectionError(MCPError):
    """Raised when unable to establish connection to the Pharos MCP server."""
    pass


class MCPResponseError(MCPError):
    """Raised when the Pharos MCP server returns an error or invalid JSON-RPC payload."""
    pass


class MCPValidationError(MCPError):
    """Raised when the MCP tool result contains malformed, non-numeric, or invalid data."""
    pass


@dataclass(frozen=True)
class MCPGasPriceReading:
    """A validated live metric observation retrieved directly from Pharos MCP."""
    metric: str
    value: float
    timestamp: str  # ISO-8601 UTC
    network: str
    chain_id: int
    source: str
    mcp_tool: str
    raw: Dict[str, Any]


class PharosMCPClient:
    """Client for querying the official Pharos MCP server."""

    def __init__(
        self,
        endpoint: str = DEFAULT_MCP_ENDPOINT,
        timeout: float = 12.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self.user_agent = user_agent
        self.ssl_context = ssl.create_default_context()

    def _parse_sse(self, sse_text: str) -> Dict[str, Any]:
        """Parse Server-Sent Events body for JSON-RPC data."""
        for line in sse_text.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except json.JSONDecodeError as err:
                    raise MCPResponseError(f"Failed to decode SSE JSON data: {err}") from err
        # Fallback: maybe raw JSON was returned directly
        try:
            return json.loads(sse_text)
        except json.JSONDecodeError:
            raise MCPResponseError("No valid 'data: ' line or JSON body found in MCP response")

    def fetch_gas_price(self) -> MCPGasPriceReading:
        """
        Query the official Pharos MCP tool 'get_gas_price' and return a validated reading.

        Returns:
            MCPGasPriceReading with genuine gas price in Gwei.

        Raises:
            MCPConnectionError: On network or HTTP transport failures.
            MCPResponseError: On JSON-RPC error responses.
            MCPValidationError: On malformed or non-numeric gas price data.
        """
        retrieval_timestamp = datetime.now(timezone.utc).isoformat()

        # Step 1: Initialize MCP session
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pharos-trend-watcher", "version": "1.0.0"},
            },
        }

        init_req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(init_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(init_req, timeout=self.timeout, context=self.ssl_context) as resp:
                session_id = resp.headers.get("mcp-session-id")
                cookie = resp.headers.get("Set-Cookie")
                init_body = resp.read().decode("utf-8")
        except Exception as err:
            raise MCPConnectionError(f"Failed to initialize MCP session at {self.endpoint}: {err}") from err

        init_data = self._parse_sse(init_body)
        if "error" in init_data:
            raise MCPResponseError(f"MCP initialize error: {init_data['error']}")

        # Step 2: Call get_gas_price tool
        call_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": self.user_agent,
        }
        if session_id:
            call_headers["mcp-session-id"] = session_id
        if cookie:
            call_headers["Cookie"] = cookie.split(";")[0]

        call_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_gas_price",
                "arguments": {},
            },
        }

        call_req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(call_payload).encode("utf-8"),
            headers=call_headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(call_req, timeout=self.timeout, context=self.ssl_context) as resp:
                call_body = resp.read().decode("utf-8")
        except Exception as err:
            raise MCPConnectionError(f"Failed to execute 'get_gas_price' tool call on {self.endpoint}: {err}") from err

        call_data = self._parse_sse(call_body)
        if "error" in call_data:
            raise MCPResponseError(f"MCP tools/call 'get_gas_price' returned error: {call_data['error']}")

        # Step 3: Validate tool execution output
        result = call_data.get("result")
        if not isinstance(result, dict):
            raise MCPValidationError(f"MCP response missing 'result' dictionary: {call_data}")

        content = result.get("content")
        if not isinstance(content, list) or len(content) == 0:
            raise MCPValidationError(f"MCP response 'result.content' must be non-empty list: {result}")

        text_content = content[0].get("text")
        if not isinstance(text_content, str):
            raise MCPValidationError(f"MCP 'result.content[0].text' missing or not string: {content[0]}")

        try:
            parsed_tool_data = json.loads(text_content)
        except json.JSONDecodeError as err:
            raise MCPValidationError(f"Failed to parse inner tool text payload as JSON: {err}") from err

        if not isinstance(parsed_tool_data, dict):
            raise MCPValidationError(f"Inner tool payload is not a JSON object: {parsed_tool_data}")

        # Extract and validate gasPriceGwei / gasPriceWei
        raw_gwei = parsed_tool_data.get("gasPriceGwei")
        raw_wei = parsed_tool_data.get("gasPriceWei")

        if raw_gwei is not None:
            try:
                gas_price_val = float(raw_gwei)
            except (ValueError, TypeError) as err:
                raise MCPValidationError(f"gasPriceGwei '{raw_gwei}' is not a valid float: {err}") from err
        elif raw_wei is not None:
            try:
                gas_price_val = float(raw_wei) / 1e9
            except (ValueError, TypeError) as err:
                raise MCPValidationError(f"gasPriceWei '{raw_wei}' is not a valid number: {err}") from err
        else:
            raise MCPValidationError(f"Tool response lacks both 'gasPriceGwei' and 'gasPriceWei': {parsed_tool_data}")

        if gas_price_val < 0 or not (gas_price_val == gas_price_val):  # checks NaN and negative
            raise MCPValidationError(f"Invalid non-positive gas price returned: {gas_price_val}")

        return MCPGasPriceReading(
            metric="pharos_gas_price_gwei",
            value=gas_price_val,
            timestamp=retrieval_timestamp,
            network=PHAROS_NETWORK_NAME,
            chain_id=PHAROS_CHAIN_ID,
            source=self.endpoint,
            mcp_tool="get_gas_price",
            raw=parsed_tool_data,
        )
