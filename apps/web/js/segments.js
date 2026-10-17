// Tiết mục (service segments): one tap switches which microphones are open,
// e.g. "Mục sư giảng" opens the pastor mic and mutes the band.
// Only channel ON/MUTE changes — faders are never moved (AGENTS.md rule 10).
// Every switch shows a preview and needs confirmation; the server applies it as
// one Safety Gate batch (mutes first, then unmutes, rollback on any mismatch).
//
// API (apps/api/main.py):
//   GET    /api/v1/segments                     -> {segments:[...], active_id, talkback_channel}
//   GET    /api/v1/segments/{id}/preview        -> {expected_sha256, to_unmute:[{channel,name}], to_mute:[...], unchanged}
//   POST   /api/v1/segments/{id}/apply          {operator_id, expected_sha256}
//   POST   /api/v1/segments                     {name, description, icon, channels}
//   PUT    /api/v1/segments/{id}                {name?, description?, icon?, channels?}
//   DELETE /api/v1/segments/{id}
//   POST   /api/v1/segments/{id}/capture        {operator_id}   (save current mixer ON/MUTE state)
//   POST   /api/v1/segments/reset-defaults

import { api, getOperator } from './api.js';
import { store } from './store.js';
import { $$, esc, icon, openDialog, toast, withLoading, callout } from './ui.js';

export const SEGMENT_ICONS = ['mic', 'users', 'church', 'headphones', 'volume', 'disc', 'broadcast', 'hand', 'sliders', 'wave'];

export async function fetchSegments() {
  return api.get('/api/v1/segments');
}

/**
 * Opens the preview + confirm dialog and applies the segment.
 * Resolves to the apply result, or null when cancelled / failed.
 */
export async function switchToSegment(segment) {
  let preview;
  try {
    preview = await api.get(`/api/v1/segments/${encodeURIComponent(segment.id)}/preview`);
  } catch (e) {
    toast(`Không xem trước được tiết mục: ${e.message}`, 'bad');
    return null;
  }

  const safety = store.telemetry?.safety_mode || store.status?.safety_mode;
  const readOnly = safety ? safety.read_only !== false : true;
  const stop = store.telemetry?.stop_auto ?? store.status?.stop_auto;
  const nothing = !preview.to_mute.length && !preview.to_unmute.length;

  const list = (items) => items.map(c => `<li><strong>${String(c.channel).padStart(2, '0')}</strong> · ${esc(c.name)}</li>`).join('');
  const body = `
    <div class="stack">
      ${segment.description ? `<p class="text-2">${esc(segment.description)}</p>` : ''}
      ${nothing ? callout('ok', 'Mixer đã đúng với tiết mục này — không cần thay đổi gì.') : `
      <div class="grid-2">
        <div class="card tight ok"><div class="card-body">
          <div class="row strong ok-text">${icon('mic')} Sẽ BẬT (${preview.to_unmute.length})</div>
          ${preview.to_unmute.length ? `<ul class="small" style="margin:8px 0 0;padding-left:18px">${list(preview.to_unmute)}</ul>` : '<p class="small muted mt-8">Không có</p>'}
        </div></div>
        <div class="card tight bad"><div class="card-body">
          <div class="row strong bad-text">${icon('micOff')} Sẽ TẮT (${preview.to_mute.length})</div>
          ${preview.to_mute.length ? `<ul class="small" style="margin:8px 0 0;padding-left:18px">${list(preview.to_mute)}</ul>` : '<p class="small muted mt-8">Không có</p>'}
        </div></div>
      </div>
      <p class="small muted">Chỉ bật/tắt micro — không thay đổi âm lượng (fader). Kênh Talkback ban nhạc không bị động tới. Máy tắt trước, mở sau để tránh hú.</p>`}
      ${stop ? callout('bad', 'Hệ thống đang khóa khẩn cấp (STOP). Mở khóa ở nút đỏ góc trên trước khi chuyển tiết mục.') : ''}
      ${!stop && readOnly && !nothing ? callout('warn', 'Hệ thống đang ở chế độ <strong>Chỉ quan sát</strong>. Bấm nút bên dưới để cho phép thay đổi và chuyển tiết mục.') : ''}
    </div>`;

  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const actions = [{ label: nothing ? 'Đóng' : 'Hủy', kind: 'ghost', onClick: (close) => { finish(null); close(); } }];
    if (!nothing && !stop) {
      actions.push({
        label: readOnly ? `Bật chế độ Hỗ trợ &amp; chuyển sang “${esc(segment.name)}”` : `Chuyển sang “${esc(segment.name)}”`,
        kind: 'primary',
        onClick: async (close, btn) => {
          const res = await withLoading(btn, async () => {
            if (readOnly) {
              await api.post('/api/v1/safety/mode', { mode: 'ASSIST', operator: getOperator() });
            }
            return api.post(`/api/v1/segments/${encodeURIComponent(segment.id)}/apply`, {
              operator_id: getOperator(), expected_sha256: preview.expected_sha256,
            });
          }, { errorPrefix: 'Không chuyển được tiết mục: ' });
          if (res) {
            toast(`Đã chuyển sang “${segment.name}”: bật ${preview.to_unmute.length}, tắt ${preview.to_mute.length} micro.`, 'ok');
            store.refreshStatus();
            finish(res);
            close();
          }
        },
      });
    }
    openDialog({ title: `Tiết mục: ${esc(segment.name)}`, body, wide: true, actions, onClose: () => finish(null) });
  });
}

/**
 * Renders a row of big segment buttons into `container`.
 * opts: { compact: bool, onChanged(result): void, manageLink: bool }
 * Returns a cleanup function.
 */
export function renderSegmentBar(container, opts = {}) {
  let alive = true;
  let data = null;

  const draw = () => {
    if (!alive) return;
    if (!data) { container.innerHTML = '<div class="skeleton" style="height:44px"></div>'; return; }
    const segs = data.segments || [];
    if (!segs.length) {
      container.innerHTML = `<p class="small muted">Chưa có tiết mục nào. ${opts.manageLink ? '<a href="#/segments">Tạo tiết mục</a>' : ''}</p>`;
      return;
    }
    container.innerHTML = `
      <div class="segbar ${opts.compact ? 'compact' : ''}">
        ${segs.map(s => `
          <button class="segbtn ${s.id === data.active_id ? 'active' : ''}" data-seg="${esc(s.id)}" title="${esc(s.description || s.name)}">
            ${icon(SEGMENT_ICONS.includes(s.icon) ? s.icon : 'mic', opts.compact ? '' : 'icon-lg')}
            <span class="segbtn-name">${esc(s.name)}</span>
            ${s.id === data.active_id ? '<span class="segbtn-tag">Đang dùng</span>' : ''}
          </button>`).join('')}
        ${opts.manageLink ? `<a class="segbtn ghost" href="#/segments">${icon('settings', opts.compact ? '' : 'icon-lg')}<span class="segbtn-name">Quản lý</span></a>` : ''}
      </div>`;
    $$('[data-seg]', container).forEach(b => b.addEventListener('click', async () => {
      const seg = segs.find(s => s.id === b.dataset.seg);
      const res = await switchToSegment(seg);
      if (res) { await load(); opts.onChanged && opts.onChanged(res); }
    }));
  };

  async function load() {
    try { data = await fetchSegments(); }
    catch (e) { if (alive) container.innerHTML = `<p class="small bad-text">Không tải được tiết mục: ${esc(e.message)}</p>`; return; }
    draw();
  }

  draw();
  load();
  // Keep "Đang dùng" honest when someone changes mutes on the console itself.
  const timer = setInterval(() => { if (!document.hidden) load(); }, 10000);
  return () => { alive = false; clearInterval(timer); };
}
