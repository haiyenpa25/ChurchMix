// "Quy trình SOP (W1–W7)" — the seven guided standard operating procedures.
// Analysis endpoints are read-only; anything that would change the mixer is
// turned into a proposal and shown with renderProposal (confirm + Safety Gate).
//
// Ported from legacy.html: switchWizardTab, loadInventoryReport/downloadInventoryReport (W1),
// fetchLineCheckData (W2 → #/prep), runVocalCalibrationUI + applyW3TuningToSafetyGate (W3),
// runAcousticMeasurementUI + hall summary/checkActiveHallBaselineUI (W4),
// runFeedbackRingoutUI + applyW5NotchToSafetyGate (W5), loadLiveAssistantUI (W6),
// loadEndOfServiceReport/downloadEndOfServiceReport (W7).

import { api } from '../api.js';
import {
  $, $$, esc, icon, badge, card, callout, pageHead, emptyState, loadingRows, errorBox,
  withLoading, downloadText, renderMarkdown, renderProposal, drawCurve, fmt,
} from '../ui.js';

const TABS = [
  { w: '1', label: 'W1 · Kiểm kê', icon: 'clipboard', title: 'Kiểm kê cấu hình & Talkback',
    when: 'Đầu buổi chuẩn bị, hoặc khi nghi ngờ ai đó đã đổi cấu hình mixer: xem nhanh 32 kênh và xác minh Talkback DL16 #11 được cách ly.' },
  { w: '2', label: 'W2 · Line check', icon: 'listCheck', title: 'Line check sáng Chúa Nhật',
    when: 'Khoảng 30–60 phút trước giờ lễ: đối chiếu từng kênh và đi kiểm tra pin, dây, tai nghe tại chỗ.' },
  { w: '3', label: 'W3 · Cân chỉnh giọng', icon: 'mic', title: 'Cân chỉnh giọng nói & giọng hát',
    when: 'Trong buổi tập, khi người nói/ca sĩ đã đứng đúng vị trí: phân tích giọng và đề xuất lọc trầm, EQ, compressor giữ giọng tự nhiên.' },
  { w: '4', label: 'W4 · Cân chỉnh loa', icon: 'volume', title: 'Cân chỉnh hệ thống loa (PA)',
    when: 'Khi hội trường còn trống và yên tĩnh: đo đáp tuyến loa tại vị trí nghe, so với mốc chuẩn (baseline) của phòng.' },
  { w: '5', label: 'W5 · Dò hú', icon: 'zap', title: 'Dò hú an toàn khi tập (Ring-out)',
    when: 'Chỉ trong buổi tập, không có hội chúng: tìm tần số dễ hú ở kênh micro và đề xuất bộ lọc notch thật hẹp để có thêm độ lớn an toàn.' },
  { w: '6', label: 'W6 · Trong lễ', icon: 'live', title: 'Trợ lý trực tiếp trong buổi lễ',
    when: 'Trong suốt buổi lễ: một màn hình gọn để theo dõi rủi ro hú, fader tổng và lời khuyên xử lý ngay.' },
  { w: '7', label: 'W7 · Báo cáo', icon: 'file', title: 'Báo cáo sau buổi lễ',
    when: 'Sau khi tan lễ: tổng kết các thay đổi EQ/HPF, số lần chặn hú, can thiệp của bộ cân bằng giọng để rút kinh nghiệm.' },
];

const W3_CHANNELS = [
  ['1', 'Kênh 1 · Micro Mục sư'], ['2', 'Kênh 2 · Phụ lễ'], ['3', 'Kênh 3 · Đơn ca chính'],
  ['4', 'Kênh 4 · Bè 1'], ['5', 'Kênh 5 · Micro treo ca đoàn'],
];
const W3_ROLES = [
  ['PASTOR_SPEECH', 'Giọng nói Mục sư (bài giảng)'],
  ['LEAD_VOCAL_FEMALE', 'Ca sĩ nữ đơn ca'],
  ['LEAD_VOCAL_MALE', 'Ca sĩ nam đơn ca'],
  ['CHOIR_OVERHEAD', 'Ca đoàn (micro treo)'],
];
const W4_POSITIONS = [
  ['Center Hall', 'Chính giữa hội trường (vị trí FOH)'],
  ['Front Row Center', 'Hàng ghế đầu, chính giữa'],
  ['Under Balcony', 'Dưới ban công'],
  ['Rear Hall Left', 'Góc cuối hội trường'],
];
const W5_CHANNELS = [
  ['3', 'Kênh 3 · Đơn ca chính (đứng gần loa)'], ['1', 'Kênh 1 · Micro bục giảng'], ['4', 'Kênh 4 · Ca sĩ bè'],
];
const W5_GAINS = [
  ['3.0', '+3 dB (khuyên dùng)'], ['4.0', '+4 dB'], ['5.0', '+5 dB (tối đa)'],
];
const BAND_PURPOSE = { 1: 'Giảm đục do đứng sát micro', 2: 'Tăng độ rõ phụ âm, dễ nghe lời', 3: 'Giảm chói, xì ở âm "s"' };

const options = (list, sel) => list.map(([v, l]) => `<option value="${esc(v)}" ${v === sel ? 'selected' : ''}>${esc(l)}</option>`).join('');
const signed = (v, unit = ' dB') => (v === null || v === undefined || Number.isNaN(+v)) ? '—' : `${+v > 0 ? '+' : ''}${+v}${unit}`;
const today = () => new Date().toISOString().slice(0, 10);
const legend = (items) => `<div class="row small muted">${items.map(([c, l]) =>
  `<span class="row" style="gap:6px"><span style="display:inline-block;width:14px;height:3px;border-radius:2px;background:${c}"></span>${esc(l)}</span>`).join('')}</div>`;

export default {
  mount(root, ctx) {
    let alive = true;
    let liveTimer = null;
    const loaded = new Set();
    const reports = { w1: '', w7: '' };

    const initial = TABS.some(t => t.w === ctx.params.get('w')) ? ctx.params.get('w') : '1';

    root.innerHTML = `
      ${pageHead('Quy trình SOP (W1–W7)',
        'Bảy quy trình chuẩn cho một buổi lễ, theo thứ tự thời gian. Các bước phân tích chỉ đọc mixer; mọi thay đổi đều thành đề xuất để bạn xem và duyệt.')}
      <div class="tabs" role="tablist">
        ${TABS.map(t => `<button role="tab" data-tab="${t.w}">${icon(t.icon, 'icon-sm')} ${esc(t.label)}</button>`).join('')}
      </div>
      ${TABS.map(t => `
        <div class="stack" data-panel="${t.w}" role="tabpanel" hidden>
          ${callout('info', `<strong>${esc(t.title)}.</strong> <span class="text-2">Khi nào dùng: ${esc(t.when)}</span>`, 'clock')}
          <div data-body></div>
        </div>`).join('')}`;

    const panel = (w) => $(`[data-panel="${w}"] [data-body]`, root);

    // ======================= W1: inventory =======================
    function buildReportPanel(w, { title, sub, endpoint, filename, extra = '' }) {
      const el = panel(w);
      el.innerHTML = card({
        title: `${icon('file')} ${title}`,
        sub,
        actions: `<div class="row">
          <button class="btn btn-sm" data-reload>${icon('refresh', 'icon-sm')}Tạo lại</button>
          <button class="btn btn-sm btn-primary" data-dl disabled>${icon('download', 'icon-sm')}Tải về (.md)</button>
        </div>`,
        body: `${extra}<div data-md>${loadingRows(6)}</div>`,
      });
      const mdEl = $('[data-md]', el);
      const dlBtn = $('[data-dl]', el);
      async function load() {
        mdEl.innerHTML = loadingRows(6);
        dlBtn.disabled = true;
        try {
          const data = await api.get(endpoint);
          if (!alive) return;
          reports[`w${w}`] = data.report_markdown || '';
          mdEl.innerHTML = reports[`w${w}`] ? renderMarkdown(reports[`w${w}`]) : emptyState('Báo cáo trống.');
          dlBtn.disabled = !reports[`w${w}`];
        } catch (e) {
          if (alive) mdEl.innerHTML = errorBox(e);
        }
      }
      $('[data-reload]', el).addEventListener('click', (e) => withLoading(e.currentTarget, load));
      dlBtn.addEventListener('click', () => {
        if (reports[`w${w}`]) downloadText(filename(), reports[`w${w}`], 'text/markdown;charset=utf-8');
      });
      return load;
    }

    const loadW1 = buildReportPanel('1', {
      title: 'Báo cáo kiểm kê mixer X32',
      sub: 'Danh sách 32 kênh, định tuyến và kiểm tra cách ly Talkback DL16 #11',
      endpoint: '/api/v1/wizards/inventory-report',
      filename: () => `X32_Inventory_Audit_${today()}.md`,
    });

    // ======================= W2: link to prep =======================
    panel('2').innerHTML = card({
      title: `${icon('listCheck')} Line check nằm ở trang “Kiểm tra trước lễ”`,
      body: `<div class="stack-sm">
        <p class="text-2">Trang đó gộp cả tự chẩn đoán 10 điểm, bảng trạng thái từng kênh và danh sách kiểm tra tại chỗ (pin micro, dây cáp, tai nghe P16…) kèm kết luận “sẵn sàng hay chưa”.</p>
        <div><button class="btn btn-primary" data-goto-prep>${icon('arrowRight')}Mở trang Kiểm tra trước lễ</button></div>
      </div>`,
    });
    $('[data-goto-prep]', panel('2')).addEventListener('click', () => ctx.navigate('prep'));

    // ======================= W3: vocal calibration =======================
    {
      const el = panel('3');
      el.innerHTML = `
        ${card({
          title: `${icon('mic')} Chọn kênh và loại giọng`,
          body: `<div class="form-grid">
              <div class="field"><label for="w3ch">Kênh cần cân chỉnh</label><select id="w3ch" class="select">${options(W3_CHANNELS, '1')}</select></div>
              <div class="field"><label for="w3role">Loại giọng</label><select id="w3role" class="select">${options(W3_ROLES, 'PASTOR_SPEECH')}</select></div>
            </div>
            <p class="hint mt-8">Nhờ người dùng micro nói hoặc hát tự nhiên 20–40 giây ở đúng vị trí trước khi bấm phân tích.</p>`,
          foot: `<button class="btn btn-primary" data-run>${icon('wand')}Phân tích giọng & đề xuất</button>`,
        })}
        <div data-result></div>`;
      const resEl = $('[data-result]', el);

      $('[data-run]', el).addEventListener('click', (e) => withLoading(e.currentTarget, async () => {
        const channel = parseInt($('#w3ch', el).value, 10);
        const role = $('#w3role', el).value;
        const data = await api.post('/api/v1/wizards/vocal-calibration', { channel_id: channel, vocal_role: role });
        if (!alive) return;
        const dyn = data.dynamics || {};
        const bands = data.bands || [];
        resEl.innerHTML = card({
          title: `${icon('checkCircle')} Kết quả phân tích · ${esc(fmt.ch(data.channel_id ?? channel))}`,
          sub: data.confidence !== undefined ? `Độ tin cậy ${fmt.pct(data.confidence)}` : '',
          body: `<div class="stack">
            ${data.mic_placement_guide ? callout('info', `<strong>Đặt micro trước, chỉnh EQ sau.</strong><div class="text-2">${esc(data.mic_placement_guide)}</div>`, 'mic') : ''}
            <div class="grid-2">
              <div class="stat"><div class="stat-label">Lọc trầm (HPF)</div>
                <div class="stat-value">${data.hpf_on === false ? 'Tắt' : esc(fmt.hz(data.hpf_freq_hz))}</div>
                <div class="stat-sub">Độ dốc 12 dB/quãng tám — bỏ tiếng ù, tiếng chạm chân micro</div></div>
              <div class="stat"><div class="stat-label">Compressor khuyên dùng</div>
                <dl class="kv mt-8">
                  <dt>Ngưỡng</dt><dd>${esc(dyn.threshold_db ?? '—')} dBFS</dd>
                  <dt>Tỷ lệ nén</dt><dd>${esc(dyn.ratio ?? '—')}</dd>
                  <dt>Attack / Release</dt><dd>${esc(dyn.attack_ms ?? '—')} ms / ${esc(dyn.release_ms ?? '—')} ms</dd>
                  <dt>Knee</dt><dd>${esc(dyn.knee ?? '—')} <span class="muted small">(mềm, giữ giọng tự nhiên)</span></dd>
                </dl></div>
            </div>
            ${bands.length ? `<div class="table-wrap"><table class="table">
              <thead><tr><th>Dải</th><th class="right">Tần số</th><th class="right">Tăng/giảm</th><th class="right">Độ rộng Q</th><th>Mục đích</th></tr></thead>
              <tbody>${bands.map(b => `<tr>
                <td>Dải ${esc(b.band)}</td>
                <td class="right mono">${esc(fmt.hz(b.freq_hz))}</td>
                <td class="right mono ${+b.gain_db < 0 ? 'bad-text' : 'ok-text'}">${esc(signed(b.gain_db))}</td>
                <td class="right mono">${esc(b.q)}</td>
                <td class="text-2">${esc(BAND_PURPOSE[b.band] || '')}</td></tr>`).join('')}</tbody>
            </table></div>` : ''}
            ${(data.simulated_curve || []).length ? `<div class="stack-sm">
              <div class="rta-wrap" style="height:180px"><canvas data-curve></canvas></div>
              ${legend([['#4f8cff', 'Đáp tuyến EQ dự kiến (mô phỏng)']])}
            </div>` : ''}
            <div data-proposal></div>
          </div>`,
          foot: `<span class="small muted grow">Kết quả trên chỉ là phân tích. Muốn áp dụng, hãy tạo đề xuất rồi duyệt.</span>
            <button class="btn btn-primary" data-propose>${icon('shieldCheck')}Tạo đề xuất để duyệt</button>`,
        });
        const canvas = $('[data-curve]', resEl);
        if (canvas) drawCurve(canvas, [{ points: data.simulated_curve.map(p => ({ freq: p.freq, db: p.response_db ?? p.db ?? 0 })), color: '#4f8cff' }], { minDb: -18, maxDb: 12 });
        const propEl = $('[data-proposal]', resEl);
        $('[data-propose]', resEl).addEventListener('click', (ev) => withLoading(ev.currentTarget, async () => {
          const proposal = await api.post('/api/v1/proposals/generate-role', { channel_id: channel, role });
          if (alive) renderProposal(propEl, proposal, { title: 'Đề xuất EQ cho giọng', note: 'Nghe thử trước khi duyệt. Có thể bỏ qua nếu giọng đã ổn.' });
        }, { errorPrefix: 'Không tạo được đề xuất: ' }));
        resEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, { errorPrefix: 'Lỗi phân tích giọng: ' }));
    }

    // ======================= W4: room & PA =======================
    let loadW4Hall;
    {
      const el = panel('4');
      el.innerHTML = `
        <div class="grid-2">
          <div data-hall></div>
          ${card({
            title: `${icon('ruler')} Đo đáp tuyến loa`,
            sub: 'Phát nhiễu hồng (pink noise −18 dBFS) và đo bằng micro đo',
            body: `<div class="stack-sm">
                <div class="field"><label for="w4pos">Vị trí đặt micro đo</label><select id="w4pos" class="select">${options(W4_POSITIONS, 'Center Hall')}</select></div>
                <p class="hint">Hệ thống luôn bật quy tắc “không tăng bù vào chỗ trũng do triệt pha” để bảo vệ loa.</p>
              </div>`,
            foot: `<button class="btn btn-primary" data-measure>${icon('play')}Bắt đầu đo</button>`,
          })}
        </div>
        <div data-measure-result></div>`;
      const hallEl = $('[data-hall]', el);
      const resEl = $('[data-measure-result]', el);
      let compare = null;
      let compareErr = null;
      let hall = null;
      let hallErr = null;

      const renderHall = () => {
        let body;
        if (hallErr) body = errorBox(hallErr);
        else if (!hall) body = loadingRows(4);
        else {
          const cmpKind = !compare || compare.status === 'INSUFFICIENT_DATA' ? 'info' : (compare.status === 'HEALTHY' ? 'ok' : 'warn');
          const cmpLabel = !compare ? 'Chưa so sánh'
            : compare.status === 'HEALTHY' ? 'Khớp baseline'
            : compare.status === 'INSUFFICIENT_DATA' ? 'Chưa đủ dữ liệu' : 'Lệch baseline';
          body = `<div class="stack-sm">
            <div class="strong">${esc(hall.name)}</div>
            <div class="grid-2">
              <div class="stat"><div class="stat-label">Mục tiêu RT60</div><div class="stat-value">${esc(fmt.num(hall.target_rt60_seconds, 2))} s</div></div>
              <div class="stat"><div class="stat-label">Độ trễ chuẩn FOH</div><div class="stat-value">${esc(fmt.num(hall.nominal_delay_ms, 1))} ms</div></div>
              <div class="stat"><div class="stat-label">Độ dốc mục tiêu</div><div class="stat-value">${esc(hall.target_curve_slope_db_per_oct ?? '—')}</div><div class="stat-sub">dB / quãng tám</div></div>
              <div class="stat"><div class="stat-label">So với baseline</div><div class="mt-8">${badge(cmpLabel, cmpKind)}</div></div>
            </div>
            ${compareErr ? errorBox(compareErr) : ''}
            ${compare ? `<dl class="kv">
                <dt>Độ lệch trung bình</dt><dd>${esc(fmt.num(compare.rms_deviation_db, 2))} dB</dd>
                <dt>Trôi độ trễ</dt><dd>${esc(signed(fmt.num(compare.delay_drift_ms, 2), ' ms'))}</dd>
              </dl>
              ${(compare.recommendations_vi || []).length ? `<ul class="small text-2" style="margin:0;padding-left:18px">${compare.recommendations_vi.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}` : ''}
          </div>`;
        }
        hallEl.innerHTML = card({
          title: `${icon('church')} Hồ sơ phòng đang dùng`,
          body,
          foot: `<button class="btn btn-ghost btn-sm" data-goto-acoustics>${icon('settings', 'icon-sm')}Quản lý hồ sơ phòng</button>
                 <button class="btn btn-sm" data-compare>${icon('compare', 'icon-sm')}So sánh baseline</button>`,
        });
        $('[data-goto-acoustics]', hallEl).addEventListener('click', () => ctx.navigate('acoustics'));
        $('[data-compare]', hallEl).addEventListener('click', (e) => withLoading(e.currentTarget, runCompare));
      };

      async function runCompare() {
        compareErr = null;
        try { compare = await api.get('/api/v1/halls/active/compare'); }
        catch (e) { compareErr = e; }
        if (alive) renderHall();
      }

      loadW4Hall = async () => {
        hall = null; hallErr = null; renderHall();
        try {
          const data = await api.get('/api/v1/halls');
          hall = (data.halls || []).find(h => h.id === data.active_hall_id) || (data.halls || [])[0] || null;
          if (!hall) hallErr = new Error('Chưa có hồ sơ phòng nào.');
        } catch (e) { hallErr = e; }
        if (alive) renderHall();
      };

      $('[data-measure]', el).addEventListener('click', (e) => withLoading(e.currentTarget, async () => {
        const pos = $('#w4pos', el).value;
        const data = await api.post(`/api/v1/acoustics/measure?position=${encodeURIComponent(pos)}`);
        if (!alive) return;
        const curve = data.curve || [];
        const step = Math.max(1, Math.floor(curve.length / 8));
        const sample = curve.filter((_, i) => i % step === 0).slice(0, 8);
        const coh = +data.coherence_avg;
        resEl.innerHTML = card({
          title: `${icon('spectrum')} Kết quả đo · ${esc((W4_POSITIONS.find(p => p[0] === pos) || [pos, pos])[1])}`,
          body: `<div class="stack">
            <div class="grid-3">
              <div class="stat"><div class="stat-label">Độ trễ hệ thống</div><div class="stat-value">${esc(fmt.num(data.delay_ms, 2))} ms</div></div>
              <div class="stat"><div class="stat-label">Độ tin cậy phép đo (coherence)</div>
                <div class="stat-value ${coh >= 0.8 ? 'ok-text' : coh >= 0.5 ? 'warn-text' : 'bad-text'}">${esc(fmt.num(coh, 2))}</div>
                <div class="stat-sub">${coh >= 0.8 ? 'Tốt, tin được' : coh >= 0.5 ? 'Tạm được — kiểm tra tiếng ồn phòng' : 'Thấp — đo lại khi phòng yên tĩnh'}</div></div>
              <div class="stat"><div class="stat-label">Bảo vệ loa</div><div class="stat-value" style="font-size:16px">${data.rule_enforced ? 'Đang bật' : 'Chuẩn'}</div>
                <div class="stat-sub">Không tăng bù vào chỗ trũng do triệt pha</div></div>
            </div>
            ${curve.length ? `<div class="stack-sm">
              <div class="rta-wrap" style="height:200px"><canvas data-curve></canvas></div>
              ${legend([['#94a3b8', 'Đáp tuyến đo được'], ['#2fbf71', 'EQ mục tiêu an toàn']])}
            </div>
            <div class="table-wrap"><table class="table">
              <thead><tr><th class="right">Tần số</th><th class="right">Đo được</th><th class="right">Coherence</th><th class="right">EQ mục tiêu</th><th>Ghi chú</th></tr></thead>
              <tbody>${sample.map(pt => {
                const isNull = pt.magnitude_db < -6 && pt.coherence < 0.6;
                const note = isNull ? '<span class="warn-text strong">Trũng do triệt pha — khóa tăng bù</span>'
                  : pt.safe_eq_target_db < 0 ? 'Cắt bớt cộng hưởng' : pt.safe_eq_target_db > 0 ? 'Bù nhẹ dải tần' : 'Phẳng';
                return `<tr>
                  <td class="right mono">${esc(fmt.hz(pt.freq))}</td>
                  <td class="right mono">${esc(signed(pt.magnitude_db))}</td>
                  <td class="right mono ${pt.coherence >= 0.8 ? 'ok-text' : pt.coherence < 0.5 ? 'bad-text' : 'warn-text'}">${esc(pt.coherence)}</td>
                  <td class="right mono">${esc(signed(pt.safe_eq_target_db))}</td>
                  <td class="small">${note}</td></tr>`;
              }).join('')}</tbody>
            </table></div>
            <p class="small muted">Bảng hiển thị 8 điểm tiêu biểu. Nên ưu tiên chỉnh vị trí/góc loa trước khi dùng EQ.</p>` : emptyState('Không có dữ liệu đáp tuyến.')}
          </div>`,
        });
        const canvas = $('[data-curve]', resEl);
        if (canvas) drawCurve(canvas, [
          { points: curve.map(p => ({ freq: p.freq, db: p.magnitude_db })), color: '#94a3b8', width: 1.5 },
          { points: curve.map(p => ({ freq: p.freq, db: p.safe_eq_target_db })), color: '#2fbf71' },
        ], { minDb: -24, maxDb: 12 });
        runCompare(); // baseline comparison uses the latest measurement
        resEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, { errorPrefix: 'Lỗi đo âm học: ' }));
    }

    // ======================= W5: feedback ring-out =======================
    {
      const el = panel('5');
      el.innerHTML = `
        ${callout('warn', '<strong>Chỉ làm trong buổi tập.</strong> Hạ fader tổng về mức an toàn trước khi bắt đầu; dò hú có thể phát ra tiếng rít lớn. Không bao giờ có “không rủi ro hú” — ưu tiên đặt micro đúng hướng và cấu trúc gain hợp lý.')}
        ${card({
          title: `${icon('zap')} Thiết lập dò hú`,
          body: `<div class="form-grid">
            <div class="field"><label for="w5ch">Kênh cần dò hú</label><select id="w5ch" class="select">${options(W5_CHANNELS, '3')}</select></div>
            <div class="field"><label for="w5gain">Muốn có thêm độ lớn an toàn</label><select id="w5gain" class="select">${options(W5_GAINS, '3.0')}</select></div>
          </div>`,
          foot: `<button class="btn btn-primary" data-run>${icon('play')}Lập kế hoạch dò hú</button>`,
        })}
        <div data-result></div>`;
      const resEl = $('[data-result]', el);

      $('[data-run]', el).addEventListener('click', (e) => withLoading(e.currentTarget, async () => {
        const channel = parseInt($('#w5ch', el).value, 10);
        const margin = parseFloat($('#w5gain', el).value);
        const data = await api.post('/api/v1/wizards/feedback-ringout', { channel_id: channel, target_gain_increase_db: margin });
        if (!alive) return;
        const steps = data.step_by_step_sop || [];
        resEl.innerHTML = card({
          title: `${icon('listCheck')} Kế hoạch dò hú · ${esc(fmt.ch(data.channel_id ?? channel))}`,
          actions: data.safety_lock_engaged ? badge('Khóa an toàn đang bật', 'ok') : '',
          body: `<div class="stack">
            <div class="grid-3">
              <div class="stat"><div class="stat-label">Tần số dễ hú</div><div class="stat-value">${esc(fmt.hz(data.candidate_freq_hz))}</div></div>
              <div class="stat"><div class="stat-label">Bộ lọc notch đề xuất</div><div class="stat-value">${esc(signed(data.notch_gain_db))}</div><div class="stat-sub">Độ hẹp Q = ${esc(data.notch_q)}</div></div>
              <div class="stat"><div class="stat-label">Độ lớn an toàn có thêm</div><div class="stat-value ok-text">${esc(signed(data.gain_margin_improvement_db))}</div></div>
            </div>
            ${steps.length ? `<div><div class="label">Các bước thực hiện</div>
              <div class="checklist">${steps.map((s, i) => `
                <div class="check-item"><span class="badge">${i + 1}</span><div class="grow text-2">${esc(s)}</div></div>`).join('')}</div></div>` : ''}
            <div data-proposal></div>
          </div>`,
          foot: `<span class="small muted grow">Notch chỉ được ghi xuống mixer sau khi bạn duyệt đề xuất.</span>
            <button class="btn btn-primary" data-propose>${icon('shieldCheck')}Tạo đề xuất notch để duyệt</button>`,
        });
        const propEl = $('[data-proposal]', resEl);
        $('[data-propose]', resEl).addEventListener('click', (ev) => withLoading(ev.currentTarget, async () => {
          const proposal = await api.post('/api/v1/proposals/generate-notch', {
            channel_id: channel, freq_hz: +data.candidate_freq_hz || 2850.0, confidence: 0.90,
          });
          if (alive) renderProposal(propEl, proposal, { title: 'Đề xuất notch chống hú', note: 'Notch hẹp chỉ cắt đúng tần số hú, không làm mỏng giọng.' });
        }, { errorPrefix: 'Không tạo được đề xuất notch: ' }));
        resEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, { errorPrefix: 'Lỗi lập kế hoạch dò hú: ' }));
    }

    // ======================= W6: live assistant =======================
    let liveEl, autoEl;
    let current = null;
    {
      const el = panel('6');
      el.innerHTML = `
        <div class="row-between">
          <label class="check small text-2"><input type="checkbox" data-auto checked>Tự làm mới mỗi 5 giây</label>
          <button class="btn btn-sm" data-refresh>${icon('refresh', 'icon-sm')}Làm mới</button>
        </div>
        <div data-live class="stack mt-16">${loadingRows(4)}</div>`;
      liveEl = $('[data-live]', el);
      autoEl = $('[data-auto]', el);
      $('[data-refresh]', el).addEventListener('click', (e) => withLoading(e.currentTarget, loadW6));
      autoEl.addEventListener('change', () => syncLiveTimer());
    }

    async function loadW6() {
      let data;
      try { data = await api.get('/api/v1/wizards/live-assistant'); }
      catch (e) { if (alive) liveEl.innerHTML = errorBox(e); return; }
      if (!alive) return;
      const healthy = data.overall_health === 'EXCELLENT';
      const chans = data.channel_highlights || [];
      const alerts = data.active_alerts || [];
      liveEl.innerHTML = `
        <div class="grid-4">
          <div class="stat"><div class="stat-label">Tình trạng</div>
            <div class="stat-value ${healthy ? 'ok-text' : 'warn-text'}" style="font-size:18px">${healthy ? 'Ổn định' : 'Cần chú ý'}</div>
            <div class="stat-sub">${healthy ? 'Không có cảnh báo' : `${alerts.length || 'Có'} cảnh báo`}</div></div>
          <div class="stat"><div class="stat-label">Fader tổng (Main)</div>
            <div class="stat-value">${esc(data.master_fader_pct ?? '—')}%</div>
            <div class="stat-sub">${+data.master_fader_pct >= 75 ? 'Khoảng 0 dB (unity)' : 'Dưới 0 dB'}</div></div>
          <div class="stat"><div class="stat-label">Quyền ghi mixer</div>
            <div class="stat-value" style="font-size:18px">${data.read_only_mode ? 'Chỉ đọc' : 'Cho phép ghi'}</div>
            <div class="stat-sub">${data.stop_auto_engaged ? '<span class="bad-text strong">Đã bấm STOP tự động</span>' : 'Tự động đang hoạt động bình thường'}</div></div>
          <div class="stat"><div class="stat-label">Mixer</div>
            <div class="stat-value" style="font-size:18px">${data.mixer_online === false ? '<span class="bad-text">Mất kết nối</span>' : '<span class="ok-text">Trực tuyến</span>'}</div>
            <div class="stat-sub">${esc(fmt.time(data.timestamp))}</div></div>
        </div>
        ${data.tactical_guidance_vi ? callout(healthy ? 'ok' : 'warn', `<strong>Việc nên làm lúc này:</strong> ${esc(data.tactical_guidance_vi)}`, 'info') : ''}
        ${alerts.length ? callout('warn', `<ul style="margin:0;padding-left:18px">${alerts.map(a => `<li>${esc(typeof a === 'string' ? a : (a.message || a.recommended_action || JSON.stringify(a)))}</li>`).join('')}</ul>`) : ''}
        ${card({
          title: `${icon('sliders')} Các kênh quan trọng`,
          body: chans.length ? `<div class="table-wrap"><table class="table">
            <thead><tr><th>Kênh</th><th>Vai trò</th><th class="right">Fader</th><th>Rủi ro hú</th><th>Khuyến nghị</th></tr></thead>
            <tbody>${chans.map(c => {
              const safe = c.feedback_risk === 'SAFE';
              return `<tr>
                <td class="nowrap"><span class="mono">${esc(fmt.ch(c.channel_id))}</span> · <strong>${esc(c.name)}</strong></td>
                <td class="text-2">${esc(c.role)}</td>
                <td class="right mono">${esc(c.fader_pct)}%</td>
                <td>${badge(safe ? 'An toàn' : 'Nghi có hú', safe ? 'ok' : 'warn')}</td>
                <td class="text-2">${esc(c.recommendation_vi || '')}</td></tr>`;
            }).join('')}</tbody></table></div>` : emptyState('Không có kênh nào để theo dõi.'),
        })}`;
    }

    function syncLiveTimer() {
      clearInterval(liveTimer);
      liveTimer = null;
      if (current === '6' && autoEl.checked) {
        liveTimer = setInterval(() => { if (!document.hidden) loadW6(); }, 5000);
      }
    }

    // ======================= W7: end-of-service =======================
    const loadW7 = buildReportPanel('7', {
      title: 'Báo cáo tổng kết buổi lễ',
      sub: 'Lịch sử thay đổi EQ/HPF, can thiệp cân bằng giọng, số lần chặn hú',
      endpoint: '/api/v1/wizards/end-of-service-report',
      filename: () => `X32_Service_Report_${today()}.md`,
      extra: `<div class="row-between" style="margin-bottom:12px">
        <span class="small muted">Cần bản in đẹp để gửi ban điều hành?</span>
        <a class="btn btn-sm" href="/api/v1/reports/sunday-service" target="_blank" rel="noopener">${icon('file', 'icon-sm')}In báo cáo buổi lễ</a>
      </div>`,
    });

    // ======================= Tab switching =======================
    const loaders = { '1': loadW1, '4': loadW4Hall, '6': loadW6, '7': loadW7 };

    function switchTab(w) {
      current = w;
      $$('[data-tab]', root).forEach(b => {
        const on = b.dataset.tab === w;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      $$('[data-panel]', root).forEach(p => { p.hidden = p.dataset.panel !== w; });
      if (loaders[w] && !loaded.has(w)) { loaded.add(w); loaders[w](); }
      else if (w === '6') loadW6();
      syncLiveTimer();
      try { history.replaceState(null, '', `#/wizards?w=${w}`); } catch { /* ignore */ }
    }

    $$('[data-tab]', root).forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    switchTab(initial);

    return () => {
      alive = false;
      clearInterval(liveTimer);
      liveTimer = null;
    };
  },
};
