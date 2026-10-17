// "Soundcheck ảo" — plays a simulated 32-track rehearsal (band + pastor) into the
// analysis pipeline so EQ / feedback / leveler can be practised before service.
// It feeds the analyser only; it never writes OSC to the mixer.
// Secondary card: end-to-end Sunday service simulation (POST /api/v1/simulation/run).
//
// Ported from legacy.html: selectSoundcheckPreset, fetchSoundcheckStatus, updateSoundcheckUI,
// toggleSoundcheckPlayback, startSoundcheckPlayback, stopSoundcheckPlayback, runSundaySimulationFromUI.

import { api } from '../api.js';
import { store } from '../store.js';
import { $, $$, esc, icon, badge, card, callout, pageHead, emptyState, loadingRows, errorBox, withLoading, toast } from '../ui.js';

// Used only if the server does not list its presets.
const FALLBACK_PRESETS = [
  { id: 'SUNDAY_WORSHIP_BALLAD', name: 'Thờ phượng êm dịu', tempo_bpm: 68, key: 'D Maj', description: 'Piano, guitar thùng, nữ đơn ca và pad nền mềm mại.' },
  { id: 'SUNDAY_UPTEMPO_PRAISE', name: 'Ngợi khen sôi động', tempo_bpm: 124, key: 'G Maj', description: 'Trống cajon/kick, bass, guitar, nam đơn ca và bè ca đoàn.' },
  { id: 'SERMON_PREACHING', name: 'Bài giảng Mục sư', tempo_bpm: 0, key: 'Giọng nói', description: 'Lời nói có ngắt nghỉ tự nhiên — kiểm tra Silence Hold và bộ cân bằng giọng.' },
  { id: 'CONGREGATIONAL_PRAYER', name: 'Cầu nguyện chung', tempo_bpm: 60, key: 'C Maj', description: 'Tiếng cầu nguyện cùng piano êm — kiểm tra ngưỡng gate.' },
];

const PRESET_ICON = { SUNDAY_WORSHIP_BALLAD: 'wave', SUNDAY_UPTEMPO_PRAISE: 'zap', SERMON_PREACHING: 'mic', CONGREGATIONAL_PRAYER: 'users' };

const SIM_PHASE_VI = [
  'Khởi động & kiểm tra cách ly Talkback',
  'Line check trước lễ',
  'Cân chỉnh giọng & phát hiện hú',
  'Theo dõi trong lễ (giữ fader khi im lặng)',
  'Tổng kết & xuất scene',
];

export default {
  mount(root) {
    let alive = true;
    let presets = null;
    let presetsErr = null;
    let status = null;
    let selected = null;
    let lastKey = '';

    root.innerHTML = `
      ${pageHead('Soundcheck ảo',
        'Phát lại một buổi tập 32 kênh mô phỏng (ban nhạc, ca sĩ, Mục sư) để luyện chỉnh EQ, dò hú và cân bằng giọng trước giờ lễ — không cần ban nhạc có mặt.')}
      <div class="stack">
        ${callout('info', 'Soundcheck ảo chỉ đưa tín hiệu mô phỏng vào bộ phân tích của ChurchMix. <strong>Không có lệnh nào được ghi xuống mixer.</strong> Mic Talkback DL16 #11 trong bản mô phỏng luôn bị cách ly khỏi loa chính.', 'shieldCheck')}
        <div class="grid-2">
          <div data-status></div>
          <div data-presets></div>
        </div>
        <div data-sim></div>
      </div>`;

    const statusEl = $('[data-status]', root);
    const presetsEl = $('[data-presets]', root);
    const simEl = $('[data-sim]', root);

    // ---------- Status card (static frame, live fields patched at telemetry rate) ----------
    statusEl.innerHTML = card({
      title: `${icon('disc')} Trạng thái phát`,
      actions: '<span data-state-badge></span>',
      body: `<div class="stack">
        <div class="grid-2">
          <div class="stat"><div class="stat-label">Phiên đang chọn</div><div class="stat-value" style="font-size:18px" data-name>—</div><div class="stat-sub" data-desc></div></div>
          <div class="stat"><div class="stat-label">Nguồn chính (lead)</div><div class="stat-value" style="font-size:18px" data-lead>—</div><div class="stat-sub" data-chans></div></div>
          <div class="stat"><div class="stat-label">Thời gian đã phát</div><div class="stat-value" data-time>0.0 s</div></div>
          <div class="stat"><div class="stat-label">Khối âm thanh đã gửi</div><div class="stat-value" data-blocks>0</div></div>
        </div>
      </div>`,
      foot: `<button class="btn btn-primary btn-lg" data-toggle>${icon('play')}Bắt đầu phát</button>`,
    });
    const toggleBtn = $('[data-toggle]', statusEl);

    function setText(sel, v) { const n = $(sel, statusEl); if (n && n.textContent !== String(v)) n.textContent = v; }

    function presetById(id) { return (presets || FALLBACK_PRESETS).find(p => p.id === id); }

    function updateStatus(s) {
      if (!s) return;
      status = s;
      const active = !!s.is_active;
      if (!selected) selected = s.session_id || (presets || FALLBACK_PRESETS)[0]?.id;
      const shown = active ? s : (presetById(selected) ? { ...presetById(selected), session_name: presetById(selected).name } : s);

      setText('[data-name]', shown.session_name || shown.name || '—');
      setText('[data-desc]', shown.description || '');
      setText('[data-lead]', (active ? s.lead_source : shown.lead_source) || '—');
      const chans = active ? (s.active_channels || []) : (shown.active_channels || []);
      setText('[data-chans]', chans.length ? `${chans.length} kênh hoạt động` : '');
      setText('[data-time]', `${(+s.time_elapsed_seconds || 0).toFixed(1)} s`);
      setText('[data-blocks]', String(s.total_blocks_streamed || 0));

      const key = `${active}|${s.session_id}|${selected}`;
      if (key !== lastKey) {
        lastKey = key;
        $('[data-state-badge]', statusEl).innerHTML = active ? badge('Đang phát', 'ok') : badge('Đang dừng', 'info');
        toggleBtn.className = `btn btn-lg ${active ? 'btn-danger' : 'btn-primary'}`;
        toggleBtn.innerHTML = active ? `${icon('stop')}Dừng phát` : `${icon('play')}Bắt đầu phát`;
        renderPresets();
      }
    }

    async function refreshStatus() {
      try { updateStatus(await api.get('/api/v1/soundcheck/status')); }
      catch (e) { if (alive && !status) toast(`Không đọc được trạng thái soundcheck: ${e.message}`, 'bad'); }
    }

    async function start(sessionId) {
      const res = await api.post('/api/v1/soundcheck/start', { session_id: sessionId });
      if (!alive) return;
      toast(`Đã bắt đầu phát: ${res.name || sessionId}`, 'ok');
      await refreshStatus();
    }

    async function stop() {
      await api.post('/api/v1/soundcheck/stop');
      if (!alive) return;
      toast('Đã dừng soundcheck ảo. Hệ thống quay về micro trực tiếp.', 'info');
      await refreshStatus();
    }

    toggleBtn.addEventListener('click', () => withLoading(toggleBtn,
      () => (status?.is_active ? stop() : start(selected)), { errorPrefix: 'Lỗi soundcheck: ' }));

    // ---------- Presets ----------
    function renderPresets() {
      let body;
      if (presetsErr && !presets) body = errorBox(presetsErr);
      else if (!presets) body = loadingRows(4);
      else if (!presets.length) body = emptyState('Chưa có phiên tập mẫu nào.');
      else {
        const playingId = status?.is_active ? status.session_id : null;
        body = `<div class="stack-sm">${presets.map(p => `
          <button type="button" class="choice ${p.id === selected ? 'selected' : ''}" data-preset="${esc(p.id)}">
            ${icon(PRESET_ICON[p.id] || 'disc')}
            <div class="grow">
              <div class="row-between"><strong>${esc(p.name)}</strong>
                <span class="row">${p.id === playingId ? badge('Đang phát', 'ok') : ''}
                  <span class="small muted">${+p.tempo_bpm ? `${esc(p.tempo_bpm)} BPM` : ''}${p.key && p.key !== 'N/A' ? ` · ${esc(p.key)}` : ''}</span></span></div>
              ${p.description ? `<div class="small text-2 mt-8">${esc(p.description)}</div>` : ''}
            </div>
          </button>`).join('')}</div>`;
      }
      presetsEl.innerHTML = card({
        title: `${icon('layers')} Chọn phiên tập`,
        sub: status?.is_active ? 'Chọn phiên khác sẽ chuyển ngay sang phiên đó' : 'Chọn phiên rồi bấm “Bắt đầu phát”',
        body,
      });
      $$('[data-preset]', presetsEl).forEach(b => b.addEventListener('click', async () => {
        const id = b.dataset.preset;
        if (id === selected && !status?.is_active) return;
        selected = id;
        lastKey = '';
        if (status?.is_active && status.session_id !== id) {
          await withLoading(b, () => start(id), { errorPrefix: 'Không chuyển được phiên: ' });
        } else if (status) {
          updateStatus(status);
        } else {
          renderPresets();
        }
      }));
    }

    async function loadPresets() {
      try {
        const data = await api.get('/api/v1/soundcheck/sessions');
        presets = data.sessions?.length ? data.sessions : (status?.available_presets?.length ? status.available_presets : FALLBACK_PRESETS);
      } catch (e) {
        presetsErr = e;
        presets = status?.available_presets?.length ? status.available_presets : FALLBACK_PRESETS;
      }
      if (!alive) return;
      if (!selected) selected = presets[0]?.id;
      lastKey = '';
      if (status) updateStatus(status); else renderPresets();
    }

    // ---------- Sunday simulation ----------
    simEl.innerHTML = card({
      title: `${icon('church')} Diễn tập trọn buổi lễ Chúa Nhật`,
      sub: 'Chạy thử tự động 5 giai đoạn từ lúc bật máy đến khi tổng kết, để chắc mọi lớp an toàn hoạt động',
      body: `<div data-sim-body><p class="text-2">Hệ thống sẽ đọc trạng thái mixer, kiểm tra cách ly Talkback, thử bộ phát hiện hú với nốt nhạc và tiếng hú giả, kiểm tra cơ chế giữ fader khi im lặng, rồi ghi một mục nhật ký. Không có lệnh ghi nào gửi xuống mixer.</p></div>`,
      foot: `<button class="btn" data-run-sim>${icon('play')}Chạy diễn tập</button>`,
    });
    const simBody = $('[data-sim-body]', simEl);

    function simRow(t, i) {
      const flags = [];
      if (t.detail) flags.push(esc(t.detail));
      if (t.channels_checked !== undefined) flags.push(`Đã kiểm tra ${esc(t.channels_checked)} kênh`);
      if (t.harmonic_safe !== undefined) flags.push(t.harmonic_safe ? 'Nốt hát không bị nhận nhầm là hú' : '<span class="bad-text">Nốt hát bị nhận nhầm là hú</span>');
      if (t.feedback_caught !== undefined) flags.push(t.feedback_caught ? 'Đã bắt được tiếng hú giả' : '<span class="bad-text">Không bắt được tiếng hú giả</span>');
      if (t.silence_hold_engaged !== undefined) flags.push(t.silence_hold_engaged ? `Fader được giữ nguyên khi im lặng${t.fader_frozen !== undefined ? ` (${Math.round(t.fader_frozen * 100)}%)` : ''}` : '<span class="bad-text">Fader không được giữ khi im lặng</span>');
      if (t.scene_name) flags.push(`Scene: <span class="mono">${esc(t.scene_name)}</span>`);
      const boolKeys = ['harmonic_safe', 'feedback_caught', 'silence_hold_engaged'].filter(k => t[k] !== undefined);
      const ok = boolKeys.length ? boolKeys.every(k => t[k]) : /PASS|COMMIT|SUCCESS|OK/i.test(t.status || 'PASS');
      return `
        <div class="check-item">
          <span class="${ok ? 'ok-text' : 'bad-text'}">${icon(ok ? 'checkCircle' : 'xCircle')}</span>
          <div class="grow">
            <div class="row"><span class="mono small muted">${esc(t.time || '')}</span><strong>${esc(SIM_PHASE_VI[i] || t.phase)}</strong></div>
            <div class="small text-2">${flags.join(' · ')}</div>
          </div>
          ${badge(ok ? 'Đạt' : 'Lỗi', ok ? 'ok' : 'bad')}
        </div>`;
    }

    $('[data-run-sim]', simEl).addEventListener('click', (e) => withLoading(e.currentTarget, async () => {
      simBody.innerHTML = loadingRows(5);
      try {
        const data = await api.post('/api/v1/simulation/run');
        if (!alive) return;
        const tl = data.timeline || [];
        const success = data.status === 'SUCCESS';
        simBody.innerHTML = `
          ${callout(success ? 'ok' : 'bad', success
            ? '<strong>Diễn tập thành công.</strong> Talkback được cách ly, bộ phát hiện hú và cơ chế giữ fader hoạt động đúng.'
            : `<strong>Diễn tập chưa đạt.</strong> ${esc(data.summary || data.status || '')}`)}
          ${tl.length ? `<div class="checklist mt-8">${tl.map(simRow).join('')}</div>` : emptyState('Không có dữ liệu tiến trình.')}`;
      } catch (err) {
        if (alive) simBody.innerHTML = errorBox(err);
      }
    }));

    // ---------- Wire up ----------
    renderPresets();
    const offTelemetry = store.on('telemetry', (t) => { if (alive && t?.soundcheck) updateStatus(t.soundcheck); });
    if (store.telemetry?.soundcheck) updateStatus(store.telemetry.soundcheck);
    refreshStatus().then(loadPresets);

    return () => {
      alive = false;
      offTelemetry();
    };
  },
};
