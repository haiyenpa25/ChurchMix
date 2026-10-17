// An toàn & nhật ký: chế độ quyền hạn, trạng thái STOP, bất biến Talkback,
// và nhật ký kiểm toán mọi thay đổi trên mixer.

import { api } from '../api.js';
import { store } from '../store.js';
import { $, esc, icon, pageHead, card, callout, statusBadge, errorBox, loadingRows, emptyState, fmt, withLoading } from '../ui.js';
import { MODES, modeLabel, openSafetyModeDialog, triggerStopAuto, resumeFromStop } from '../safety-actions.js';

const ACTION_VI = {
  STOP_AUTO: 'Dừng khẩn cấp',
  RESUME_AUTO: 'Mở khóa sau STOP',
  APPLY_PROPOSAL: 'Áp dụng đề xuất',
  REJECT_PROPOSAL: 'Đề xuất bị từ chối',
  CHANNEL_MUTE_TOGGLED: 'Bật/tắt kênh',
  PRE_SERVICE_CHECK: 'Kiểm tra trước lễ',
  STARTUP: 'Khởi động hệ thống',
  SAFETY_MODE_CHANGED: 'Đổi chế độ',
  AUTO_DISENGAGE: 'Tự ngắt an toàn',
};

export default {
  mount(root) {
    root.innerHTML = `
      ${pageHead('An toàn & nhật ký', 'Ai được phép thay đổi mixer, trạng thái khóa khẩn cấp, và lịch sử mọi thao tác.',
        `<a class="btn" href="/api/v1/reports/sunday-service" target="_blank" rel="noopener">${icon('file')}In báo cáo buổi lễ</a>`)}
      <div class="grid-3" data-tiles></div>
      <div class="grid-2 mt-16">
        ${card({ title: 'Chế độ quyền hạn', sub: 'Quyết định hệ thống được làm gì với mixer', body: '<div data-modes></div>',
          foot: `<button class="btn btn-primary" data-change-mode>${icon('shield')}Đổi chế độ</button>` })}
        ${card({ title: 'Bất biến Talkback (DL16 #11)', sub: 'Micro talkback ban nhạc chỉ được đi vào tai nghe P16', body: '<div data-tb></div>' })}
      </div>
      <div class="mt-16">
        ${card({ title: 'Nhật ký thao tác', sub: '50 sự kiện gần nhất, lưu trong cơ sở dữ liệu',
          actions: `<button class="btn btn-sm" data-reload>${icon('refresh', 'icon-sm')}Tải lại</button>`, body: '<div data-audit></div>' })}
      </div>`;

    const tiles = $('[data-tiles]', root);
    const renderStatus = () => {
      const s = store.status;
      const safety = store.telemetry?.safety_mode || s?.safety_mode;
      const stop = store.telemetry?.stop_auto ?? s?.stop_auto;
      const tb = s?.dl16_talkback_invariant;
      tiles.innerHTML = `
        <div class="stat"><div class="stat-label">Chế độ hiện tại</div><div class="stat-value" style="font-size:18px">${esc(modeLabel(safety?.current_mode))}</div>
          <div class="stat-sub">${safety?.read_only === false ? '<span class="warn-text">Cho phép ghi sau khi duyệt</span>' : 'Chỉ đọc — không ghi xuống mixer'}</div></div>
        <div class="stat"><div class="stat-label">Khóa khẩn cấp (STOP)</div>
          <div class="stat-value" style="font-size:18px">${stop ? '<span class="bad-text">ĐANG KHÓA</span>' : '<span class="ok-text">Không khóa</span>'}</div>
          <div class="row mt-8">${stop
            ? `<button class="btn btn-sm" data-resume>${icon('unlock', 'icon-sm')}Mở khóa</button>`
            : `<button class="btn btn-sm btn-danger" data-stop>${icon('hand', 'icon-sm')}STOP ngay</button>`}</div></div>
        <div class="stat"><div class="stat-label">Bản chụp mixer (SHA-256)</div><div class="stat-value mono" style="font-size:15px">${esc((s?.sha256 || '—').slice(0, 16))}</div>
          <div class="stat-sub">Dùng để phát hiện mixer bị chỉnh từ bên ngoài</div></div>`;
      $('[data-stop]', tiles)?.addEventListener('click', (e) => triggerStopAuto(e.currentTarget));
      $('[data-resume]', tiles)?.addEventListener('click', (e) => resumeFromStop(e.currentTarget));

      $('[data-modes]', root).innerHTML = `
        ${safety?.is_disengaged ? callout('bad', `<strong>Đã tự ngắt an toàn:</strong> ${esc(safety.disengage_reason)} — ${esc(safety.disengage_detail || '')}`) : ''}
        <div class="stack-sm mt-8">${MODES.map(m => `
          <div class="row" style="align-items:flex-start;gap:12px;flex-wrap:nowrap;opacity:${m.id === safety?.current_mode ? 1 : 0.6}">
            <span class="${m.id === safety?.current_mode ? 'ok-text' : 'muted'}">${icon(m.id === safety?.current_mode ? 'checkCircle' : 'disc')}</span>
            <div class="grow"><strong>${esc(m.label)}</strong> <span class="small muted">· ${esc(m.tag)}</span><div class="small text-2">${esc(m.desc)}</div></div>
          </div>`).join('')}</div>
        ${safety?.changed_by ? `<p class="small muted mt-16">Đổi lần cuối bởi ${esc(safety.changed_by)} lúc ${fmt.time(safety.last_mode_change_at)}</p>` : ''}`;

      $('[data-tb]', root).innerHTML = tb
        ? `${callout(tb.safe ? 'ok' : 'bad', `<strong>${tb.safe ? 'An toàn' : 'VI PHẠM — Talkback có thể lọt ra loa chính!'}</strong><div class="small mt-8 mono">${esc(tb.message)}</div>`)}
           <p class="small muted mt-16">Nếu vi phạm: mọi lệnh ghi tự động bị chặn. Kiểm tra trên mixer các send của kênh talkback tới Main, Mono, các Bus và Matrix.</p>`
        : loadingRows(2);
    };

    const auditBox = $('[data-audit]', root);
    async function loadAudit(btn) {
      if (!btn) auditBox.innerHTML = loadingRows(4);
      let data;
      try {
        data = btn ? await withLoading(btn, () => api.get('/api/v1/audit/events?limit=50')) : await api.get('/api/v1/audit/events?limit=50');
      } catch (e) {
        auditBox.innerHTML = errorBox(e);
        return;
      }
      if (!data) return;
      const events = data.events || [];
      auditBox.innerHTML = events.length ? `
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Thời gian</th><th>Thao tác</th><th>Người thực hiện</th><th>Kết quả</th><th>Mã kiểm</th></tr></thead>
          <tbody>${events.map(ev => `<tr>
            <td class="nowrap mono small">${esc(ev.iso_time || fmt.time(ev.timestamp))}</td>
            <td><strong>${esc(ACTION_VI[ev.action] || ev.action)}</strong>${ev.proposal_id ? `<div class="tiny muted mono">${esc(ev.proposal_id)}</div>` : ''}</td>
            <td>${esc(ev.actor)}</td>
            <td>${statusBadge(ev.status)}</td>
            <td class="mono tiny muted">${esc(ev.immutable_hash || '')}</td></tr>`).join('')}</tbody>
        </table></div>` : emptyState('Chưa có sự kiện nào.');
    }

    $('[data-reload]', root).addEventListener('click', (e) => loadAudit(e.currentTarget));
    $('[data-change-mode]', root).addEventListener('click', openSafetyModeDialog);

    renderStatus();
    loadAudit();
    store.refreshStatus();
    const offs = [store.on('status', renderStatus)];
    let last = '';
    offs.push(store.on('telemetry', (t) => {
      const k = `${t.safety_mode?.current_mode}|${t.safety_mode?.is_disengaged}|${t.stop_auto}`;
      if (k !== last) { last = k; renderStatus(); }
    }));
    return () => offs.forEach(off => off());
  },
};
