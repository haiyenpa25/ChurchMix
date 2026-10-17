// Kết nối & thiết bị — choose the mixer target (simulator or real X32 on the
// LAN, always READ-ONLY on connect) and the USB audio capture device.
// Shows the live safety/connection status from store.status.

import { $, $$, esc, icon, badge, card, callout, pageHead, emptyState, loadingRows, withLoading, toast, confirmDialog, fmt } from '../ui.js';
import { api } from '../api.js';
import { store } from '../store.js';

const SIM_TARGET = '127.0.0.1:10023';
const MODE_LABEL = { OBSERVE: 'Chỉ quan sát', ASSIST: 'Hỗ trợ (cần duyệt)', AUTO: 'Tự động có giới hạn', ADMIN: 'Quản trị' };

function mixerInfoText(info) {
  if (!info) return '—';
  if (typeof info === 'string') return info;
  if (Array.isArray(info)) return info.filter(v => v !== null && v !== '').join(' · ');
  if (typeof info === 'object') {
    const inner = info.info ?? info.args ?? info;
    if (Array.isArray(inner)) return inner.filter(v => v !== null && v !== '').join(' · ');
    if (typeof inner === 'string') return inner;
    try { return JSON.stringify(inner); } catch { return String(inner); }
  }
  return String(info);
}

export default {
  mount(root) {
    let alive = true;
    let mode = 'SIMULATOR';
    let capturing = false;
    let pollTimer = null;
    const unsubs = [];

    root.innerHTML = `
      ${pageHead('Kết nối &amp; thiết bị',
        'Chọn bàn trộn ChurchMix sẽ theo dõi và card âm thanh dùng để thu tín hiệu phân tích.')}
      <div class="stack">
        <div data-slot="status">${card({ title: 'Trạng thái hiện tại', body: loadingRows(3) })}</div>
        <div class="grid-2">
          ${card({
            title: 'Bàn trộn X32',
            sub: 'Giả lập để tập luyện, hoặc bàn thật qua mạng LAN',
            body: `
              <div class="stack">
                <div class="grid-2" role="radiogroup" aria-label="Chế độ kết nối">
                  <button type="button" class="choice selected" data-mode="SIMULATOR" role="radio" aria-checked="true">
                    ${icon('disc')}<div><div class="strong">Bàn giả lập</div><div class="small muted">An toàn để thử nghiệm · <span class="mono">${SIM_TARGET}</span></div></div>
                  </button>
                  <button type="button" class="choice" data-mode="REAL_HARDWARE" role="radio" aria-checked="false">
                    ${icon('network')}<div><div class="strong">Bàn X32 thật</div><div class="small muted">Qua mạng LAN của nhà thờ</div></div>
                  </button>
                </div>
                <div data-slot="real" hidden>
                  <div class="stack-sm">
                    <div class="row-between">
                      <span class="label">Tìm bàn trộn trên mạng</span>
                      <button class="btn btn-sm" data-act="discover">${icon('refresh')}Dò tìm trong mạng LAN</button>
                    </div>
                    <div data-slot="found"></div>
                    <div class="grid-2">
                      <div class="field"><label for="hwIp">Địa chỉ IP của bàn</label>
                        <input id="hwIp" class="input mono" value="192.168.1.50" placeholder="Ví dụ: 192.168.1.50" inputmode="decimal"></div>
                      <div class="field"><label for="hwPort">Cổng OSC (UDP)</label>
                        <input id="hwPort" class="input mono" type="number" value="10023" min="1" max="65535">
                        <span class="hint">Mặc định của X32 là 10023.</span></div>
                    </div>
                  </div>
                </div>
                ${callout('info', `<strong>Luôn kết nối ở chế độ CHỈ ĐỌC.</strong>
                  <div class="small text-2">ChurchMix chỉ nghe và đọc thông số, không ghi gì xuống bàn cho tới khi kỹ thuật viên chủ động đổi chế độ ở trang An toàn.
                  Ngay khi kết nối, hệ thống kiểm tra Talkback kênh 11 không ra loa hội trường.</div>`, 'shield')}
                <div data-slot="connect-result"></div>
              </div>`,
            foot: `<button class="btn btn-primary" data-act="connect">${icon('arrowRight')}Kết nối</button>`,
          })}
          ${card({
            title: 'Card thu âm USB',
            sub: 'Card X-USB / DN32-USB của X32 hoặc micro đo',
            body: `
              <div class="stack">
                <div class="field"><label for="audDev">Thiết bị đầu vào</label>
                  <select id="audDev" class="select"><option value="-1">Card X-USB giả lập (32 kênh, 48 kHz)</option></select></div>
                <div class="grid-2">
                  <div class="field"><label for="audCh">Số kênh thu</label>
                    <select id="audCh" class="select">
                      <option value="2">2 kênh (stereo / tham chiếu + mic)</option>
                      <option value="16">16 kênh (stagebox DL16)</option>
                      <option value="32">32 kênh (toàn bộ X-USB)</option>
                    </select></div>
                  <div class="field"><label>Tần số lấy mẫu</label>
                    <input class="input mono" value="48 000 Hz (chuẩn X32)" readonly></div>
                </div>
                <div data-slot="capture">${loadingRows(2)}</div>
              </div>`,
            foot: `<button class="btn btn-primary" data-act="capture">${icon('play')}Bắt đầu thu</button>`,
          })}
        </div>
      </div>`;

    const statusSlot = $('[data-slot="status"]', root);
    const realSlot = $('[data-slot="real"]', root);
    const foundSlot = $('[data-slot="found"]', root);
    const connectResult = $('[data-slot="connect-result"]', root);
    const captureSlot = $('[data-slot="capture"]', root);
    const captureBtn = $('[data-act="capture"]', root);
    const devSel = $('#audDev', root);
    const chSel = $('#audCh', root);

    // ---------- Status (from store) ----------
    function renderStatus(st) {
      if (!alive) return;
      if (!st) {
        statusSlot.innerHTML = card({
          title: 'Trạng thái hiện tại',
          body: callout('bad', '<strong>Không đọc được trạng thái bàn trộn.</strong><div class="small">Máy chủ ChurchMix hoặc bàn trộn chưa phản hồi. Thử kết nối lại bên dưới.</div>'),
        });
        return;
      }
      const sm = st.safety_mode || {};
      const tb = st.dl16_talkback_invariant || {};
      const readOnly = st.read_only_mode || sm.read_only;
      statusSlot.innerHTML = card({
        title: 'Trạng thái hiện tại',
        sub: 'Tự cập nhật mỗi 5 giây',
        actions: `<button class="btn btn-sm btn-ghost btn-icon" data-act="refresh-status" title="Làm mới" aria-label="Làm mới trạng thái">${icon('refresh')}</button>`,
        body: `
          <div class="grid-4">
            <div class="stat"><div class="stat-label">Bàn trộn</div>
              <div class="stat-value" style="font-size:18px">${st.status === 'ONLINE' ? '<span class="ok-text">Đang kết nối</span>' : esc(st.status || '—')}</div>
              <div class="stat-sub small" title="${esc(mixerInfoText(st.mixer))}" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(mixerInfoText(st.mixer))}</div></div>
            <div class="stat"><div class="stat-label">Quyền ghi</div>
              <div class="stat-value" style="font-size:18px">${readOnly ? `${icon('lock')} Chỉ đọc` : '<span class="warn-text">Cho phép ghi</span>'}</div>
              <div class="stat-sub">Chế độ: ${esc(MODE_LABEL[sm.current_mode] || sm.current_mode || '—')}</div></div>
            <div class="stat"><div class="stat-label">Talkback kênh 11</div>
              <div class="stat-value" style="font-size:18px">${tb.safe === false ? '<span class="bad-text">Vi phạm!</span>' : tb.safe ? '<span class="ok-text">An toàn</span>' : '—'}</div>
              <div class="stat-sub small">${esc(tb.message || 'Chỉ đi P16, không ra FOH')}</div></div>
            <div class="stat"><div class="stat-label">Tự động hóa</div>
              <div class="stat-value" style="font-size:18px">${st.stop_auto ? '<span class="bad-text">Đã DỪNG</span>' : sm.is_disengaged ? '<span class="warn-text">Tự ngắt</span>' : 'Bình thường'}</div>
              <div class="stat-sub small">${sm.is_disengaged ? esc(sm.disengage_detail || sm.disengage_reason || '') : st.sha256 ? `Mã trạng thái <span class="mono">${esc(String(st.sha256).slice(0, 8))}</span>` : ''}</div></div>
          </div>
          ${tb.safe === false ? `<div class="mt-16">${callout('bad', `<strong>Talkback kênh 11 đang bị định tuyến ra FOH.</strong> Kiểm tra ngay trên bàn trộn. ${esc(tb.message || '')}`)}</div>` : ''}`,
      });
    }
    unsubs.push(store.on('status', renderStatus));
    if (store.status) renderStatus(store.status);
    store.refreshStatus();

    // ---------- Mixer target ----------
    function setMode(m) {
      mode = m;
      $$('[data-mode]', root).forEach(b => {
        const on = b.dataset.mode === m;
        b.classList.toggle('selected', on);
        b.setAttribute('aria-checked', String(on));
      });
      realSlot.hidden = m !== 'REAL_HARDWARE';
      connectResult.innerHTML = '';
    }

    async function discover(btn) {
      foundSlot.innerHTML = `<div class="small muted">Đang gửi gói tìm kiếm /info trên cổng 10023…</div>`;
      const data = await withLoading(btn, () => api.post('/api/v1/hardware/discover', {}), { errorPrefix: 'Lỗi dò tìm: ' });
      if (!alive) return;
      if (!data) { foundSlot.innerHTML = ''; return; }
      const list = data.consoles || [];
      if (!list.length) {
        foundSlot.innerHTML = callout('warn', 'Không tìm thấy bàn X32 nào trên mạng. Kiểm tra cáp mạng / Wi-Fi của bàn, hoặc nhập địa chỉ IP thủ công bên dưới.');
        return;
      }
      foundSlot.innerHTML = `
        <div class="stack-sm">
          <span class="hint">Tìm thấy ${list.length} thiết bị — bấm để điền địa chỉ:</span>
          ${list.map((c, i) => `
            <button type="button" class="choice" data-found="${i}">
              ${icon('network')}
              <div class="grow"><div class="strong">${esc(c.model || 'X32')}</div><div class="small muted mono">${esc(c.ip)}:${esc(c.port)}</div></div>
              ${c.firmware ? badge(`FW ${c.firmware}`, 'info') : ''}
            </button>`).join('')}
        </div>`;
      $$('[data-found]', foundSlot).forEach(b => b.addEventListener('click', () => {
        const c = list[Number(b.dataset.found)];
        $('#hwIp', root).value = c.ip;
        $('#hwPort', root).value = c.port;
        $$('[data-found]', foundSlot).forEach(x => x.classList.toggle('selected', x === b));
      }));
    }

    async function connect(btn) {
      const ip = $('#hwIp', root).value.trim();
      const port = parseInt($('#hwPort', root).value.trim(), 10) || 10023;
      if (mode === 'REAL_HARDWARE') {
        if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) { toast('Địa chỉ IP chưa đúng dạng, ví dụ 192.168.1.50.', 'warn'); $('#hwIp', root).focus(); return; }
        const ok = await confirmDialog({
          title: 'Kết nối tới bàn X32 thật?',
          message: `ChurchMix sẽ ngắt kết nối hiện tại và kết nối tới <strong class="mono">${esc(ip)}:${port}</strong>.<br><br>
            ${icon('lock', 'icon-sm')} Kết nối luôn ở chế độ <strong>CHỈ ĐỌC</strong>: không có thông số nào trên bàn bị thay đổi.
            Muốn cho phép ghi, kỹ thuật viên phải tự đổi chế độ ở trang An toàn.<br><br>
            Nếu không kết nối được, hệ thống sẽ tự quay về bàn giả lập.`,
          confirmText: 'Kết nối (chỉ đọc)',
        });
        if (!ok) return;
      }
      connectResult.innerHTML = `<div class="small muted">Đang kết nối và kiểm tra phản hồi…</div>`;
      try {
        btn.classList.add('loading'); btn.disabled = true;
        const data = await api.post('/api/v1/hardware/connect', { mode, ip, port });
        if (!alive) return;
        connectResult.innerHTML = callout('ok', `<strong>Đã kết nối ${mode === 'SIMULATOR' ? 'bàn giả lập' : 'bàn X32 thật'}.</strong>
          <dl class="kv small mt-8">
            <dt>Địa chỉ</dt><dd class="mono">${esc(data.target)}</dd>
            <dt>Quyền ghi</dt><dd>${data.read_only_mode ? 'Chỉ đọc' : 'Cho phép ghi'}</dd>
            <dt>Thiết bị</dt><dd>${esc(mixerInfoText(data.mixer_info) || 'X32')}</dd>
          </dl>`);
        toast(`Đã kết nối ${data.target} (chỉ đọc).`, 'ok');
      } catch (e) {
        if (!alive) return;
        connectResult.innerHTML = callout('bad', `<strong>Kết nối thất bại.</strong> ChurchMix đã quay về bàn giả lập.
          <div class="small mono mt-8">${esc(e.message)}</div>`);
      } finally {
        btn.classList.remove('loading'); btn.disabled = false;
        store.refreshStatus();
      }
    }

    // ---------- Audio capture ----------
    async function loadDevices() {
      try {
        const data = await api.get('/api/v1/audio/devices');
        if (!alive) return;
        const devices = data?.devices || [];
        if (devices.length) {
          devSel.innerHTML = devices.map(d => `
            <option value="${esc(d.device_id)}" ${data.active_device_id === d.device_id ? 'selected' : ''}>
              ${esc(d.name)} — ${esc(d.max_inputs)} vào, ${esc(Math.round(d.default_samplerate || 48000))} Hz${d.is_x32_compatible ? ' · tương thích X32' : ''}
            </option>`).join('');
        }
        setCapturing(!!data?.is_capturing);
      } catch (e) {
        if (alive) toast(`Không đọc được danh sách card âm thanh: ${e.message}`, 'warn');
      }
    }

    function setCapturing(on) {
      capturing = on;
      captureBtn.className = `btn ${on ? 'btn-danger' : 'btn-primary'}`;
      captureBtn.innerHTML = on ? `${icon('stop')}Dừng thu` : `${icon('play')}Bắt đầu thu`;
      devSel.disabled = on;
      chSel.disabled = on;
    }

    async function pollCapture() {
      if (document.hidden) return;
      try {
        const s = await api.get('/api/v1/audio/capture/status');
        if (!alive) return;
        if (s?.is_running !== capturing) setCapturing(!!s?.is_running);
        if (s?.is_running) {
          captureSlot.innerHTML = `
            <div class="row-between">${badge('Đang thu', 'ok')}<span class="small muted">${esc(s.channels)} kênh · ${esc(s.sample_rate)} Hz</span></div>
            <dl class="kv mt-8">
              <dt>Khối âm thanh đã xử lý</dt><dd class="mono">${esc(s.blocks_processed ?? 0)}</dd>
              <dt>Mất mẫu (tràn bộ đệm)</dt><dd class="mono ${s.overflow_count ? 'warn-text' : ''}">${esc(s.overflow_count ?? 0)}</dd>
              ${s.peak_dbfs !== undefined ? `<dt>Mức đỉnh</dt><dd class="mono">${fmt.num(s.peak_dbfs)} dBFS</dd>` : ''}
              ${s.rms_dbfs !== undefined ? `<dt>Mức trung bình</dt><dd class="mono">${fmt.num(s.rms_dbfs)} dBFS</dd>` : ''}
            </dl>
            ${s.overflow_count ? `<div class="mt-8">${callout('warn', 'Có mất mẫu âm thanh. Các phép đo trong lúc này có thể không chính xác — đóng bớt ứng dụng hoặc giảm số kênh thu.')}</div>` : ''}`;
        } else {
          captureSlot.innerHTML = `
            <div class="row-between">${badge('Chưa thu', 'info')}<span class="small muted">Đang dùng tín hiệu giả lập</span></div>
            <p class="small text-2 mt-8">Bấm “Bắt đầu thu” để phân tích tín hiệu thật từ card USB.</p>`;
        }
      } catch (e) {
        if (alive) captureSlot.innerHTML = emptyState(`Không đọc được trạng thái thu âm: ${e.message}`);
      }
    }

    async function toggleCapture(btn) {
      if (!capturing) {
        const device_id = parseInt(devSel.value, 10);
        const channels = parseInt(chSel.value, 10);
        const res = await withLoading(btn, () => api.post('/api/v1/audio/capture/start', { device_id, channels, sample_rate: 48000 }),
          { errorPrefix: 'Không bắt đầu thu được: ' });
        if (res) { setCapturing(true); toast(`Đã bắt đầu thu ${channels} kênh.`, 'ok'); }
      } else {
        const res = await withLoading(btn, () => api.post('/api/v1/audio/capture/stop'), { errorPrefix: 'Không dừng được: ' });
        if (res) { setCapturing(false); toast('Đã dừng thu âm.', 'ok'); }
      }
      pollCapture();
    }

    // ---------- Wiring ----------
    root.addEventListener('click', (e) => {
      const m = e.target.closest('[data-mode]');
      if (m) { setMode(m.dataset.mode); return; }
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.dataset.act;
      if (act === 'discover') discover(b);
      else if (act === 'connect') connect(b);
      else if (act === 'capture') toggleCapture(b);
      else if (act === 'refresh-status') withLoading(b, () => store.refreshStatus());
    });

    loadDevices();
    pollCapture();
    pollTimer = setInterval(pollCapture, 1500);

    return () => {
      alive = false;
      clearInterval(pollTimer);
      unsubs.forEach(u => u());
    };
  },
};
