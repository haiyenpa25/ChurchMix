// STOP AUTO and Safety Engine mode switching, shared by the top bar,
// the simple-mode home screen and the "An toàn & nhật ký" page.

import { api, getOperator } from './api.js';
import { store } from './store.js';
import { $, $$, esc, icon, openDialog, confirmDialog, toast, withLoading, callout } from './ui.js';

export const MODES = [
  { id: 'OBSERVE', label: 'Chỉ quan sát', tag: 'Khuyên dùng trong lễ',
    desc: 'Chỉ đọc mixer. Không lệnh nào được ghi xuống X32.' },
  { id: 'ASSIST', label: 'Hỗ trợ (duyệt từng lệnh)', tag: 'Buổi tập',
    desc: 'Cho phép áp dụng EQ, trim, cắt hú, expander — chỉ sau khi bạn bấm duyệt từng đề xuất.' },
  { id: 'LIMITED_AUTO', label: 'Tự động có giới hạn', tag: 'Nâng cao',
    desc: 'Automix và expander được vi chỉnh trong biên độ an toàn. Không bao giờ tự đẩy fader lên khi im lặng.' },
  { id: 'ADMIN_MAINTENANCE', label: 'Bảo trì (quản trị)', tag: 'Cần mã PIN',
    desc: 'Chỉ dành cho quản trị viên âm thanh. Bất biến cách ly Talkback DL16 #11 vẫn luôn được giữ.' },
];

export const modeLabel = (id) => MODES.find(m => m.id === id)?.label || id || '—';

/** Immediate — no confirmation: this is the panic button. */
export async function triggerStopAuto(btn) {
  const res = await withLoading(btn, () => api.post('/api/v1/emergency/stop-auto'), { errorPrefix: 'Không gửi được lệnh dừng: ' });
  if (res) {
    toast('Đã DỪNG mọi tự động. Mixer bị khóa chỉ đọc.', 'bad', 7000);
    store.refreshStatus();
  }
  return res;
}

export async function resumeFromStop(btn) {
  const ok = await confirmDialog({
    title: 'Mở khóa sau STOP?',
    message: 'Hệ thống sẽ về chế độ <strong>Chỉ quan sát</strong> (vẫn chỉ đọc). Bạn có thể bật lại chế độ Hỗ trợ sau khi kiểm tra xong.',
    confirmText: 'Mở khóa',
  });
  if (!ok) return null;
  const res = await withLoading(btn, () => api.post('/api/v1/emergency/resume-auto'), { errorPrefix: 'Không mở khóa được: ' });
  if (res) { toast('Đã mở khóa. Hệ thống ở chế độ Chỉ quan sát.', 'ok'); store.refreshStatus(); }
  return res;
}

export async function openSafetyModeDialog() {
  let state;
  try { state = await api.get('/api/v1/safety/mode'); }
  catch (e) { toast(e.message, 'bad'); return; }

  let selected = state.current_mode;
  const body = document.createElement('div');
  body.className = 'stack';
  body.innerHTML = `
    ${state.is_disengaged ? callout('bad', `<strong>Đã tự ngắt an toàn.</strong> Lý do: ${esc(state.disengage_reason)} — ${esc(state.disengage_detail || 'Mọi lệnh ghi bị khóa.')}`) : ''}
    <div class="stack-sm">
      ${MODES.map(m => `
        <label class="choice ${m.id === selected ? 'selected' : ''}" data-mode="${m.id}">
          <input type="radio" name="safetyMode" value="${m.id}" ${m.id === selected ? 'checked' : ''}>
          <div class="grow">
            <div class="row-between"><strong>${esc(m.label)}</strong><span class="badge">${esc(m.tag)}</span></div>
            <div class="small text-2 mt-8">${esc(m.desc)}</div>
          </div>
        </label>`).join('')}
    </div>
    <div class="field" data-pin hidden>
      <label for="adminPin">Mã PIN quản trị</label>
      <input id="adminPin" class="input" type="password" autocomplete="off" inputmode="numeric">
    </div>
    <div class="row-between" style="border-top:1px solid var(--border);padding-top:14px">
      <span class="small muted">Khẩn cấp: ngắt toàn bộ tự động và khóa chỉ đọc.</span>
      <button class="btn btn-danger btn-sm" data-panic>${icon('hand', 'icon-sm')}Ngắt khẩn cấp</button>
    </div>`;

  const pinBox = $('[data-pin]', body);
  $$('.choice', body).forEach(c => c.addEventListener('click', () => {
    selected = c.dataset.mode;
    $$('.choice', body).forEach(x => x.classList.toggle('selected', x === c));
    $('input', c).checked = true;
    pinBox.hidden = selected !== 'ADMIN_MAINTENANCE';
  }));
  pinBox.hidden = selected !== 'ADMIN_MAINTENANCE';

  const dlg = openDialog({
    title: 'Chế độ quyền hạn',
    body,
    actions: [
      { label: 'Đóng', kind: 'ghost' },
      { label: 'Áp dụng chế độ', kind: 'primary', onClick: async (close, btn) => {
        const res = await withLoading(btn, () => api.post('/api/v1/safety/mode', {
          mode: selected, operator: getOperator(), admin_pin: $('#adminPin', body).value || null,
        }), { errorPrefix: 'Không đổi được chế độ: ' });
        if (res) {
          toast(`Đã chuyển sang: ${modeLabel(res.current_mode)}`, res.read_only ? 'info' : 'warn');
          store.refreshStatus();
          close();
        }
      } },
    ],
  });

  $('[data-panic]', body).addEventListener('click', async (e) => {
    const res = await withLoading(e.currentTarget, () => api.post('/api/v1/safety/disengage', {
      reason: 'PANIC_BUTTON', detail: 'Kỹ thuật viên bấm ngắt khẩn cấp', operator: getOperator(),
    }));
    if (res) { toast('Đã ngắt khẩn cấp. Hệ thống về Chỉ quan sát.', 'bad', 7000); store.refreshStatus(); dlg.close(); }
  });
}
