// Shared live state: one WebSocket for the whole app, plus periodic /status.
// Views subscribe with store.on(event, fn) and MUST call the returned
// unsubscribe function in their unmount().
//
// Events:
//   'telemetry'  -> TELEMETRY payload {rta, meters, feedback_alerts, read_only_mode,
//                    stop_auto, safety_mode, soundcheck, timestamp}  (~10 Hz)
//   'connection' -> {ws: 'open'|'closed'}
//   'status'     -> /api/v1/status payload (every 5 s, and after store.refreshStatus())

import { api } from './api.js';

const listeners = new Map();
let ws = null;
let reconnectTimer = null;
let statusTimer = null;

export const store = {
  telemetry: null,
  status: null,
  wsState: 'closed',

  on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
    return () => listeners.get(event)?.delete(fn);
  },

  emit(event, payload) {
    listeners.get(event)?.forEach(fn => {
      try { fn(payload); } catch (e) { console.error(`[store] ${event} listener failed`, e); }
    });
  },

  async refreshStatus() {
    try {
      this.status = await api.get('/api/v1/status');
      this.emit('status', this.status);
    } catch (e) {
      this.status = null;
      this.emit('status', null);
    }
    return this.status;
  },

  start() {
    connect();
    this.refreshStatus();
    clearInterval(statusTimer);
    statusTimer = setInterval(() => {
      if (!document.hidden) this.refreshStatus();
    }, 5000);
  },
};

function connect() {
  clearTimeout(reconnectTimer);
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  try {
    ws = new WebSocket(`${proto}//${location.host}/ws/live`);
  } catch {
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    store.wsState = 'open';
    store.emit('connection', { ws: 'open' });
  };
  ws.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    if (data && data.type === 'TELEMETRY') {
      store.telemetry = data;
      store.emit('telemetry', data);
    }
  };
  ws.onclose = () => {
    store.wsState = 'closed';
    store.emit('connection', { ws: 'closed' });
    scheduleReconnect();
  };
  ws.onerror = () => { try { ws.close(); } catch { /* already closed */ } };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 2000);
}
