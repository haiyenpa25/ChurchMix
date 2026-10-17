// Nghe thử mù A/B — double-blind A/B listening test with 7-criteria scoring.
// The operator hears two versions (original vs. proposed tuning) without
// knowing which is which, at matched loudness, scores them, and only then
// reveals the identity. Saving an evaluation never touches the mixer; applying
// the linked proposal is a separate, confirmed step through the Safety Gate.

import { $, esc, icon, badge, card, callout, pageHead, emptyState, loadingRows, errorBox, withLoading, toast, openDialog, confirmDialog, fmt } from '../ui.js';
import { api, getOperator } from '../api.js';

const TALKBACK_CH = 11;

// Fallback when /api/v1/listening-test/templates is unavailable (same as backend).
const DEFAULT_CRITERIA = [
  { id: 'intelligibility', name_vi: 'Độ rõ lời', weight: 0.20, description_vi: 'Phát âm rõ ràng từng phụ âm, từ ngữ sáng và dễ hiểu' },
  { id: 'timbre_naturalness', name_vi: 'Độ tự nhiên chất giọng', weight: 0.20, description_vi: 'Giữ trọn bản sắc giọng thật của người nói/ca sĩ, không bị bóp méo' },
  { id: 'warmth_body', name_vi: 'Độ ấm & thân giọng', weight: 0.15, description_vi: 'Đầy đặn vùng trầm-trung (200–400 Hz), không bị mỏng hay rỗng giọng' },
  { id: 'harshness_control', name_vi: 'Kiểm soát gắt & chói', weight: 0.15, description_vi: 'Không bị xì (5–8 kHz) hay chát tai' },
  { id: 'band_balance', name_vi: 'Hòa quyện với ban nhạc', weight: 0.10, description_vi: 'Nổi trên nền nhạc mà không lấn át nhạc cụ khác' },
  { id: 'hall_coverage', name_vi: 'Độ phủ đều hội trường', weight: 0.10, description_vi: 'Nghe đều từ hàng ghế đầu đến cuối nhà thờ' },
  { id: 'feedback_margin', name_vi: 'Dự trữ chống hú', weight: 0.10, description_vi: 'Còn khoảng an toàn trước khi bắt đầu hú (gain trước feedback)' },
];
// Defaults mirror ListeningEvaluationRequest in the backend.
const DEFAULT_SCORES = {
  intelligibility: 4.5, timbre_naturalness: 4.5, warmth_body: 4.0, harshness_control: 4.0,
  band_balance: 4.0, hall_coverage: 4.0, feedback_margin: 4.5,
};
// Criteria whose score below 2.5 is a hard fail (same rule as the old page).
const CRITICAL = ['intelligibility', 'timbre_naturalness', 'feedback_margin'];
const FALLBACK_CHANNELS = [
  { channel: 1, name: 'Pastor Mic' }, { channel: 2, name: 'Worship Lead' },
  { channel: 3, name: 'Vocal Alto' }, { channel: 4, name: 'Podium Mic' },
];

const REC = {
  RECOMMENDED_FOR_COMMIT: { kind: 'ok', label: 'Nên áp dụng' },
  ACCEPTABLE_WITH_MONITORING: { kind: 'warn', label: 'Chấp nhận, cần theo dõi' },
  REJECT_OR_REFINE: { kind: 'bad', label: 'Chưa đạt — chỉnh lại' },
};
const recBadge = (r) => badge(REC[r]?.label || r || '—', REC[r]?.kind || statusKindFallback(r));
function statusKindFallback(r) { return /REJECT|FAIL/.test(String(r)) ? 'bad' : /ACCEPT|WARN/.test(String(r)) ? 'warn' : 'info'; }

function localVerdict(scores, criteria) {
  const mos = criteria.reduce((sum, c) => sum + (scores[c.id] ?? 4) * (c.weight ?? 0), 0);
  const criticalFail = CRITICAL.some(k => (scores[k] ?? 5) < 2.5);
  let rec = 'REJECT_OR_REFINE';
  let advice = 'Điểm dưới ngưỡng an toàn: giọng có thể bị mỏng, gắt hoặc dễ hú. Nên chỉnh lại EQ trước khi áp dụng.';
  if (mos >= 4.0 && !criticalFail) {
    rec = 'RECOMMENDED_FOR_COMMIT';
    advice = 'Chất lượng rất tốt: giọng trung thực, rõ lời và an toàn chống hú. Có thể áp dụng cho buổi lễ.';
  } else if (mos >= 3.2 && !criticalFail) {
    rec = 'ACCEPTABLE_WITH_MONITORING';
    advice = 'Ở mức chấp nhận được. Nên theo dõi thêm trong lúc diễn ra buổi lễ.';
  }
  return { mos, rec, advice, criticalFail };
}

export default {
  mount(root, ctx) {
    let alive = true;
    const params = ctx?.params || new URLSearchParams();
    const proposalId = params.get('proposal') || null;
    let channel = Number(params.get('ch')) || 1;
    if (channel === TALKBACK_CH) channel = 1;
    let channelList = FALLBACK_CHANNELS;
    let criteria = DEFAULT_CRITERIA;
    const scores = { ...DEFAULT_SCORES };
    let session = null;
    let current = 'A';
    let revealed = null; // { a: 'TUNING_PROPOSAL'|'DRY_ORIGINAL', b: ... }

    root.innerHTML = `
      ${pageHead('Nghe thử mù A/B',
        'So sánh bản gốc và bản đã chỉnh mà không biết trước bản nào là bản nào, để chấm điểm công bằng bằng tai.')}
      <div class="stack">
        ${callout('info', `<strong>Vì sao nghe “mù”?</strong> Khi biết đâu là bản đã chỉnh, ta dễ tin nó hay hơn. Ở đây hai bản được đặt tên A và B ngẫu nhiên,
          và đã <strong>cân bằng độ to</strong> (bản to hơn thường bị nghe là “hay hơn”).
          <div class="small text-2 mt-8">Cách làm: (1) chọn kênh → (2) nghe lần lượt A và B → (3) chấm 7 tiêu chí → (4) mở danh tính → (5) lưu đánh giá.</div>`)}
        <div class="grid-2">
          ${card({
            title: 'Phiên nghe',
            sub: proposalId ? `Gắn với đề xuất <span class="mono">${esc(proposalId)}</span>` : 'Chưa gắn với đề xuất nào — chỉ lưu đánh giá',
            actions: `<button class="btn btn-sm btn-ghost" data-act="new-session" title="Tạo phiên mới, xáo lại A/B">${icon('refresh')}Phiên mới</button>`,
            body: `
              <div class="stack">
                <div class="grid-2">
                  <div class="field"><label for="ltCh">Kênh đang đánh giá</label>
                    <select id="ltCh" class="select"></select></div>
                  <div class="field"><label>Bù độ to (cân bằng âm lượng)</label>
                    <div class="input mono" style="display:flex;align-items:center" data-slot="comp">—</div></div>
                </div>
                <div class="grid-2" role="radiogroup" aria-label="Bản đang nghe">
                  <button type="button" class="choice" data-opt="A" role="radio">
                    ${icon('headphones', 'icon-lg')}
                    <div class="grow"><div class="row-between"><span class="strong" style="font-size:16px">Bản A</span><span data-badge="A"></span></div>
                      <div class="small text-2" data-desc="A"></div></div>
                  </button>
                  <button type="button" class="choice" data-opt="B" role="radio">
                    ${icon('headphones', 'icon-lg')}
                    <div class="grow"><div class="row-between"><span class="strong" style="font-size:16px">Bản B</span><span data-badge="B"></span></div>
                      <div class="small text-2" data-desc="B"></div></div>
                  </button>
                </div>
                <p class="small muted">Nút A/B ghi nhận bạn đang nghe bản nào. Chuyển qua lại nhiều lần, nghe cùng một đoạn để so sánh.</p>
                <div class="row-between">
                  <span class="small muted" data-slot="session-id"></span>
                  <button class="btn" data-act="reveal">${icon('eye')}Mở danh tính A/B</button>
                </div>
              </div>`,
          })}
          ${card({
            title: 'Kết quả tạm tính',
            sub: 'Cập nhật ngay khi bạn kéo thanh điểm',
            body: `<div data-slot="verdict"></div>`,
            foot: `
              ${proposalId ? `<button class="btn" data-act="save-apply">${icon('shieldCheck')}Lưu &amp; áp dụng đề xuất</button>` : ''}
              <button class="btn btn-primary" data-act="save">${icon('check')}Lưu đánh giá</button>`,
          })}
        </div>
        ${card({
          title: 'Chấm điểm 7 tiêu chí',
          sub: 'Thang 1.0 (rất kém) – 5.0 (xuất sắc). Mỗi tiêu chí nên từ 2.5 trở lên.',
          body: `<div class="grid-2" data-slot="criteria">${loadingRows(4)}</div>`,
        })}
        ${card({
          title: 'Các lần đánh giá gần đây',
          actions: `<button class="btn btn-sm btn-ghost btn-icon" data-act="history" title="Làm mới" aria-label="Làm mới lịch sử">${icon('refresh')}</button>`,
          body: `<div data-slot="history">${loadingRows(3)}</div>`,
        })}
      </div>`;

    const chSel = $('#ltCh', root);
    const compEl = $('[data-slot="comp"]', root);
    const sidEl = $('[data-slot="session-id"]', root);
    const verdictEl = $('[data-slot="verdict"]', root);
    const critEl = $('[data-slot="criteria"]', root);
    const histEl = $('[data-slot="history"]', root);
    const revealBtn = $('[data-act="reveal"]', root);

    const channelName = () => channelList.find(c => c.channel === channel)?.name || `Kênh ${channel}`;

    // ---------- Channels ----------
    function renderChannelSelect() {
      if (!channelList.some(c => c.channel === channel)) channel = channelList[0]?.channel || 1;
      chSel.innerHTML = channelList.map(c =>
        `<option value="${c.channel}" ${c.channel === channel ? 'selected' : ''}>${esc(fmt.ch(c.channel))}: ${esc(c.name)}</option>`).join('');
    }
    async function loadChannels() {
      try {
        const data = await api.get('/api/v1/config/church-channels');
        if (!alive) return;
        const list = (data?.channels || [])
          .filter(c => c.channel !== TALKBACK_CH && !c.is_protected) // talkback never goes to FOH — nothing to audition
          .sort((a, b) => a.channel - b.channel)
          .map(c => ({ channel: c.channel, name: c.name }));
        if (list.length) channelList = list;
      } catch { /* keep fallback list */ }
      renderChannelSelect();
    }

    // ---------- Session ----------
    function renderAB() {
      ['A', 'B'].forEach(opt => {
        const btn = $(`[data-opt="${opt}"]`, root);
        const on = current === opt;
        btn.classList.toggle('selected', on);
        btn.setAttribute('aria-checked', String(on));
        $(`[data-badge="${opt}"]`, root).innerHTML = on ? badge('Đang nghe', 'info') : '<span class="small muted">Bấm để chuyển</span>';
        const id = revealed ? revealed[opt.toLowerCase()] : null;
        $(`[data-desc="${opt}"]`, root).innerHTML = !id
          ? 'Danh tính đang được ẩn.'
          : id === 'TUNING_PROPOSAL'
            ? `<strong class="ok-text">Bản đã chỉnh (đề xuất)</strong> — đã qua EQ / xử lý đề xuất.`
            : `<strong>Bản gốc</strong> — tín hiệu trước khi chỉnh.`;
      });
      revealBtn.disabled = !session || !!revealed;
      revealBtn.innerHTML = revealed ? `${icon('check')}Đã mở danh tính` : `${icon('eye')}Mở danh tính A/B`;
    }

    async function startSession() {
      session = null; revealed = null; current = 'A';
      compEl.textContent = '…';
      sidEl.textContent = '';
      renderAB();
      try {
        const s = await api.post('/api/v1/listening-test/blind-session', {
          target_channel: channel,
          channel_name: channelName(),
          proposal_id: proposalId,
        });
        if (!alive) return;
        session = s;
        const comp = Number(s.loudness_compensation_db || 0);
        compEl.textContent = `${comp > 0 ? '+' : ''}${comp.toFixed(2)} dB`;
        sidEl.innerHTML = `Mã phiên <span class="mono">${esc(String(s.session_id).slice(0, 8))}</span>`;
        renderAB();
      } catch (e) {
        if (!alive) return;
        compEl.textContent = '—';
        toast(`Không tạo được phiên nghe: ${e.message}`, 'bad');
        renderAB();
      }
    }

    async function reveal(btn) {
      if (!session) return;
      const data = await withLoading(btn, () => api.post(`/api/v1/listening-test/blind-session/${encodeURIComponent(session.session_id)}/reveal`),
        { errorPrefix: 'Không mở được danh tính: ' });
      if (!data || !alive) return;
      revealed = { a: data.option_a_identity, b: data.option_b_identity };
      renderAB();
    }

    // ---------- Criteria ----------
    function renderCriteria() {
      critEl.innerHTML = criteria.map(c => `
        <div class="stack-sm" style="padding:12px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface-2)">
          <div class="row-between">
            <label class="strong" for="crit-${c.id}">${esc(c.name_vi)} <span class="small muted">· ${Math.round((c.weight || 0) * 100)}%</span></label>
            <span class="mono strong" data-val="${c.id}">${(scores[c.id] ?? 4).toFixed(1)}</span>
          </div>
          <p class="small muted">${esc(c.description_vi || '')}</p>
          <input id="crit-${c.id}" class="range" type="range" min="1" max="5" step="0.1" value="${scores[c.id] ?? 4}" data-crit="${c.id}">
        </div>`).join('');
      renderVerdict();
    }
    async function loadCriteria() {
      try {
        const data = await api.get('/api/v1/listening-test/templates');
        if (alive && data?.criteria?.length) {
          criteria = data.criteria;
          criteria.forEach(c => { if (scores[c.id] === undefined) scores[c.id] = 4.0; });
        }
      } catch { /* keep built-in criteria */ }
      if (alive) renderCriteria();
    }

    function renderVerdict() {
      const v = localVerdict(scores, criteria);
      const low = criteria.filter(c => (scores[c.id] ?? 5) < 2.5);
      verdictEl.innerHTML = `
        <div class="stack-sm">
          <div class="row-between">
            <div><div class="stat-label">Điểm chất lượng (MOS)</div>
              <div class="stat-value ${REC[v.rec].kind}-text">${v.mos.toFixed(2)} <span class="small muted">/ 5.0</span></div></div>
            ${recBadge(v.rec)}
          </div>
          <div class="bar ${REC[v.rec].kind}"><span style="width:${Math.max(0, Math.min(100, ((v.mos - 1) / 4) * 100)).toFixed(0)}%"></span></div>
          <p class="text-2">${esc(v.advice)}</p>
          ${low.length ? callout('warn', `Dưới ngưỡng 2.5: <strong>${low.map(c => esc(c.name_vi)).join(', ')}</strong>.`) : ''}
          <p class="small muted">Đây là kết quả tạm tính trên máy. Kết quả chính thức do máy chủ tính khi lưu.</p>
        </div>`;
    }

    critEl.addEventListener('input', (e) => {
      const r = e.target.closest('[data-crit]');
      if (!r) return;
      const id = r.dataset.crit;
      scores[id] = parseFloat(r.value) || 1;
      const out = $(`[data-val="${id}"]`, critEl);
      if (out) out.textContent = scores[id].toFixed(1);
      renderVerdict();
    });

    // ---------- Submit ----------
    function payload() {
      const body = {
        target_channel: channel,
        channel_name: channelName(),
        operator: getOperator(),
        proposal_id: proposalId,
        loudness_compensation_db: session ? Number(session.loudness_compensation_db || 0) : 0.0,
        is_blind_test: true,
      };
      criteria.forEach(c => { body[c.id] = scores[c.id]; });
      return body;
    }

    function showResult(data, extraHtml = '') {
      openDialog({
        title: 'Đã lưu đánh giá',
        body: `
          <div class="stack">
            <div class="row-between">
              <div><div class="stat-label">Điểm MOS chính thức</div><div class="stat-value">${fmt.num(data.overall_mos, 2)} <span class="small muted">/ 5.0</span></div></div>
              ${recBadge(data.recommendation)}
            </div>
            ${data.advice_vi ? `<p class="text-2">${esc(data.advice_vi)}</p>` : ''}
            ${(data.strengths_vi || []).length ? `<div><div class="label">Điểm mạnh</div><ul class="small text-2" style="margin:4px 0 0;padding-left:18px">${data.strengths_vi.map(s => `<li>${esc(s)}</li>`).join('')}</ul></div>` : ''}
            ${(data.weaknesses_vi || []).length ? `<div><div class="label">Cần cải thiện</div><ul class="small text-2" style="margin:4px 0 0;padding-left:18px">${data.weaknesses_vi.map(s => `<li>${esc(s)}</li>`).join('')}</ul></div>` : ''}
            ${extraHtml}
          </div>`,
        actions: [{ label: 'Đóng', kind: 'primary' }],
      });
    }

    async function save(btn) {
      const data = await withLoading(btn, () => api.post('/api/v1/listening-test/evaluate', payload()), { errorPrefix: 'Không lưu được đánh giá: ' });
      if (!data || !alive) return;
      toast(`Đã lưu đánh giá ${fmt.ch(channel)}: MOS ${fmt.num(data.overall_mos, 2)}.`, 'ok');
      showResult(data);
      loadHistory();
    }

    async function saveAndApply(btn) {
      if (!proposalId) return;
      const v = localVerdict(scores, criteria);
      const ok = await confirmDialog({
        title: 'Lưu đánh giá và áp dụng đề xuất lên mixer?',
        message: `Đánh giá sẽ được lưu, sau đó đề xuất <span class="mono">${esc(proposalId)}</span> cho <strong>${esc(fmt.ch(channel))}</strong> sẽ được ghi xuống bàn trộn.<br><br>
          Người duyệt: <strong>${esc(getOperator())}</strong>. Mixer phải ở chế độ <strong>ASSIST</strong> trở lên.
          Lệnh đi qua Safety Gate: kiểm tra, ghi chậm, đọc lại và tự hoàn tác nếu sai.
          ${v.rec === 'REJECT_OR_REFINE' ? `<br><br><strong class="bad-text">Lưu ý: điểm tạm tính đang ở mức “Chưa đạt”.</strong>` : ''}`,
        confirmText: 'Lưu & áp dụng',
        danger: v.rec === 'REJECT_OR_REFINE',
      });
      if (!ok) return;
      const data = await withLoading(btn, () => api.post('/api/v1/listening-test/evaluate', payload()), { errorPrefix: 'Không lưu được đánh giá: ' });
      if (!data || !alive) return;
      loadHistory();
      let applyHtml;
      try {
        btn.classList.add('loading'); btn.disabled = true;
        await api.post('/api/v1/proposals/apply', { proposal_id: proposalId, operator_id: getOperator() });
        applyHtml = callout('ok', 'Đã áp dụng đề xuất và xác minh trên mixer.');
        toast('Đã áp dụng đề xuất lên mixer.', 'ok');
      } catch (e) {
        applyHtml = callout('bad', `<strong>Đánh giá đã lưu nhưng chưa áp dụng được đề xuất.</strong><div class="small">${esc(e.message)}</div>`);
      } finally {
        btn.classList.remove('loading'); btn.disabled = false;
      }
      if (alive) showResult(data, applyHtml);
    }

    // ---------- History ----------
    async function loadHistory() {
      histEl.innerHTML = loadingRows(3);
      try {
        const data = await api.get('/api/v1/listening-test/history?limit=10');
        if (!alive) return;
        const rows = data?.evaluations || [];
        if (!rows.length) { histEl.innerHTML = emptyState('Chưa có lần đánh giá nào.'); return; }
        histEl.innerHTML = `
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Thời gian</th><th>Kênh</th><th>Người chấm</th><th class="right">MOS</th><th>Kết luận</th><th>Nghe mù</th></tr></thead>
            <tbody>${rows.map(r => `
              <tr>
                <td class="small nowrap">${esc(r.iso_time || fmt.time(r.timestamp))}</td>
                <td>${esc(fmt.ch(r.target_channel))} <span class="small muted">${esc(r.channel_name || '')}</span></td>
                <td>${esc(r.operator || '—')}</td>
                <td class="right mono">${fmt.num(r.overall_mos, 2)}</td>
                <td>${recBadge(r.recommendation)}</td>
                <td>${r.is_blind_test ? 'Có' : 'Không'}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>`;
      } catch (e) {
        if (alive) histEl.innerHTML = errorBox(e);
      }
    }

    // ---------- Wiring ----------
    chSel.addEventListener('change', () => {
      channel = Number(chSel.value) || 1;
      startSession();
    });
    root.addEventListener('click', (e) => {
      const opt = e.target.closest('[data-opt]');
      if (opt) { current = opt.dataset.opt; renderAB(); return; }
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.dataset.act;
      if (act === 'new-session') startSession();
      else if (act === 'reveal') reveal(b);
      else if (act === 'save') save(b);
      else if (act === 'save-apply') saveAndApply(b);
      else if (act === 'history') loadHistory();
    });

    renderChannelSelect();
    renderAB();
    loadChannels().then(() => { if (alive) startSession(); });
    loadCriteria();
    loadHistory();

    return () => { alive = false; };
  },
};
