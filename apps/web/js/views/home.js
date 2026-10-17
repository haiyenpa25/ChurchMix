// Tổng quan hôm nay — màn hình chính của chế độ Đơn giản.
// Dành cho người không chuyên: một câu trạng thái lớn, 3 bước Trước – Trong – Sau lễ,
// ngôn ngữ đời thường, nút to. Mọi lệnh ghi đều phải xác nhận và đi qua Safety Gate.

import { api, getOperator } from '../api.js';
import { store } from '../store.js';
import { meterPercent, safeMeterLevel } from '../signal-levels.js';
import {
  $, $$, esc, icon, fmt, callout, card, renderMarkdown, renderProposal, confirmDialog,
  withLoading, toast, downloadText, loadingRows, errorBox,
} from '../ui.js';
import { renderCopilotBox } from './copilot.js';
import { renderSegmentBar } from '../segments.js';

const STEP_KEY = 'churchmix.homeStep';
const KEY_ROLES = ['PASTOR_SPEECH', 'LEAD_VOCAL_FEMALE', 'LEAD_VOCAL_MALE', 'CHOIR_OVERHEAD'];
const MANUAL_CHECKS = [
  'Thay pin / sạc đầy micro không dây (Mục sư, MC, ca đoàn)',
  'Cắm dây chắc chắn, không vướng lối đi',
  'Loa monitor không chĩa thẳng vào micro',
  'Nói thử từng micro chính — nghe rõ, không rè',
  'Bật thiết bị livestream (nếu có)',
];

function readStep() {
  try { return sessionStorage.getItem(STEP_KEY) || 'before'; } catch { return 'before'; }
}
function saveStep(s) {
  try { sessionStorage.setItem(STEP_KEY, s); } catch { /* storage blocked */ }
}

export default {
  mount(root, ctx) {
    const offs = [];
    let step = readStep();
    let diag = null;          // last /system/diagnostics result
    let channels = [];        // /api/v1/channels
    const manual = new Set();

    root.innerHTML = `
      <div class="stack">
        <div class="hero" data-hero>
          <div class="hero-icon">${icon('shield', 'icon-lg')}</div>
          <div class="grow"><h2>Đang kiểm tra hệ thống…</h2><p>Vui lòng đợi vài giây.</p></div>
        </div>
        <div class="steps">
          <button class="step" data-step="before"><span class="step-num">1</span><h3>Trước lễ</h3><p>Kiểm tra micro, dây, mixer. Khoảng 5 phút.</p></button>
          <button class="step" data-step="during"><span class="step-num">2</span><h3>Trong lễ</h3><p>Theo dõi cảnh báo hú, mức micro chính và livestream.</p></button>
          <button class="step" data-step="after"><span class="step-num">3</span><h3>Sau lễ</h3><p>Lưu cấu hình, xem báo cáo, ghi chú cho lần sau.</p></button>
        </div>
        <div data-panel></div>
        <div class="row-between small muted" style="padding:4px 2px">
          <span>Cần công cụ chi tiết (EQ, gain, monitor, scene…)?</span>
          <button class="btn btn-sm" data-go-tech>${icon('sliders', 'icon-sm')}Mở chế độ Kỹ thuật</button>
        </div>
      </div>`;

    const hero = $('[data-hero]', root);
    const panel = $('[data-panel]', root);

    $('[data-go-tech]', root).addEventListener('click', () => {
      try { localStorage.setItem('churchmix.mode', 'tech'); } catch { /* storage blocked */ }
      ctx.navigate('live');
    });
    $$('[data-step]', root).forEach(b => b.addEventListener('click', () => { step = b.dataset.step; saveStep(step); renderStep(); }));

    function channelName(id) {
      const c = channels.find(x => x.channel === id);
      return c ? `kênh ${id} (${c.name})` : `kênh ${id}`;
    }

    // ---------- Hero: one sentence that says if it is safe ----------
    function renderHero() {
      const s = store.status;
      const t = store.telemetry;
      const alerts = t?.feedback_alerts || [];
      const stop = t?.stop_auto ?? s?.stop_auto;
      const safety = t?.safety_mode || s?.safety_mode;
      let kind = 'ok', ic = 'checkCircle', title = 'Mọi thứ sẵn sàng', text = 'Mixer đã kết nối, Talkback ban nhạc được cách ly khỏi loa chính.';
      let action = '';

      if (!s) {
        kind = 'bad'; ic = 'xCircle'; title = 'Mất kết nối với mixer';
        text = 'Kiểm tra cáp mạng tới X32 và máy chủ ChurchMix. Âm thanh vẫn chạy bình thường trên mixer.';
      } else if (s.dl16_talkback_invariant && s.dl16_talkback_invariant.safe === false) {
        kind = 'bad'; ic = 'alert'; title = 'Talkback ban nhạc có thể lọt ra loa chính!';
        text = 'Báo ngay kỹ thuật viên chính. Hệ thống đã chặn mọi thay đổi tự động.';
      } else if (stop) {
        kind = 'bad'; ic = 'hand'; title = 'Hệ thống đang khóa khẩn cấp (STOP)';
        text = 'Không có thay đổi nào được gửi xuống mixer. Bấm nút đỏ góc trên để mở khóa khi đã ổn.';
      } else if (alerts.length) {
        const a = alerts[0];
        kind = 'bad'; ic = 'volume'; title = `Có dấu hiệu hú ở ${channelName(a.channel_id)}`;
        text = `Khoảng ${fmt.hz(a.freq_hz)}. Xem hướng dẫn ở bước "Trong lễ".`;
        action = `<button class="btn btn-danger" data-hero-go="during">Xử lý ngay</button>`;
      } else if (safety?.is_disengaged) {
        kind = 'warn'; ic = 'alert'; title = 'Hệ thống đã tự ngắt chế độ tự động';
        text = `Lý do: ${safety.disengage_detail || safety.disengage_reason}. Mixer vẫn hoạt động, chỉ tạm dừng hỗ trợ tự động.`;
      } else if (diag && diag.overall_status !== 'PASS') {
        kind = 'warn'; ic = 'alert'; title = `Còn ${diag.total_count - diag.passed_count} mục cần kiểm tra`;
        text = 'Xem danh sách ở bước "Trước lễ".';
        action = `<button class="btn" data-hero-go="before">Xem</button>`;
      } else if (!diag) {
        kind = 'warn'; ic = 'stethoscope'; title = 'Chưa kiểm tra trước lễ hôm nay';
        text = 'Bấm "Kiểm tra tự động" ở bước 1 — mất khoảng 10 giây.';
      }

      const key = [kind, title, text, action].join('|');
      if (hero.dataset.key === key) return;
      hero.dataset.key = key;
      hero.className = `hero ${kind}`;
      hero.innerHTML = `<div class="hero-icon">${icon(ic, 'icon-lg')}</div>
        <div class="grow"><h2>${esc(title)}</h2><p>${esc(text)}</p></div>${action}`;
      $('[data-hero-go]', hero)?.addEventListener('click', (e) => { step = e.currentTarget.dataset.heroGo; saveStep(step); renderStep(); });
    }

    // ---------- Steps ----------
    let stepCleanup = null;
    function renderStep() {
      $$('[data-step]', root).forEach(b => b.classList.toggle('active', b.dataset.step === step));
      if (stepCleanup) { stepCleanup(); stepCleanup = null; }
      if (step === 'before') stepCleanup = renderBefore();
      else if (step === 'during') stepCleanup = renderDuring();
      else stepCleanup = renderAfter();
    }

    // Step 1 — before service
    function renderBefore() {
      panel.innerHTML = `
        <div class="grid-2">
          ${card({
            title: 'Kiểm tra tự động',
            sub: 'Máy kiểm tra mixer, cổng an toàn, cơ sở dữ liệu và từng kênh',
            actions: `<button class="btn btn-primary" data-run>${icon('stethoscope')}Kiểm tra tự động</button>`,
            body: `<div data-auto>${diag ? '' : '<p class="muted">Bấm nút để bắt đầu.</p>'}</div>`,
          })}
          ${card({
            title: 'Kiểm tra bằng tay',
            sub: 'Đánh dấu khi bạn đã tự kiểm tra',
            body: `<div class="checklist">${MANUAL_CHECKS.map((c, i) => `
              <label class="check-item" style="cursor:pointer"><input type="checkbox" data-manual="${i}" ${manual.has(i) ? 'checked' : ''} style="width:20px;height:20px;accent-color:var(--ok)"><span>${esc(c)}</span></label>`).join('')}
            </div><div data-manual-sum class="mt-8"></div>`,
          })}
        </div>`;
      const auto = $('[data-auto]', panel);
      const sumManual = () => {
        $('[data-manual-sum]', panel).innerHTML = manual.size === MANUAL_CHECKS.length
          ? callout('ok', 'Đã kiểm tra đủ bằng tay.')
          : `<p class="small muted">Đã xong ${manual.size}/${MANUAL_CHECKS.length} mục.</p>`;
      };
      $$('[data-manual]', panel).forEach(cb => cb.addEventListener('change', () => {
        cb.checked ? manual.add(+cb.dataset.manual) : manual.delete(+cb.dataset.manual);
        sumManual();
      }));
      sumManual();

      const run = async () => {
        auto.innerHTML = loadingRows(5);
        try {
          const [d, lc] = await Promise.all([
            api.get('/api/v1/system/diagnostics'),
            api.get('/api/v1/wizards/line-check').catch(() => null),
          ]);
          diag = d;
          renderHero();
          const problems = (lc?.items || []).filter(it => it.status !== 'OK' && !/talkback/i.test(it.notes || ''));
          auto.innerHTML = `
            ${d.overall_status === 'PASS'
              ? callout('ok', `<strong>Đạt ${d.passed_count}/${d.total_count} mục.</strong> Hệ thống sẵn sàng.`)
              : callout('warn', `<strong>Đạt ${d.passed_count}/${d.total_count} mục.</strong> Xem các mục màu đỏ bên dưới.`)}
            <div class="checklist mt-8">${(d.checks || []).map(c => `
              <div class="check-item">
                <span class="${c.passed ? 'ok-text' : 'bad-text'}">${icon(c.passed ? 'checkCircle' : 'xCircle')}</span>
                <div class="grow"><div class="strong">${esc(c.name.replace(/^\d+\.\s*/, ''))}</div><div class="small muted">${esc(c.message)}</div></div>
              </div>`).join('')}</div>
            ${lc ? `<h3 class="mt-16">Các kênh</h3>
              ${problems.length
                ? `<div class="checklist">${problems.map(p => `<div class="check-item"><span class="warn-text">${icon('alert')}</span>
                    <div class="grow"><strong>Kênh ${p.channel_id} · ${esc(p.name)}</strong><div class="small muted">${esc(p.notes || p.status)}</div></div></div>`).join('')}</div>`
                : `<p class="small ok-text mt-8">Tất cả kênh đang dùng đều sẵn sàng.</p>`}` : ''}
            <div class="row mt-16"><button class="btn btn-sm" data-go-prep>Xem chi tiết kỹ thuật</button></div>`;
          $('[data-go-prep]', auto).addEventListener('click', () => ctx.navigate('prep'));
        } catch (e) {
          auto.innerHTML = errorBox(e);
        }
      };
      $('[data-run]', panel).addEventListener('click', (e) => withLoading(e.currentTarget, run));
      if (diag) run();
      return () => {};
    }

    // Step 2 — during service
    function renderDuring() {
      panel.innerHTML = `
        <div class="stack">
          <div data-suggest></div>
          <div data-program></div>
          ${card({
            title: 'Đang diễn ra tiết mục nào?',
            sub: 'Bấm một tiết mục: máy tự mở đúng micro và tắt các micro khác. Luôn hỏi lại trước khi đổi.',
            body: '<div data-segments></div>',
          })}
          <div data-autopilot></div>
          <div data-feedback></div>
          <div class="grid-2">
            ${card({ title: 'Micro chính', sub: 'Mức tín hiệu trực tiếp. Thanh xanh khi đang nói.', body: '<div data-mics>' + loadingRows(3) + '</div>' })}
            ${card({ title: 'Livestream', sub: 'Độ to cho người xem qua mạng', body: '<div data-ls>' + loadingRows(2) + '</div>' })}
          </div>
          ${callout('info', `<strong>Khi có sự cố lạ</strong> (tiếng rít, tiếng nổ, âm lượng tự thay đổi): bấm nút đỏ <strong>STOP</strong> góc trên bên phải. Mixer vẫn chạy bình thường, chỉ dừng mọi hỗ trợ tự động.`, 'hand')}
        </div>`;

      const fb = $('[data-feedback]', panel);
      const mics = $('[data-mics]', panel);
      const ls = $('[data-ls]', panel);
      let fbKey = null;
      let proposalOpen = false;

      // Feedback guidance — rebuild only when the alert changes
      const renderFeedback = (alerts) => {
        if (proposalOpen) return;
        const a = alerts[0];
        const key = a ? `${a.channel_id}|${Math.round(a.freq_hz / 50)}` : '';
        if (key === fbKey) return;
        fbKey = key;
        if (!a) { fb.innerHTML = callout('ok', 'Không phát hiện tiếng hú.'); return; }
        fb.innerHTML = `
          <div class="big-alert">
            <span class="bad-text">${icon('volume', 'icon-xl')}</span>
            <div class="grow">
              <h2>Có dấu hiệu hú ở ${esc(channelName(a.channel_id))}</h2>
              <p class="text-2 mt-8">Tần số khoảng <strong>${fmt.hz(a.freq_hz)}</strong> · độ tin cậy ${fmt.pct(a.confidence)}</p>
              <ol class="text-2" style="margin:10px 0 0;padding-left:20px">
                <li>Kéo fader <strong>${esc(channelName(a.channel_id))}</strong> xuống một chút (khoảng 3–5 dB) trên mixer.</li>
                <li>Nhắc người cầm micro không đứng trước loa, không che đầu micro.</li>
                <li>Nếu vẫn hú: bấm "Nhờ hệ thống đề xuất cắt hú" và đưa kỹ thuật viên duyệt.</li>
              </ol>
            </div>
            <button class="btn btn-lg" data-notch>${icon('scissors')}Nhờ hệ thống đề xuất cắt hú</button>
          </div>
          <div data-proposal class="card mt-16" hidden><div class="card-body"></div></div>`;
        $('[data-notch]', fb).addEventListener('click', async (e) => {
          const p = await withLoading(e.currentTarget, () => api.post('/api/v1/proposals/generate-notch', {
            channel_id: a.channel_id, freq_hz: a.freq_hz, confidence: a.confidence,
          }), { errorPrefix: 'Không tạo được đề xuất: ' });
          if (!p) return;
          proposalOpen = true;
          const box = $('[data-proposal]', fb);
          box.hidden = false;
          renderProposal($('.card-body', box), p, {
            title: 'Đề xuất cắt hú hẹp',
            note: 'Cần chế độ "Hỗ trợ" để áp dụng. Nếu bạn không chắc, hãy nhờ kỹ thuật viên.',
            onApplied: () => { proposalOpen = false; },
            onDismiss: () => { proposalOpen = false; fbKey = null; box.hidden = true; },
          });
        });
      };

      // Key microphones with live level
      const keyChannels = () => channels.filter(c => KEY_ROLES.includes(c.church_role)).slice(0, 6);
      const renderMics = () => {
        const list = keyChannels();
        if (!list.length) { mics.innerHTML = '<p class="muted">Chưa có kênh micro chính trong sơ đồ kênh.</p>'; return; }
        mics.innerHTML = `<div class="stack-sm">${list.map(c => `
          <div class="row" style="flex-wrap:nowrap" data-mic="${c.channel}">
            <div style="width:150px;min-width:0"><div class="strong" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.name)}</div>
              <div class="tiny muted">Kênh ${c.channel}</div></div>
            <div class="bar grow"><span style="width:0%"></span></div>
            <span class="badge ${c.on ? 'badge-ok' : 'badge-warn'}">${c.on ? 'Đang bật' : 'Đang tắt'}</span>
            <button class="btn btn-sm" data-toggle="${c.channel}">${c.on ? 'Tắt' : 'Bật'}</button>
          </div>`).join('')}</div>
          <p class="small muted mt-8">Bật/tắt từ đây cần chế độ "Hỗ trợ". Cách nhanh nhất vẫn là nút Mute trên mixer.</p>`;
        $$('[data-toggle]', mics).forEach(b => b.addEventListener('click', async () => {
          const id = +b.dataset.toggle;
          const ch = channels.find(x => x.channel === id);
          const target = ch.on ? 0 : 1;
          const ok = await confirmDialog({
            title: `${target ? 'Bật' : 'Tắt'} micro ${esc(ch.name)}?`,
            message: `Kênh ${id} sẽ được ${target ? '<strong>bật</strong>' : '<strong>tắt tiếng</strong>'} trên mixer. Người thực hiện: ${esc(getOperator())}.`,
            confirmText: target ? 'Bật micro' : 'Tắt micro',
            danger: !target,
          });
          if (!ok) return;
          const res = await withLoading(b, () => api.post(`/api/v1/channels/${id}/mute`, { on: target, operator_id: getOperator() }),
            { errorPrefix: 'Không đổi được: ' });
          if (res) {
            ch.on = res.on;
            toast(`${ch.name}: ${res.on ? 'đã bật' : 'đã tắt'}`, 'ok');
            renderMics();
          }
        }));
      };
      const updateMicMeters = (meters, source) => {
        meters.forEach(m => {
          const row = mics.querySelector(`[data-mic="${m.channel}"]`);
          if (!row) return;
          const level = safeMeterLevel(m, source);
          const pct = meterPercent(level);
          const bar = row.querySelector('.bar');
          bar.firstElementChild.style.width = `${pct}%`;
          bar.title = level === null ? 'Chưa có dữ liệu micro đã xác minh' : `${level.toFixed(1)} dBFS`;
          const cls = level !== null && level > -6 ? 'bar grow bad' : level !== null && level > -40 ? 'bar grow ok' : 'bar grow';
          if (bar.className !== cls) bar.className = cls;
        });
      };

      // Livestream traffic light
      const renderLivestream = async () => {
        if (document.hidden) return;
        try {
          const d = await api.get('/api/v1/broadcast/loudness?target_profile=YOUTUBE_STREAMING&livestream_bus=5');
          const st = d.compliance_status;
          const level = st === 'COMPLIANT' || st === 'ON_TARGET' ? 'ok' : (st === 'TOO_LOUD' || st === 'CLIPPING' ? 'bad' : 'warn');
          const label = { ok: 'Vừa đủ', warn: st === 'TOO_QUIET' ? 'Hơi nhỏ' : 'Cần chỉnh', bad: 'Quá to' }[level];
          ls.innerHTML = `
            <div class="traffic">
              <span class="light ${level === 'bad' ? 'on bad' : ''}"></span><span class="light ${level === 'warn' ? 'on warn' : ''}"></span><span class="light ${level === 'ok' ? 'on ok' : ''}"></span>
              <div><div class="strong" style="font-size:18px">${label}</div><div class="small muted">${fmt.num(d.integrated_lufs)} LUFS · mục tiêu ${fmt.num(d.target_lufs)}</div></div>
            </div>
            <p class="small text-2 mt-8">${esc(d.recommendation_vi || '')}</p>
            ${d.talkback_isolated === false ? callout('bad', esc(d.talkback_warning || 'Talkback đang lọt vào livestream!')) : ''}`;
        } catch (e) {
          ls.innerHTML = `<p class="muted small">Chưa đo được livestream: ${esc(e.message)}</p>`;
        }
      };

      let duringAlive = true;
      const refreshChannels = () => api.get('/api/v1/channels').then(d => { channels = d.channels || []; renderMics(); }).catch(() => {});
      let segCleanup = () => {};
      const mountSegBar = () => {
        segCleanup();
        segCleanup = renderSegmentBar($('[data-segments]', panel), { onChanged: () => { refreshChannels(); loadProgram(); } });
      };

      // Chương trình lễ — "Đang / Tiếp theo". Switching always goes through switchToSegment
      // (preview + confirm + Safety Gate); the program marker moves only after it succeeded.
      const progBox = $('[data-program]', panel);
      let prog = null;
      const switchSeg = async (seg) => (await import('../segments.js')).switchToSegment(seg);
      const afterSwitch = async (index, segmentId) => {
        try { prog = await api.post('/api/v1/program/current', { index, segment_id: segmentId, operator_id: getOperator() }); }
        catch (e) { toast(`Đã chuyển micro nhưng chưa cập nhật chương trình: ${e.message}`, 'warn'); }
        if (duringAlive) { renderProgram(); mountSegBar(); refreshChannels(); }
      };
      const renderProgram = () => {
        if (!prog) { progBox.innerHTML = ''; return; }
        if (!prog.items.length) {
          progBox.innerHTML = `<p class="small muted">Chưa có chương trình lễ. <a href="#/program">Lập chương trình</a> để chỉ cần bấm “Tiếp theo” trong lễ.</p>`;
          return;
        }
        const cur = prog.current, nxt = prog.next;
        progBox.innerHTML = `
          <div class="hero" style="padding:14px 16px;flex-wrap:wrap">
            <div class="hero-icon" style="width:44px;height:44px">${icon('clipboard')}</div>
            <div class="grow" style="min-width:180px">
              <p class="small">Chương trình lễ · <a href="#/program">Sửa</a></p>
              <h3 style="font-size:17px">Đang: ${cur ? esc(cur.title) : 'chưa bắt đầu'}</h3>
            </div>
            ${nxt
              ? `<button class="btn btn-primary btn-lg" data-prog-next style="max-width:100%;white-space:normal;height:auto;min-height:48px">${icon('arrowRight')}Tiếp theo: ${esc(nxt.title)}</button>`
              : `<span class="small muted">Đã hết chương trình.</span><button class="btn btn-sm" data-prog-reset>Làm lại từ đầu</button>`}
          </div>`;
        $('[data-prog-next]', progBox)?.addEventListener('click', async (e) => {
          const index = prog.next_index;
          const item = prog.next;
          if (item.segment_missing) { toast('Tiết mục của phần này đã bị xóa. Sửa chương trình trước.', 'warn'); return; }
          const res = await switchSeg({ id: item.segment_id, name: item.segment_name || item.title, description: item.note || '' });
          if (res) { await afterSwitch(index, item.segment_id); return; }
          // Cancelled — or nothing to change because the mixer already matches: then just move the marker.
          const pv = await api.get(`/api/v1/segments/${encodeURIComponent(item.segment_id)}/preview`).catch(() => null);
          if (pv && !pv.to_mute.length && !pv.to_unmute.length) await afterSwitch(index, item.segment_id);
        });
        $('[data-prog-reset]', progBox)?.addEventListener('click', async (e) => {
          const p = await withLoading(e.currentTarget, () => api.post('/api/v1/program/reset', { operator_id: getOperator() }));
          if (p && duringAlive) { prog = p; renderProgram(); }
        });
      };
      const loadProgram = () => api.get('/api/v1/program')
        .then(p => { if (duringAlive) { prog = p; renderProgram(); } })
        .catch(() => { if (duringAlive) progBox.innerHTML = ''; });

      // Tự nhận diện tiết mục — a suggestion only; the operator decides.
      const sugBox = $('[data-suggest]', panel);
      let sugKey = '';
      const DISMISS_KEY = 'churchmix.dismissedSuggestion';
      const dismissed = () => { try { return sessionStorage.getItem(DISMISS_KEY) || ''; } catch { return ''; } };
      const renderSuggestion = (s) => {
        const key = s ? `${s.segment_id}|${s.since}` : '';
        const show = s && key !== dismissed() ? key : '';
        if (show === sugKey) return;
        sugKey = show;
        if (!show) { sugBox.innerHTML = ''; return; }
        sugBox.innerHTML = `
          <div class="callout callout-info" style="flex-wrap:wrap">${icon('eye')}
            <div class="grow" style="min-width:180px"><strong>Có vẻ đang là tiết mục: ${esc(s.name)} — Chuyển?</strong>
              <div class="small muted">${esc(s.reason_vi || '')} Máy chỉ gợi ý, không tự chuyển.</div></div>
            <div class="row" style="gap:6px">
              <button class="btn btn-primary" data-sug-go>${icon('arrowRight')}Chuyển</button>
              <button class="btn btn-ghost" data-sug-x aria-label="Bỏ qua gợi ý">Bỏ qua</button>
            </div>
          </div>`;
        $('[data-sug-x]', sugBox).addEventListener('click', () => {
          try { sessionStorage.setItem(DISMISS_KEY, key); } catch { /* storage blocked */ }
          sugKey = ''; renderSuggestion(s);
        });
        $('[data-sug-go]', sugBox).addEventListener('click', async () => {
          const res = await switchSeg({ id: s.segment_id, name: s.name, description: s.reason_vi || '' });
          if (!res || !duringAlive) return;
          try { sessionStorage.setItem(DISMISS_KEY, key); } catch { /* storage blocked */ }
          sugKey = ''; renderSuggestion(null);
          if (prog?.next && prog.next.segment_id === s.segment_id) await afterSwitch(prog.next_index, s.segment_id);
          else { mountSegBar(); refreshChannels(); }
        });
      };

      mountSegBar();
      loadProgram();
      renderSuggestion(store.telemetry?.segment_suggestion);

      // Lái tự động — one big switch for volunteers; details live on the technical page.
      const apBox = $('[data-autopilot]', panel);
      let apKey = '';
      const renderAutopilot = (ap) => {
        const key = ap ? `${ap.enabled}|${ap.inactive_reason}` : 'none';
        if (key === apKey) return;
        apKey = key;
        const on = !!ap?.enabled;
        apBox.innerHTML = `
          <div class="hero ${on ? (ap.inactive_reason ? 'warn' : 'ok') : ''}" style="padding:16px 18px">
            <div class="hero-icon" style="width:44px;height:44px">${icon('zap')}</div>
            <div class="grow">
              <h3 style="font-size:17px">${on ? (ap.inactive_reason ? 'Lái tự động đang chờ dữ liệu' : 'Lái tự động đang giúp bạn') : 'Lái tự động: tắt'}</h3>
              <p class="small">${on
                ? esc(ap.inactive_reason || 'Máy đang giữ giọng nói đều, chống hú và cân livestream trong giới hạn an toàn. Bạn vẫn kéo fader tay được bất cứ lúc nào.')
                : 'Bật để máy tự giữ giọng Mục sư đều, tự cắt hú nhẹ và giữ livestream vừa nghe — trong giới hạn đã duyệt sẵn.'}</p>
            </div>
            <a class="btn btn-ghost btn-sm" href="#/autopilot">Chi tiết</a>
            <button class="btn ${on ? 'btn-danger' : 'btn-primary'}" data-ap-toggle>${on ? 'Tắt' : 'Bật lái tự động'}</button>
          </div>`;
        $('[data-ap-toggle]', apBox).addEventListener('click', async (e) => {
          if (on) {
            const res = await withLoading(e.currentTarget, () => api.post('/api/v1/autopilot/disable', { operator_id: getOperator() }));
            if (res) { toast('Đã tắt lái tự động.', 'info'); apKey = ''; renderAutopilot(res); }
            return;
          }
          const ok = await confirmDialog({
            title: 'Bật lái tự động?',
            message: 'Máy sẽ tự chỉnh <strong>nhẹ</strong> (giọng nói tối đa ±3 dB, cắt hú hẹp có giới hạn, chỉ bus livestream). Máy <strong>không</strong> tăng âm lượng khi im lặng và <strong>không</strong> đụng tới Talkback. Bấm nút đỏ STOP để dừng ngay bất cứ lúc nào.',
            confirmText: 'Bật lái tự động',
          });
          if (!ok) return;
          const res = await withLoading(e.currentTarget, () => api.post('/api/v1/autopilot/enable', { operator_id: getOperator() }), { errorPrefix: 'Không bật được: ' });
          if (res) { toast('Lái tự động đang chạy.', 'ok'); apKey = ''; renderAutopilot(res); }
        });
      };
      renderAutopilot(store.telemetry?.autopilot);

      renderFeedback(store.telemetry?.feedback_alerts || []);
      renderMics();
      renderLivestream();
      const off = store.on('telemetry', (t) => { renderFeedback(t.feedback_alerts || []); updateMicMeters(t.meters || [], t.source); renderAutopilot(t.autopilot); renderSuggestion(t.segment_suggestion); });
      const lsTimer = setInterval(renderLivestream, 5000);
      return () => { duringAlive = false; off(); clearInterval(lsTimer); segCleanup(); };
    }

    // Step 3 — after service
    function renderAfter() {
      panel.innerHTML = `
        <div class="grid-2">
          ${card({
            title: 'Lưu cấu hình hôm nay',
            sub: 'Tạo bản sao lưu để lần sau dùng lại hoặc khôi phục',
            body: `<div class="field"><label for="bkNote">Ghi chú (không bắt buộc)</label>
              <input id="bkNote" class="input" placeholder="Ví dụ: Lễ sáng Chúa Nhật — micro MC hơi nhỏ"></div><div data-bk class="mt-8"></div>`,
            foot: `<button class="btn btn-primary" data-backup>${icon('archive')}Lưu bản sao lưu</button>`,
          })}
          ${card({
            title: 'Báo cáo buổi lễ',
            sub: 'Tóm tắt sự cố, thay đổi và khuyến nghị cho buổi tập sau',
            body: '<div data-report><p class="muted">Bấm "Tạo báo cáo" để xem.</p></div>',
            foot: `<a class="btn" href="/api/v1/reports/sunday-service" target="_blank" rel="noopener">${icon('file')}Bản in</a>
                   <button class="btn btn-primary" data-report-btn>${icon('clipboard')}Tạo báo cáo</button>`,
          })}
        </div>
        <div class="mt-16">${card({ title: 'Hỏi trợ lý AI', sub: 'Thắc mắc về âm thanh? Hỏi bằng tiếng Việt.', body: '<div data-copilot></div>' })}</div>`;

      $('[data-backup]', panel).addEventListener('click', async (e) => {
        const note = $('#bkNote', panel).value.trim();
        const name = `Le_${new Date().toISOString().slice(0, 10)}`;
        const res = await withLoading(e.currentTarget, () => api.post('/api/v1/vault/snapshots', { name, author: getOperator(), note }),
          { errorPrefix: 'Không lưu được: ' });
        if (res) $('[data-bk]', panel).innerHTML = callout('ok', `Đã lưu bản sao lưu <strong>${esc(res.backup?.name || name)}</strong>. Xem lại trong Kỹ thuật → Scene &amp; sao lưu.`);
      });

      let reportMd = '';
      $('[data-report-btn]', panel).addEventListener('click', async (e) => {
        const box = $('[data-report]', panel);
        const res = await withLoading(e.currentTarget, () => api.get('/api/v1/wizards/end-of-service-report'), { errorPrefix: 'Không tạo được báo cáo: ' });
        if (!res) return;
        reportMd = res.report_markdown || '';
        box.innerHTML = `<div style="max-height:420px;overflow:auto">${renderMarkdown(reportMd)}</div>
          <button class="btn btn-sm mt-8" data-dl>${icon('download', 'icon-sm')}Tải về (.md)</button>`;
        $('[data-dl]', box).addEventListener('click', () => downloadText(`BaoCao_${new Date().toISOString().slice(0, 10)}.md`, reportMd, 'text/markdown;charset=utf-8'));
      });

      renderCopilotBox($('[data-copilot]', panel), { compact: true });
      return () => {};
    }

    // ---------- Boot ----------
    api.get('/api/v1/channels').then(d => { channels = d.channels || []; if (step === 'during') renderStep(); renderHero(); }).catch(() => {});
    renderStep();
    renderHero();
    offs.push(store.on('status', renderHero));
    let heroTick = 0;
    offs.push(store.on('telemetry', () => { if (++heroTick % 5 === 0) renderHero(); })); // ~2 Hz is enough for the hero

    return () => {
      if (stepCleanup) stepCleanup();
      offs.forEach(off => off());
    };
  },
};
