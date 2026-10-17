// Giọng nói & Automix: bộ automix lời nói kiểu Dugan (chia sẻ gain giữa các micro
// phát biểu, NOM = 1), đề xuất cài AutoMix gốc của X32, và trạng thái bộ giữ mức
// giọng nói (Speech Leveler / Anti-Clip / Silence Hold) của micro Mục sư.
// Mọi thay đổi trên mixer chỉ đi qua đề xuất + duyệt (renderProposal).

import { api } from '../api.js';
import {
  $, esc, icon, badge, pageHead, card, callout, errorBox, loadingRows, emptyState,
  fmt, withLoading, toast, renderProposal,
} from '../ui.js';

const POLL_MS = 2000;

// Cấu hình AutoMix mặc định (giữ nguyên payload của giao diện cũ).
const AUTOMIX_SETUP = {
  channels: [1, 2, 3, 4],
  weights_db: { 1: 3.0, 2: 0.0, 3: 0.0, 4: -3.0 },
};

const ROLE_VI = {
  PASTOR: 'Mục sư', PASTOR_SPEECH: 'Mục sư giảng', SPEECH: 'Lời nói', MC: 'Dẫn chương trình', LEADER: 'Hướng dẫn',
  VOCAL: 'Giọng hát', LEAD_VOCAL: 'Giọng chính', CHOIR: 'Ca đoàn', READER: 'Đọc Kinh Thánh', PRAYER: 'Cầu nguyện',
};
const roleVi = (r) => {
  const k = String(r || '').toUpperCase();
  const g = /_FEMALE$/.test(k) ? ' (nữ)' : /_MALE$/.test(k) ? ' (nam)' : '';
  const base = ROLE_VI[k.replace(/_(FEMALE|MALE)$/, '')];
  return base ? base + g : (r || '—');
};

const LEVELER_ACTION = {
  HOLD: { label: 'Giữ nguyên fader', kind: 'ok', desc: 'Mức giọng ổn hoặc người nói đang ngừng — không thay đổi gì.' },
  ANTI_CLIP: { label: 'Chống vỡ tiếng: hạ nhẹ', kind: 'bad', desc: 'Đỉnh tín hiệu sát ngưỡng méo, cần hạ ngay một chút.' },
  DOWNWARD_NUDGE: { label: 'Nên hạ nhẹ', kind: 'warn', desc: 'Giọng đang to hơn mục tiêu.' },
  UPWARD_NUDGE: { label: 'Có thể tăng nhẹ, từ từ', kind: 'info', desc: 'Giọng nhỏ hơn mục tiêu trong lúc đang nói.' },
};

const signed = (v, digits = 1) =>
  (v === null || v === undefined || Number.isNaN(+v)) ? '—' : `${+v > 0 ? '+' : ''}${(+v).toFixed(digits)}`;

export default {
  mount(root) {
    root.innerHTML = `
      ${pageHead('Giọng nói & Automix',
        'Ai đang nói, hệ thống chia gain giữa các micro phát biểu ra sao, và mức giọng Mục sư có an toàn không.',
        `<span class="small muted" data-updated></span>`)}
      <div class="stack">
        <div data-tb></div>
        <div class="grid-4" data-tiles></div>
        ${card({ title: 'Micro trong nhóm chia sẻ gain', sub: 'Micro đang nói được giữ to, các micro im lặng tự giảm để bớt ồn và chống hú',
          body: `<div data-channels>${loadingRows(4)}</div>` })}
        <div data-advice></div>
        <div class="grid-2">
          ${card({ title: 'Cài AutoMix gốc của X32', sub: 'Tạo đề xuất bật Automix trên chính mixer — phải duyệt mới ghi',
            body: `
              <p class="small text-2">X32 có sẵn AutoMix (kiểu Dugan) cho tối đa 8 kênh (kênh 1–8). Đề xuất sẽ đưa các kênh dưới đây vào nhóm và đặt trọng số ưu tiên.</p>
              <div class="table-wrap mt-8"><table class="table">
                <thead><tr><th>Kênh</th><th class="right">Trọng số ưu tiên</th></tr></thead>
                <tbody>${AUTOMIX_SETUP.channels.map(ch => `<tr><td>${fmt.ch(ch)}</td><td class="right mono">${signed(AUTOMIX_SETUP.weights_db[ch])} dB</td></tr>`).join('')}</tbody>
              </table></div>
              <div class="row mt-16">
                <div class="field" style="min-width:160px">
                  <label for="am-group">Nhóm AutoMix</label>
                  <select id="am-group" class="select"><option value="1">Nhóm X</option><option value="2">Nhóm Y</option></select>
                </div>
              </div>
              <div class="mt-8">${callout('info', 'Kênh 11 (talkback ban nhạc) <strong>không bao giờ</strong> được đưa vào AutoMix — hệ thống sẽ từ chối.', 'shieldCheck')}</div>
              <div class="stack mt-16" data-proposals></div>`,
            foot: `<button class="btn btn-primary" data-propose>${icon('wand')}Tạo đề xuất AutoMix</button>` })}
          ${card({ title: 'Giữ mức giọng nói (micro Mục sư)', sub: 'Speech Leveler · chống vỡ tiếng · giữ yên khi ngừng nói',
            actions: `<button class="btn btn-sm" data-leveler-refresh>${icon('refresh', 'icon-sm')}Kiểm tra lại</button>`,
            body: `<div data-leveler>${loadingRows(4)}</div>` })}
        </div>
      </div>`;

    let alive = true;
    let inflight = false;
    let lastOk = null;
    const tbBox = $('[data-tb]', root);
    const tiles = $('[data-tiles]', root);
    const chBox = $('[data-channels]', root);
    const adviceBox = $('[data-advice]', root);
    const updated = $('[data-updated]', root);

    // ---------- Automixer status (polled) ----------
    async function pollAutomix() {
      if (!alive || document.hidden || inflight) return;
      inflight = true;
      try {
        const r = await api.get('/api/v1/automixer/status');
        if (!alive) return;
        lastOk = Date.now();
        renderAutomix(r);
      } catch (e) {
        if (!alive) return;
        if (!lastOk) {
          tiles.innerHTML = '';
          chBox.innerHTML = errorBox(e);
        } else {
          updated.innerHTML = `<span class="warn-text">Mất kết nối: ${esc(e.message)}</span>`;
        }
      } finally {
        inflight = false;
      }
    }

    function renderAutomix(r) {
      const channels = r.channels || [];
      const primary = channels.find(c => c.channel_id === r.primary_speaker_id);
      updated.textContent = `Cập nhật lúc ${new Date().toLocaleTimeString('vi-VN')}`;

      tbBox.innerHTML = r.talkback_safe === false
        ? `<div class="big-alert">${icon('alert', 'icon-lg')}<div class="grow"><h3>Talkback ban nhạc (kênh 11) đang bị lọt!</h3>
            <p class="text-2">Kênh 11 chỉ được đi vào tai nghe P16. Mọi đề xuất tự động bị chặn cho tới khi xử lý xong.</p></div></div>`
        : callout('ok', '<strong>Talkback ban nhạc (kênh 11) được cách ly</strong> — không tham gia nhóm Automix, không ra loa chính.', 'shieldCheck');

      const gain = +r.total_system_gain_db;
      tiles.innerHTML = `
        <div class="stat"><div class="stat-label">Tổng gain của nhóm</div>
          <div class="stat-value ${gain <= 0.05 ? 'ok-text' : 'bad-text'}">${fmt.db(gain)}</div>
          <div class="stat-sub">≤ 0 dB: mở thêm micro không làm to hơn (NOM = 1)</div></div>
        <div class="stat"><div class="stat-label">Ồn nền giảm được</div>
          <div class="stat-value">${signed(r.noise_reduction_savings_db)} dB</div>
          <div class="stat-sub">So với để mọi micro mở cùng lúc</div></div>
        <div class="stat"><div class="stat-label">Người đang nói chính</div>
          <div class="stat-value" style="font-size:18px">${primary ? esc(primary.channel_name) : (r.primary_speaker_id ? fmt.ch(r.primary_speaker_id) : 'Không ai nói')}</div>
          <div class="stat-sub">${esc(r.active_speakers_count ?? 0)} micro đang phát biểu</div></div>
        <div class="stat"><div class="stat-label">Giữ yên khi im lặng</div>
          <div class="stat-value" style="font-size:18px">${r.silence_hold_engaged ? '<span class="warn-text">Đang khóa gain</span>' : '<span class="ok-text">Đang chia gain</span>'}</div>
          <div class="stat-sub">${r.silence_hold_engaged ? 'Mọi micro im lặng — không tự kéo ồn nền lên' : 'Có người nói, gain theo người nói'}</div></div>`;

      if (!channels.length) {
        chBox.innerHTML = emptyState('Chưa có micro nào trong nhóm.');
      } else {
        chBox.innerHTML = `
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Kênh</th><th>Tên</th><th>Vai trò</th><th>Đang nói</th>
              <th class="right">Mức vào</th><th class="right">Ưu tiên</th><th style="min-width:180px">Gain được chia</th></tr></thead>
            <tbody>${channels.map(c => {
              const isPrimary = c.channel_id === r.primary_speaker_id;
              const attn = +c.gain_sharing_attenuation_db;
              const pct = Math.max(0, Math.min(100, ((attn + 18) / 18) * 100));
              return `<tr>
                <td class="mono nowrap">${fmt.ch(c.channel_id)}</td>
                <td><strong>${esc(c.channel_name)}</strong>${isPrimary ? ` ${badge('Ưu tiên số 1', 'info')}` : ''}</td>
                <td class="text-2">${esc(roleVi(c.role))}</td>
                <td class="nowrap">${c.is_speaking ? '<span class="row" style="gap:6px"><span class="dot dot-ok"></span>Đang nói</span>' : '<span class="row muted" style="gap:6px"><span class="dot"></span>Im lặng</span>'}</td>
                <td class="right mono">${fmt.num(c.level_dbfs, 1)} dBFS</td>
                <td class="right mono">${signed(c.weight_db)} dB</td>
                <td><div class="row" style="flex-wrap:nowrap">
                  <div class="bar ${isPrimary ? 'ok' : ''} grow"><span style="width:${pct.toFixed(0)}%"></span></div>
                  <span class="mono small nowrap" style="min-width:64px;text-align:right">${signed(attn)} dB</span></div></td>
              </tr>`;
            }).join('')}</tbody>
          </table></div>
          <p class="small muted mt-8">Gain được chia: 0 dB là giữ nguyên, −18 dB là giảm tối đa. Micro nói to nhất (cộng trọng số ưu tiên) nhận nhiều gain nhất.</p>`;
      }

      adviceBox.innerHTML = r.advice_vi ? callout('info', esc(r.advice_vi), 'info') : '';
    }

    // ---------- Native AutoMix proposals ----------
    const propBox = $('[data-proposals]', root);
    $('[data-propose]', root).addEventListener('click', async (e) => {
      const group_id = parseInt($('#am-group', root).value, 10) || 1;
      const data = await withLoading(e.currentTarget, () => api.post('/api/v1/automixer/propose-setup', {
        channels: AUTOMIX_SETUP.channels,
        weights_db: Object.fromEntries(Object.entries(AUTOMIX_SETUP.weights_db).map(([k, v]) => [String(k), v])),
        group_id,
      }), { errorPrefix: 'Không tạo được đề xuất AutoMix: ' });
      if (!data || !alive) return;
      const proposals = data.proposals || [];
      if (!proposals.length) {
        propBox.innerHTML = callout('ok', 'Không cần thay đổi — AutoMix đã đúng cấu hình.');
        return;
      }
      propBox.innerHTML = `${callout('info', `Đã tạo <strong>${proposals.length}</strong> đề xuất (mỗi kênh một đề xuất). Duyệt từng cái bên dưới.`)}
        ${proposals.map((_, i) => `<div class="stat" data-prop="${i}"></div>`).join('')}`;
      proposals.forEach((p, i) => renderProposal($(`[data-prop="${i}"]`, propBox), p, {
        title: `AutoMix ${group_id === 2 ? 'nhóm Y' : 'nhóm X'}`,
        note: 'Bật AutoMix gốc trên X32 và đặt trọng số ưu tiên. Có thể tắt lại trên mixer bất cứ lúc nào.',
      }));
      toast(`Đã tạo ${proposals.length} đề xuất AutoMix. Hãy duyệt trước khi áp dụng.`, 'info');
    });

    // ---------- Speech leveler ----------
    const levBox = $('[data-leveler]', root);
    async function loadLeveler(btn) {
      let d;
      try {
        d = btn ? await withLoading(btn, () => api.get('/api/v1/mix-assistant/speech-status')) : await api.get('/api/v1/mix-assistant/speech-status');
      } catch (e) {
        if (alive) levBox.innerHTML = errorBox(e);
        return;
      }
      if (!alive || !d) return;
      const a = LEVELER_ACTION[d.action] || { label: d.action || '—', kind: 'info', desc: '' };
      const silence = /SILENCE/i.test(d.rationale || '');
      const inv = d.safety_invariants || {};
      levBox.innerHTML = `
        <div class="grid-2">
          <div class="stat"><div class="stat-label">Khuyến nghị lúc này</div>
            <div class="stat-value" style="font-size:17px"><span class="${a.kind === 'info' ? '' : `${a.kind}-text`}">${esc(a.label)}</span></div>
            <div class="stat-sub">${esc(silence ? 'Người nói đang ngừng — fader được khóa, không kéo ồn nền lên.' : a.desc)}</div></div>
          <div class="stat"><div class="stat-label">Vị trí fader mục tiêu</div>
            <div class="stat-value">${d.target_fader === undefined ? '—' : `${Math.round(+d.target_fader * 100)}%`}</div>
            <div class="stat-sub">Thay đổi ${signed((+d.fader_delta || 0) * 100, 1)}% · chỉ là gợi ý, không tự ghi</div></div>
        </div>
        <dl class="kv mt-16">
          <dt>Kênh theo dõi</dt><dd>${fmt.ch(d.channel_id)} · ${esc(roleVi(d.role))}</dd>
          <dt>Giữ yên khi ngừng nói</dt><dd>${/ENGAGED/i.test(inv.silence_hold || '') ? badge('Đang bật', 'ok') : badge('Không rõ', 'warn')}
            <span class="small muted">Fader không bao giờ tự tăng lúc người nói tạm dừng</span></dd>
          <dt>Chống vỡ tiếng</dt><dd>${/ARMED/i.test(inv.anti_clipping || '') ? badge('Sẵn sàng', 'ok') : badge('Không rõ', 'warn')}
            <span class="small muted">Tự đề xuất hạ khi đỉnh vượt −1,5 dBFS</span></dd>
          <dt>Chi tiết kỹ thuật</dt><dd class="small mono text-2">${esc(d.rationale || '—')}</dd>
        </dl>`;
    }
    $('[data-leveler-refresh]', root).addEventListener('click', (e) => loadLeveler(e.currentTarget));

    // ---------- Start ----------
    tiles.innerHTML = Array.from({ length: 4 }, () => `<div class="stat">${loadingRows(2)}</div>`).join('');
    pollAutomix();
    loadLeveler();
    const timer = setInterval(pollAutomix, POLL_MS);
    const onVisible = () => { if (!document.hidden) pollAutomix(); };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
};
