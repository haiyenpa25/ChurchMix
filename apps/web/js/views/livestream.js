// Livestream: đo độ to tiếng gửi lên livestream theo chuẩn ITU-R BS.1770 / EBU R128
// (LUFS, True Peak) cho bus livestream đã chọn, và kiểm tra talkback ban nhạc
// (DL16 #11) không lọt vào bus livestream. Trang chỉ đọc — không ghi xuống mixer.

import { api } from '../api.js';
import { $, esc, icon, badge, pageHead, card, callout, errorBox, loadingRows, fmt } from '../ui.js';

const POLL_MS = 2500;
const PREF_KEY = 'churchmix.livestream';

const PROFILES = [
  { id: 'YOUTUBE_STREAMING', label: 'YouTube / Facebook Live', target: -14.0, tol: 1.0, tp: -1.0, note: 'Tránh bị nền tảng tự nén giảm âm lượng.' },
  { id: 'SANCTUARY_FOH', label: 'Hội trường / FOH', target: -18.0, tol: 1.5, tp: -0.5, note: 'Giữ độ động thoáng cho ban nhạc sống.' },
  { id: 'EBU_R128_TV', label: 'Truyền hình EBU R128', target: -23.0, tol: 0.5, tp: -1.0, note: 'Chuẩn phát sóng truyền hình quốc tế.' },
];
const BUSES = [5, 6, 7, 8];

const COMPLIANCE = {
  OPTIMAL: { label: 'Đúng chuẩn', kind: 'ok' },
  TOO_QUIET: { label: 'Quá nhỏ', kind: 'warn' },
  TOO_LOUD: { label: 'Quá to', kind: 'warn' },
  PEAK_WARNING: { label: 'Đỉnh sắp vỡ tiếng', kind: 'bad' },
};

const signed = (v, digits = 1) =>
  (v === null || v === undefined || Number.isNaN(+v)) ? '—' : `${+v > 0 ? '+' : ''}${(+v).toFixed(digits)}`;
const lufsPct = (v) => Math.min(100, Math.max(0, ((+v + 40) / 40) * 100));   // −40..0 LUFS
const tpPct = (v) => Math.min(100, Math.max(0, ((+v + 20) / 23) * 100));     // −20..+3 dBTP

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREF_KEY) || '{}') || {}; } catch { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch { /* storage blocked */ }
}

export default {
  mount(root) {
    const prefs = loadPrefs();
    const initProfile = PROFILES.some(p => p.id === prefs.profile) ? prefs.profile : 'YOUTUBE_STREAMING';
    const initBus = BUSES.includes(+prefs.bus) ? +prefs.bus : 5;

    root.innerHTML = `
      ${pageHead('Livestream',
        'Độ to của tiếng gửi lên livestream có đúng chuẩn không, và talkback ban nhạc có lọt vào stream không.',
        `<span class="small muted" data-updated></span>`)}
      <div class="stack">
        <div class="row">
          <div class="field" style="min-width:260px">
            <label for="ls-profile">Chuẩn mục tiêu</label>
            <select id="ls-profile" class="select">${PROFILES.map(p =>
              `<option value="${p.id}" ${p.id === initProfile ? 'selected' : ''}>${esc(p.label)} (${p.target.toFixed(1)} LUFS)</option>`).join('')}</select>
          </div>
          <div class="field" style="min-width:200px">
            <label for="ls-bus">Bus gửi livestream</label>
            <select id="ls-bus" class="select">${BUSES.map(b =>
              `<option value="${b}" ${b === initBus ? 'selected' : ''}>Mix bus ${String(b).padStart(2, '0')}${b === 5 ? ' (mặc định)' : ''}</option>`).join('')}</select>
          </div>
        </div>
        <div data-source></div>
        <div data-tb>${loadingRows(1)}</div>
        <div data-hero>${loadingRows(3)}</div>
        <div class="grid-4" data-tiles></div>
        <div data-rec></div>
        ${card({ title: 'Các chuẩn độ to tham khảo', sub: 'LUFS: đơn vị đo độ to theo cảm nhận tai người · dBTP: mức đỉnh thực',
          body: `<div class="table-wrap"><table class="table">
            <thead><tr><th>Chuẩn</th><th class="right">Mục tiêu</th><th class="right">Cho phép</th><th class="right">Đỉnh tối đa</th><th>Ghi chú</th></tr></thead>
            <tbody data-ref></tbody></table></div>
            <p class="small muted mt-8">Giá trị của mẫu hiện tại, chưa tích lũy cả buổi. Nguồn mô phỏng không phải số đo của bus livestream thật.</p>` })}
      </div>`;

    const profileSel = $('#ls-profile', root);
    const busSel = $('#ls-bus', root);
    const tbBox = $('[data-tb]', root);
    const sourceBox = $('[data-source]', root);
    const heroBox = $('[data-hero]', root);
    const tiles = $('[data-tiles]', root);
    const recBox = $('[data-rec]', root);
    const updated = $('[data-updated]', root);
    const refBody = $('[data-ref]', root);

    let alive = true;
    let inflight = false;
    let seq = 0;

    const currentProfile = () => PROFILES.find(p => p.id === profileSel.value) || PROFILES[0];

    function renderRef() {
      const cur = profileSel.value;
      refBody.innerHTML = PROFILES.map(p => `<tr ${p.id === cur ? 'style="background:var(--accent-soft)"' : ''}>
        <td><strong>${esc(p.label)}</strong>${p.id === cur ? ` ${badge('Đang dùng', 'info')}` : ''}</td>
        <td class="right mono">${p.target.toFixed(1)} LUFS</td>
        <td class="right mono">±${p.tol.toFixed(1)} dB</td>
        <td class="right mono">${p.tp.toFixed(1)} dBTP</td>
        <td class="small text-2">${esc(p.note)}</td></tr>`).join('');
    }

    async function poll(force = false) {
      if (!alive || (!force && (document.hidden || inflight))) return;
      inflight = true;
      const my = ++seq;
      const qs = `target_profile=${encodeURIComponent(profileSel.value)}&livestream_bus=${encodeURIComponent(busSel.value)}`;
      try {
        const r = await api.get(`/api/v1/broadcast/loudness?${qs}`);
        if (!alive || my !== seq) return; // bỏ kết quả cũ khi đã đổi lựa chọn
        render(r);
        updated.textContent = `Cập nhật lúc ${new Date().toLocaleTimeString('vi-VN')}`;
      } catch (e) {
        if (!alive || my !== seq) return;
        tbBox.innerHTML = '';
        sourceBox.innerHTML = '';
        heroBox.innerHTML = errorBox(e);
        tiles.innerHTML = '';
        recBox.innerHTML = '';
        updated.textContent = 'Chưa có số liệu hợp lệ';
      } finally {
        if (my === seq) inflight = false;
      }
    }

    function render(r) {
      sourceBox.innerHTML = r.source?.simulated ? callout('warn', 'Dữ liệu mô phỏng — không phải số đo bus livestream thật.') : '';
      const prof = PROFILES.find(p => p.id === r.target_profile) || currentProfile();
      const target = r.target_lufs ?? prof.target;
      const comp = COMPLIANCE[r.compliance_status] || { label: r.compliance_status || '—', kind: 'info' };
      const delta = +r.delta_to_target_db;
      // Đèn: trong dung sai = xanh; lệch tới 2 lần dung sai = vàng; xa hơn hoặc đỉnh vượt = đỏ.
      let light = comp.kind;
      if (r.compliance_status !== 'OPTIMAL' && r.compliance_status !== 'PEAK_WARNING') {
        light = Math.abs(delta) > prof.tol * 2 + 1 ? 'bad' : 'warn';
      }
      const peakOver = +r.true_peak_dbtp > prof.tp;

      // Talkback isolation
      tbBox.innerHTML = r.talkback_isolated === false
        ? `<div class="big-alert">${icon('alert', 'icon-xl')}<div class="grow">
            <h2>Talkback ban nhạc đang lọt vào livestream!</h2>
            <p class="text-2 mt-8">${esc(r.talkback_warning || `Kênh 11 (talkback) đang gửi vào Mix bus ${busSel.value}.`)}</p>
            <p class="small mt-8">Người xem online có thể nghe lời trao đổi của ban nhạc. Tắt ngay đường gửi kênh talkback tới bus livestream trên mixer.</p>
          </div>${badge('Phát hiện rò rỉ', 'bad')}</div>`
        : callout('ok', `<strong>Talkback ban nhạc (DL16 #11) được cách ly</strong> — không lọt vào Mix bus ${esc(String(busSel.value).padStart(2, '0'))} hay loa chính.`, 'shieldCheck');

      // Hero: độ to livestream (ngắn hạn 3 s là con số dễ theo dõi nhất)
      heroBox.innerHTML = `
        <div class="hero ${light}">
          <div class="hero-icon">${icon('broadcast', 'icon-lg')}</div>
          <div class="grow">
            <div class="small muted">Độ to của buffer hiện tại (${fmt.num(r.measurement_window_s, 2)} giây)</div>
            <h2 class="mono">${fmt.num(r.short_term_lufs, 1)} LUFS</h2>
            <p>Mục tiêu ${fmt.num(target, 1)} LUFS (±${prof.tol.toFixed(1)}) · ${Math.abs(delta) < 0.05 ? 'không cần chỉnh' : `cần chỉnh ${signed(delta)} dB`} · ${esc(prof.label)}</p>
          </div>
          <div class="stack-sm" style="align-items:flex-end">
            <div class="traffic">
              <span class="light ${light === 'ok' ? 'on ok' : ''}"></span>
              <span class="light ${light === 'warn' ? 'on warn' : ''}"></span>
              <span class="light ${light === 'bad' ? 'on bad' : ''}"></span>
            </div>
            ${badge(comp.label, comp.kind)}
          </div>
        </div>`;

      const tile = (label, sub, value, unit, pct, barKind = '') => `
        <div class="stat"><div class="stat-label">${label}</div>
          <div class="stat-value mono">${value} <span class="small muted">${unit}</span></div>
          <div class="bar ${barKind} mt-8"><span style="width:${pct.toFixed(0)}%"></span></div>
          <div class="stat-sub">${sub}</div></div>`;
      const near = (v) => Math.abs(+v - target) <= prof.tol ? 'ok' : 'warn';
      tiles.innerHTML = [
        tile('Tức thời', 'Trung bình 0,4 giây — dao động nhiều là bình thường', fmt.num(r.momentary_lufs, 1), 'LUFS', lufsPct(r.momentary_lufs), near(r.momentary_lufs)),
        tile('Ngắn hạn', 'Cửa sổ tối đa 3 giây, giới hạn bởi buffer hiện tại', fmt.num(r.short_term_lufs, 1), 'LUFS', lufsPct(r.short_term_lufs), near(r.short_term_lufs)),
        tile('Buffer hiện tại', 'Chưa tích lũy cả buổi', fmt.num(r.integrated_lufs, 1), 'LUFS', lufsPct(r.integrated_lufs), near(r.integrated_lufs)),
        tile('Đỉnh thực', `Tối đa ${prof.tp.toFixed(1)} dBTP — ${peakOver ? '<span class="bad-text">đang vượt</span>' : 'trong giới hạn'}`,
          signed(r.true_peak_dbtp, 1), 'dBTP', tpPct(r.true_peak_dbtp), peakOver ? 'bad' : 'ok'),
      ].join('');

      recBox.innerHTML = r.recommendation_vi
        ? callout(comp.kind === 'ok' ? 'ok' : comp.kind === 'bad' ? 'bad' : 'warn', `<strong>Gợi ý:</strong> ${esc(r.recommendation_vi)}`)
        : '';
    }

    const onChange = () => {
      savePrefs({ profile: profileSel.value, bus: +busSel.value });
      renderRef();
      heroBox.innerHTML = loadingRows(3);
      poll(true);
    };
    profileSel.addEventListener('change', onChange);
    busSel.addEventListener('change', onChange);

    renderRef();
    poll(true);
    const timer = setInterval(() => poll(), POLL_MS);
    const onVisible = () => { if (!document.hidden) poll(); };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
};
