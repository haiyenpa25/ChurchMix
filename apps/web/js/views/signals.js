// Giám sát tín hiệu: mức Peak/RMS của 32 đầu vào, headroom, thời gian vượt ngưỡng.
// Chỉ đọc — chỉnh ngưỡng không gửi OSC và không thay đổi mixer.
// Backend: packages/monitoring (GET /api/v1/monitoring/analysis, PUT /api/v1/monitoring/thresholds);
// khung đo trực tiếp đến qua telemetry.analysis của WebSocket dùng chung.

import { api } from '../api.js';
import { store } from '../store.js';
import { $, esc, icon, pageHead, card, callout, withLoading, toast, downloadText } from '../ui.js';

const LABELS = { NORMAL: 'Dưới ngưỡng', WARNING: 'Cảnh báo', CRITICAL: 'Nguy hiểm', CLIP_RISK: 'Sát clipping', SILENT: 'Ít tín hiệu / nghỉ', UNKNOWN: 'Chưa đo được' };
const COLORS = { NORMAL: '#38bdf8', WARNING: '#f5a524', CRITICAL: '#fb7185', CLIP_RISK: '#ef4444', SILENT: '#64748b', UNKNOWN: '#475569' };
const BADGE = { NORMAL: 'info', WARNING: 'warn', CRITICAL: 'bad', CLIP_RISK: 'bad', SILENT: '', UNKNOWN: '' };
const PRIORITY = { CLIP_RISK: 0, CRITICAL: 1, WARNING: 2, UNKNOWN: 3, NORMAL: 4, SILENT: 5 };
const OVER = ['WARNING', 'CRITICAL', 'CLIP_RISK'];

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const db = (v) => (finite(v) ? `${v.toFixed(1)} dBFS` : '—');
const secs = (v) => (finite(v) ? `${v.toFixed(1)} s` : '—');
const tag = (s) => `<span class="badge ${BADGE[s] ? `badge-${BADGE[s]}` : ''}">${esc(LABELS[s] || s)}</span>`;

function legend() {
  return `<div class="row small muted mt-8">${['NORMAL', 'WARNING', 'CRITICAL', 'CLIP_RISK', 'UNKNOWN'].map(s =>
    `<span class="row" style="gap:6px"><span style="width:10px;height:10px;border-radius:2px;background:${COLORS[s]};display:inline-block"></span>${LABELS[s]}</span>`).join('')}</div>`;
}

export default {
  mount(root) {
    let alive = true;
    let latest = null;
    let lastReceived = 0;
    let history = [];
    let session = null;
    let selected = 1;
    let rafPending = false;
    let lastRender = 0;
    let inFlight = null;
    let channelSig = '';

    root.innerHTML = `
      ${pageHead('Giám sát tín hiệu', 'Đầu vào nào đang vượt ngưỡng? Theo dõi mức tín hiệu, headroom và các đỉnh lớn theo thời gian.',
        `<button class="btn" data-export>${icon('download')}Xuất báo cáo CSV</button>`)}
      <div data-source></div>
      <div class="grid-4 mt-16" data-kpis></div>
      <div class="grid-2 mt-16">
        <div class="span-2">${card({
          title: 'Mức Peak của 32 đầu vào',
          sub: 'Bấm vào cột để chọn đầu vào. Vạch đứt là ngưỡng; vạch trắng nhỏ là peak cao nhất của phiên.',
          actions: '<span class="small muted" data-updated>Chưa cập nhật</span>',
          body: `<div class="rta-wrap" style="height:240px"><canvas data-levels role="img" aria-label="Biểu đồ Peak 32 đầu vào"></canvas></div>${legend()}`,
        })}</div>
        ${card({
          title: 'Diễn biến 2 phút gần nhất',
          sub: 'Peak (đỉnh tức thời) và RMS (mức trung bình) của đầu vào đang chọn',
          actions: '<select class="select" data-select style="width:auto" aria-label="Chọn đầu vào"></select>',
          body: `<div class="rta-wrap" style="height:220px"><canvas data-trend role="img" aria-label="Lịch sử Peak và RMS 120 giây"></canvas></div>
            <div class="row small muted mt-8"><span class="row" style="gap:6px"><span style="width:14px;height:3px;background:#38bdf8;display:inline-block"></span>Peak</span>
              <span class="row" style="gap:6px"><span style="width:14px;height:3px;background:#a78bfa;display:inline-block"></span>RMS</span></div>
            <dl class="kv mt-16" data-facts></dl><p class="small text-2 mt-8" data-advice>Đang chờ dữ liệu.</p>`,
        })}
        ${card({
          title: 'Vượt ngưỡng lâu nhất',
          sub: 'Thời gian quan sát vượt ngưỡng trong phiên (ước lượng theo khung đo, không phải số sample clipping)',
          body: '<div class="rta-wrap" style="height:220px;background:transparent;border:0"><canvas data-durations role="img" aria-label="Xếp hạng thời gian vượt ngưỡng"></canvas></div>',
        })}
        <div class="span-2">${card({
          title: 'Phân tích từng đầu vào',
          sub: 'Đầu vào cần chú ý được đưa lên trước. Bấm một dòng để xem lịch sử.',
          actions: '<label class="check small"><input type="checkbox" data-only-alerts>Chỉ xem vượt ngưỡng / chưa đo được</label>',
          body: `<div class="table-wrap"><table class="table">
            <thead><tr><th>Đầu vào / nguồn</th><th>Trạng thái</th><th class="right">Peak / RMS</th><th class="right">Headroom</th><th class="right">Vượt liên tục</th><th>Phân tích &amp; bước kiểm tra</th></tr></thead>
            <tbody data-table><tr><td colspan="6" class="muted">Đang chờ dữ liệu đo…</td></tr></tbody></table></div>`,
        })}</div>
        ${card({
          title: 'Ngưỡng theo dõi',
          sub: 'dBFS: càng gần 0 tín hiệu càng lớn. Không đo nhiệt độ, SPL hay chứng minh có hú.',
          body: `<form class="form-grid" data-thresholds>
              <div class="field"><label>Cảnh báo (dBFS)</label><input class="input" name="warning" type="number" min="-60" max="0" step="0.5" value="-12" required></div>
              <div class="field"><label>Nguy hiểm (dBFS)</label><input class="input" name="critical" type="number" min="-60" max="0" step="0.5" value="-6" required></div>
              <div class="field"><label>Sát clipping (dBFS)</label><input class="input" name="clip" type="number" min="-60" max="0" step="0.5" value="-0.5" required></div>
              <div class="field" style="justify-content:flex-end"><button class="btn btn-primary" type="submit">Cập nhật ngưỡng</button></div>
            </form>
            <p class="small muted mt-8">Điều kiện: −60 ≤ cảnh báo &lt; nguy hiểm &lt; sát clipping ≤ 0. Đổi ngưỡng bắt đầu phiên thống kê mới, chỉ giữ trong phiên máy chủ và <strong>không thay đổi mixer</strong>.</p>`,
        })}
        ${card({ title: 'Nhật ký chuyển ngưỡng', sub: 'Ghi khi đầu vào lên mức cảnh báo mới. Một đỉnh lớn không có nghĩa thiết bị hỏng.', body: '<div class="stack-sm" data-events></div>' })}
      </div>`;

    const els = {
      source: $('[data-source]', root), kpis: $('[data-kpis]', root), updated: $('[data-updated]', root),
      levels: $('[data-levels]', root), trend: $('[data-trend]', root), durations: $('[data-durations]', root),
      select: $('[data-select]', root), facts: $('[data-facts]', root), advice: $('[data-advice]', root),
      table: $('[data-table]', root), onlyAlerts: $('[data-only-alerts]', root), events: $('[data-events]', root),
      form: $('[data-thresholds]', root),
    };

    // ---------- Data in ----------
    function update(data) {
      if (!data || !Array.isArray(data.channels)) return;
      if (session !== data.session) { history = []; session = data.session; }
      latest = data;
      lastReceived = performance.now();
      if (performance.now() - lastRender > 250) schedule();
    }

    function current() {
      if (!latest) return null;
      if (performance.now() - lastReceived <= 1500 && !latest.stale) return latest;
      return {
        ...latest, stale: true,
        source: { ...latest.source, valid: false, reasons: ['Không nhận được dữ liệu mới; kiểm tra kết nối.'] },
        channels: latest.channels.map(r => ({ ...r, status: 'UNKNOWN', measured: false, peak_dbfs: null, rms_dbfs: null, headroom_db: null })),
      };
    }

    async function pollHistory() {
      if (!alive || document.hidden || inFlight === selected) return;
      const ch = selected;
      inFlight = ch;
      try {
        const data = await api.get(`/api/v1/monitoring/analysis?channel=${ch}`);
        if (!alive || ch !== selected) return;
        update(data);
        history = data.history || [];
        schedule();
      } catch {
        if (performance.now() - lastReceived > 1500) schedule();
      } finally {
        if (inFlight === ch) inFlight = null;
      }
    }

    function choose(ch) {
      selected = ch;
      els.select.value = String(ch);
      history = [];
      schedule();
      pollHistory();
    }

    // ---------- Render ----------
    function schedule() {
      if (rafPending || !alive) return;
      rafPending = true;
      requestAnimationFrame(() => {
        rafPending = false;
        if (!alive || document.hidden) return;
        lastRender = performance.now();
        render();
      });
    }

    function render() {
      const data = current();
      if (!data) return;
      const source = data.source || {};
      const rows = data.channels;
      const measured = rows.filter(r => r.measured);
      const over = rows.filter(r => OVER.includes(r.status));
      const severe = rows.filter(r => r.status === 'CRITICAL' || r.status === 'CLIP_RISK');
      const worst = measured.reduce((a, b) => (!a || b.peak_dbfs > a.peak_dbfs ? b : a), null);

      const context = source.simulated
        ? 'MÔ PHỎNG — không phải mức đo trên thiết bị thật.'
        : `Đo đầu vào USB • ${source.sample_rate || '—'} Hz • tap: ${source.tap_point || 'chưa xác nhận'}`;
      const srcTag = !source.valid ? 'DỮ LIỆU CHƯA HỢP LỆ' : source.simulated ? 'MÔ PHỎNG' : 'USB • CHƯA ÁNH XẠ';
      const srcHtml = callout(!source.valid ? 'bad' : source.simulated ? 'warn' : 'info',
        `<div class="row-between"><strong>${esc(source.label || 'Chưa có nguồn đo')}</strong><span class="badge">${esc(srcTag)}</span></div>
         <div class="small mt-8">${esc([context, ...(source.reasons || [])].join(' • '))}</div>`, 'gauge');
      if (els.source.dataset.html !== srcHtml) { els.source.dataset.html = srcHtml; els.source.innerHTML = srcHtml; }

      els.kpis.innerHTML = `
        <div class="stat"><div class="stat-label">Đầu vào có dữ liệu</div><div class="stat-value">${measured.length}</div><div class="stat-sub">trong tối đa 32 đầu vào</div></div>
        <div class="stat"><div class="stat-label">Vượt ngưỡng theo dõi</div><div class="stat-value warn-text">${over.length}</div><div class="stat-sub">gồm nguy hiểm / sát clipping</div></div>
        <div class="stat"><div class="stat-label">Nguy hiểm / sát clipping</div><div class="stat-value bad-text">${severe.length}</div><div class="stat-sub">headroom còn rất ít</div></div>
        <div class="stat"><div class="stat-label">Peak lớn nhất hiện tại</div><div class="stat-value">${db(worst?.peak_dbfs)}</div><div class="stat-sub">${esc(worst?.name || 'chưa có dữ liệu')} · ${rows.filter(r => !r.measured).length} chưa đo được</div></div>`;
      els.updated.textContent = source.valid && data.sampled_at
        ? `Cập nhật ${new Date(data.sampled_at * 1000).toLocaleTimeString('vi-VN')}` : 'Đang chờ khung đo hợp lệ';

      const sig = JSON.stringify(rows.map(r => [r.channel, r.name]));
      if (sig !== channelSig) {
        channelSig = sig;
        els.select.innerHTML = rows.map(r => `<option value="${r.channel}">${String(r.channel).padStart(2, '0')} • ${esc(r.name)}</option>`).join('');
        if (!rows.some(r => r.channel === selected)) selected = rows[0]?.channel || 1;
        els.select.value = String(selected);
      }

      const chosen = rows.find(r => r.channel === selected);
      els.facts.innerHTML = `
        <dt>Headroom hiện tại</dt><dd>${chosen?.measured && finite(chosen.headroom_db) ? `${chosen.headroom_db.toFixed(1)} dB` : '—'}</dd>
        <dt>Peak lớn nhất phiên</dt><dd>${db(chosen?.peak_hold_dbfs)}</dd>
        <dt>Thời gian vượt ngưỡng</dt><dd>${secs(chosen?.over_seconds)}</dd>
        <dt>Số đợt sát clipping</dt><dd>${esc(chosen?.clip_events ?? '—')}</dd>`;
      els.advice.textContent = data.stale
        ? 'Dữ liệu đã cũ. Các giá trị thống kê là lịch sử của phiên trước khung đo cuối.'
        : chosen?.advice || 'Đang chờ dữ liệu.';

      renderTable(rows);
      renderEvents(data.events || []);
      drawLevels(data);
      drawTrend(data);
      drawDurations(data);

      if (!els.form.contains(document.activeElement) && data.thresholds) {
        const t = data.thresholds;
        if (finite(t.warning_dbfs)) els.form.warning.value = t.warning_dbfs;
        if (finite(t.critical_dbfs)) els.form.critical.value = t.critical_dbfs;
        if (finite(t.clip_dbfs)) els.form.clip.value = t.clip_dbfs;
      }
    }

    function renderTable(rows) {
      const list = rows
        .filter(r => !els.onlyAlerts.checked || [...OVER, 'UNKNOWN'].includes(r.status))
        .sort((a, b) => PRIORITY[a.status] - PRIORITY[b.status] || (b.peak_dbfs ?? -200) - (a.peak_dbfs ?? -200));
      els.table.innerHTML = list.length ? list.map(r => `
        <tr data-ch="${r.channel}" tabindex="0" style="cursor:pointer;${r.channel === selected ? 'background:var(--accent-soft)' : ''}">
          <td><span class="mono muted">${String(r.channel).padStart(2, '0')}</span> ${esc(r.name)}</td>
          <td>${tag(r.status)}</td>
          <td class="right mono">${db(r.peak_dbfs)} / ${db(r.rms_dbfs)}</td>
          <td class="right mono">${r.measured && finite(r.headroom_db) ? `${r.headroom_db.toFixed(1)} dB` : '—'}</td>
          <td class="right mono">${secs(r.streak_seconds)}</td>
          <td class="small text-2">${esc(r.advice || '')}</td>
        </tr>`).join('') : '<tr><td colspan="6" class="muted">Không có đầu vào phù hợp bộ lọc.</td></tr>';
    }

    function renderEvents(events) {
      els.events.innerHTML = events.length ? events.slice(0, 30).map(e => `
        <div class="row" style="flex-wrap:nowrap">${tag(e.status)}
          <span class="small">${new Date(e.timestamp * 1000).toLocaleTimeString('vi-VN')} • ${esc(e.name)} • ${db(e.peak_dbfs)}</span></div>`).join('')
        : '<p class="small muted">Chưa ghi nhận đợt vượt ngưỡng trong phiên này.</p>';
    }

    // ---------- Canvas ----------
    function canvasCtx(el) {
      const ratio = window.devicePixelRatio || 1;
      const w = Math.max(1, el.clientWidth), h = Math.max(1, el.clientHeight);
      if (el.width !== Math.round(w * ratio) || el.height !== Math.round(h * ratio)) {
        el.width = Math.round(w * ratio);
        el.height = Math.round(h * ratio);
      }
      const ctx = el.getContext('2d');
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.font = '11px ui-monospace, Consolas, monospace';
      return { ctx, w, h };
    }

    function grid(c, thresholds) {
      const { ctx, w, h } = c;
      const left = 42, right = w - 12, top = 12, bottom = h - 30;
      const y = (v) => bottom - Math.max(0, Math.min(60, v + 60)) / 60 * (bottom - top);
      for (let level = -60; level <= 0; level += 12) {
        ctx.strokeStyle = '#1f2a3a'; ctx.beginPath(); ctx.moveTo(left, y(level)); ctx.lineTo(right, y(level)); ctx.stroke();
        ctx.fillStyle = '#7d8a9c'; ctx.fillText(String(level), 6, y(level) + 4);
      }
      for (const [key, color] of [['warning_dbfs', COLORS.WARNING], ['critical_dbfs', COLORS.CRITICAL], ['clip_dbfs', COLORS.CLIP_RISK]]) {
        const v = thresholds?.[key];
        if (!finite(v)) continue;
        ctx.setLineDash([5, 4]); ctx.strokeStyle = color; ctx.beginPath(); ctx.moveTo(left, y(v)); ctx.lineTo(right, y(v)); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = color; ctx.fillText(`${v} dBFS`, right - 66, y(v) + 12);
      }
      return { left, right, top, bottom, y };
    }

    function drawLevels(data) {
      const c = canvasCtx(els.levels), g = grid(c, data.thresholds), step = (g.right - g.left) / 32;
      data.channels.forEach(r => {
        const x = g.left + (r.channel - 1) * step + 2, width = Math.max(2, step - 4);
        c.ctx.fillStyle = COLORS[r.status] || COLORS.UNKNOWN;
        if (r.measured && finite(r.peak_dbfs)) { const y = g.y(r.peak_dbfs); c.ctx.fillRect(x, y, width, Math.max(2, g.bottom - y)); }
        else c.ctx.fillRect(x, g.bottom - 5, width, 5);
        if (finite(r.peak_hold_dbfs)) {
          c.ctx.strokeStyle = '#dae8fa'; c.ctx.beginPath();
          c.ctx.moveTo(x, g.y(r.peak_hold_dbfs)); c.ctx.lineTo(x + width, g.y(r.peak_hold_dbfs)); c.ctx.stroke();
        }
        if (r.channel === selected) { c.ctx.strokeStyle = '#f8fafc'; c.ctx.strokeRect(x - 1, g.top, width + 2, g.bottom - g.top); }
        if (c.w > 650 || r.channel % 2 === 1) {
          c.ctx.fillStyle = r.channel === selected ? '#fff' : '#8b98a9'; c.ctx.textAlign = 'center';
          c.ctx.fillText(String(r.channel).padStart(2, '0'), x + width / 2, g.bottom + 18); c.ctx.textAlign = 'left';
        }
      });
    }

    function drawTrend(data) {
      const c = canvasCtx(els.trend), g = grid(c, data.thresholds);
      for (const age of [120, 90, 60, 30, 0]) {
        const x = g.left + (1 - age / 120) * (g.right - g.left);
        c.ctx.fillStyle = '#7d8a9c'; c.ctx.textAlign = age === 0 ? 'right' : 'left';
        c.ctx.fillText(age === 0 ? 'hiện tại' : `−${age}s`, x, g.bottom + 20);
      }
      c.ctx.textAlign = 'left';
      for (const [key, color] of [['peak_dbfs', '#38bdf8'], ['rms_dbfs', '#a78bfa']]) {
        c.ctx.strokeStyle = color; c.ctx.lineWidth = 1.8; c.ctx.beginPath();
        let drawing = false;
        history.forEach(p => {
          const v = p.levels.find(r => r.channel === selected)?.[key];
          if (!finite(v)) { drawing = false; return; }
          const x = g.left + (1 - p.seconds_ago / 120) * (g.right - g.left);
          if (drawing) c.ctx.lineTo(x, g.y(v)); else c.ctx.moveTo(x, g.y(v));
          drawing = true;
        });
        c.ctx.stroke(); c.ctx.lineWidth = 1;
      }
      if (!history.some(p => p.levels.some(r => r.channel === selected && finite(r.peak_dbfs)))) {
        c.ctx.fillStyle = '#8b98a9'; c.ctx.fillText('Chưa có lịch sử hợp lệ cho đầu vào này', g.left + 10, (g.top + g.bottom) / 2);
      }
    }

    function drawDurations(data) {
      const c = canvasCtx(els.durations);
      const rows = [...data.channels].filter(r => r.over_seconds > 0).sort((a, b) => b.over_seconds - a.over_seconds).slice(0, 6);
      if (!rows.length) { c.ctx.fillStyle = '#8b98a9'; c.ctx.fillText('Chưa ghi nhận thời gian vượt ngưỡng', 12, c.h / 2); return; }
      const max = Math.max(1, ...rows.map(r => r.over_seconds));
      rows.forEach((r, i) => {
        const y = 10 + i * 34;
        c.ctx.fillStyle = '#b4c0cf'; c.ctx.fillText(`${String(r.channel).padStart(2, '0')} • ${String(r.name).slice(0, 23)}`, 10, y + 12);
        const width = (c.w - 100) * r.over_seconds / max;
        c.ctx.fillStyle = COLORS.WARNING; c.ctx.fillRect(10, y + 19, width, 7);
        c.ctx.fillStyle = '#e6edf3'; c.ctx.fillText(secs(r.over_seconds), width + 20, y + 26);
      });
    }

    // ---------- CSV (same columns as legacy monitoring.js) ----------
    function exportCSV() {
      const data = current();
      if (!data) { toast('Chưa có dữ liệu để xuất.', 'warn'); return; }
      const safe = (v) => { let s = String(v ?? ''); if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`; return `"${s.replaceAll('"', '""')}"`; };
      const rows = [['ChurchMix — báo cáo mức tín hiệu'], ['Nguồn', data.source?.label], ['Mô phỏng', data.source?.simulated ? 'Có' : 'Không'],
        ['Dữ liệu hợp lệ', data.source?.valid ? 'Có' : 'Không'], ['Cảnh báo dBFS', data.thresholds?.warning_dbfs],
        ['Nguy hiểm dBFS', data.thresholds?.critical_dbfs], ['Sát clipping dBFS', data.thresholds?.clip_dbfs],
        ['Input', 'Tên nguồn', 'Trạng thái', 'Peak dBFS', 'RMS dBFS', 'Headroom dB', 'Peak lớn nhất phiên', 'Thời gian vượt s', 'Đợt sát clipping', 'Phân tích']];
      data.channels.forEach(r => rows.push([r.channel, r.name, LABELS[r.status], r.peak_dbfs, r.rms_dbfs, r.headroom_db, r.peak_hold_dbfs, r.over_seconds, r.clip_events, r.advice]));
      rows.push([], ['Lịch sử đầu vào', selected], ['Giây trước hiện tại', 'Peak dBFS', 'RMS dBFS']);
      history.forEach(p => { const r = p.levels.find(x => x.channel === selected); rows.push([p.seconds_ago, r?.peak_dbfs, r?.rms_dbfs]); });
      downloadText(`ChurchMix-signal-${new Date().toISOString().replaceAll(':', '-').slice(0, 19)}.csv`,
        '﻿' + rows.map(row => row.map(safe).join(',')).join('\r\n'), 'text/csv;charset=utf-8');
    }

    // ---------- Events ----------
    $('[data-export]', root).addEventListener('click', exportCSV);
    els.select.addEventListener('change', (e) => choose(Number(e.target.value)));
    els.onlyAlerts.addEventListener('change', schedule);
    els.table.addEventListener('click', (e) => { const tr = e.target.closest('tr[data-ch]'); if (tr) choose(+tr.dataset.ch); });
    els.table.addEventListener('keydown', (e) => { const tr = e.target.closest('tr[data-ch]'); if (tr && e.key === 'Enter') choose(+tr.dataset.ch); });
    els.levels.addEventListener('click', (e) => {
      const rect = els.levels.getBoundingClientRect();
      const ch = Math.floor((e.clientX - rect.left - 42) / (rect.width - 54) * 32) + 1;
      if (ch >= 1 && ch <= 32) choose(ch);
    });
    els.form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = e.submitter || $('button[type=submit]', els.form);
      const res = await withLoading(btn, () => api.put('/api/v1/monitoring/thresholds', {
        warning_dbfs: Number(els.form.warning.value), critical_dbfs: Number(els.form.critical.value), clip_dbfs: Number(els.form.clip.value),
      }), { errorPrefix: 'Ngưỡng không hợp lệ: ' });
      if (res) { history = []; toast(res.message || 'Đã cập nhật ngưỡng.', 'ok'); inFlight = null; pollHistory(); }
    });

    const offTelemetry = store.on('telemetry', (t) => {
      if (t.analysis) update({ ...t.analysis, source: t.analysis.source || t.source });
    });
    const ro = new ResizeObserver(schedule);
    ro.observe(root);
    const pollTimer = setInterval(pollHistory, 1000);
    const staleTimer = setInterval(() => { if (latest && performance.now() - lastReceived > 1500) schedule(); }, 500);
    pollHistory();

    return () => {
      alive = false;
      offTelemetry();
      ro.disconnect();
      clearInterval(pollTimer);
      clearInterval(staleTimer);
    };
  },
};
