// Âm học hội trường: hồ sơ âm học từng không gian (hội trường lớn, phòng nhóm...),
// so sánh đáp tuyến hiện tại với chuẩn của phòng, đo hàm truyền H1 và nhập CSV
// từ Open Sound Meter / REW. Trang này KHÔNG ghi gì xuống mixer.

import { api } from '../api.js';
import {
  $, esc, icon, badge, pageHead, card, callout, errorBox, loadingRows, emptyState,
  fmt, withLoading, toast, openDialog, confirmDialog, drawCurve,
} from '../ui.js';

const COLORS = { measured: '#4f8cff', baseline: '#f5a524', safe: '#2fbf71' };

const signed = (v, digits = 1, unit = '') =>
  (v === null || v === undefined || Number.isNaN(+v)) ? '—' : `${+v > 0 ? '+' : ''}${(+v).toFixed(digits)}${unit}`;

function curveRange(series) {
  let lo = Infinity, hi = -Infinity;
  series.forEach(s => (s.points || []).forEach(p => { lo = Math.min(lo, p.db); hi = Math.max(hi, p.db); }));
  if (!Number.isFinite(lo)) return { minDb: -15, maxDb: 15 };
  return { minDb: Math.max(-48, Math.floor(Math.min(lo - 3, -6))), maxDb: Math.min(24, Math.ceil(Math.max(hi + 3, 6))) };
}

function legend(items) {
  return `<div class="row small text-2 mt-8">${items.map(([color, label, dashed]) =>
    `<span class="row" style="gap:6px"><span style="display:inline-block;width:18px;height:0;border-top:2px ${dashed ? 'dashed' : 'solid'} ${color}"></span>${esc(label)}</span>`).join('')}</div>`;
}

function chartBox(attr) {
  return `<div class="rta-wrap" style="height:200px"><canvas ${attr}></canvas></div>`;
}

export default {
  mount(root) {
    root.innerHTML = `
      ${pageHead('Âm học hội trường',
        'Chọn đúng không gian đang dùng, đo đáp tuyến loa và so với chuẩn âm học của phòng đó.',
        `<button class="btn" data-reload>${icon('refresh')}Tải lại</button>`)}
      <div class="stack">
        ${card({ title: 'Không gian đang dùng', sub: 'Mọi phép so sánh và gợi ý EQ dựa trên hồ sơ này', id: 'ac-active',
          actions: `<button class="btn btn-sm btn-primary" data-compare>${icon('compare', 'icon-sm')}So với chuẩn phòng</button>`,
          body: `<div data-active>${loadingRows(3)}</div>` })}
        ${card({ title: 'So sánh với chuẩn của phòng', sub: 'Đáp tuyến đo được lệch bao nhiêu so với đường cong mục tiêu (baseline)',
          body: `<div data-compare-box>${loadingRows(3)}</div>` })}
        <div class="grid-2">
          ${card({ title: 'Đo đáp tuyến loa FOH (H1)', sub: 'So tín hiệu gốc với micro đo để biết độ trễ và độ tin cậy',
            body: `
              <p class="text-2 small">Phép đo hàm truyền 2 kênh: tự tính độ trễ đường truyền và áp dụng quy tắc
                <strong>Không bù EQ vào hố triệt pha</strong> (No-Boost-in-Nulls) — chỗ hụt do dội sàn / triệt pha không được kích EQ lên.</p>
              <div class="grid-3 mt-16" data-measure-stats>
                <div class="stat"><div class="stat-label">Độ trễ loa</div><div class="stat-value">—</div><div class="stat-sub">Chưa đo</div></div>
                <div class="stat"><div class="stat-label">Độ tin cậy phép đo</div><div class="stat-value">—</div><div class="stat-sub">Coherence, gần 1 là tốt</div></div>
                <div class="stat"><div class="stat-label">Chống bù hố triệt pha</div><div class="stat-value ok-text" style="font-size:18px">Đang bật</div><div class="stat-sub">Không kích EQ vào chỗ hụt</div></div>
              </div>
              <div data-measure-result class="mt-16"></div>`,
            foot: `<button class="btn btn-primary" data-measure>${icon('play')}Chạy đo H1</button>` })}
          ${card({ title: 'Nhập file đo Open Sound Meter', sub: 'CSV xuất từ Open Sound Meter (OSM) hoặc REW',
            body: `
              <p class="text-2 small">Nếu đã đo bằng phần mềm ngoài, nhập file CSV để xem đường đáp tuyến tại đây.</p>
              <div data-osm-result class="mt-16">${emptyState('Chưa nhập file nào.')}</div>`,
            foot: `<button class="btn" data-osm>${icon('upload')}Nhập CSV…</button>` })}
        </div>
        ${card({ title: 'Các không gian đã lưu', sub: 'Chọn phòng trước buổi lễ — chỉ đổi chuẩn so sánh, không ghi xuống mixer',
          body: `<div data-halls>${loadingRows(3)}</div>` })}
      </div>`;

    let alive = true;
    const redraws = new Map(); // key -> () => void, re-run on resize
    const draw = (key, canvas, series) => {
      if (!canvas) { redraws.delete(key); return; }
      const fn = () => { if (canvas.isConnected) drawCurve(canvas, series, curveRange(series)); };
      redraws.set(key, fn);
      requestAnimationFrame(fn);
    };
    const onResize = () => redraws.forEach(fn => fn());
    window.addEventListener('resize', onResize);

    const activeBox = $('[data-active]', root);
    const hallsBox = $('[data-halls]', root);
    const compareBox = $('[data-compare-box]', root);
    let hallsData = null;

    // ---------- Hall profiles ----------
    async function loadHalls() {
      try {
        hallsData = await api.get('/api/v1/halls');
      } catch (e) {
        if (!alive) return;
        activeBox.innerHTML = errorBox(e);
        hallsBox.innerHTML = errorBox(e);
        return;
      }
      if (!alive) return;
      renderActive();
      renderHalls();
    }

    function activeHall() {
      const halls = hallsData?.halls || [];
      return halls.find(h => h.id === hallsData.active_hall_id) || halls[0] || null;
    }

    function renderActive() {
      const h = activeHall();
      if (!h) { activeBox.innerHTML = emptyState('Chưa có hồ sơ phòng nào.'); return; }
      activeBox.innerHTML = `
        <div class="row-between">
          <div class="row">${icon('church')}<h2>${esc(h.name)}</h2>${badge('Đang dùng', 'ok')}</div>
          <span class="small muted">Phiên bản ${esc(h.version ?? 1)} · cập nhật ${fmt.time(h.updated_at)}</span>
        </div>
        <div class="grid-4 mt-16">
          <div class="stat"><div class="stat-label">Độ vang mục tiêu (RT60)</div><div class="stat-value">${fmt.num(h.target_rt60_seconds, 2)} s</div>
            <div class="stat-sub">Thời gian tiếng vang tắt dần 60 dB</div></div>
          <div class="stat"><div class="stat-label">Độ trễ loa chuẩn</div><div class="stat-value">${fmt.num(h.nominal_delay_ms, 1)} ms</div>
            <div class="stat-sub">Từ loa FOH tới vị trí đo</div></div>
          <div class="stat"><div class="stat-label">Ồn nền phòng</div><div class="stat-value">${fmt.num(h.ambient_noise_dbfs, 1)} dBFS</div>
            <div class="stat-sub">Càng thấp càng yên tĩnh</div></div>
          <div class="stat"><div class="stat-label">Sức chứa</div><div class="stat-value">${esc(h.capacity_seats ?? '—')} chỗ</div>
            <div class="stat-sub">Phòng đầy người sẽ bớt vang</div></div>
        </div>
        <dl class="kv mt-16">
          <dt>Hệ thống loa</dt><dd>${esc(h.speaker_system || '—')}</dd>
          <dt>Độ dốc đường cong mục tiêu</dt><dd>${signed(h.target_curve_slope_db_per_oct, 1)} dB/quãng tám</dd>
          <dt>Giới hạn tăng EQ an toàn</dt><dd>${fmt.num(h.safe_gain_limit_db, 1)} dB</dd>
          <dt>Ghi chú âm học</dt><dd class="text-2">${esc(h.notes || 'Không có ghi chú.')}</dd>
        </dl>`;
    }

    function renderHalls() {
      const halls = hallsData?.halls || [];
      if (!halls.length) { hallsBox.innerHTML = emptyState('Chưa có hồ sơ phòng nào.'); return; }
      const activeId = hallsData.active_hall_id;
      hallsBox.innerHTML = `<div class="grid-3">${halls.map(h => {
        const isActive = h.id === activeId;
        return `
          <div class="stat" style="${isActive ? 'border-color:var(--accent);background:var(--accent-soft)' : ''}">
            <div class="row-between"><strong>${esc(h.name)}</strong>${isActive ? badge('Đang dùng', 'ok') : badge(`${h.capacity_seats ?? '—'} chỗ`)}</div>
            ${h.notes ? `<p class="small text-2 mt-8">${esc(h.notes)}</p>` : ''}
            <dl class="kv mt-8 small">
              <dt>RT60</dt><dd>${fmt.num(h.target_rt60_seconds, 2)} s</dd>
              <dt>Độ trễ</dt><dd>${fmt.num(h.nominal_delay_ms, 1)} ms</dd>
              <dt>Loa</dt><dd>${esc(h.speaker_system || '—')}</dd>
            </dl>
            <div class="mt-16">${isActive
              ? `<button class="btn btn-sm btn-block" disabled>${icon('check', 'icon-sm')}Đang hoạt động</button>`
              : `<button class="btn btn-sm btn-block" data-activate="${esc(h.id)}">Dùng phòng này</button>`}</div>
          </div>`;
      }).join('')}</div>`;
    }

    hallsBox.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-activate]');
      if (!btn) return;
      const hall = (hallsData?.halls || []).find(h => h.id === btn.dataset.activate);
      const ok = await confirmDialog({
        title: 'Đổi không gian đang dùng?',
        message: `Chuyển hồ sơ âm học sang <strong>${esc(hall?.name || btn.dataset.activate)}</strong>.<br>
          Thao tác này chỉ đổi chuẩn so sánh (RT60, độ trễ, đường cong mục tiêu) và được ghi vào nhật ký — <strong>không ghi gì xuống mixer</strong>.`,
        confirmText: 'Đổi phòng',
      });
      if (!ok) return;
      const res = await withLoading(btn, () => api.post(`/api/v1/halls/${encodeURIComponent(btn.dataset.activate)}/activate`),
        { errorPrefix: 'Không đổi được phòng: ' });
      if (!res || !alive) return;
      const a = res.active_hall || {};
      toast(`Đã chuyển sang ${a.name}. RT60 mục tiêu ${fmt.num(a.target_rt60_seconds, 2)} s, độ trễ ${fmt.num(a.nominal_delay_ms, 1)} ms.`, 'ok');
      await loadHalls();
      loadCompare();
    });

    // ---------- Baseline comparison ----------
    async function loadCompare(btn) {
      if (!btn) compareBox.innerHTML = loadingRows(3);
      let diff;
      try {
        diff = btn ? await withLoading(btn, () => api.get('/api/v1/halls/active/compare')) : await api.get('/api/v1/halls/active/compare');
      } catch (e) {
        if (alive) compareBox.innerHTML = errorBox(e);
        return;
      }
      if (!alive || !diff) return;
      renderCompare(diff);
    }

    function renderCompare(d) {
      const recs = d.recommendations_vi || [];
      if (d.status === 'INSUFFICIENT_DATA') {
        compareBox.innerHTML = `${callout('info', `<strong>Chưa đủ dữ liệu để so sánh.</strong>
          <div class="small">${!d.baseline_available ? 'Phòng này chưa có đường cong chuẩn. ' : ''}${!d.measurement_available ? 'Chưa có phép đo nào. ' : ''}</div>
          ${recs.map(r => `<div class="small">${esc(r)}</div>`).join('')}`)}`;
        redraws.delete('compare');
        return;
      }
      const healthy = d.status === 'HEALTHY';
      const rms = +d.rms_deviation_db;
      const rmsKind = rms < 2.0 ? 'ok' : rms < 2.5 ? 'warn' : 'bad';
      const drift = +d.delay_drift_ms;
      const driftKind = Math.abs(drift) <= 0.8 ? 'ok' : Math.abs(drift) <= 2 ? 'warn' : 'bad';
      const points = d.point_comparisons || [];
      compareBox.innerHTML = `
        <div class="row-between">
          <div class="traffic">
            <span class="light ${healthy ? 'on ok' : ''}"></span><span class="light ${!healthy ? 'on warn' : ''}"></span>
            <strong>${healthy ? 'Đáp tuyến bám sát chuẩn phòng' : 'Đáp tuyến đang lệch chuẩn phòng'}</strong>
          </div>
          <span class="small muted">${esc(d.hall_name || '')}</span>
        </div>
        <div class="grid-3 mt-16">
          <div class="stat"><div class="stat-label">Độ lệch trung bình toàn dải</div>
            <div class="stat-value ${rmsKind}-text">${fmt.num(rms, 2)} dB</div><div class="stat-sub">Mục tiêu dưới 2,5 dB</div></div>
          <div class="stat"><div class="stat-label">Lệch độ trễ loa</div>
            <div class="stat-value ${driftKind}-text">${signed(drift, 2, ' ms')}</div>
            <div class="stat-sub">Đo ${fmt.num(d.measured_delay_ms, 2)} ms · chuẩn ${fmt.num(d.nominal_delay_ms, 1)} ms (cho phép ±0,8)</div></div>
          <div class="stat"><div class="stat-label">Điểm lệch đáng kể</div>
            <div class="stat-value">${points.filter(p => p.is_significant).length} / ${points.length}</div><div class="stat-sub">Lệch quá 2,5 dB</div></div>
        </div>
        ${points.length ? `<div class="mt-16">${chartBox('data-compare-chart')}${legend([[COLORS.baseline, 'Chuẩn của phòng (baseline)', true], [COLORS.measured, 'Đo được']])}</div>` : ''}
        ${recs.length ? `<div class="stack-sm mt-16">${recs.map(r => callout(healthy ? 'ok' : 'warn', esc(r))).join('')}</div>` : ''}
        ${points.length ? `
        <div class="table-wrap mt-16"><table class="table">
          <thead><tr><th>Tần số</th><th class="right">Chuẩn</th><th class="right">Đo được</th><th class="right">Chênh lệch</th><th class="right">Độ tin cậy</th><th></th></tr></thead>
          <tbody>${points.map(p => `<tr>
            <td class="mono">${fmt.hz(p.freq_hz)}</td>
            <td class="right mono">${signed(p.baseline_target_db, 1)} dB</td>
            <td class="right mono">${signed(p.measured_db, 1)} dB</td>
            <td class="right mono ${p.is_significant ? 'warn-text strong' : ''}">${signed(p.delta_db, 1)} dB</td>
            <td class="right mono ${+p.coherence < 0.6 ? 'warn-text' : ''}">${fmt.num(p.coherence, 2)}</td>
            <td>${p.is_significant ? badge('Lệch nhiều', 'warn') : badge('Ổn', 'ok')}</td>
          </tr>`).join('')}</tbody>
        </table></div>` : ''}`;
      if (points.length) {
        const sorted = [...points].sort((a, b) => a.freq_hz - b.freq_hz);
        draw('compare', $('[data-compare-chart]', compareBox), [
          { points: sorted.map(p => ({ freq: p.freq_hz, db: +p.baseline_target_db })), color: COLORS.baseline, dash: [6, 4] },
          { points: sorted.map(p => ({ freq: p.freq_hz, db: +p.measured_db })), color: COLORS.measured },
        ]);
      }
    }

    // ---------- H1 measurement ----------
    $('[data-measure]', root).addEventListener('click', async (e) => {
      const data = await withLoading(e.currentTarget, () => api.post('/api/v1/acoustics/measure'), { errorPrefix: 'Lỗi đo âm học: ' });
      if (!data || !alive) return;
      const coh = +data.coherence_avg;
      const cohKind = coh >= 0.8 ? 'ok' : coh >= 0.6 ? 'warn' : 'bad';
      $('[data-measure-stats]', root).innerHTML = `
        <div class="stat"><div class="stat-label">Độ trễ loa</div><div class="stat-value">${fmt.num(data.delay_ms, 2)} ms</div><div class="stat-sub">Vị trí: ${esc(data.position || '—')}</div></div>
        <div class="stat"><div class="stat-label">Độ tin cậy phép đo</div><div class="stat-value ${cohKind}-text">${fmt.num(coh, 3)}</div>
          <div class="stat-sub">${cohKind === 'ok' ? 'Phép đo sạch, dùng được' : cohKind === 'warn' ? 'Hơi nhiễu, đo lại nếu được' : 'Nhiễu nhiều — đừng chỉnh EQ theo kết quả này'}</div></div>
        <div class="stat"><div class="stat-label">Chống bù hố triệt pha</div><div class="stat-value ok-text" style="font-size:18px">Đã áp dụng</div><div class="stat-sub">Chỗ hụt bị giữ ≤ 0 dB</div></div>`;
      const curve = (data.curve || []).filter(p => +p.freq >= 20);
      const box = $('[data-measure-result]', root);
      box.innerHTML = curve.length
        ? `${chartBox('data-measure-chart')}${legend([[COLORS.measured, 'Đáp tuyến đo được'], [COLORS.safe, 'EQ an toàn gợi ý (chỉ cắt ở hố)', true]])}
           <p class="small muted mt-8">${esc(data.rule_enforced || '')}</p>`
        : emptyState('Phép đo không trả về đường cong.');
      if (curve.length) {
        draw('measure', $('[data-measure-chart]', box), [
          { points: curve.map(p => ({ freq: +p.freq, db: +p.magnitude_db })), color: COLORS.measured },
          { points: curve.map(p => ({ freq: +p.freq, db: +p.safe_eq_target_db })), color: COLORS.safe, dash: [6, 4] },
        ]);
      }
      toast(`Đo xong: độ trễ ${fmt.num(data.delay_ms, 2)} ms, độ tin cậy ${fmt.num(coh, 2)}.`, 'ok');
      loadCompare(); // so sánh lại với phép đo mới nhất
    });

    // ---------- OSM CSV import ----------
    $('[data-osm]', root).addEventListener('click', () => {
      const dlg = openDialog({
        title: 'Nhập file đo Open Sound Meter / REW',
        wide: true,
        body: `
          <div class="stack-sm">
            <div class="field"><label for="osm-name">Tên phép đo</label>
              <input id="osm-name" class="input" value="Hall_Measurement_1" autofocus></div>
            <div class="field"><label for="osm-file">Chọn file CSV</label>
              <input id="osm-file" class="input" type="file" accept=".csv,.txt,text/csv,text/plain" style="padding-top:6px">
              <span class="hint">Hoặc dán nội dung CSV vào ô dưới đây.</span></div>
            <div class="field"><label for="osm-csv">Nội dung CSV</label>
              <textarea id="osm-csv" class="textarea mono" rows="10" placeholder="Frequency,Magnitude,Coherence&#10;20,-3.1,0.82&#10;…"></textarea></div>
          </div>`,
        actions: [
          { label: 'Hủy', kind: 'ghost' },
          { label: 'Nhập dữ liệu', kind: 'primary', onClick: async (close, btn) => {
            const csv = $('#osm-csv', dlg.root).value.trim();
            const name = $('#osm-name', dlg.root).value.trim() || 'Hall_Measurement_1';
            if (!csv) { toast('Chưa có nội dung CSV.', 'warn'); return; }
            const data = await withLoading(btn, () => api.post('/api/v1/acoustics/import-osm', { name, csv_content: csv }),
              { errorPrefix: 'Lỗi phân tích file OSM: ' });
            if (!data) return;
            close();
            if (alive) renderOsm(data);
            toast(`Đã nhập ${data.row_count} điểm tần số.`, 'ok');
          } },
        ],
      });
      $('#osm-file', dlg.root).addEventListener('change', async (ev) => {
        const f = ev.target.files?.[0];
        if (!f) return;
        try {
          $('#osm-csv', dlg.root).value = await f.text();
          const nameEl = $('#osm-name', dlg.root);
          if (nameEl.value === 'Hall_Measurement_1') nameEl.value = f.name.replace(/\.[^.]+$/, '');
        } catch (err) {
          toast(`Không đọc được file: ${err.message || err}`, 'bad');
        }
      });
    });

    function renderOsm(data) {
      const freqs = data.freqs || [], mags = data.magnitude_db || [], cohs = data.coherence || [];
      const pts = freqs.map((f, i) => ({ freq: +f, db: +mags[i] })).filter(p => p.freq >= 20 && Number.isFinite(p.db));
      const cohAvg = cohs.length ? cohs.reduce((a, b) => a + +b, 0) / cohs.length : null;
      const box = $('[data-osm-result]', root);
      box.innerHTML = `
        <div class="grid-2">
          <div class="stat"><div class="stat-label">Số điểm tần số</div><div class="stat-value">${esc(data.row_count)}</div>
            <div class="stat-sub">${esc(data.name)}${data.row_count > freqs.length ? ` · hiển thị ${freqs.length} điểm đầu` : ''}</div></div>
          <div class="stat"><div class="stat-label">Độ tin cậy trung bình</div><div class="stat-value">${cohAvg === null ? '—' : fmt.num(cohAvg, 2)}</div>
            <div class="stat-sub">Coherence, gần 1 là tốt</div></div>
        </div>
        ${pts.length ? `<div class="mt-16">${chartBox('data-osm-chart')}${legend([[COLORS.measured, 'Đáp tuyến từ file']])}</div>` : ''}`;
      if (pts.length) draw('osm', $('[data-osm-chart]', box), [{ points: pts, color: COLORS.measured }]);
    }

    // ---------- Wiring ----------
    $('[data-compare]', root).addEventListener('click', (e) => loadCompare(e.currentTarget));
    $('[data-reload]', root).addEventListener('click', async (e) => {
      await withLoading(e.currentTarget, () => Promise.all([loadHalls(), loadCompare()]));
    });

    loadHalls();
    loadCompare();

    return () => {
      alive = false;
      window.removeEventListener('resize', onResize);
      redraws.clear();
    };
  },
};
