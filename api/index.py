"""
Vercel Serverless Function: /api/index.py

Directly connects to official Pharos Chain MCP endpoint (https://mcp.pharos.xyz/mcp)
to retrieve live on-chain gas price and network provenance.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Ensure trend module is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from trend.mcp import MCPError, PharosMCPClient


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            client = PharosMCPClient()
            reading = client.fetch_gas_price()
            resp = {
                "status": "ok",
                "metric": reading.metric,
                "value": reading.value,
                "timestamp": reading.timestamp,
                "network": reading.network,
                "chainId": reading.chain_id,
                "source": reading.source,
                "tool": reading.mcp_tool,
                "raw": reading.raw,
                "fixtureFallback": False,
            }
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
        except Exception as err:
            err_resp = {
                "status": "error",
                "error": str(err),
                "source": "https://mcp.pharos.xyz/mcp",
                "tool": "get_gas_price",
                "fixtureFallback": False,
            }
            self.wfile.write(json.dumps(err_resp, indent=2).encode("utf-8"))

    def do_POST(self):
        return self.do_GET()
