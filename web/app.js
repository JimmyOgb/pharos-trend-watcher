/**
 * Pharos Trend Watcher — Client-Side Interactive Engine
 * 
 * Implements the verified Stage 2 trend evaluation semantics in client-side JavaScript
 * backed by persistent browser localStorage. Mirrors the deterministic Python core engine.
 */

const STORAGE_KEY = 'pharos_trend_watcher_state';

// 8-Point Official Single-Spike Verification Scenario
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
      version: '1.0.0',
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

  ingest(value, timestamp, customId) {
    const valFloat = parseFloat(value);
    if (isNaN(valFloat)) {
      throw new Error('Value must be a valid number.');
    }

    const isoTime = timestamp || new Date().toISOString();
    const obsId = customId || this.generateId('obs');

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
          if (this.state.config.strict_monotonic) resetReason = 'Flat reading';
        } else {
          streak = 1;
          resetReason = 'Upward reversal';
        }
      } else { // UPWARD
        if (delta > 0) {
          streak = prev.streak + 1;
        } else if (delta === 0) {
          streak = this.state.config.strict_monotonic ? 1 : prev.streak;
          if (this.state.config.strict_monotonic) resetReason = 'Flat reading';
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
      streak: streak
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
        rationale: rationale
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

  generateId(prefix) {
    return `${prefix}_${Math.random().toString(36).substring(2, 10)}`;
  }
}

// UI Controller
document.addEventListener('DOMContentLoaded', () => {
  const engine = new ClientTrendEngine();

  // Elements
  const statusStreak = document.getElementById('status-streak');
  const statusTriggered = document.getElementById('status-triggered');
  const statusCount = document.getElementById('status-count');
  const statusLatest = document.getElementById('status-latest');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');

  const inputThreshold = document.getElementById('cfg-threshold');
  const selectDirection = document.getElementById('cfg-direction');
  const checkMonotonic = document.getElementById('cfg-monotonic');
  const thresholdError = document.getElementById('threshold-error');

  const triggerCard = document.getElementById('trigger-card');
  const trigIdEl = document.getElementById('trig-id');
  const trigTimeEl = document.getElementById('trig-timestamp');
  const trigObsEl = document.getElementById('trig-obs-id');
  const trigValEl = document.getElementById('trig-val');
  const trigRationaleEl = document.getElementById('trig-rationale');

  const tableBody = document.getElementById('history-tbody');
  const emptyState = document.getElementById('empty-state');

  const manualValInput = document.getElementById('manual-value');
  const btnManualIngest = document.getElementById('btn-manual-ingest');
  const btnRunSpike = document.getElementById('btn-run-spike');
  const btnRunThreeDrop = document.getElementById('btn-run-threedrop');
  const btnSimulateReload = document.getElementById('btn-simulate-reload');
  const btnReset = document.getElementById('btn-reset');
  const actionBanner = document.getElementById('action-banner');

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
      statusLatest.textContent = `${latestObs.value.toFixed(2)} (${deltaStr})`;
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

        const tagHtml = isTriggerObs 
          ? '<span class="badge-tag trig">TRIGGER CONFIRMED</span>'
          : '<span class="badge-tag none">No</span>';

        tr.innerHTML = `
          <td>${idx + 1}</td>
          <td>${obs.id}</td>
          <td>${obs.timestamp.replace('T', ' ').substring(0, 19)}</td>
          <td><strong>${obs.value.toFixed(2)}</strong></td>
          <td>${deltaHtml}</td>
          <td>${obs.streak} / ${cfg.threshold}</td>
          <td>${tagHtml}</td>
        `;
        tableBody.appendChild(tr);
      });
    }
  }

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
      alert('Please enter a valid numeric value.');
      return;
    }
    const res = engine.ingest(val);
    manualValInput.value = '';
    render();
  });

  // Event: Run 3-Drop Trend
  btnRunThreeDrop.addEventListener('click', async () => {
    btnRunThreeDrop.disabled = true;
    engine.reset();
    render();

    const sequence = [100.0, 95.0, 90.0];
    for (let i = 0; i < sequence.length; i++) {
      engine.ingest(sequence[i], new Date(Date.now() + i * 60000).toISOString(), `demo_drop_0${i + 1}`);
      render();
      await new Promise(r => setTimeout(r, 400));
    }
    btnRunThreeDrop.disabled = false;
  });

  // Event: Run 8-Point Single Spike Scenario
  btnRunSpike.addEventListener('click', async () => {
    btnRunSpike.disabled = true;
    engine.reset();
    render();

    for (const item of SPIKE_SCENARIO) {
      engine.ingest(item.value, item.timestamp, item.id);
      render();
      await new Promise(r => setTimeout(r, 450));
    }
    btnRunSpike.disabled = false;
  });

  const toastBanner = document.getElementById('toast-banner');

  function showToast(message, duration = 3000) {
    if (!toastBanner) return;
    toastBanner.textContent = message;
    toastBanner.style.display = 'block';
    setTimeout(() => {
      toastBanner.style.display = 'none';
    }, duration);
  }

  // Event: Simulate Reload
  btnSimulateReload.addEventListener('click', () => {
    const currentCount = engine.state.observations.length;
    // Instantiate fresh engine from localStorage
    const reloaded = new ClientTrendEngine();
    engine.state = reloaded.state;
    render();
    showToast(`Durable State Reloaded from localStorage! Preserved ${currentCount} observations and ${engine.state.triggers.length} trigger events.`);
  });

  // Event: Reset
  btnReset.addEventListener('click', () => {
    engine.reset();
    render();
    showToast('Observation history and stored state cleared.');
  });

  // Initial render
  render();
});
