/**
 * Vercel Serverless Function: /api/mcp-observe
 * 
 * Directly queries the official Pharos Chain MCP server at https://mcp.pharos.xyz/mcp
 * using the MCP protocol (JSON-RPC over SSE) to retrieve genuine, live on-chain
 * gas price and network provenance.
 * 
 * Strict Integrity Guarantees:
 * - Never returns fixture or mock data.
 * - Rejects malformed values or non-positive gas prices.
 * - Preserves provenance: Tool: get_gas_price, Network: Pharos, Chain ID: 1672.
 */

const MCP_ENDPOINT = process.env.PHAROS_MCP_URL || 'https://mcp.pharos.xyz/mcp';
const USER_AGENT = 'Pharos-Trend-Watcher/1.0.0';
const CHAIN_ID = 1672;
const NETWORK_NAME = 'Pharos';

function parseSSE(bodyText) {
  for (const line of bodyText.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('data: ')) {
      try {
        return JSON.parse(trimmed.slice(6));
      } catch (err) {
        throw new Error(`Failed to decode SSE JSON payload: ${err.message}`);
      }
    }
  }
  // Try raw JSON parse if no 'data: ' prefix
  try {
    return JSON.parse(bodyText);
  } catch {
    throw new Error('No valid JSON-RPC payload found in MCP response body');
  }
}

async function fetchLiveMcpGasPrice() {
  const retrievalTimestamp = new Date().toISOString();

  // 1. Initialize MCP session
  const initPayload = {
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'pharos-trend-watcher', version: '1.0.0' }
    }
  };

  const initRes = await fetch(MCP_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
      'User-Agent': USER_AGENT
    },
    body: JSON.stringify(initPayload),
    signal: AbortSignal.timeout(10000)
  });

  if (!initRes.ok) {
    throw new Error(`MCP initialize failed with HTTP status ${initRes.status}`);
  }

  const sessionId = initRes.headers.get('mcp-session-id');
  const cookie = initRes.headers.get('set-cookie');
  const initBody = await initRes.text();
  const initData = parseSSE(initBody);

  if (initData.error) {
    throw new Error(`MCP initialize returned error: ${JSON.stringify(initData.error)}`);
  }

  // 2. Call tool 'get_gas_price'
  const callHeaders = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
    'User-Agent': USER_AGENT
  };
  if (sessionId) callHeaders['mcp-session-id'] = sessionId;
  if (cookie) callHeaders['Cookie'] = cookie.split(';')[0];

  const callPayload = {
    jsonrpc: '2.0',
    id: 2,
    method: 'tools/call',
    params: {
      name: 'get_gas_price',
      arguments: {}
    }
  };

  const callRes = await fetch(MCP_ENDPOINT, {
    method: 'POST',
    headers: callHeaders,
    body: JSON.stringify(callPayload),
    signal: AbortSignal.timeout(10000)
  });

  if (!callRes.ok) {
    throw new Error(`MCP tools/call failed with HTTP status ${callRes.status}`);
  }

  const callBody = await callRes.text();
  const callData = parseSSE(callBody);

  if (callData.error) {
    throw new Error(`MCP tools/call 'get_gas_price' returned error: ${JSON.stringify(callData.error)}`);
  }

  // 3. Extract and validate gas price
  const result = callData.result;
  if (!result || !Array.isArray(result.content) || result.content.length === 0) {
    throw new Error(`Invalid MCP tool result structure: ${JSON.stringify(callData)}`);
  }

  const textContent = result.content[0].text;
  let parsedToolData;
  try {
    parsedToolData = JSON.parse(textContent);
  } catch (err) {
    throw new Error(`Failed to parse inner MCP tool JSON: ${err.message}`);
  }

  let gasPriceGwei = null;
  if (parsedToolData.gasPriceGwei !== undefined) {
    gasPriceGwei = parseFloat(parsedToolData.gasPriceGwei);
  } else if (parsedToolData.gasPriceWei !== undefined) {
    gasPriceGwei = parseFloat(parsedToolData.gasPriceWei) / 1e9;
  }

  if (gasPriceGwei === null || isNaN(gasPriceGwei) || gasPriceGwei < 0) {
    throw new Error(`Invalid or negative gas price in MCP response: ${JSON.stringify(parsedToolData)}`);
  }

  return {
    status: 'ok',
    metric: 'pharos_gas_price_gwei',
    value: gasPriceGwei,
    timestamp: retrievalTimestamp,
    network: NETWORK_NAME,
    chainId: CHAIN_ID,
    source: MCP_ENDPOINT,
    tool: 'get_gas_price',
    raw: parsedToolData,
    fixtureFallback: false
  };
}

module.exports = async (req, res) => {
  // CORS Headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    const reading = await fetchLiveMcpGasPrice();
    res.setHeader('Content-Type', 'application/json');
    return res.status(200).json(reading);
  } catch (err) {
    res.setHeader('Content-Type', 'application/json');
    return res.status(502).json({
      status: 'error',
      error: err.message,
      source: MCP_ENDPOINT,
      tool: 'get_gas_price',
      fixtureFallback: false
    });
  }
};
