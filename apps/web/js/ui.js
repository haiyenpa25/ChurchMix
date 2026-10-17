// Shared UI helpers and components. Views build markup as template strings
// using the classes in assets/app.css and these helpers; no framework.

import { icon } from './icons.js';
import { api, getOperator } from './api.js';

export { icon };

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Create a DOM node from an HTML string (first element). */
export function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export const fmt = {
  db: (v, digits = 1) => (v === null || v === undefined || Number.isNaN(+v)) ? '—' : `${(+v).toFixed(digits)} dB`,
  num: (v, digits = 1) => (v === null || v === undefined || Number.isNaN(+v)) ? '—' : (+v).toFixed(digits),
  pct: (v) => (v === null || v === undefined) ? '—' : `${Math.round(+v * (v <= 1 ? 100 : 1))}%`,
  hz: (v) => (v === null || v === undefined) ? '—' : (+v >= 1000 ? `${(+v / 1000).toFixed(+v >= 10000 ? 0 : 1)} kHz` : `${Math.round(+v)} Hz`),
  ch: (n) => `Kênh ${String(n).padStart(2, '0')}`,
  time: (ts) => {
    if (!ts) return '—';
    const d = typeof ts === 'number' ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
    return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString('vi-VN');
  },
};

// ---------- Status mapping ----------
const STATUS_KIND = {
  PASS: 'ok', OK: 'ok', SAFE: 'ok', READY: 'ok', SUCCESS: 'ok', COMMITTED: 'ok', HEALTHY: 'ok', COMPLIANT: 'ok', ON_TARGET: 'ok', CONNECTED: 'ok',
  WARN: 'warn', WARNING: 'warn', TOO_QUIET: 'warn', TOO_LOUD: 'warn', DRIFT: 'warn', DEGRADED: 'warn', MUTED: 'warn', PENDING: 'warn',
  FAIL: 'bad', FAILED: 'bad', ERROR: 'bad', CRITICAL: 'bad', VIOLATION: 'bad', REJECTED: 'bad', UNSAFE: 'bad', CLIPPING: 'bad', ROLLED_BACK: 'bad',
};
export function statusKind(status) {
  if (status === true) return 'ok';
  if (status === false) return 'bad';
  const s = String(status || '').toUpperCase();
  if (STATUS_KIND[s]) return STATUS_KIND[s];
  if (/FAIL|ERROR|CRIT|VIOL|UNSAFE|CLIP|DANGER|HIGH/.test(s)) return 'bad';
  if (/WARN|QUIET|LOUD|DRIFT|MEDIUM|CAUTION/.test(s)) return 'warn';
  if (/PASS|OK|SAFE|READY|GOOD|LOW|HEALTH/.test(s)) return 'ok';
  return 'info';
}
export function badge(text, kind = 'info') {
  return `<span class="badge badge-${kind}">${esc(text)}</span>`;
}
export function statusBadge(status, label) {
  return badge(label ?? status, statusKind(status));
}

// ---------- Building blocks ----------
export function card({ title, sub = '', actions = '', body = '', foot = '', cls = '', id = '' }) {
  return `
  <section class="card ${cls}" ${id ? `id="${id}"` : ''}>
    ${title ? `<header class="card-head"><h3>${title}${sub ? `<span class="card-sub">${sub}</span>` : ''}</h3>${actions}</header>` : ''}
    <div class="card-body">${body}</div>
    ${foot ? `<footer class="card-foot">${foot}</footer>` : ''}
  </section>`;
}

export function callout(kind, html, iconName) {
  const ic = iconName || { ok: 'checkCircle', warn: 'alert', bad: 'xCircle', info: 'info' }[kind] || 'info';
  return `<div class="callout callout-${kind}">${icon(ic)}<div class="grow">${html}</div></div>`;
}

export function pageHead(title, desc = '', actions = '') {
  return `<div class="page-head"><div class="page-title"><h1>${title}</h1>${desc ? `<p>${desc}</p>` : ''}</div><div class="row">${actions}</div></div>`;
}

export function emptyState(text = 'Chưa có dữ liệu.') {
  return `<div class="empty">${esc(text)}</div>`;
}

export function loadingRows(n = 3) {
  return `<div class="stack-sm">${Array.from({ length: n }, () => '<div class="skeleton"></div>').join('')}</div>`;
}

export function errorBox(err) {
  return callout('bad', `<strong>Không tải được dữ liệu.</strong><div class="small">${esc(err?.message || err)}</div>`);
}

// ---------- Async button helper ----------
/** Disables the button and shows a spinner while fn runs. Errors become a toast. Returns fn's result or undefined. */
export async function withLoading(btn, fn, { errorPrefix = '' } = {}) {
  if (btn) { btn.classList.add('loading'); btn.disabled = true; }
  try {
    return await fn();
  } catch (e) {
    toast(`${errorPrefix}${e.message || e}`, 'bad');
    return undefined;
  } finally {
    if (btn) { btn.classList.remove('loading'); btn.disabled = false; }
  }
}

// ---------- Toasts ----------
let toastRoot = null;
export function toast(message, kind = 'info', timeout = 4500) {
  if (!toastRoot) {
    toastRoot = el('<div class="toasts" role="status" aria-live="polite"></div>');
    document.body.appendChild(toastRoot);
  }
  const ic = { ok: 'checkCircle', warn: 'alert', bad: 'xCircle', info: 'info' }[kind] || 'info';
  const t = el(`<div class="toast ${kind}">${icon(ic)}<div class="grow">${esc(message)}</div></div>`);
  toastRoot.appendChild(t);
  setTimeout(() => t.remove(), timeout);
}

// ---------- Dialogs ----------
/**
 * openDialog({ title, body, wide, drawer, actions:[{label, kind, onClick(close, btn), id}], onClose })
 * body: HTML string or Node. Returns { root, body, close }.
 */
export function openDialog({ title, body = '', wide = false, drawer = false, actions = [], onClose } = {}) {
  const overlay = el(`
    <div class="overlay ${drawer ? 'drawer' : ''}" role="dialog" aria-modal="true">
      <div class="dialog ${wide ? 'wide' : ''}">
        <div class="dialog-head"><h3>${title || ''}</h3><button class="btn btn-ghost btn-icon" data-close aria-label="Đóng">${icon('x')}</button></div>
        <div class="dialog-body"></div>
        ${actions.length ? '<div class="dialog-foot"></div>' : ''}
      </div>
    </div>`);
  const bodyEl = $('.dialog-body', overlay);
  if (typeof body === 'string') bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);

  const close = () => {
    overlay.remove();
    document.removeEventListener('keydown', onKey);
    onClose && onClose();
  };
  // Only the top-most dialog reacts to Escape (a confirm over a drawer must not close both).
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    const overlays = document.querySelectorAll('.overlay');
    if (overlays[overlays.length - 1] === overlay) close();
  };
  document.addEventListener('keydown', onKey);
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
  $('[data-close]', overlay).addEventListener('click', close);

  const foot = $('.dialog-foot', overlay);
  actions.forEach(a => {
    const b = el(`<button class="btn ${a.kind ? `btn-${a.kind}` : ''}" ${a.id ? `id="${a.id}"` : ''}>${a.label}</button>`);
    b.addEventListener('click', () => a.onClick ? a.onClick(close, b) : close());
    foot.appendChild(b);
  });

  document.body.appendChild(overlay);
  setTimeout(() => (overlay.querySelector('[autofocus]') || overlay.querySelector('.dialog-foot .btn:last-child'))?.focus(), 0);
  return { root: overlay, body: bodyEl, close };
}

/** Promise<boolean>. Use before every write to the mixer. */
export function confirmDialog({ title = 'Xác nhận', message = '', confirmText = 'Đồng ý', cancelText = 'Hủy', danger = false } = {}) {
  return new Promise(resolve => {
    let done = false;
    const finish = (v, close) => { if (!done) { done = true; resolve(v); } close(); };
    openDialog({
      title,
      body: `<div class="text-2">${message}</div>`,
      actions: [
        { label: cancelText, kind: 'ghost', onClick: (close) => finish(false, close) },
        { label: confirmText, kind: danger ? 'danger' : 'primary', onClick: (close) => finish(true, close) },
      ],
      onClose: () => { if (!done) { done = true; resolve(false); } },
    });
  });
}

// ---------- Downloads ----------
export function downloadText(filename, text, mime = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = el(`<a href="${url}" download="${esc(filename)}"></a>`);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- Minimal Markdown (wizard reports) ----------
export function renderMarkdown(md = '') {
  const lines = String(md).replace(/\r/g, '').split('\n');
  const out = [];
  let list = false;
  let table = null;
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
  const flushList = () => { if (list) { out.push('</ul>'); list = false; } };
  const flushTable = () => {
    if (!table) return;
    const rows = table.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r));
    const cells = (r) => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => inline(c.trim()));
    out.push('<div class="table-wrap"><table><thead><tr>' + cells(rows[0]).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' +
      rows.slice(1).map(r => '<tr>' + cells(r).map(c => `<td>${c}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>');
    table = null;
  };
  for (const line of lines) {
    if (/^\s*\|.*\|\s*$/.test(line)) { flushList(); (table ||= []).push(line); continue; }
    flushTable();
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { flushList(); out.push(`<h${Math.min(h[1].length, 3)}>${inline(h[2])}</h${Math.min(h[1].length, 3)}>`); continue; }
    if (/^\s*[-*]\s+/.test(line)) { if (!list) { out.push('<ul>'); list = true; } out.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ''))}</li>`); continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) { flushList(); out.push('<hr>'); continue; }
    if (!line.trim()) { flushList(); continue; }
    flushList();
    out.push(`<p>${inline(line)}</p>`);
  }
  flushList(); flushTable();
  return `<div class="md">${out.join('\n')}</div>`;
}

// ---------- Proposal review (shared by EQ, notch, trim, expander, automix, monitors) ----------
/**
 * Renders a proposal returned by any /propose* or /generate-* endpoint into `container`
 * with a changes table and an "Áp dụng" button gated by a confirm dialog.
 * Apply always goes through POST /api/v1/proposals/apply (server Safety Gate).
 * opts: { title, onApplied(result), onDismiss(), note }
 */
export function renderProposal(container, proposal, opts = {}) {
  if (!proposal) { container.innerHTML = ''; return; }
  const changes = proposal.changes || [];
  const detail = proposal.tuning_detail || {};
  const tradeoffs = detail.expected_tradeoffs || proposal.expected_tradeoffs || [];
  container.innerHTML = `
    <div class="stack-sm">
      <div class="row-between">
        <div class="row">${icon('wand')}<strong>${esc(opts.title || 'Đề xuất điều chỉnh')}</strong>
          ${proposal.target_channel ? badge(fmt.ch(proposal.target_channel), 'info') : ''}</div>
        ${proposal.confidence !== undefined ? `<span class="small muted">Độ tin cậy ${fmt.pct(proposal.confidence)}</span>` : ''}
      </div>
      ${proposal.hypothesis ? `<p class="text-2">${esc(proposal.hypothesis)}</p>` : ''}
      ${changes.length ? `
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Tham số OSC</th><th class="right">Hiện tại</th><th class="right">Đề xuất</th></tr></thead>
        <tbody>${changes.map(c => `<tr><td class="mono">${esc(c.parameter)}</td><td class="right mono">${esc(fmtVal(c.from))}</td><td class="right mono">${esc(fmtVal(c.to))}</td></tr>`).join('')}</tbody>
      </table></div>` : ''}
      ${tradeoffs.length ? `<ul class="small text-2" style="margin:0;padding-left:18px">${tradeoffs.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : ''}
      ${opts.note ? `<p class="small muted">${opts.note}</p>` : ''}
      <div class="row">
        <button class="btn btn-primary" data-apply>${icon('shieldCheck')}Duyệt &amp; áp dụng</button>
        <button class="btn btn-ghost" data-dismiss>Bỏ qua</button>
        <span class="small muted">Lệnh đi qua Safety Gate: kiểm tra, ghi chậm, đọc lại, tự hoàn tác nếu sai.</span>
      </div>
    </div>`;
  $('[data-dismiss]', container).addEventListener('click', () => { container.innerHTML = ''; opts.onDismiss && opts.onDismiss(); });
  $('[data-apply]', container).addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const ok = await confirmDialog({
      title: 'Áp dụng thay đổi lên mixer?',
      message: `Sẽ ghi <strong>${changes.length}</strong> tham số${proposal.target_channel ? ` cho <strong>${fmt.ch(proposal.target_channel)}</strong>` : ''}.<br>
        Người duyệt: <strong>${esc(getOperator())}</strong>. Mixer phải ở chế độ <strong>ASSIST</strong> trở lên.`,
      confirmText: 'Áp dụng',
    });
    if (!ok) return;
    const result = await withLoading(btn, () =>
      api.post('/api/v1/proposals/apply', { proposal_id: proposal.proposal_id, operator_id: getOperator() }),
      { errorPrefix: 'Không áp dụng được: ' });
    if (result) {
      toast('Đã áp dụng và xác minh trên mixer.', 'ok');
      container.innerHTML = callout('ok', `Đã áp dụng đề xuất <span class="mono">${esc(proposal.proposal_id)}</span>.`);
      opts.onApplied && opts.onApplied(result);
    }
  });
}

function fmtVal(v) {
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (v === null || v === undefined) return '—';
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}

// ---------- Small chart: EQ / curve preview on canvas ----------
/**
 * drawCurve(canvas, series, {minDb, maxDb})
 * series: [{ points:[{freq, db}], color, width, dash }]  — log-frequency x axis 20 Hz..20 kHz.
 */
export function drawCurve(canvas, series, { minDb = -15, maxDb = 15 } = {}) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const x = (f) => (Math.log10(Math.max(20, f)) - Math.log10(20)) / (Math.log10(20000) - Math.log10(20)) * w;
  const y = (db) => h - ((db - minDb) / (maxDb - minDb)) * h;
  ctx.strokeStyle = '#1f2937'; ctx.lineWidth = 1; ctx.fillStyle = '#64748b'; ctx.font = '10px ui-monospace, Consolas, monospace';
  [100, 1000, 10000].forEach(f => { ctx.beginPath(); ctx.moveTo(x(f), 0); ctx.lineTo(x(f), h); ctx.stroke(); ctx.fillText(f >= 1000 ? `${f / 1000}k` : `${f}`, x(f) + 3, h - 4); });
  ctx.beginPath(); ctx.moveTo(0, y(0)); ctx.lineTo(w, y(0)); ctx.stroke();
  series.forEach(s => {
    if (!s.points?.length) return;
    ctx.strokeStyle = s.color || '#4f8cff'; ctx.lineWidth = s.width || 2; ctx.setLineDash(s.dash || []);
    ctx.beginPath();
    s.points.forEach((p, i) => { const px = x(p.freq), py = y(p.db); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke(); ctx.setLineDash([]);
  });
}
