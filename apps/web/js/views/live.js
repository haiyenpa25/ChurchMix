// Bàn trộn trực tiếp — X32-Edit style mixer page.
//
// Layout: segment quick bar → feedback focus panel (only while something howls)
// → 32 channel strips in two layers (1–16, 17–32) → selected-channel detail with a
// large EQ/RTA chart, band table, routing, mute and the EQ / gain / bleed tools.
//
// Performance (this runs during services): one shared WebSocket via store, every
// canvas is drawn at most once per animation frame with the latest telemetry,
// nothing is drawn while the tab is hidden, strip meters move via transform only,
// EQ thumbnails redraw only when that channel's EQ changes.
//
// Safety: nothing here writes to the mixer without an explicit confirm dialog.
// Generating a notch / EQ / trim / expander proposal is read-only; applying goes
// through POST /api/v1/proposals/apply (server Safety Gate, readback, rollback).

import {
  $, $$, esc, fmt, icon, badge, card, callout, pageHead, emptyState, loadingRows, errorBox,
  withLoading, toast, confirmDialog, renderProposal, drawCurve,
} from '../ui.js';
import { api, getOperator } from '../api.js';
import { store } from '../store.js';
import { safeMeterLevel } from '../signal-levels.js';
import { renderSegmentBar } from '../segments.js';

// ---------- Domain constants ----------
const ROLES = [
  ['PASTOR_SPEECH', 'Giọng nói Mục sư'],
  ['LEAD_VOCAL_FEMALE', 'Nữ đơn ca'],
  ['LEAD_VOCAL_MALE', 'Nam đơn ca'],
  ['CHOIR_OVERHEAD', 'Ca đoàn (mic treo)'],
  ['ACOUSTIC_GUITAR', 'Guitar acoustic'],
  ['PIANO_KEYS', 'Piano / Keyboard'],
  ['BASS_GUITAR', 'Guitar bass'],
];
const ROLE_LABEL = Object.fromEntries([...ROLES, ['FEEDBACK_NOTCH', 'Cắt hú (notch)']]);

// Church-profile role → EQ recommender role (best guess for the default selection).
const CHURCH_TO_EQ_ROLE = {
  PASTOR: 'PASTOR_SPEECH', SERMON: 'PASTOR_SPEECH', PRAYER: 'PASTOR_SPEECH', SPEECH: 'PASTOR_SPEECH',
  FEMALE_LEAD: 'LEAD_VOCAL_FEMALE', MALE_LEAD: 'LEAD_VOCAL_MALE', CHOIR: 'CHOIR_OVERHEAD',
  ACOUSTIC_GUITAR: 'ACOUSTIC_GUITAR', PIANO: 'PIANO_KEYS', KEYS: 'PIANO_KEYS', BASS: 'BASS_GUITAR',
};

const HEALTH = {
  OPTIMAL: ['Tối ưu', 'ok', 'ok'],
  LOW_GAIN: ['Gain thấp', 'warn', 'warn'],
  HIGH_GAIN: ['Gain cao', 'warn', 'warn'],
  CLIPPING_DETECTED: ['Đang clip!', 'bad', 'bad'],
};
const COMB_RISK = { LOW: ['Thấp', 'ok'], MODERATE: ['Vừa', 'warn'], HIGH: ['Cao', 'bad'], SEVERE: ['Nghiêm trọng', 'bad'] };
const PHASE = { IN_PHASE: 'Cùng pha', REVERSED_PHASE: 'Ngược pha', DECORRELATED: 'Không tương quan' };
// Detector severities: CRITICAL / HIGH / MEDIUM / LOW (ALARM / WARNING kept for older payloads).
const SEVERITY = {
  CRITICAL: ['Nghiêm trọng', 'bad', 4], HIGH: ['Cao', 'bad', 3], ALARM: ['Báo động', 'bad', 3],
  MEDIUM: ['Trung bình', 'warn', 2], WARNING: ['Cảnh báo', 'warn', 2], LOW: ['Thấp', 'info', 1],
};
const BAND_NAMES = ['Trầm', 'Trung trầm', 'Trung cao', 'Cao'];
const DEFAULT_TALKBACK_CH = 11; // DL16 input 11; real channel comes from /api/v1/routing when available.

// X32 scribble-strip colours: 0 off, 1 red, 2 green, 3 yellow, 4 blue, 5 magenta, 6 cyan, 7 white; 8–15 inverted.
const X32_COLORS = ['#3a4350', '#ef4444', '#22c55e', '#eab308', '#3b82f6', '#d946ef', '#06b6d4', '#e5e7eb'];
const X32_COLOR_NAMES = ['Tắt', 'Đỏ', 'Xanh lá', 'Vàng', 'Xanh dương', 'Hồng tím', 'Xanh ngọc', 'Trắng'];

const METER_FLOOR = -60;      // dBFS shown as empty meter
const RTA_MIN_DB = -90;
const RTA_MAX_DB = 0;
const EQ_RANGE_DB = 18;       // detail chart EQ axis ±18 dB
const FB_HOLD_MS = 2000;      // keep the feedback panel ~2 s after alerts clear (no flicker)
const RELOAD_MS = 20000;      // quiet channel refresh (console-side changes)
const FS = 48000;             // sample rate used for the client-side biquad model

// ---------- X32 normalized value → engineering units (same mappings as packages/eq_optimizer) ----------
const x32Freq = (v) => 20 * Math.pow(1000, +v || 0);          // 20 Hz … 20 kHz
const x32Hpf = (v) => 20 * Math.pow(20, +v || 0);             // 20 Hz … 400 Hz
const x32Gain = (v) => ((+v || 0) - 0.5) * 30;               // −15 … +15 dB
const x32Q = (v) => 0.3 * Math.pow(10 / 0.3, +v || 0);       // 0.3 … 10
function x32FaderDb(f) {
  f = +f;
  if (!Number.isFinite(f) || f <= 0) return -Infinity;
  if (f >= 0.5) return f * 40 - 30;
  if (f >= 0.25) return f * 80 - 50;
  if (f >= 0.0625) return f * 160 - 70;
  return f * 480 - 90;
}

// ---------- EQ response model (RBJ biquads, magnitude only) ----------
const GRID_N = 160;
const GRID = Array.from({ length: GRID_N }, (_, i) => {
  const f = 20 * Math.pow(1000, i / (GRID_N - 1));
  const w = 2 * Math.PI * f / FS;
  return { f, c1: Math.cos(w), s1: Math.sin(w), c2: Math.cos(2 * w), s2: Math.sin(2 * w) };
});

function biquad(type, f0, gainDb, q) {
  f0 = Math.min(Math.max(f0, 10), FS * 0.45);
  q = Math.max(0.1, q || 0.707);
  const A = Math.pow(10, gainDb / 40);
  const w = 2 * Math.PI * f0 / FS, c = Math.cos(w), s = Math.sin(w), al = s / (2 * q);
  const sA = 2 * Math.sqrt(A) * al;
  switch (type) {
    case 'hpf': return [(1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + al, -2 * c, 1 - al];
    case 'lpf': return [(1 - c) / 2, 1 - c, (1 - c) / 2, 1 + al, -2 * c, 1 - al];
    case 'lshelf': return [
      A * ((A + 1) - (A - 1) * c + sA), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sA),
      (A + 1) + (A - 1) * c + sA, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sA];
    case 'hshelf': return [
      A * ((A + 1) + (A - 1) * c + sA), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sA),
      (A + 1) - (A - 1) * c + sA, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sA];
    default: return [1 + al * A, -2 * c, 1 - al * A, 1 + al / A, -2 * c, 1 - al / A]; // peaking
  }
}
function addResponse(out, co) {
  const [b0, b1, b2, a0, a1, a2] = co;
  for (let i = 0; i < GRID_N; i++) {
    const g = GRID[i];
    const nr = b0 + b1 * g.c1 + b2 * g.c2, ni = -(b1 * g.s1 + b2 * g.s2);
    const dr = a0 + a1 * g.c1 + a2 * g.c2, di = -(a1 * g.s1 + a2 * g.s2);
    out[i] += 10 * Math.log10(Math.max(1e-12, (nr * nr + ni * ni) / Math.max(1e-12, dr * dr + di * di)));
  }
}
// X32 /eq/N/type enum: 0 LCut, 1 LShv, 2 PEQ, 3 VEQ, 4 HShv, 5 HCut. The API does not
// expose it yet, so bands without `type` are modelled as peaking EQ.
const EQ_TYPE = { 0: 'hpf', 1: 'lshelf', 2: 'peq', 3: 'peq', 4: 'hshelf', 5: 'lpf' };
function bandUnits(b) {
  return { f: x32Freq(b.f), g: x32Gain(b.gain ?? b.g), q: x32Q(b.q), type: EQ_TYPE[b.type] || 'peq' };
}
/** Returns Float64Array (GRID_N) of dB for the channel's HPF + 4 EQ bands. `override` replaces one band. */
function channelResponse(ch, override) {
  const out = new Float64Array(GRID_N);
  if (!ch) return out;
  if (isTrue(ch.hpon)) addResponse(out, biquad('hpf', x32Hpf(ch.hpf), 0, 0.707));
  const bands = ch.eq_bands || [];
  if (isTrue(ch.eq_on) || override) {
    bands.forEach((b, i) => {
      const u = override && override.band === (+b.band || i + 1) ? override : bandUnits(b);
      if (!isTrue(ch.eq_on) && u !== override) return;
      if (u.type === 'peq' && Math.abs(u.g) < 0.05) return;
      addResponse(out, biquad(u.type, u.f, u.g, u.q));
    });
  }
  return out;
}
const eqSig = (ch) => ch ? JSON.stringify([ch.eq_on, ch.hpon, ch.hpf, ch.eq_bands]) : '';

// ---------- Plain-language helpers ----------
const isTrue = (v) => +v === 1 || v === true;
const isOn = (ch) => isTrue(ch?.on);
const signed = (v, d = 1) => (v === null || v === undefined || Number.isNaN(+v)) ? '—' : `${+v > 0 ? '+' : ''}${(+v).toFixed(d)}`;
const pad2 = (n) => String(n).padStart(2, '0');
function qLabel(q) {
  if (q >= 6) return 'cắt rất hẹp';
  if (q >= 3) return 'hẹp';
  if (q >= 1) return 'vừa';
  return 'rộng';
}
function gainWord(db) {
  if (db > 0.05) return 'tăng';
  if (db < -0.05) return 'cắt';
  return 'phẳng';
}
function freqZone(hz) {
  if (hz < 250) return 'vùng trầm – tiếng ù, rền';
  if (hz < 2000) return 'vùng trung – tiếng hú tròn "u u"';
  if (hz < 5000) return 'vùng trung cao – tiếng rít, chói tai';
  return 'vùng cao – tiếng xì, huýt sáo';
}
function zoneTip(hz) {
  if (hz < 250) return 'Hú trầm thường do loa sub/monitor quá to hoặc mic để gần sàn sân khấu: kiểm tra HPF của kênh.';
  if (hz < 2000) return 'Hú vùng trung thường do mic quay về phía loa monitor: xoay monitor ra phía sau mic (đuôi mic cardioid).';
  if (hz < 5000) return 'Hú rít thường do monitor quá to so với giọng: hạ monitor của người này trước, giữ mic sát miệng.';
  return 'Hú cao thường do mic quá gần loa treble: kiểm tra hướng loa hội trường và khoảng cách mic.';
}
function faderDbText(f) {
  const db = x32FaderDb(f);
  if (!Number.isFinite(db)) return '−∞';
  return signed(db);
}
function faderText(f) {
  const db = x32FaderDb(f);
  const pct = Number.isFinite(+f) ? `${Math.round(+f * 100)}%` : '—';
  if (!Number.isFinite(db)) return `${pct} (−∞ dB, kéo hết xuống)`;
  const note = Math.abs(db) < 0.25 ? ' — đúng mức chuẩn (unity)' : '';
  return `${pct} (${signed(db)} dB${note})`;
}
const eqRoleFor = (churchRole) => {
  const r = String(churchRole || '').toUpperCase();
  return ROLE_LABEL[r] && r !== 'FEEDBACK_NOTCH' ? r : CHURCH_TO_EQ_ROLE[r];
};
const sevInfo = (s) => SEVERITY[String(s || '').toUpperCase()] || ['Nguy cơ', 'warn', 0];
const freqBucket = (f) => Math.round(12 * Math.log2(Math.max(20, +f) / 440)); // semitone bucket
const alertKeyOf = (a) => `${+a.channel_id}:${freqBucket(a.freq_hz)}`;
function colorStyle(c) {
  c = Math.max(0, Math.min(15, +c || 0));
  const base = X32_COLORS[c % 8];
  const inv = c >= 8;
  if (c % 8 === 0) return { bg: 'transparent', fg: 'var(--muted)', border: 'var(--border-strong)', name: X32_COLOR_NAMES[0] };
  return inv
    ? { bg: '#070a0e', fg: base, border: base, name: `${X32_COLOR_NAMES[c % 8]} (đảo)` }
    : { bg: base, fg: '#0b0f14', border: base, name: X32_COLOR_NAMES[c % 8] };
}
/** Pull band/freq/gain/Q out of a notch proposal's OSC changes. */
function parseNotch(p) {
  const out = { band: null, f: null, g: null, q: null, ch: +p?.target_channel || null };
  (p?.changes || []).forEach(c => {
    const m = /^\/ch\/(\d+)\/eq\/(\d)\/(f|g|q)$/.exec(c.parameter || '');
    if (!m) return;
    out.ch = out.ch || +m[1];
    out.band = +m[2];
    if (m[3] === 'f') out.f = x32Freq(c.to);
    if (m[3] === 'g') out.g = x32Gain(c.to);
    if (m[3] === 'q') out.q = x32Q(c.to);
  });
  return out;
}

export default {
  mount(root, ctx) {
    // ---------- State ----------
    let channels = [];
    let talkbackCh = DEFAULT_TALKBACK_CH;
    const strips = new Map();   // ch → { el, meter, cap, fdb, route, on, name, scribble, thumb, sig, lastScale, hot, sel }
    const curves = new Map();   // ch → { sig, resp }
    let selected = 1;
    let pinned = false;
    let pending = store.telemetry || null;
    let lastT = store.telemetry || null;
    let raf = 0;
    let disposed = false;
    let loading = false;
    let chartDirty = true;      // curve layer needs rebuild
    let chartNeedsDraw = true;
    let hotSet = new Set();
    let lastRO = null;
    // Feedback focus
    let fbAlerts = [];          // latest non-empty alert list
    let fbFocusKey = '';        // alert being shown
    let fbUserKey = '';         // alert the user picked from "others"
    let fbLastSeen = 0;
    let fbOthersKey = '';
    const notchCache = new Map(); // alertKey → { status: 'loading'|'ok'|'error'|'applied'|'dismissed', data, err }
    let applying = false;
    // Detail
    let tabs = { active: 'eq', loaded: new Set() };
    let meterEl = null, meterLast = '';
    const curveRedraws = new Set();
    const unsubs = [];

    // ---------- Skeleton ----------
    root.innerHTML = `
      ${pageHead('Bàn trộn trực tiếp',
        'Giống X32-Edit: 32 kênh, EQ và phổ âm. Khi có hú, trang tự nhảy tới kênh gây hú và đưa ra cách xử lý. Mọi thay đổi chỉ là đề xuất — bạn duyệt rồi mới ghi xuống mixer.',
        `<span id="mxMode"></span><button class="btn" id="mxRefresh">${icon('refresh')}Làm mới</button>`)}
      <div class="stack mx">
        <div id="mxSeg"></div>
        <section id="mxFb" class="mx-fb" hidden aria-live="assertive"></section>

        ${card({
          title: `${icon('sliders')} Kênh 1–32`,
          sub: 'Bấm vào một kênh để xem EQ, phổ âm và công cụ. Fader chỉ hiển thị (không kéo được từ đây).',
          actions: '<span class="small muted" id="mxTbNote"></span>',
          cls: 'mx-console',
          body: `<div id="mxStrips">${loadingRows(4)}</div>`,
        })}

        <section class="card mx-detail" id="mxDetail">
          <header class="card-head">
            <h3 id="mxDTitle">Chi tiết kênh</h3>
            <div class="row">
              <button class="btn btn-sm btn-ghost mx-pin" id="mxPin" aria-pressed="false" title="Khi ghim, trang không tự nhảy sang kênh đang hú">${icon('lock')}Ghim kênh</button>
            </div>
          </header>
          <div class="card-body stack">
            <div class="mx-dgrid">
              <div class="stack-sm" style="min-width:0">
                <div class="mx-chart" id="mxChartWrap">
                  <canvas id="mxChart" aria-label="Đáp tuyến EQ của kênh và phổ âm thời gian thực"></canvas>
                  <div class="mx-tip" id="mxTip" hidden></div>
                </div>
                <div class="row small muted mx-legend">
                  <span class="row" style="gap:6px"><span class="mx-key" style="background:rgba(79,140,255,.35)"></span>Phổ âm (RTA)</span>
                  <span class="row" style="gap:6px"><span class="mx-key line" style="border-color:#f5a524"></span>EQ hiện tại (HPF + 4 dải)</span>
                  <span class="row" style="gap:6px"><span class="mx-key line dash" style="border-color:#2fbf71"></span>Sau khi cắt hú (mô phỏng)</span>
                  <span class="row" style="gap:6px"><span class="mx-key line" style="border-color:#ef4444"></span>Tần số đang hú</span>
                </div>
                <p class="tiny muted" id="mxCaption">RTA là phổ của tín hiệu đầu vào đang được phân tích, không phải tín hiệu riêng của kênh sau fader.</p>
              </div>
              <div id="mxSide" class="stack-sm" style="min-width:0"></div>
            </div>
            <div>
              <div class="tabs" role="tablist" id="mxTabs">
                <button class="active" data-tab="eq" role="tab">EQ theo vai trò</button>
                <button data-tab="gain" role="tab">Gain staging</button>
                <button data-tab="bleed" role="tab">Bleed &amp; expander</button>
              </div>
              <div data-pane="eq"></div>
              <div data-pane="gain" hidden></div>
              <div data-pane="bleed" hidden></div>
            </div>
            <div class="row small">
              <span class="muted">Quy trình liên quan:</span>
              <button class="btn btn-ghost btn-sm" data-go="3">${icon('mic')}Cân chỉnh vocal (W3)</button>
              <button class="btn btn-ghost btn-sm" data-go="5">${icon('alert')}Dò hú tập dượt (W5)</button>
            </div>
          </div>
        </section>
      </div>`;

    const stripsEl = $('#mxStrips', root);
    const fbEl = $('#mxFb', root);
    const sideEl = $('#mxSide', root);
    const chartWrap = $('#mxChartWrap', root);
    const chart = $('#mxChart', root);
    const tipEl = $('#mxTip', root);
    const captionEl = $('#mxCaption', root);
    const detailEl = $('#mxDetail', root);
    const pinBtn = $('#mxPin', root);
    const modeEl = $('#mxMode', root);

    const segCleanup = renderSegmentBar($('#mxSeg', root), {
      compact: true, manageLink: true, onChanged: () => loadAll({ quiet: true }),
    });

    // ---------- Data loading ----------
    async function loadAll({ quiet = false } = {}) {
      if (loading) return false;
      loading = true;
      try {
        if (!quiet && !channels.length) stripsEl.innerHTML = loadingRows(4);
        const [chRes, routeRes] = await Promise.allSettled([
          api.get('/api/v1/channels'),
          api.get('/api/v1/routing'),
        ]);
        if (disposed) return false;
        if (routeRes.status === 'fulfilled') {
          const assigned = +routeRes.value?.dl16_input_11_status?.channel_assigned;
          if (assigned >= 1 && assigned <= 32) talkbackCh = assigned;
        }
        $('#mxTbNote', root).innerHTML = `${icon('lock', 'icon-sm')} Talkback ban nhạc (DL16 #11) = <strong>${esc(fmt.ch(talkbackCh))}</strong>, chỉ ra P16`;
        if (chRes.status === 'rejected') {
          if (!channels.length) {
            stripsEl.innerHTML = `${errorBox(chRes.reason)}<div class="mt-8"><button class="btn btn-sm" data-retry>${icon('refresh')}Thử lại</button></div>`;
            $('[data-retry]', stripsEl).addEventListener('click', () => loadAll());
          } else if (!quiet) {
            toast(`Không tải lại được danh sách kênh: ${chRes.reason?.message || chRes.reason}`, 'bad');
          }
          return false;
        }
        channels = chRes.value?.channels || [];
        syncStrips();
        renderSide();
        chartDirty = true;
        requestDraw();
        return true;
      } finally {
        loading = false;
      }
    }

    const chById = (n) => channels.find(c => +c.channel === +n);
    function curveOf(ch) {
      const n = +ch.channel;
      const sig = eqSig(ch);
      let c = curves.get(n);
      if (!c || c.sig !== sig) { c = { sig, resp: channelResponse(ch) }; curves.set(n, c); }
      return c;
    }

    // ---------- Channel strips (built once, then mutated) ----------
    function syncStrips() {
      if (!channels.length) { stripsEl.innerHTML = emptyState('Mixer chưa trả về kênh nào.'); strips.clear(); return; }
      if (!$('.mx-banks', stripsEl)) {
        stripsEl.innerHTML = `
          <div class="mx-banks">
            <div class="mx-bank"><div class="mx-bank-label">Kênh 1–16</div><div class="mx-row" data-bank="0"></div></div>
            <div class="mx-bank"><div class="mx-bank-label">Kênh 17–32</div><div class="mx-row" data-bank="1"></div></div>
          </div>`;
        strips.clear();
      }
      const rows = [$('[data-bank="0"]', stripsEl), $('[data-bank="1"]', stripsEl)];
      const seen = new Set();
      [...channels].sort((a, b) => a.channel - b.channel).forEach(ch => {
        const n = +ch.channel;
        seen.add(n);
        let ref = strips.get(n);
        if (!ref) {
          const node = document.createElement('button');
          node.type = 'button';
          node.className = 'mx-strip';
          node.dataset.ch = String(n);
          node.innerHTML = `
            <span class="mx-scribble"><span class="mx-num">${pad2(n)}</span><span class="mx-name"></span></span>
            <canvas class="mx-thumb" aria-hidden="true"></canvas>
            <span class="mx-body">
              <span class="mx-meter" title="Mức tín hiệu"><span></span></span>
              <span class="mx-fader" title="Vị trí fader"><span class="mx-unity"></span><span class="mx-cap"></span></span>
            </span>
            <span class="mx-fdb"></span>
            <span class="mx-route"></span>
            <span class="mx-on"></span>`;
          (rows[n > 16 ? 1 : 0] || rows[0]).appendChild(node);
          ref = {
            el: node, scribble: $('.mx-scribble', node), name: $('.mx-name', node), thumb: $('.mx-thumb', node),
            meter: $('.mx-meter > span', node), cap: $('.mx-cap', node), fdb: $('.mx-fdb', node),
            route: $('.mx-route', node), on: $('.mx-on', node), sig: '', lastScale: -1, hot: false,
          };
          strips.set(n, ref);
        }
        updateStripStatic(ref, ch);
      });
      for (const [n, ref] of strips) if (!seen.has(n)) { ref.el.remove(); strips.delete(n); }
      markSelected();
      if (lastT) { pending = pending || lastT; scheduleFrame(); }
    }

    function updateStripStatic(ref, ch) {
      const n = +ch.channel;
      const prot = n === talkbackCh;
      const on = isOn(ch);
      const col = colorStyle(ch.color);
      ref.el.classList.toggle('protected', prot);
      ref.el.classList.toggle('muted-ch', !on);
      ref.scribble.style.background = col.bg;
      ref.scribble.style.color = col.fg;
      ref.scribble.style.borderColor = col.border;
      ref.name.innerHTML = `${prot ? icon('lock', 'icon-sm') : ''}${esc(ch.name || fmt.ch(n))}`;
      const f = Math.max(0, Math.min(1, +ch.fader || 0));
      ref.cap.style.bottom = `calc(${(f * 100).toFixed(1)}% - 4px)`;
      ref.fdb.textContent = faderDbText(ch.fader);
      const route = prot ? 'P16' : ch.is_foh && ch.is_p16 ? 'FOH·P16' : ch.is_foh ? 'FOH' : ch.is_p16 ? 'P16' : '—';
      ref.route.textContent = route;
      ref.route.className = `mx-route ${prot ? 'prot' : ch.is_foh ? 'foh' : ch.is_p16 ? 'p16' : ''}`;
      ref.on.textContent = on ? 'ON' : 'MUTE';
      ref.on.className = `mx-on ${on ? 'is-on' : 'is-mute'}`;
      ref.el.title = `${fmt.ch(n)} · ${ch.name || ''}\nMàu: ${col.name}\nFader ${faderText(ch.fader)} · ${on ? 'đang mở' : 'đang tắt tiếng (mute)'}\nĐịnh tuyến: ${route}${prot ? '\nKênh talkback được bảo vệ: chỉ ra P16, không ra FOH' : ''}\nBấm để xem chi tiết`;
      ref.el.setAttribute('aria-label', `${fmt.ch(n)} ${ch.name || ''}, ${on ? 'đang mở' : 'đang mute'}`);
      const sig = eqSig(ch);
      if (sig !== ref.sig) { ref.sig = sig; drawThumb(ref, ch); }
    }

    function drawThumb(ref, ch) {
      const cv = ref.thumb;
      const w = 56, h = 24, dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
      const c = cv.getContext('2d');
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, w, h);
      c.strokeStyle = 'rgba(125,138,156,.35)'; c.lineWidth = 1;
      c.beginPath(); c.moveTo(0, h / 2 + 0.5); c.lineTo(w, h / 2 + 0.5); c.stroke();
      const resp = curveOf(ch).resp;
      const eqOn = isTrue(ch.eq_on);
      c.strokeStyle = eqOn ? '#f5a524' : '#64748b'; c.lineWidth = 1.5;
      c.beginPath();
      for (let i = 0; i < GRID_N; i++) {
        const x = i / (GRID_N - 1) * w;
        const y = h / 2 - Math.max(-15, Math.min(15, resp[i])) / 15 * (h / 2 - 2);
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.stroke();
    }

    function markSelected() {
      for (const [n, ref] of strips) {
        const sel = n === selected;
        if (sel !== ref.sel) { ref.el.classList.toggle('sel', sel); ref.el.setAttribute('aria-pressed', String(sel)); ref.sel = sel; }
      }
    }

    stripsEl.addEventListener('click', (e) => {
      const s = e.target.closest('.mx-strip');
      if (s) selectChannel(+s.dataset.ch, { user: true });
    });

    function centerStrip(n) {
      const ref = strips.get(n);
      if (!ref) return;
      const row = ref.el.parentElement;
      if (row && row.scrollWidth > row.clientWidth) {
        const left = ref.el.offsetLeft - row.offsetLeft - (row.clientWidth - ref.el.offsetWidth) / 2;
        row.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
      }
    }

    function selectChannel(n, { user = false, fromAlert = false } = {}) {
      if (!chById(n)) { if (user) toast(`Không tìm thấy ${fmt.ch(n)}.`, 'warn'); return; }
      const changed = n !== selected;
      selected = n;
      markSelected();
      if (fromAlert) centerStrip(n);
      if (changed || !sideEl.childElementCount) {
        renderSide();
        resetTabs();
      }
      chartDirty = true;
      requestDraw();
    }

    pinBtn.addEventListener('click', () => {
      pinned = !pinned;
      pinBtn.setAttribute('aria-pressed', String(pinned));
      pinBtn.classList.toggle('active', pinned);
      pinBtn.innerHTML = `${icon(pinned ? 'lock' : 'unlock')}${pinned ? `Đã ghim ${esc(fmt.ch(selected))}` : 'Ghim kênh'}`;
      if (fbFocusKey) renderFeedbackPanel();
    });

    // ---------- Telemetry → one draw per animation frame ----------
    function scheduleFrame() {
      if (!raf && !disposed) raf = requestAnimationFrame(frame);
    }
    function requestDraw() { chartNeedsDraw = true; scheduleFrame(); }
    function frame() {
      raf = 0;
      if (disposed || document.hidden) return;
      const t = pending;
      pending = null;
      if (t) {
        lastT = t;
        updateMeters(t.meters || [], t.source);
        updateFeedback(Array.isArray(t.feedback_alerts) ? t.feedback_alerts : []);
        updateMode(t);
        updateCaption(t.source);
        chartNeedsDraw = true;
      }
      if (chartNeedsDraw) { chartNeedsDraw = false; drawChart(); }
    }
    unsubs.push(store.on('telemetry', (t) => { pending = t; scheduleFrame(); }));
    const onVisible = () => {
      if (!document.hidden) { pending = store.telemetry || lastT; chartNeedsDraw = true; scheduleFrame(); }
    };
    document.addEventListener('visibilitychange', onVisible);

    function updateMeters(meters, source) {
      for (let i = 0; i < meters.length; i++) {
        const m = meters[i];
        const level = safeMeterLevel(m, source);
        const db = level === null ? NaN : level;
        const ref = strips.get(+m.channel);
        if (ref) {
          const scale = Number.isFinite(db) ? Math.max(0, Math.min(1, (db - METER_FLOOR) / -METER_FLOOR)) : 0;
          if (Math.abs(scale - ref.lastScale) > 0.004) {
            ref.meter.style.transform = `scaleY(${scale.toFixed(3)})`;
            ref.lastScale = scale;
          }
          const hot = db > -3;
          if (hot !== ref.hot) { ref.el.classList.toggle('clip', hot); ref.hot = hot; }
        }
        if (+m.channel === selected && meterEl) {
          const txt = Number.isFinite(db) && db > METER_FLOOR
            ? `${db.toFixed(1)} dBFS${m.rms_dbfs !== null && m.rms_dbfs !== undefined ? ` · RMS ${(+m.rms_dbfs).toFixed(1)}` : ''}`
            : (Number.isFinite(db) ? 'Không có tín hiệu' : 'Chưa đo được');
          if (txt !== meterLast) { meterEl.textContent = txt; meterLast = txt; }
        }
      }
    }

    function updateMode(t) {
      const ro = !!t.read_only_mode;
      if (ro === lastRO) return;
      lastRO = ro;
      modeEl.innerHTML = ro
        ? `<span title="Mixer đang ở chế độ chỉ đọc: vẫn tạo được đề xuất nhưng Safety Gate sẽ từ chối ghi.">${badge('Chỉ đọc', 'info')}</span>`
        : `<span title="Mixer cho phép ghi sau khi bạn duyệt.">${badge('Cho phép ghi', 'warn')}</span>`;
      if (fbFocusKey) renderProposalBox();
    }

    let captionKey = '';
    function updateCaption(src) {
      const key = src ? `${src.id}|${src.spectrum_input}|${src.valid}|${src.tap_point}` : 'none';
      if (key === captionKey) return;
      captionKey = key;
      let txt = 'RTA là phổ của tín hiệu đầu vào đang được phân tích, không phải tín hiệu riêng của kênh sau fader.';
      if (src) {
        const inp = src.spectrum_input ? ` Đang phân tích: đầu vào số ${src.spectrum_input}${src.mapping_verified ? '' : ' (chưa xác nhận tương ứng kênh X32 nào)'}.` : '';
        const tap = src.tap_point && src.tap_point !== 'SIMULATED' ? ` Điểm lấy tín hiệu: ${src.tap_point}.` : '';
        txt += ` Nguồn: ${src.label || src.id}.${inp}${tap}${src.valid ? '' : ' Dữ liệu hiện KHÔNG hợp lệ — không dùng để suy luận.'}`;
      }
      captionEl.textContent = txt;
    }

    // ---------- Detail chart ----------
    const layers = { grid: document.createElement('canvas'), curve: document.createElement('canvas'), key: '' };
    let markers = [];   // [{x, y, html}] in CSS px
    const PAD = { l: 34, r: 40, t: 12, b: 20 };
    const xOf = (f, w) => PAD.l + (Math.log10(Math.max(20, Math.min(20000, f))) - Math.log10(20)) / 3 * (w - PAD.l - PAD.r);
    const yEq = (db, h) => PAD.t + (h - PAD.t - PAD.b) * (1 - (Math.max(-EQ_RANGE_DB, Math.min(EQ_RANGE_DB, db)) + EQ_RANGE_DB) / (2 * EQ_RANGE_DB));
    const yRta = (db, h) => PAD.t + (h - PAD.t - PAD.b) * (1 - Math.max(0, Math.min(1, (db - RTA_MIN_DB) / (RTA_MAX_DB - RTA_MIN_DB))));

    function sizeLayer(cv, W, H) { if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; } }

    function buildGrid(w, h, dpr) {
      const c = layers.grid.getContext('2d');
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, w, h);
      c.fillStyle = '#070a0e'; c.fillRect(0, 0, w, h);
      c.font = '10px ui-monospace, Consolas, monospace';
      c.lineWidth = 1;
      const bottom = h - PAD.b;
      [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].forEach(f => {
        const x = Math.round(xOf(f, w)) + 0.5;
        c.strokeStyle = f === 100 || f === 1000 || f === 10000 ? '#243142' : '#18212d';
        c.beginPath(); c.moveTo(x, PAD.t); c.lineTo(x, bottom); c.stroke();
        c.fillStyle = '#64748b';
        const label = f >= 1000 ? `${f / 1000}k` : String(f);
        const tw = c.measureText(label).width;
        c.fillText(label, Math.max(PAD.l, Math.min(x - tw / 2, w - PAD.r - tw)), h - 6);
      });
      for (let db = -EQ_RANGE_DB; db <= EQ_RANGE_DB; db += 6) {
        const y = Math.round(yEq(db, h)) + 0.5;
        c.strokeStyle = db === 0 ? '#34445a' : '#18212d';
        c.beginPath(); c.moveTo(PAD.l, y); c.lineTo(w - PAD.r, y); c.stroke();
        c.fillStyle = '#b4874a';
        c.fillText(`${db > 0 ? '+' : ''}${db}`, 4, y + 3);
      }
      c.fillStyle = '#5b7bb8';
      [0, -30, -60, -90].forEach(db => c.fillText(String(db), w - PAD.r + 6, yRta(db, h) + (db === 0 ? 8 : db === -90 ? -2 : 3)));
      c.fillStyle = '#64748b';
      c.fillText('dBFS', w - PAD.r + 4, h - 6);
    }

    function curvePath(c, resp, w, h) {
      c.beginPath();
      for (let i = 0; i < GRID_N; i++) {
        const x = xOf(GRID[i].f, w), y = yEq(resp[i], h);
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      }
    }

    function buildCurve(w, h, dpr) {
      const c = layers.curve.getContext('2d');
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, w, h);
      markers = [];
      const ch = chById(selected);
      if (!ch) return;
      const eqOn = isTrue(ch.eq_on);
      const resp = curveOf(ch).resp;
      const y0 = yEq(0, h);
      // fill to 0 dB
      curvePath(c, resp, w, h);
      c.lineTo(xOf(20000, w), y0); c.lineTo(xOf(20, w), y0); c.closePath();
      c.fillStyle = eqOn ? 'rgba(245,165,36,.12)' : 'rgba(100,116,139,.10)';
      c.fill();
      curvePath(c, resp, w, h);
      c.strokeStyle = eqOn ? '#f5a524' : '#64748b'; c.lineWidth = 2.2; c.stroke();

      // proposed notch overlay for this channel
      const prop = notchFor(selected);
      if (prop) {
        const p = parseNotch(prop);
        if (p.band && p.f && p.g !== null && p.q) {
          const after = channelResponse(ch, { band: p.band, f: p.f, g: p.g, q: p.q, type: 'peq' });
          c.setLineDash([5, 4]);
          curvePath(c, after, w, h);
          c.strokeStyle = '#2fbf71'; c.lineWidth = 1.8; c.stroke();
          c.setLineDash([]);
        }
      }

      // HPF marker
      c.font = '600 10px ui-monospace, Consolas, monospace';
      if (isTrue(ch.hpon)) {
        const hf = x32Hpf(ch.hpf);
        const x = xOf(hf, w);
        c.strokeStyle = 'rgba(34,184,207,.6)'; c.setLineDash([2, 3]);
        c.beginPath(); c.moveTo(x, PAD.t); c.lineTo(x, h - PAD.b); c.stroke(); c.setLineDash([]);
        c.fillStyle = '#22b8cf'; c.fillText('HPF', x + 3, h - PAD.b - 4);
        markers.push({ x, y: h - PAD.b - 8, html: `<strong>Lọc cắt trầm (HPF)</strong><br>${esc(fmt.hz(hf))} — bỏ tiếng ù, rung sàn phía dưới` });
      }
      // band markers
      (ch.eq_bands || []).forEach((b, i) => {
        const u = bandUnits(b);
        const x = xOf(u.f, w), y = yEq(eqOn ? u.g : 0, h);
        c.beginPath(); c.arc(x, y, 8, 0, Math.PI * 2);
        c.fillStyle = eqOn ? '#18202b' : '#121821'; c.fill();
        c.strokeStyle = eqOn ? '#f5a524' : '#64748b'; c.lineWidth = 1.5; c.stroke();
        c.fillStyle = eqOn ? '#ffd38a' : '#94a3b8';
        const label = String(+b.band || i + 1);
        c.fillText(label, x - c.measureText(label).width / 2, y + 3.5);
        markers.push({ x, y, html: `<strong>Dải ${esc(label)} · ${esc(BAND_NAMES[i] || 'PEQ')}</strong><br>${esc(fmt.hz(u.f))} · ${esc(signed(u.g))} dB (${gainWord(u.g)})<br>Q=${u.q.toFixed(1)} (${qLabel(u.q)})${eqOn ? '' : '<br><em>EQ đang tắt</em>'}` });
      });
    }

    function drawChart() {
      const w = chart.clientWidth, h = chart.clientHeight;
      if (!w || !h) return;
      const dpr = window.devicePixelRatio || 1;
      const W = Math.round(w * dpr), H = Math.round(h * dpr);
      const key = `${W}x${H}`;
      if (chart.width !== W || chart.height !== H) { chart.width = W; chart.height = H; }
      if (layers.key !== key) {
        sizeLayer(layers.grid, W, H); sizeLayer(layers.curve, W, H);
        buildGrid(w, h, dpr);
        layers.key = key;
        chartDirty = true;
      }
      if (chartDirty) { buildCurve(w, h, dpr); chartDirty = false; }

      const c = chart.getContext('2d');
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.drawImage(layers.grid, 0, 0);
      c.setTransform(dpr, 0, 0, dpr, 0, 0);

      // RTA bars (background)
      const t = lastT;
      const bands = t?.rta || [];
      const alerts = Array.isArray(t?.feedback_alerts) ? t.feedback_alerts : [];
      const af = alerts.map(a => +a.freq_hz).filter(Number.isFinite);
      const base = h - PAD.b;
      if (bands.length) {
        c.fillStyle = 'rgba(79,140,255,.30)';
        const hotBars = [];
        for (let i = 0; i < bands.length; i++) {
          const cf = +bands[i].center_freq;
          if (!(cf >= 20 && cf <= 20000)) continue;
          const lo = i > 0 ? Math.sqrt(cf * +bands[i - 1].center_freq) : cf / 1.03;
          const hi = i < bands.length - 1 ? Math.sqrt(cf * +bands[i + 1].center_freq) : cf * 1.03;
          const x0 = xOf(lo, w), x1 = xOf(hi, w);
          const y = yRta(+bands[i].level_dbfs, h);
          if (base - y < 0.5) continue;
          let hot = false;
          for (let k = 0; k < af.length; k++) if (Math.abs(af[k] - cf) < cf * 0.06) { hot = true; break; }
          if (hot) { hotBars.push([x0, y, x1 - x0]); continue; }
          c.fillRect(x0 + 0.3, y, Math.max(0.8, x1 - x0 - 0.6), base - y);
        }
        if (hotBars.length) {
          c.fillStyle = 'rgba(239,68,68,.55)';
          hotBars.forEach(([x, y, bw]) => c.fillRect(x + 0.3, y, Math.max(0.8, bw - 0.6), base - y));
        }
      } else {
        c.fillStyle = '#64748b'; c.font = '12px system-ui, sans-serif';
        const msg = 'Đang chờ dữ liệu phổ âm…';
        c.fillText(msg, (w - c.measureText(msg).width) / 2, PAD.t + 18);
      }

      // EQ curve + markers
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.drawImage(layers.curve, 0, 0);
      c.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Feedback markers: solid red for this channel, dashed orange for others
      if (alerts.length) {
        c.font = '600 11px system-ui, sans-serif';
        alerts.slice(0, 4).forEach((a, i) => {
          const f = +a.freq_hz;
          if (!Number.isFinite(f)) return;
          const mine = +a.channel_id === selected;
          const x = Math.round(xOf(f, w)) + 0.5;
          c.strokeStyle = mine ? '#ef4444' : 'rgba(245,165,36,.75)';
          c.lineWidth = mine ? 2 : 1;
          c.setLineDash(mine ? [] : [4, 4]);
          c.beginPath(); c.moveTo(x, PAD.t); c.lineTo(x, base); c.stroke();
          c.setLineDash([]);
          const label = mine ? `Hú ${fmt.hz(f)}` : `Hú K${pad2(a.channel_id)} ${fmt.hz(f)}`;
          const tw = c.measureText(label).width;
          const tx = Math.min(x + 5, w - PAD.r - tw - 4);
          const ty = PAD.t + 14 + i * 15;
          c.fillStyle = 'rgba(7,10,14,.8)'; c.fillRect(tx - 3, ty - 11, tw + 6, 15);
          c.fillStyle = mine ? '#ff8a8a' : '#ffc960';
          c.fillText(label, tx, ty);
        });
        c.lineWidth = 1;
      }
    }

    chart.addEventListener('mousemove', (e) => {
      const r = chart.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      let best = null, bd = 196;
      markers.forEach(m => { const d = (m.x - mx) ** 2 + (m.y - my) ** 2; if (d < bd) { bd = d; best = m; } });
      if (!best) { tipEl.hidden = true; return; }
      tipEl.innerHTML = best.html;
      tipEl.hidden = false;
      const tw = tipEl.offsetWidth;
      tipEl.style.left = `${Math.max(4, Math.min(best.x + 12, r.width - tw - 4))}px`;
      tipEl.style.top = `${Math.max(4, best.y - 10 - tipEl.offsetHeight)}px`;
    });
    chart.addEventListener('mouseleave', () => { tipEl.hidden = true; });

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => { layers.key = ''; requestDraw(); }) : null;
    ro?.observe(chartWrap);

    let resizeRaf = 0;
    const onResize = () => {
      if (resizeRaf) return;
      resizeRaf = requestAnimationFrame(() => { resizeRaf = 0; curveRedraws.forEach(fn => fn()); layers.key = ''; requestDraw(); });
    };
    window.addEventListener('resize', onResize);

    // ---------- Selected-channel side panel ----------
    function renderSide() {
      const ch = chById(selected);
      const title = $('#mxDTitle', root);
      if (!ch) { sideEl.innerHTML = emptyState('Chọn một kênh ở trên.'); title.textContent = 'Chi tiết kênh'; return; }
      const n = +ch.channel;
      const prot = n === talkbackCh;
      const on = isOn(ch);
      const hpOn = isTrue(ch.hpon);
      const eqOn = isTrue(ch.eq_on);
      const col = colorStyle(ch.color);
      title.innerHTML = `<span class="mx-dchip" style="background:${col.bg};color:${col.fg};border-color:${col.border}">${pad2(n)}</span> ${esc(ch.name || fmt.ch(n))}
        <span class="card-sub">${esc(fmt.ch(n))}${ch.church_role ? ` · ${esc(ROLE_LABEL[String(ch.church_role).toUpperCase()] || ch.church_role)}` : ''}</span>`;
      if (pinned) pinBtn.innerHTML = `${icon('lock')}Đã ghim ${esc(fmt.ch(selected))}`;
      const route = prot ? badge('Chỉ P16 (bảo vệ)', 'warn')
        : ch.is_foh && ch.is_p16 ? badge('FOH + P16', 'ok')
          : ch.is_foh ? badge('FOH', 'ok')
            : ch.is_p16 ? badge('Chỉ P16', 'info') : badge('Không ra FOH', 'info');
      const bands = ch.eq_bands || [];
      sideEl.innerHTML = `
        ${prot ? callout('warn', `<strong>Kênh talkback ban nhạc (DL16 #11).</strong> Chỉ gửi về tai nghe P16 của ban nhạc, tuyệt đối không ra loa hội trường (FOH).`, 'shield') : ''}
        ${prot && ch.is_foh ? callout('bad', `<strong>Vi phạm an toàn:</strong> kênh talkback đang được định tuyến ra FOH. Kiểm tra ngay ở trang <a href="#/safety">An toàn &amp; nhật ký</a>.`) : ''}
        <div class="mx-stats">
          <div class="stat"><div class="stat-label">Mức tín hiệu</div><div class="mx-stat-v" data-level>—</div></div>
          <div class="stat"><div class="stat-label">Fader</div><div class="mx-stat-v">${esc(faderDbText(ch.fader))} dB</div><div class="stat-sub">${esc(Number.isFinite(+ch.fader) ? `${Math.round(+ch.fader * 100)}%` : '—')}${Math.abs(x32FaderDb(ch.fader)) < 0.25 ? ' · unity' : ''}</div></div>
          <div class="stat"><div class="stat-label">HPF</div><div class="mx-stat-v">${hpOn ? esc(fmt.hz(x32Hpf(ch.hpf))) : 'Tắt'}</div><div class="stat-sub">${hpOn ? 'cắt ù, rung sàn' : 'không lọc trầm'}</div></div>
          <div class="stat"><div class="stat-label">Tiếng</div>
            <div class="row-between" style="gap:6px;margin-top:4px">
              <span class="strong ${on ? 'ok-text' : 'bad-text'}">${on ? 'ON' : 'MUTE'}</span>
              <button class="btn btn-sm ${on ? 'btn-danger' : 'btn-ok'}" data-mute>${icon(on ? 'micOff' : 'mic')}${on ? 'Mute' : 'Mở'}</button>
            </div>
          </div>
        </div>
        <div class="row">${route}${!on ? badge('Đang mute', 'bad') : ''}${badge(eqOn ? 'EQ bật' : 'EQ tắt', eqOn ? 'ok' : 'info')}</div>
        ${bands.length ? `
        <div class="table-wrap"><table class="table mx-btable">
          <thead><tr><th>Dải</th><th class="right">Tần số</th><th class="right">Mức</th><th class="right">Q</th></tr></thead>
          <tbody>${bands.map((b, i) => {
            const u = bandUnits(b);
            return `<tr>
              <td><span class="mx-bnum">${esc(b.band ?? i + 1)}</span>${esc(BAND_NAMES[i] || 'PEQ')}</td>
              <td class="right mono">${esc(fmt.hz(u.f))}</td>
              <td class="right mono ${u.g < -0.05 ? 'text-2' : u.g > 0.05 ? 'warn-text' : 'muted'}">${esc(signed(u.g))} dB<div class="tiny muted">${gainWord(u.g)}</div></td>
              <td class="right mono">Q=${esc(u.q.toFixed(1))}<div class="tiny muted">${qLabel(u.q)}</div></td>
            </tr>`;
          }).join('')}</tbody>
        </table></div>` : emptyState('Không đọc được EQ của kênh này.')}
        <dl class="kv small">
          <dt>Ra loa hội trường</dt><dd>${ch.is_foh ? 'Có' : 'Không'}${ch.mix_st !== undefined ? ` <span class="muted">(Main LR: ${+ch.mix_st ? 'bật' : 'tắt'})</span>` : ''}</dd>
          <dt>Ra tai nghe P16</dt><dd>${ch.is_p16 ? `Có${(ch.p16_slots || []).length ? ` — ${esc(ch.p16_slots.join(', '))}` : ''}` : 'Không'}</dd>
        </dl>`;
      meterEl = $('[data-level]', sideEl);
      meterLast = '';
      $('[data-mute]', sideEl).addEventListener('click', (e) => toggleMute(ch, e.currentTarget));
      if (lastT) updateMeters(lastT.meters || [], lastT.source);
    }

    async function toggleMute(ch, btn) {
      const n = +ch.channel;
      const target = isOn(ch) ? 0 : 1;
      const ok = await confirmDialog({
        title: target ? `Mở tiếng ${fmt.ch(n)}?` : `Mute ${fmt.ch(n)}?`,
        message: `${esc(ch.name || fmt.ch(n))} sẽ ${target ? '<strong>mở tiếng</strong> trở lại' : '<strong>tắt tiếng</strong> ngay lập tức'} trên mixer.
          ${n === talkbackCh ? '<br>Đây là kênh talkback ban nhạc — thay đổi chỉ ảnh hưởng P16.' : ''}
          <br>Người thực hiện: <strong>${esc(getOperator())}</strong>.`,
        confirmText: target ? 'Mở tiếng' : 'Mute',
        danger: !target,
      });
      if (!ok) return;
      const res = await withLoading(btn, () => api.post(`/api/v1/channels/${n}/mute`, { on: target, operator_id: getOperator() }),
        { errorPrefix: 'Không đổi được trạng thái mute: ' });
      if (!res || disposed) return;
      const c = chById(n);
      if (c) c.on = res.on ?? target;
      const ref = strips.get(n);
      if (ref && c) updateStripStatic(ref, c);
      if (n === selected) renderSide();
      toast(`${fmt.ch(n)}: ${(res.on ?? target) ? 'đã mở tiếng' : 'đã mute'} (đã xác minh).`, 'ok');
      loadAll({ quiet: true });
    }

    // ---------- Feedback focus panel ----------
    function pickFocus(alerts) {
      const keyed = alerts.map(a => ({ a, key: alertKeyOf(a) }));
      if (fbUserKey) { const u = keyed.find(k => k.key === fbUserKey); if (u) return u; fbUserKey = ''; }
      const cur = keyed.find(k => k.key === fbFocusKey);
      if (cur) return cur;
      return keyed.sort((x, y) => (sevInfo(y.a.severity)[2] - sevInfo(x.a.severity)[2]) || ((+y.a.confidence || 0) - (+x.a.confidence || 0)))[0];
    }

    function updateFeedback(alerts) {
      const now = performance.now();
      // Strip pulse for every channel with an alert
      const nextHot = new Set(alerts.map(a => +a.channel_id));
      for (const n of hotSet) if (!nextHot.has(n)) strips.get(n)?.el.classList.remove('hot');
      for (const n of nextHot) if (!hotSet.has(n)) strips.get(n)?.el.classList.add('hot');
      hotSet = nextHot;

      if (alerts.length) {
        fbLastSeen = now;
        fbAlerts = alerts;
        const focus = pickFocus(alerts);
        if (focus.key !== fbFocusKey) {
          const first = !fbFocusKey || fbEl.hidden;
          fbFocusKey = focus.key;
          const n = +focus.a.channel_id;
          if (!pinned) selectChannel(n, { fromAlert: true });
          else centerStrip(n);
          renderFeedbackPanel();
          ensureNotch(focus.a, focus.key);
          if (fbEl.hidden) fbEl.hidden = false;
          if (first && !document.querySelector('.overlay')) {
            const r = fbEl.getBoundingClientRect();
            if (r.top < 60 || r.top > window.innerHeight - 120) fbEl.scrollIntoView({ block: 'start', behavior: 'smooth' });
          }
        } else {
          updateFeedbackLive(focus.a);
        }
        const othersKey = alerts.map(alertKeyOf).filter(k => k !== fbFocusKey).join('|');
        if (othersKey !== fbOthersKey) { fbOthersKey = othersKey; renderOthers(); }
        if (fbEl.hidden) fbEl.hidden = false;
      } else {
        checkFeedbackHold(now);
      }
    }

    function checkFeedbackHold(now = performance.now()) {
      if (fbEl.hidden || applying || now - fbLastSeen < FB_HOLD_MS) return;
      fbEl.hidden = true;
      fbEl.innerHTML = '';
      fbFocusKey = ''; fbUserKey = ''; fbOthersKey = '';
      fbAlerts = [];
      chartDirty = true; requestDraw();
    }
    const holdTimer = setInterval(() => { if (!disposed && !document.hidden && !(store.telemetry?.feedback_alerts || []).length) checkFeedbackHold(); }, 1000);

    function focusAlert() { return fbAlerts.find(a => alertKeyOf(a) === fbFocusKey) || null; }

    function renderFeedbackPanel() {
      const a = focusAlert();
      if (!a) return;
      const n = +a.channel_id, f = +a.freq_hz;
      const ch = chById(n);
      const name = ch?.name || fmt.ch(n);
      const [sevText, sevKind] = sevInfo(a.severity);
      const ev = (a.evidence || []).filter(Boolean);
      const prot = n === talkbackCh;
      fbEl.innerHTML = `
        <div class="mx-fb-head">
          <span class="mx-fb-icon">${icon('alert', 'icon-lg')}</span>
          <div class="grow">
            <div class="mx-fb-title">Đang hú ở <span class="mono">${esc(fmt.hz(f))}</span> — <span>${esc(fmt.ch(n))} · ${esc(name)}</span></div>
            <div class="small text-2">Thuộc ${esc(freqZone(f))}. ${a.simulated ? '<span class="muted">(dữ liệu mô phỏng)</span>' : ''}</div>
          </div>
          <div class="row">
            ${badge(sevText, sevKind)}
            <span class="small muted">Tin cậy <strong data-fb-conf>${esc(fmt.pct(a.confidence ?? 0))}</strong></span>
            ${a.level_dbfs !== undefined && a.level_dbfs !== null ? `<span class="small muted">Mức <strong data-fb-lvl>${esc(fmt.num(a.level_dbfs))}</strong> dBFS</span>` : ''}
          </div>
        </div>
        ${pinned && n !== selected ? `<div class="row small"><span class="warn-text">${icon('lock', 'icon-sm')} Đang ghim ${esc(fmt.ch(selected))}, không tự chuyển kênh.</span><button class="btn btn-sm" data-fb-view="${n}">Xem ${esc(fmt.ch(n))}</button></div>` : ''}
        <div class="mx-fb-grid">
          <div class="stack-sm">
            <div class="label">Xử lý nhanh — làm theo thứ tự</div>
            <ol class="mx-steps">
              <li><strong>Kéo fader ${esc(fmt.ch(n))} (${esc(name)}) xuống 3–5 dB</strong> ngay trên bàn X32 — cách nhanh và an toàn nhất.</li>
              <li><strong>Kiểm tra mic không chĩa vào loa</strong> hội trường hay loa monitor; mic cầm sát miệng.</li>
              <li><strong>Nhờ người hát/nói lùi xa loa monitor</strong> hoặc xoay monitor ra phía sau mic.</li>
              <li><strong>Nếu vẫn hú: cắt hẹp (notch)</strong> theo đề xuất bên cạnh — bấm “Đồng ý cắt”.</li>
            </ol>
            <p class="small muted">${esc(zoneTip(f))}</p>
            ${prot ? callout('warn', 'Kênh này là talkback ban nhạc (chỉ ra P16): tiếng hú nghe trong tai nghe ban nhạc, không ra hội trường. Ưu tiên hạ mức P16.', 'shield') : ''}
            ${ev.length ? `<details class="small"><summary class="muted">Căn cứ phát hiện (${ev.length})</summary><ul class="text-2" style="margin:6px 0 0;padding-left:18px">${ev.map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
            ${a.recommended_action ? `<div class="small muted">Gợi ý hệ thống: ${esc(a.recommended_action)}</div>` : ''}
          </div>
          <div class="mx-fb-prop" data-fb-prop></div>
        </div>
        <div data-fb-others></div>
        <p class="tiny muted">Không có cách nào bảo đảm hết hú hoàn toàn. Ưu tiên vị trí mic, hướng loa và gain trước khi cắt EQ.</p>`;
      renderProposalBox();
      renderOthers();
    }

    function updateFeedbackLive(a) {
      const c = $('[data-fb-conf]', fbEl);
      const t = fmt.pct(a.confidence ?? 0);
      if (c && c.textContent !== t) c.textContent = t;
      const l = $('[data-fb-lvl]', fbEl);
      const lt = fmt.num(a.level_dbfs);
      if (l && l.textContent !== lt) l.textContent = lt;
    }

    function renderOthers() {
      const box = $('[data-fb-others]', fbEl);
      if (!box) return;
      const others = fbAlerts.filter(a => alertKeyOf(a) !== fbFocusKey).slice(0, 4);
      box.innerHTML = others.length ? `
        <div class="row small mx-fb-others">
          <span class="muted">Cũng có nguy cơ:</span>
          ${others.map(a => `<button class="btn btn-sm btn-ghost" data-fb-pick="${esc(alertKeyOf(a))}">${esc(fmt.ch(a.channel_id))} @ ${esc(fmt.hz(a.freq_hz))}</button>`).join('')}
        </div>` : '';
    }

    fbEl.addEventListener('click', (e) => {
      const pick = e.target.closest('[data-fb-pick]');
      if (pick) {
        fbUserKey = pick.dataset.fbPick;
        const a = fbAlerts.find(x => alertKeyOf(x) === fbUserKey);
        if (a) {
          fbFocusKey = fbUserKey;
          selectChannel(+a.channel_id, { fromAlert: true });
          renderFeedbackPanel();
          ensureNotch(a, fbFocusKey);
          fbOthersKey = '';
        }
        return;
      }
      const view = e.target.closest('[data-fb-view]');
      if (view) { selectChannel(+view.dataset.fbView, { fromAlert: true }); renderFeedbackPanel(); return; }
      if (e.target.closest('[data-fb-apply]')) { applyNotch(e.target.closest('[data-fb-apply]')); return; }
      if (e.target.closest('[data-fb-regen]')) {
        const a = focusAlert();
        if (a) { notchCache.delete(fbFocusKey); ensureNotch(a, fbFocusKey); }
        return;
      }
      if (e.target.closest('[data-fb-dismiss]')) {
        const entry = notchCache.get(fbFocusKey);
        if (entry) entry.status = 'dismissed';
        renderProposalBox();
        chartDirty = true; requestDraw();
      }
    });

    /** Generating a notch proposal is read-only (no OSC writes). Once per distinct alert. */
    async function ensureNotch(a, key) {
      if (notchCache.has(key)) return;
      const entry = { status: 'loading', data: null, err: null, alert: a };
      notchCache.set(key, entry);
      renderProposalBox();
      try {
        entry.data = await api.post('/api/v1/proposals/generate-notch', {
          channel_id: +a.channel_id, freq_hz: +a.freq_hz, confidence: +(a.confidence ?? 0.88),
        });
        entry.status = 'ok';
      } catch (err) {
        entry.status = 'error';
        entry.err = err;
      }
      if (disposed) return;
      if (key === fbFocusKey) renderProposalBox();
      chartDirty = true; requestDraw();
    }

    function notchFor(n) {
      // Only the focused alert's proposal is overlaid, and only while it is pending review.
      const entry = notchCache.get(fbFocusKey);
      if (!entry || entry.status !== 'ok' || !entry.data) return null;
      return +(entry.data.target_channel ?? entry.alert.channel_id) === +n ? entry.data : null;
    }

    function renderProposalBox() {
      const box = $('[data-fb-prop]', fbEl);
      if (!box) return;
      const entry = notchCache.get(fbFocusKey);
      if (!entry || entry.status === 'loading') {
        box.innerHTML = `<div class="label">Đề xuất cắt hú</div><div class="row small muted mt-8"><span class="mx-spin"></span>Đang tính đề xuất (chỉ đọc, chưa ghi gì)…</div>`;
        return;
      }
      if (entry.status === 'error') {
        box.innerHTML = `<div class="label">Đề xuất cắt hú</div>${errorBox(entry.err)}<div class="mt-8"><button class="btn btn-sm" data-fb-regen>${icon('refresh')}Thử lại</button></div>`;
        return;
      }
      if (entry.status === 'applied') {
        box.innerHTML = `<div class="label">Đề xuất cắt hú</div>${callout('ok', `Đã cắt và xác minh trên mixer (<span class="mono">${esc(entry.data?.proposal_id || '')}</span>). Nếu vẫn hú, kéo fader xuống và kiểm tra vị trí mic.`)}`;
        return;
      }
      if (entry.status === 'dismissed') {
        box.innerHTML = `<div class="label">Đề xuất cắt hú</div><p class="small muted mt-8">Đã bỏ qua đề xuất.</p><button class="btn btn-sm mt-8" data-fb-regen>${icon('wand')}Xem lại đề xuất</button>`;
        return;
      }
      const p = parseNotch(entry.data);
      const ch = chById(p.ch);
      const cur = ch && p.band ? (ch.eq_bands || []).find((b, i) => (+b.band || i + 1) === p.band) : null;
      const curU = cur ? bandUnits(cur) : null;
      const busy = curU && Math.abs(curU.g) >= 0.5;
      const t = store.telemetry || lastT || {};
      const readOnly = t.read_only_mode !== false;
      const stop = !!(t.stop_auto ?? store.status?.stop_auto);
      box.innerHTML = `
        <div class="row-between"><div class="label">Đề xuất cắt hú</div><span class="small muted">Tin cậy ${esc(fmt.pct(entry.data.confidence ?? 0))}</span></div>
        <div class="mx-rec">
          <div class="mx-rec-main">${p.g !== null ? esc(signed(p.g)) : '—'} dB <span>tại</span> ${esc(fmt.hz(p.f))}</div>
          <div class="small text-2">Dải EQ số ${esc(p.band ?? '—')} của ${esc(fmt.ch(p.ch))}, Q=${p.q ? esc(p.q.toFixed(1)) : '—'} (${p.q ? qLabel(p.q) : '—'}): chỉ hạ đúng tần số hú, giọng gần như không đổi.</div>
          ${ch && !isTrue(ch.eq_on) ? `<div class="small warn-text mt-8">${icon('alert', 'icon-sm')} EQ của kênh này đang TẮT — notch chỉ có tác dụng khi bật EQ trên bàn X32.</div>` : ''}
          ${busy ? `<div class="small warn-text mt-8">${icon('alert', 'icon-sm')} Dải ${esc(p.band)} hiện đang ${esc(signed(curU.g))} dB tại ${esc(fmt.hz(curU.f))} — sẽ bị thay bằng notch này.</div>` : ''}
          <div class="tiny muted mt-8">Đường nét đứt màu xanh trên biểu đồ bên dưới là đáp tuyến sau khi cắt (mô phỏng).</div>
        </div>
        ${stop ? callout('bad', 'Hệ thống đang khóa khẩn cấp (STOP). Mở khóa trước khi cắt.') : readOnly ? `<p class="small warn-text">Mixer đang <strong>Chỉ quan sát</strong>: khi bạn đồng ý, hệ thống sẽ chuyển sang chế độ Hỗ trợ (ASSIST) rồi mới cắt.</p>` : ''}
        <div class="row mt-8">
          <button class="btn btn-danger btn-lg" data-fb-apply ${stop ? 'disabled' : ''}>${icon('scissors')}Đồng ý cắt</button>
          <button class="btn btn-ghost btn-sm" data-fb-dismiss>Bỏ qua</button>
          <button class="btn btn-ghost btn-sm" data-fb-regen title="Tính lại theo trạng thái mixer mới nhất">${icon('refresh')}Tạo lại</button>
        </div>
        <p class="tiny muted">Lệnh đi qua Safety Gate: kiểm tra snapshot, ghi chậm, đọc lại, tự hoàn tác nếu sai.</p>`;
    }

    async function applyNotch(btn) {
      const key = fbFocusKey;
      const entry = notchCache.get(key);
      if (!entry || entry.status !== 'ok' || applying) return;
      const p = parseNotch(entry.data);
      const ch = chById(p.ch);
      const t = store.telemetry || lastT || {};
      const readOnly = t.read_only_mode !== false;
      applying = true;
      try {
        const ok = await confirmDialog({
          title: `Cắt hú ${fmt.ch(p.ch)} tại ${fmt.hz(p.f)}?`,
          message: `Sẽ ghi <strong>${(entry.data.changes || []).length}</strong> tham số EQ dải ${esc(p.band)} cho <strong>${esc(fmt.ch(p.ch))}${ch?.name ? ` · ${esc(ch.name)}` : ''}</strong>:
            ${esc(signed(p.g))} dB tại ${esc(fmt.hz(p.f))}, Q=${esc(p.q?.toFixed(1))} (${p.q ? qLabel(p.q) : ''}).<br>
            ${readOnly ? '<strong>Mixer đang Chỉ quan sát</strong> — đồng ý sẽ chuyển sang chế độ <strong>Hỗ trợ (ASSIST)</strong> trước khi ghi.<br>' : ''}
            Người duyệt: <strong>${esc(getOperator())}</strong>. Nếu đọc lại không khớp, hệ thống tự hoàn tác.`,
          confirmText: readOnly ? 'Bật Hỗ trợ &amp; cắt' : 'Đồng ý cắt',
          danger: true,
        });
        if (!ok || disposed) return;
        const result = await withLoading(btn, async () => {
          if (readOnly) await api.post('/api/v1/safety/mode', { mode: 'ASSIST', operator: getOperator() });
          return api.post('/api/v1/proposals/apply', { proposal_id: entry.data.proposal_id, operator_id: getOperator() });
        }, { errorPrefix: 'Không cắt được: ' });
        if (disposed) return;
        if (result) {
          entry.status = 'applied';
          toast(`Đã cắt ${fmt.hz(p.f)} trên ${fmt.ch(p.ch)} và xác minh trên mixer.`, 'ok');
          store.refreshStatus();
          loadAll({ quiet: true });
        }
        if (key === fbFocusKey) renderProposalBox();
        chartDirty = true; requestDraw();
      } finally {
        applying = false;
      }
    }

    // ---------- Tabs (EQ by role / gain staging / bleed) ----------
    const tabsEl = $('#mxTabs', root);
    tabsEl.addEventListener('click', (e) => {
      const b = e.target.closest('[data-tab]');
      if (!b) return;
      tabs.active = b.dataset.tab;
      showTab();
    });
    function showTab() {
      $$('[data-tab]', tabsEl).forEach(x => x.classList.toggle('active', x.dataset.tab === tabs.active));
      $$('[data-pane]', detailEl).forEach(p => { p.hidden = p.dataset.pane !== tabs.active; });
      loadPane(tabs.active);
    }
    function resetTabs() {
      tabs.loaded = new Set();
      $$('[data-pane]', detailEl).forEach(p => { p.innerHTML = ''; });
      showTab();
    }
    function loadPane(tab) {
      if (tabs.loaded.has(tab) || !chById(selected)) return;
      tabs.loaded.add(tab);
      const pane = $(`[data-pane="${tab}"]`, detailEl);
      const n = selected;
      if (tab === 'eq') renderEqPane(pane, n);
      else if (tab === 'gain') renderGainPane(pane, n);
      else if (tab === 'bleed') renderBleedPane(pane, n);
    }
    $$('[data-go]', detailEl).forEach(b => b.addEventListener('click', () => ctx.navigate('wizards', { w: b.dataset.go, ch: String(selected) })));

    // A/B curve preview for EQ proposals
    function mountCurve(container, curve, height = 140) {
      if (!container) return;
      if (!Array.isArray(curve) || !curve.length) { container.innerHTML = ''; return; }
      container.innerHTML = `
        <div class="rta-wrap" style="height:${height}px"><canvas aria-label="Đáp tuyến EQ trước và sau"></canvas></div>
        <div class="row small muted mt-8">
          <span class="row" style="gap:6px"><span style="display:inline-block;width:16px;border-top:2px dashed #64748b"></span>A · hiện tại (phẳng)</span>
          <span class="row" style="gap:6px"><span style="display:inline-block;width:16px;border-top:2px solid #2fbf71"></span>B · sau khi áp dụng (mô phỏng)</span>
        </div>`;
      const canvas = $('canvas', container);
      const n = curve.length;
      const pts = curve.map((p, i) => ({
        freq: Number.isFinite(+p.freq) ? +p.freq : 20 * Math.pow(1000, n > 1 ? i / (n - 1) : 0),
        db: +p.response_db || 0,
      }));
      const series = [
        { points: pts.map(p => ({ freq: p.freq, db: 0 })), color: '#64748b', width: 1.5, dash: [4, 4] },
        { points: pts, color: '#2fbf71', width: 2 },
      ];
      const draw = () => { if (canvas.isConnected) drawCurve(canvas, series, { minDb: -18, maxDb: 18 }); else curveRedraws.delete(draw); };
      curveRedraws.add(draw);
      requestAnimationFrame(draw);
    }

    function roleOptions(sel) {
      return ROLES.map(([v, l]) => `<option value="${v}" ${v === sel ? 'selected' : ''}>${esc(l)}</option>`).join('');
    }

    async function generateRole(channelId, role, btn, resultEl, curveEl) {
      if (+channelId === talkbackCh) {
        const ok = await confirmDialog({
          title: 'Kênh talkback được bảo vệ',
          message: `${esc(fmt.ch(channelId))} là talkback ban nhạc (DL16 #11), chỉ đi P16. Vẫn tạo đề xuất EQ cho kênh này?`,
          confirmText: 'Vẫn tạo',
        });
        if (!ok) return;
      }
      const data = await withLoading(btn, () => api.post('/api/v1/proposals/generate-role', { channel_id: +channelId, role }),
        { errorPrefix: 'Không tạo được đề xuất EQ: ' });
      if (!data || disposed || !resultEl.isConnected) return;
      renderEqResult(data, resultEl, curveEl);
    }

    function renderEqResult(data, resultEl, curveEl) {
      const d = data.tuning_detail || {};
      const bands = d.bands || [];
      mountCurve(curveEl, d.simulated_curve);
      const items = [];
      if (+d.hpf_freq_hz > 0) {
        items.push(`<li><strong>Lọc cắt trầm (HPF) ${esc(fmt.hz(d.hpf_freq_hz))}</strong> — bỏ tiếng ù, tiếng bước chân và rung sàn bên dưới tần số này.</li>`);
      }
      bands.forEach(b => {
        const q = +b.q;
        items.push(`<li><strong>Dải ${esc(b.band)}: ${esc(gainWord(+b.gain_db))} ${esc(signed(b.gain_db))} dB tại ${esc(fmt.hz(b.freq_hz))}</strong>,
          Q=${esc(fmt.num(q))} (${esc(qLabel(q))})${b.rationale ? ` — ${esc(b.rationale)}` : ''}</li>`);
      });
      resultEl.innerHTML = `
        <div class="stack-sm">
          <div class="row">${badge(ROLE_LABEL[d.role] || d.role || 'EQ', 'info')}<span class="small muted mono">${esc(data.proposal_id || '')}</span></div>
          ${items.length ? `<div><div class="label">Vì sao đề xuất như vậy</div><ul class="small text-2" style="margin:6px 0 0;padding-left:18px">${items.join('')}</ul></div>` : ''}
          <div data-prop></div>
        </div>`;
      renderProposal($('[data-prop]', resultEl), data, {
        title: `EQ cho ${ROLE_LABEL[d.role] || 'kênh'}`,
        onApplied: () => { if (curveEl) curveEl.innerHTML = ''; loadAll({ quiet: true }); },
        onDismiss: () => { if (curveEl) curveEl.innerHTML = ''; resultEl.innerHTML = emptyState('Đã bỏ qua đề xuất.'); },
      });
    }

    function renderEqPane(pane, n) {
      const ch = chById(n);
      const def = eqRoleFor(ch?.church_role) || 'PASTOR_SPEECH';
      pane.innerHTML = `
        <div class="grid-2">
          <div class="stack-sm">
            <p class="small text-2">Tạo EQ khởi điểm an toàn cho <strong>${esc(fmt.ch(n))}</strong> theo loại nguồn âm. Bạn xem trước đáp tuyến (A/B) rồi mới quyết định.</p>
            <div class="row">
              <select class="select grow" data-role name="mxRole" aria-label="Vai trò nguồn âm" style="width:auto">${roleOptions(def)}</select>
              <button class="btn btn-primary" data-gen>${icon('wand')}Tạo đề xuất</button>
            </div>
            ${n !== 1 && chById(1) ? `<div><button class="btn btn-ghost btn-sm" data-pastor title="Chuyển sang Kênh 1 và tạo EQ giọng nói Mục sư">Nhanh: Mục sư (Kênh 1)</button></div>` : ''}
            <div data-curve></div>
          </div>
          <div data-result>${emptyState('Chưa có đề xuất. Chọn vai trò rồi bấm "Tạo đề xuất".')}</div>
        </div>`;
      $('[data-gen]', pane).addEventListener('click', (e) =>
        generateRole(n, $('[data-role]', pane).value, e.currentTarget, $('[data-result]', pane), $('[data-curve]', pane)));
      $('[data-pastor]', pane)?.addEventListener('click', () => {
        selectChannel(1, { user: true, fromAlert: true });
        const p2 = $('[data-pane="eq"]', detailEl);
        const sel = $('[data-role]', p2);
        if (sel) sel.value = 'PASTOR_SPEECH';
        generateRole(1, 'PASTOR_SPEECH', $('[data-gen]', p2), $('[data-result]', p2), $('[data-curve]', p2));
      });
    }

    async function renderGainPane(pane, n) {
      pane.innerHTML = loadingRows(4);
      let r;
      try { r = await api.get(`/api/v1/gain-staging/${n}`); } catch (e) {
        if (!pane.isConnected || selected !== n) return;
        pane.innerHTML = `${errorBox(e)}<div class="mt-8"><button class="btn btn-sm" data-retry>${icon('refresh')}Thử lại</button></div>`;
        $('[data-retry]', pane).addEventListener('click', () => renderGainPane(pane, n));
        return;
      }
      if (!pane.isConnected || selected !== n || disposed) return;
      const [hText, hKind, barKind] = HEALTH[r.health_status] || [r.health_status || '—', 'info', ''];
      const pct = Math.min(100, Math.max(0, ((+r.peak_dbfs + 40) / 40) * 100));
      const delta = +r.recommended_trim_delta_db || 0;
      pane.innerHTML = `
        <div class="stack-sm">
          ${r.source?.simulated ? callout('warn', 'Dữ liệu mô phỏng — chưa đo đầu vào thật của kênh này.') : ''}
          <div class="row-between"><strong>Headroom &amp; mức vào — ${esc(fmt.ch(n))}</strong>${badge(hText, hKind)}</div>
          <div class="grid-3">
            <div class="stat"><div class="stat-label">Đỉnh (peak)</div><div class="stat-value" style="font-size:18px">${esc(signed(r.peak_dbfs))}</div><div class="stat-sub">dBFS · mục tiêu ${esc(signed(r.target_peak_dbfs))}</div></div>
            <div class="stat"><div class="stat-label">Trung bình (RMS)</div><div class="stat-value" style="font-size:18px">${esc(signed(r.rms_dbfs))}</div><div class="stat-sub">dBFS · crest ${esc(fmt.num(r.crest_factor_db))} dB</div></div>
            <div class="stat"><div class="stat-label">Khoảng dự trữ</div><div class="stat-value" style="font-size:18px">${esc(fmt.num(r.headroom_db))} dB</div><div class="stat-sub">trước khi bị méo (clip)</div></div>
          </div>
          <div class="bar ${barKind}" title="Đỉnh tín hiệu trên thang −40…0 dBFS"><span style="width:${pct.toFixed(0)}%"></span></div>
          ${r.advice_vi ? callout('info', esc(r.advice_vi)) : ''}
          <dl class="kv">
            <dt>Trim hiện tại</dt><dd class="mono">${esc(signed(r.current_trim_db))} dB</dd>
            <dt>Trim đề xuất</dt><dd class="mono">${esc(signed(r.proposed_trim_db))} dB <span class="small muted">(${delta > 0 ? 'tăng' : delta < 0 ? 'giảm' : 'giữ nguyên'} ${esc(fmt.num(Math.abs(delta)))} dB)</span></dd>
          </dl>
          <div class="row">
            <button class="btn btn-primary" data-propose>${icon('sliders')}Tạo đề xuất chỉnh trim</button>
            <button class="btn btn-ghost btn-sm" data-reload>${icon('refresh')}Đo lại</button>
          </div>
          ${Math.abs(delta) < 0.1 ? '<p class="small muted">Mức vào đã gần mục tiêu — thường không cần chỉnh.</p>' : ''}
          <div data-prop></div>
        </div>`;
      $('[data-reload]', pane).addEventListener('click', () => renderGainPane(pane, n));
      $('[data-propose]', pane).addEventListener('click', async (e) => {
        const data = await withLoading(e.currentTarget, () => api.post(`/api/v1/gain-staging/${n}/propose-trim`),
          { errorPrefix: 'Không tạo được đề xuất trim: ' });
        if (!data || !pane.isConnected) return;
        renderProposal($('[data-prop]', pane), data, {
          title: 'Chỉnh digital trim',
          note: 'Trim thay đổi mức vào của cả kênh (ảnh hưởng FOH, monitor và livestream). Chỉ áp dụng khi người nói/hát đang ở mức bình thường.',
          onApplied: () => loadAll({ quiet: true }),
        });
      });
    }

    async function renderBleedPane(pane, n) {
      if (n === talkbackCh || n === DEFAULT_TALKBACK_CH) {
        pane.innerHTML = callout('warn', `<strong>Không áp dụng cho kênh này.</strong> ${esc(fmt.ch(n))} là kênh talkback được bảo vệ — hệ thống không phân tích rò âm hay đặt expander/gate cho kênh này.`, 'shield');
        return;
      }
      pane.innerHTML = loadingRows(4);
      let r;
      try { r = await api.get(`/api/v1/bleed-analysis/${n}`); } catch (e) {
        if (!pane.isConnected || selected !== n) return;
        pane.innerHTML = `${errorBox(e)}<div class="mt-8"><button class="btn btn-sm" data-retry>${icon('refresh')}Thử lại</button></div>`;
        $('[data-retry]', pane).addEventListener('click', () => renderBleedPane(pane, n));
        return;
      }
      if (!pane.isConnected || selected !== n || disposed) return;
      const [riskText, riskKind] = COMB_RISK[r.comb_filtering_risk] || [r.comb_filtering_risk || '—', 'info'];
      const x = r.recommended_expander || r.expander_settings || {};
      const src = r.bleed_source_name || r.dominant_bleed_source;
      const floor = r.ambient_noise_floor_dbfs ?? r.estimated_noise_floor_dbfs;
      const advice = r.advice_vi || r.tactical_advice_vi;
      pane.innerHTML = `
        <div class="stack-sm">
          <div class="row-between"><strong>Rò âm sân khấu vào mic — ${esc(fmt.ch(n))}</strong><span class="row" style="gap:6px"><span class="small muted">Nguy cơ méo pha (comb):</span>${badge(riskText, riskKind)}</span></div>
          <div class="grid-3">
            <div class="stat"><div class="stat-label">Nguồn rò chính</div><div class="stat-value" style="font-size:15px">${esc(src || 'Không đáng kể')}</div><div class="stat-sub">${r.bleed_source_channel_id ? esc(fmt.ch(r.bleed_source_channel_id)) : ''}</div></div>
            <div class="stat"><div class="stat-label">Mức rò so với giọng</div><div class="stat-value" style="font-size:18px">${esc(signed(r.relative_bleed_level_db))} dB</div><div class="stat-sub">càng âm càng ít rò</div></div>
            <div class="stat"><div class="stat-label">Tiếng nền</div><div class="stat-value" style="font-size:18px">${esc(fmt.num(floor))}</div><div class="stat-sub">dBFS khi không nói</div></div>
          </div>
          <dl class="kv">
            <dt>Tương quan với nguồn rò</dt><dd class="mono">${esc(fmt.num(r.correlation_coeff, 2))} <span class="small muted">(${esc(PHASE[r.phase_alignment_status] || r.phase_alignment_status || '—')})</span></dd>
          </dl>
          ${advice ? callout('info', esc(advice)) : ''}
          <div>
            <div class="label">Expander đề xuất (hạ nhẹ khi không nói, không cắt cứng như gate)</div>
            <dl class="kv mt-8">
              <dt>Ngưỡng</dt><dd class="mono">${esc(fmt.num(x.threshold_dbfs ?? x.threshold_db))} dBFS <span class="small muted">— dưới mức này mic được hạ xuống</span></dd>
              <dt>Mức hạ</dt><dd class="mono">${esc(fmt.num(x.range_db))} dB <span class="small muted">— hạ nhẹ, vẫn nghe tự nhiên</span></dd>
              <dt>Attack / Hold / Release</dt><dd class="mono">${esc(fmt.num(x.attack_ms, 0))} / ${esc(fmt.num(x.hold_ms, 0))} / ${esc(fmt.num(x.release_ms, 0))} ms</dd>
              <dt>Lọc sidechain</dt><dd class="mono">${x.filter_on === false ? 'Tắt' : esc(fmt.hz(x.filter_freq_hz ?? x.sidechain_filter_freq_hz))} <span class="small muted">— bỏ qua tiếng trống/rung sàn khi quyết định mở</span></dd>
            </dl>
          </div>
          <div class="row">
            <button class="btn btn-primary" data-propose>${icon('sliders')}Tạo đề xuất expander</button>
            <button class="btn btn-ghost btn-sm" data-reload>${icon('refresh')}Phân tích lại</button>
          </div>
          <p class="small muted">Ưu tiên chỉnh vị trí mic và monitor trước; expander chỉ giảm phần rò còn lại.</p>
          <div data-prop></div>
        </div>`;
      $('[data-reload]', pane).addEventListener('click', () => renderBleedPane(pane, n));
      $('[data-propose]', pane).addEventListener('click', async (e) => {
        const data = await withLoading(e.currentTarget, () => api.post(`/api/v1/bleed-analysis/${n}/propose-expander`),
          { errorPrefix: 'Không tạo được đề xuất expander: ' });
        if (!data || !pane.isConnected) return;
        const box = $('[data-prop]', pane);
        if (!data.proposal) { box.innerHTML = callout('ok', 'Hệ thống không thấy cần thay đổi expander cho kênh này.'); return; }
        renderProposal(box, data.proposal, { title: 'Downward expander', onApplied: () => loadAll({ quiet: true }) });
      });
    }

    // ---------- Wire up & initial load ----------
    $('#mxRefresh', root).addEventListener('click', (e) => withLoading(e.currentTarget, async () => {
      const ok = await loadAll();
      if (ok) toast('Đã cập nhật trạng thái 32 kênh.', 'ok');
    }));

    const want = +ctx.params?.get('ch');
    if (want >= 1 && want <= 32) selected = want;
    loadAll().then((ok) => {
      if (!ok || disposed) return;
      if (!chById(selected)) selected = +channels[0]?.channel || 1;
      markSelected();
      renderSide();
      resetTabs();
      if (want >= 1 && want <= 32) {
        centerStrip(want);
        detailEl.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }
    });
    const reloadTimer = setInterval(() => {
      if (!document.hidden && !disposed && !applying && !document.querySelector('.overlay')) loadAll({ quiet: true });
    }, RELOAD_MS);
    if (pending) scheduleFrame();

    // ---------- Cleanup ----------
    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (resizeRaf) cancelAnimationFrame(resizeRaf);
      raf = 0; resizeRaf = 0;
      clearInterval(holdTimer);
      clearInterval(reloadTimer);
      unsubs.forEach(u => u());
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('resize', onResize);
      ro?.disconnect();
      curveRedraws.clear();
      segCleanup && segCleanup();
    };
  },
};
