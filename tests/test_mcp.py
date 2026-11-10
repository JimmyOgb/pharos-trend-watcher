"""
Unit and regression tests for official Pharos Chain MCP integration.

Validates that:
- Live MCP observations parse genuine gas price values, network names, and chain IDs.
- Malformed, negative, or missing values raise MCPValidationError.
- MCP JSON-RPC errors raise MCPResponseError.
- No fixture fallback occurs upon communication failure.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from trend.mcp import (
    DEFAULT_MCP_ENDPOINT,
    PHAROS_CHAIN_ID,
    PHAROS_NETWORK_NAME,
    MCPConnectionError,
    MCPError,
    MCPGasPriceReading,
    MCPResponseError,
    MCPValidationError,
    PharosMCPClient,
)


def _make_mock_response(body_text: str, session_id: str = "mock-session-123"):
    mock_resp = MagicMock()
    mock_resp.headers = {"mcp-session-id": session_id}
    mock_resp.read.return_value = body_text.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


def test_mcp_client_parses_valid_gwei_response():
    client = PharosMCPClient()

    init_sse = 'data: {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}}\n\n'
    tool_inner = {
        "gasPriceWei": "10000000000",
        "gasPriceGwei": "10",
        "gasPriceHex": "0x2540be400",
    }
    call_sse = f'data: {{"jsonrpc": "2.0", "id": 2, "result": {{"content": [{{"type": "text", "text": {json.dumps(json.dumps(tool_inner))}}}]}}}}\n\n'

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            _make_mock_response(init_sse),
            _make_mock_response(call_sse),
        ]
        reading = client.fetch_gas_price()

    assert isinstance(reading, MCPGasPriceReading)
    assert reading.value == 10.0
    assert reading.metric == "pharos_gas_price_gwei"
    assert reading.network == PHAROS_NETWORK_NAME
    assert reading.chain_id == PHAROS_CHAIN_ID
    assert reading.mcp_tool == "get_gas_price"
    assert reading.source == DEFAULT_MCP_ENDPOINT


def test_mcp_client_converts_wei_when_gwei_missing():
    client = PharosMCPClient()

    init_sse = 'data: {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}}\n\n'
    tool_inner = {
        "gasPriceWei": "15000000000",
    }
    call_sse = f'data: {{"jsonrpc": "2.0", "id": 2, "result": {{"content": [{{"type": "text", "text": {json.dumps(json.dumps(tool_inner))}}}]}}}}\n\n'

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            _make_mock_response(init_sse),
            _make_mock_response(call_sse),
        ]
        reading = client.fetch_gas_price()

    assert reading.value == 15.0


def test_mcp_client_rejects_negative_gas_price():
    client = PharosMCPClient()

    init_sse = 'data: {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}}\n\n'
    tool_inner = {"gasPriceGwei": "-5.0"}
    call_sse = f'data: {{"jsonrpc": "2.0", "id": 2, "result": {{"content": [{{"type": "text", "text": {json.dumps(json.dumps(tool_inner))}}}]}}}}\n\n'

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            _make_mock_response(init_sse),
            _make_mock_response(call_sse),
        ]
        with pytest.raises(MCPValidationError, match="Invalid non-positive gas price"):
            client.fetch_gas_price()


def test_mcp_client_rejects_rpc_error_response():
    client = PharosMCPClient()

    init_sse = 'data: {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}}\n\n'
    call_sse = 'data: {"jsonrpc": "2.0", "id": 2, "error": {"code": -32603, "message": "Internal error"}}\n\n'

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            _make_mock_response(init_sse),
            _make_mock_response(call_sse),
        ]
        with pytest.raises(MCPResponseError, match="returned error"):
            client.fetch_gas_price()


def test_mcp_client_no_silent_fallback_on_network_failure():
    client = PharosMCPClient()

    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        with pytest.raises(MCPConnectionError) as exc_info:
            client.fetch_gas_price()
        assert "Connection refused" in str(exc_info.value)


def test_live_pharos_mcp_connection():
    """Live integration test against official Pharos MCP server (https://mcp.pharos.xyz/mcp)."""
    client = PharosMCPClient()
    reading = client.fetch_gas_price()

    assert reading.metric == "pharos_gas_price_gwei"
    assert reading.value >= 0.0
    assert reading.chain_id == 1672
    assert reading.network == "Pharos"
    assert reading.mcp_tool == "get_gas_price"
    assert reading.source == "https://mcp.pharos.xyz/mcp"
