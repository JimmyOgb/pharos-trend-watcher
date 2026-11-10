/**
 * Pharos Trend Watcher — Client-Side Interactive Engine
 * 
 * Implements deterministic multi-observation trend evaluation semantics in client-side JavaScript
 * backed by persistent browser localStorage. Connects to official Pharos Chain MCP
 * endpoint (https://mcp.pharos.xyz/mcp) via /api/mcp-observe.
 * 
 * Strict Integrity Guarantees:
 * - Observes genuine live Pharos metrics with tool & network provenance.
 * - Enforces minimum 3-observation threshold before confirming any trend.
 * - Rejects single-spike noise.
 * - Never silently falls back to fixture files on live failure.
 */

const STORAGE_KEY = 'pharos_trend_watcher_state';

// 8-Point Offline Unit Test Scenario for Requirement 05 Verification
const SPIKE_SCENARIO = [
  { step: 1, id: 'obs_spike_01', timestamp: '2026-10-24T10:00:00Z', value: 100.0, note: 'Baseline established' },
  { step: 2, id: 'obs_spike_02', timestamp: '2026-10-24T10:01:00Z', value: 102.0, note: 'Slight upward noise; resets streak' },
  { step: 3, id: 'obs_spike_03', timestamp: '2026-10-24T10:02:00Z', value: 40.0,  note: 'EXTREME ISOLATED SPIKE (-60.8%); streak=2, MUST NOT TRIGGER' },
  { step: 4, id: 'obs_spike_04', timestamp: '2026-10-24T10:03:00Z', value: 99.0,  note: 'IMMEDIATE RECOVERY (+147.5%); resets streak, MUST NOT TRIGGER' },
  { step: 5, id: 'obs_spike_05', timestamp: '2026-10-24T10:04:00Z', value: 100.0, note: 'Normalized baseline reading' },
  { step: 6, id: 'obs_spike_06', timestamp: '2026-10-24T10:05:00Z', value: 94.0,  note: 'Qualifying downward drop 1 (streak=2/3)' },
  { step: 7, id: 'obs_spike_07', timestamp: '2026-10-24T10:06:00Z', value: 88.0,  note: 'Qualifying downward drop 2 (streak=3/3); REACHES THRESHOLD 3 -> TRIGGER CONFIRMED' },
  { step: 8, id: 'obs_spike_08', timestamp: '2026-10-24T10:07:00Z', value: 81.0,  note: 'Continued trend drop (streak=4/3); does not duplicate trigger' }
];

class ClientTrendEngine {
  constructor() {
    this.state = this.loadState();
  }

  loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && Array.isArray(parsed.observations)) {
          return parsed;
        }
      }
    } catch (e) {
      console.warn('Failed to load localStorage state; initializing fresh state.', e);
    }
    return this.getInitialState();
  }

  getInitialState() {
    return {
      version: '1.1.0',
      config: {
        metric: 'pharos_gas_price_gwei',
        direction: 'DOWNWARD',
        threshold: 3,
        strict_monotonic: true,
        max_interval_seconds: 3600
      },
      observations: [],
      triggers: []
    };
  }

  saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.state));
    } catch (e) {
      console.error('Failed to persist to localStorage', e);
    }
  }

  reset() {
    this.state = this.getInitialState();
    this.saveState();
  }

  updateConfig(threshold, direction, strictMonotonic) {
    if (threshold < 3) {
      throw new Error('Threshold must be at least 3 observations (Requirement 02).');
    }
    this.state.config.threshold = threshold;
    this.state.config.direction = direction;
    this.state.config.strict_monotonic = strictMonotonic;
    this.saveState();
  }

  ingest(value, timestamp, customId, provenanceInfo = null) {
    const valFloat = parseFloat(value);
    if (isNaN(valFloat)) {
      throw new Error('Value must be a valid number.');
    }

    const isoTime = timestamp || new Date().toISOString();
    const obsId = customId || this.generateDeterministicId(this.state.config.metric, isoTime, valFloat);

    // 1. Deduplication check
    const existing = this.state.observations.find(o => o.id === obsId);
    if (existing) {
      return {
        status: 'DUPLICATE',
        observation: existing,
        triggered: false,
        streak: existing.streak,
        message: `Observation '${obsId}' already processed. Deduplicated.`
      };
    }

    // 2. Compute streak & delta
    let streak = 1;
    let delta = null;
    let resetReason = null;

    if (this.state.observations.length > 0) {
      const prev = this.state.observations[this.state.observations.length - 1];
      delta = parseFloat((valFloat - prev.value).toFixed(4));

      // Interval check
      const prevDt = new Date(prev.timestamp).getTime();
      const currDt = new Date(isoTime).getTime();
      const elapsedSec = (currDt - prevDt) / 1000;

      if (this.state.config.max_interval_seconds && elapsedSec > this.state.config.max_interval_seconds) {
        streak = 1;
        resetReason = 'Interval exceeded';
      } else if (this.state.config.direction === 'DOWNWARD') {
        if (delta < 0) {
          streak = prev.streak + 1;
        } else if (delta === 0) {
          streak = this.state.config.strict_monotonic ? 1 : prev.streak;
          if (this.state.config.strict_monotonic) resetReason = 'Flat reading broke strictly monotonic downward streak';
        } else {
          streak = 1;
          resetReason = 'Upward reversal';
        }
      } else { // UPWARD
        if (delta > 0) {
          streak = prev.streak + 1;
        } else if (delta === 0) {
          streak = this.state.config.strict_monotonic ? 1 : prev.streak;
          if (this.state.config.strict_monotonic) resetReason = 'Flat reading broke strictly monotonic upward streak';
        } else {
          streak = 1;
          resetReason = 'Downward reversal';
        }
      }
    }

    const newObs = {
      id: obsId,
      timestamp: isoTime,
      metric: this.state.config.metric,
      value: valFloat,
      delta: delta,
      streak: streak,
      network: provenanceInfo?.network || (provenanceInfo?.tool ? 'Pharos' : 'Local'),
      chainId: provenanceInfo?.chainId || (provenanceInfo?.tool ? 1672 : null),
      source: provenanceInfo?.source || (provenanceInfo?.tool ? 'https://mcp.pharos.xyz/mcp' : 'manual'),
      tool: provenanceInfo?.tool || null,
      raw: provenanceInfo?.raw || null
    };

    this.state.observations.push(newObs);

    // 3. Evaluate Trigger Condition
    // Triggers at the EXACT moment streak reaches threshold (streak === threshold)
    let triggered = false;
    let triggerRecord = null;

    if (streak === this.state.config.threshold) {
      const windowSize = this.state.config.threshold;
      const qualifying = this.state.observations.slice(-windowSize);
      const qualIds = qualifying.map(o => o.id);
      const trigId = 'trig_' + Math.random().toString(16).substring(2, 10);

      const valuesStr = qualifying.map(o => o.value.toFixed(2)).join(' -> ');
      const rationale = `Confirmed ${this.state.config.direction.toLowerCase()} trend: ${windowSize} consecutive qualifying observations (${valuesStr}). Triggered by observation '${obsId}'.`;

      triggerRecord = {
        trigger_id: trigId,
        timestamp: isoTime,
        triggering_observation_id: obsId,
        triggering_value: valFloat,
        threshold: this.state.config.threshold,
        qualifying_window_ids: qualIds,
        rationale: rationale,
        network: newObs.network,
        chainId: newObs.chainId,
        tool: newObs.tool
      };

      this.state.triggers.push(triggerRecord);
      triggered = true;
    }

    this.saveState();

    return {
      status: 'ACCEPTED',
      observation: newObs,
      triggered: triggered,
      trigger_record: triggerRecord,
      streak: streak,
      reset_reason: resetReason
    };
  }

  generateDeterministicId(metric, timestamp, value) {
    let hash = 0;
    const str = `${metric}:${timestamp}:${value.toFixed(6)}`;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash |= 0;
    }
    const hex = Math.abs(hash).toString(16).padStart(8, '0');
    return `obs_${hex}`;
  }
}

// UI Controller
document.addEventListener('DOMContentLoaded', () => {
  const engine = new ClientTrendEngine();
  let pollIntervalId = null;

  // Status Elements
  const statusStreak = document.getElementById('status-streak');
  const statusTriggered = document.getElementById('status-triggered');
  const statusCount = document.getElementById('status-count');
  const statusLatest = document.getElementById('status-latest');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');
  const mcpPingStatus = document.getElementById('mcp-ping-status');

  // Form Elements
  const inputThreshold = document.getElementById('cfg-threshold');
  const selectDirection = document.getElementById('cfg-direction');
  const checkMonotonic = document.getElementById('cfg-monotonic');
  const thresholdError = document.getElementById('threshold-error');

  // Trigger Card Elements
  const triggerCard = document.getElementById('trigger-card');
  const trigIdEl = document.getElementById('trig-id');
  const trigTimeEl = document.getElementById('trig-timestamp');
  const trigObsEl = document.getElementById('trig-obs-id');
  const trigValEl = document.getElementById('trig-val');
  const trigRationaleEl = document.getElementById('trig-rationale');

  // History Table Elements
  const tableBody = document.getElementById('history-tbody');
  const emptyState = document.getElementById('empty-state');

  // Action Buttons
  const btnFetchMcp = document.getElementById('btn-fetch-mcp');
  const btnPollMcp = document.getElementById('btn-poll-mcp');
  const btnSimulateReload = document.getElementById('btn-simulate-reload');
  const btnReset = document.getElementById('btn-reset');
  const manualValInput = document.getElementById('manual-value');
  const btnManualIngest = document.getElementById('btn-manual-ingest');
  const btnRunSpike = document.getElementById('btn-run-spike');
  const btnRunThreeDrop = document.getElementById('btn-run-threedrop');

  const toastBanner = document.getElementById('toast-banner');

  function showToast(message, isError = false, duration = 3500) {
    if (!toastBanner) return;
    toastBanner.textContent = message;
    if (isError) {
      toastBanner.style.background = 'rgba(244, 63, 94, 0.2)';
      toastBanner.style.borderColor = '#f43f5e';
      toastBanner.style.color = '#fca5a5';
    } else {
      toastBanner.style.background = 'rgba(16, 185, 129, 0.2)';
      toastBanner.style.borderColor = '#10b981';
      toastBanner.style.color = '#6ee7b7';
    }
    toastBanner.style.display = 'block';
    setTimeout(() => {
      toastBanner.style.display = 'none';
    }, duration);
  }

  function render() {
    const state = engine.state;
    const cfg = state.config;
    const obsList = state.observations;
    const latestObs = obsList.length > 0 ? obsList[obsList.length - 1] : null;
    const latestTrig = state.triggers.length > 0 ? state.triggers[state.triggers.length - 1] : null;

    // Form inputs
    inputThreshold.value = cfg.threshold;
    selectDirection.value = cfg.direction;
    checkMonotonic.checked = cfg.strict_monotonic;

    // Status cards
    const currentStreak = latestObs ? latestObs.streak : 0;
    statusStreak.textContent = `${currentStreak} / ${cfg.threshold}`;
    statusCount.textContent = obsList.length;

    if (state.triggers.length > 0) {
      statusTriggered.textContent = 'TRIGGERED';
      statusTriggered.className = 'status-value confirmed';
    } else {
      statusTriggered.textContent = 'MONITORING';
      statusTriggered.className = 'status-value monitoring';
    }

    if (latestObs) {
      const deltaStr = latestObs.delta !== null ? (latestObs.delta >= 0 ? `+${latestObs.delta}` : `${latestObs.delta}`) : 'baseline';
      statusLatest.textContent = `${latestObs.value.toFixed(2)} Gwei (${deltaStr})`;
    } else {
      statusLatest.textContent = 'No data';
    }

    // Progress bar
    const pct = Math.min(100, Math.round((currentStreak / cfg.threshold) * 100));
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `${currentStreak} / ${cfg.threshold} observations (${pct}%)`;

    if (state.triggers.length > 0) {
      progressFill.classList.add('triggered');
    } else {
      progressFill.classList.remove('triggered');
    }

    // Trigger card
    if (latestTrig) {
      triggerCard.classList.add('active');
      trigIdEl.textContent = latestTrig.trigger_id;
      trigTimeEl.textContent = latestTrig.timestamp;
      trigObsEl.textContent = latestTrig.triggering_observation_id;
      trigValEl.textContent = `${latestTrig.triggering_value.toFixed(2)} Gwei`;
      trigRationaleEl.textContent = latestTrig.rationale;
    } else {
      triggerCard.classList.remove('active');
    }

    // History Table
    tableBody.innerHTML = '';
    if (obsList.length === 0) {
      emptyState.style.display = 'block';
    } else {
      emptyState.style.display = 'none';

      const triggeredObsIds = new Set(state.triggers.map(t => t.triggering_observation_id));

      obsList.forEach((obs, idx) => {
        const tr = document.createElement('tr');
        const isTriggerObs = triggeredObsIds.has(obs.id);
        if (isTriggerObs) tr.classList.add('trigger-row');

        let deltaHtml = '<span class="val-flat">-</span>';
        if (obs.delta !== null) {
          if (obs.delta < 0) {
            deltaHtml = `<span class="val-down">${obs.delta.toFixed(2)}</span>`;
          } else if (obs.delta > 0) {
            deltaHtml = `<span class="val-up">+${obs.delta.toFixed(2)}</span>`;
          } else {
            deltaHtml = `<span class="val-flat">0.00</span>`;
          }
        }

        // Provenance Tag
        let provHtml = '<span class="badge-tag manual">Manual</span>';
        if (obs.tool === 'get_gas_price') {
          provHtml = '<span class="badge-tag mcp">Live MCP (Pharos #1672)</span>';
        } else if (obs.source === 'test_fixture') {
          provHtml = '<span class="badge-tag" style="background:rgba(245,158,11,0.15); color:#f59e0b; border:1px solid rgba(245,158,11,0.3);">Fixture</span>';
        }

        const tagHtml = isTriggerObs 
          ? '<span class="badge-tag trig">TRIGGER CONFIRMED</span>'
          : '<span class="badge-tag none">No</span>';

        tr.innerHTML = `
          <td>${idx + 1}</td>
          <td><code style="font-size:11px;">${obs.id}</code></td>
          <td>${obs.timestamp.replace('T', ' ').substring(0, 19)}</td>
          <td>${provHtml}</td>
          <td><strong>${obs.value.toFixed(2)}</strong></td>
          <td>${deltaHtml}</td>
          <td>${obs.streak} / ${cfg.threshold}</td>
          <td>${tagHtml}</td>
        `;
        tableBody.appendChild(tr);
      });
    }
  }

  // Live MCP Fetch Function
  async function fetchLiveMcpObservation(silent = false) {
    if (btnFetchMcp) btnFetchMcp.disabled = true;
    if (mcpPingStatus) {
      mcpPingStatus.textContent = 'Querying MCP...';
      mcpPingStatus.className = 'badge hard';
    }

    try {
      const resp = await fetch('/api/mcp-observe');
      if (!resp.ok) {
        throw new Error(`MCP API returned HTTP status ${resp.status}`);
      }
      const data = await resp.json();

      if (data.status !== 'ok') {
        throw new Error(data.error || 'Unknown MCP error response');
      }

      // Ingest live observation
      const res = engine.ingest(
        data.value,
        data.timestamp,
        null,
        {
          network: data.network,
          chainId: data.chainId,
          source: data.source,
          tool: data.tool,
          raw: data.raw
        }
      );

      render();

      if (mcpPingStatus) {
        mcpPingStatus.textContent = 'Connected (200 OK)';
        mcpPingStatus.className = 'badge ready';
      }

      if (!silent) {
        if (res.status === 'DUPLICATE') {
          showToast(`Live observation from MCP ${data.tool}: ${data.value} Gwei (Deduplicated)`);
        } else {
          showToast(`Recorded genuine MCP observation: ${data.value} Gwei (Tool: ${data.tool}, Network: ${data.network})`);
        }
      }
    } catch (err) {
      console.error('Failed to query Pharos MCP:', err);
      if (mcpPingStatus) {
        mcpPingStatus.textContent = 'Error';
        mcpPingStatus.className = 'badge danger';
      }
      showToast(`MCP Fetch Error: ${err.message}. Never falling back to fixtures.`, true);
    } finally {
      if (btnFetchMcp) btnFetchMcp.disabled = false;
    }
  }

  // Event: Fetch Live Pharos MCP Observation
  btnFetchMcp.addEventListener('click', () => {
    fetchLiveMcpObservation();
  });

  // Event: Auto-Poll MCP Toggle
  btnPollMcp.addEventListener('click', () => {
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
      btnPollMcp.textContent = '⏱️ Auto-Poll MCP (Every 10s): OFF';
      btnPollMcp.classList.remove('btn-live', 'polling');
      showToast('Live MCP polling stopped.');
    } else {
      fetchLiveMcpObservation(); // immediate first fetch
      pollIntervalId = setInterval(() => {
        fetchLiveMcpObservation(true);
      }, 10000);
      btnPollMcp.textContent = '⏱️ Auto-Poll MCP (Every 10s): ON';
      btnPollMcp.classList.add('btn-live', 'polling');
      showToast('Live MCP polling active (every 10 seconds).');
    }
  });

  // Event: Configuration Update
  function handleConfigChange() {
    const val = parseInt(inputThreshold.value, 10);
    if (isNaN(val) || val < 3) {
      thresholdError.style.display = 'block';
      return;
    }
    thresholdError.style.display = 'none';
    engine.updateConfig(val, selectDirection.value, checkMonotonic.checked);
    render();
  }

  inputThreshold.addEventListener('change', handleConfigChange);
  selectDirection.addEventListener('change', handleConfigChange);
  checkMonotonic.addEventListener('change', handleConfigChange);

  // Event: Manual Ingest
  btnManualIngest.addEventListener('click', () => {
    const val = parseFloat(manualValInput.value);
    if (isNaN(val)) {
      showToast('Please enter a valid numeric value.', true);
      return;
    }
    const res = engine.ingest(val, null, null, { source: 'manual' });
    manualValInput.value = '';
    render();
    showToast(`Manual reading ${val} Gwei ingested.`);
  });

  // Event: Evaluate 3-Drop Test Sequence (Offline fixture)
  btnRunThreeDrop.addEventListener('click', async () => {
    btnRunThreeDrop.disabled = true;
    engine.reset();
    render();

    const sequence = [100.0, 95.0, 90.0];
    for (let i = 0; i < sequence.length; i++) {
      engine.ingest(
        sequence[i],
        new Date(Date.now() + i * 60000).toISOString(),
        `seq_drop_0${i + 1}`,
        { source: 'test_fixture', tool: 'three_drop_test' }
      );
      render();
      await new Promise(r => setTimeout(r, 400));
    }
    btnRunThreeDrop.disabled = false;
  });

  // Event: Run Spike Negative Test (Offline fixture)
  btnRunSpike.addEventListener('click', async () => {
    btnRunSpike.disabled = true;
    engine.reset();
    render();

    for (const item of SPIKE_SCENARIO) {
      engine.ingest(
        item.value,
        item.timestamp,
        item.id,
        { source: 'test_fixture', tool: 'spike_scenario.json' }
      );
      render();
      await new Promise(r => setTimeout(r, 450));
    }
    btnRunSpike.disabled = false;
  });

  // Event: Verify Persistence (Reload from localStorage)
  btnSimulateReload.addEventListener('click', () => {
    const currentCount = engine.state.observations.length;
    const reloaded = new ClientTrendEngine();
    engine.state = reloaded.state;
    render();
    showToast(`Durable state verified from localStorage: ${currentCount} observations and ${engine.state.triggers.length} trigger events preserved.`);
  });

  // Event: Clear Observation History
  btnReset.addEventListener('click', () => {
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
      btnPollMcp.textContent = '⏱️ Auto-Poll MCP (Every 10s): OFF';
      btnPollMcp.classList.remove('btn-live', 'polling');
    }
    engine.reset();
    render();
    showToast('Observation history and active streak cleared.');
  });

  // Initial render
  render();
});
