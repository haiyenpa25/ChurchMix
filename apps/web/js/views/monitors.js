// Monitor & P16: ma trận các bus monitor (loa sàn, in-ear, FX), kiểm tra 16 khe
// Ultranet P16 và bất biến sống còn: micro talkback ban nhạc (DL16 #11) chỉ được
// đi vào tai nghe P16, không bao giờ ra loa chính / Matrix FOH.
// Đề xuất cân bằng bus chỉ áp dụng sau khi kỹ thuật viên duyệt (renderProposal).

import { api, getOperator } from '../api.js';
import {
  $, $$, esc, icon, badge, pageHead, card, callout, errorBox, loadingRows, emptyState,
  fmt, withLoading, toast, renderProposal,
} from '../ui.js';

const REFRESH_MS = 15000;

const BUS_TYPE = {
  WEDGE: { label: 'Loa sàn', kind: 'warn' },
  IEM: { label: 'In-ear', kind: 'info' },
  FX: { label: 'Hiệu ứng', kind: '' },
  SUBGROUP: { label: 'Nhóm phụ', kind: '' },
};
const OVERALL = {
  SAFE: { label: 'An toàn', kind: 'ok', text: 'Không có nguy cơ hú hay lỗi cấu hình.' },
  WARNING: { label: 'Cần xem', kind: 'warn', text: 'Có nguy cơ hú hoặc lỗi điểm lấy tín hiệu.' },
  CRITICAL_VIOLATION: { label: 'Vi phạm talkback', kind: 'bad', text: 'Talkback ban nhạc đang lọt ra ngoài P16!' },
};
const TAP_VI = {
  PRE: 'Trước fader', 'PRE FADER': 'Trước fader', POST: 'Sau fader', 'POST FADER': 'Sau fader',
  'PRE EQ': 'Trước EQ', 'POST EQ': 'Sau EQ', IN: 'Đầu vào', INPUT: 'Đầu vào', 'IN LC': 'Đầu vào (sau lọc trầm)',
};
const tapVi = (t) => TAP_VI[String(t || '').toUpperCase().replace(/[-_/]+/g, ' ').trim()] || t || '—';
const pad2 = (n) => String(n ?? '—').padStart(2, '0');

export default {
  mount(root) {
    root.innerHTML = `
      ${pageHead('Monitor & P16',
        'Kiểm tra loa monitor sân khấu, tai nghe in-ear P16, và bảo đảm micro talkback ban nhạc không bao giờ lọt ra loa chính.',
        `<span class="small muted" data-updated></span><button class="btn" data-reload>${icon('refresh')}Kiểm tra lại</button>`)}
      <div class="stack">
        <div data-invariant>${loadingRows(2)}</div>
        <div class="grid-4" data-tiles></div>
        <section class="card">
          <div class="card-body">
            <div class="tabs" role="tablist">
              <button class="active" data-tab="p16">${icon('headphones', 'icon-sm')} Ultranet P16 (16 khe)</button>
              <button data-tab="buses">${icon('layers', 'icon-sm')} Bus monitor</button>
              <button data-tab="alerts">${icon('alert', 'icon-sm')} Cảnh báo <span data-alert-count></span></button>
            </div>
            <div data-pane="p16">${loadingRows(5)}</div>
            <div data-pane="buses" hidden>${loadingRows(5)}</div>
            <div data-pane="alerts" hidden>${loadingRows(3)}</div>
          </div>
        </section>
        <div data-proposal-card hidden>
          ${card({ title: 'Đề xuất cân bằng & chống hú', sub: 'Xem kỹ từng thay đổi trước khi duyệt',
            actions: `<button class="btn btn-sm btn-ghost" data-close-prop>${icon('x', 'icon-sm')}Đóng</button>`,
            body: '<div class="stack" data-proposals></div>' })}
        </div>
      </div>`;

    let alive = true;
    let inflight = false;
    let loadedOnce = false;
    const invBox = $('[data-invariant]', root);
    const tiles = $('[data-tiles]', root);
    const updated = $('[data-updated]', root);
    const panes = { p16: $('[data-pane="p16"]', root), buses: $('[data-pane="buses"]', root), alerts: $('[data-pane="alerts"]', root) };

    // ---------- Tabs ----------
    $$('[data-tab]', root).forEach(b => b.addEventListener('click', () => {
      $$('[data-tab]', root).forEach(x => x.classList.toggle('active', x === b));
      Object.entries(panes).forEach(([k, p]) => { p.hidden = k !== b.dataset.tab; });
    }));

    // ---------- Load ----------
    async function load(btn) {
      if (!alive || inflight) return;
      if (!btn && document.hidden) return;
      inflight = true;
      const run = () => Promise.all([api.get('/api/v1/monitors/iem-matrix'), api.get('/api/v1/monitors/p16-audit')]);
      try {
        const [matrix, p16] = btn ? await withLoading(btn, run).then(r => { if (!r) throw null; return r; }) : await run();
        if (!alive) return;
        loadedOnce = true;
        render(matrix, p16);
        updated.textContent = `Cập nhật lúc ${new Date().toLocaleTimeString('vi-VN')}`;
      } catch (e) {
        if (!alive || e === null) return; // withLoading đã báo lỗi bằng toast
        if (!loadedOnce) {
          invBox.innerHTML = errorBox(e);
          tiles.innerHTML = '';
          Object.values(panes).forEach(p => { p.innerHTML = emptyState('Chưa đọc được dữ liệu từ mixer.'); });
        } else {
          updated.innerHTML = `<span class="warn-text">Không làm mới được: ${esc(e.message)}</span>`;
        }
      } finally {
        inflight = false;
      }
    }

    function render(m, p16) {
      const p16Safe = p16.p16_talkback_safe !== false && m.p16_talkback_safe !== false;
      const isolated = m.talkback_isolation_verified !== false;
      const safe = p16Safe && isolated;
      const violations = [...new Set([...(p16.violations || [])])];
      const hazards = m.feedback_hazards || [];
      const taps = m.tap_inconsistencies || [];
      const buses = m.mixbuses || [];
      const overall = OVERALL[m.overall_status] || { label: m.overall_status || '—', kind: 'info', text: '' };

      // Bất biến talkback — luôn hiển thị nổi bật nhất.
      invBox.innerHTML = `
        <div class="hero ${safe ? 'ok' : 'bad'}">
          <div class="hero-icon">${icon(safe ? 'shieldCheck' : 'alert', 'icon-lg')}</div>
          <div class="grow">
            <h2>${safe ? 'Talkback ban nhạc chỉ vào tai nghe P16' : 'NGUY HIỂM: Talkback ban nhạc đang lọt ra ngoài P16'}</h2>
            <p>${safe
              ? 'Micro talkback (DL16 ngõ vào 11) chỉ gửi tới khe P16 dành riêng, không đi ra loa chính hay Matrix FOH.'
              : 'Hội chúng có thể nghe thấy lời trao đổi của ban nhạc. Kiểm tra ngay các đường gửi của kênh talkback trên mixer. Mọi lệnh ghi tự động bị chặn.'}</p>
            ${violations.length ? `<ul class="small" style="margin:8px 0 0;padding-left:18px">${violations.map(v => `<li>${esc(v)}</li>`).join('')}</ul>` : ''}
          </div>
          ${badge(safe ? 'Cách ly OK' : 'Vi phạm', safe ? 'ok' : 'bad')}
        </div>`;

      const crit = hazards.filter(h => h.risk_level === 'CRITICAL').length;
      tiles.innerHTML = `
        <div class="stat"><div class="stat-label">Tình trạng chung</div>
          <div class="stat-value ${overall.kind}-text" style="font-size:18px">${esc(overall.label)}</div>
          <div class="stat-sub">${esc(overall.text)}</div></div>
        <div class="stat"><div class="stat-label">Nguy cơ hú loa sàn</div>
          <div class="stat-value ${hazards.length ? (crit ? 'bad-text' : 'warn-text') : 'ok-text'}">${hazards.length}</div>
          <div class="stat-sub">${crit ? `${crit} mức rất cao` : hazards.length ? 'Đường gửi monitor quá lớn' : 'Không có đường gửi quá lớn'}</div></div>
        <div class="stat"><div class="stat-label">Lỗi điểm lấy tín hiệu</div>
          <div class="stat-value ${taps.length ? 'warn-text' : 'ok-text'}">${taps.length}</div>
          <div class="stat-sub">Monitor nên lấy trước fader</div></div>
        <div class="stat"><div class="stat-label">Bus monitor</div>
          <div class="stat-value">${buses.length}</div>
          <div class="stat-sub">${esc(m.proposals_available ?? 0)} đề xuất có thể tạo</div></div>`;

      // P16 slots
      const slots = p16.slots || m.p16_slots || [];
      panes.p16.innerHTML = slots.length ? `
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Khe P16</th><th>Tên</th><th>Nguồn</th><th>Điểm lấy tín hiệu</th><th>Trạng thái</th><th>Ghi chú</th></tr></thead>
          <tbody>${slots.map(s => {
            const viol = s.status === 'CRITICAL_INVARIANT_VIOLATION';
            const tb = s.is_band_talkback || s.slot === 11;
            const st = viol ? badge('Lọt talkback', 'bad') : tb ? badge('Talkback ban nhạc', 'warn')
              : s.status === 'WARNING' ? badge('Cần xem', 'warn') : badge('Ổn', 'ok');
            return `<tr ${viol ? 'style="background:var(--bad-soft)"' : tb ? 'style="background:var(--warn-soft)"' : ''}>
              <td class="mono nowrap">Khe ${pad2(s.slot)}</td>
              <td><strong>${esc(s.name)}</strong></td>
              <td class="mono nowrap">${fmt.ch(s.source_channel)}</td>
              <td>${esc(tapVi(s.tap_point))}</td>
              <td>${st}</td>
              <td class="small text-2">${esc(s.details || '')}</td>
            </tr>`;
          }).join('')}</tbody>
        </table></div>
        <p class="small muted mt-8">Lưu ý: số khe P16 không nhất thiết trùng số kênh X32 hay số ngõ vào DL16 — xem cột “Nguồn”.</p>`
        : emptyState('Không có dữ liệu khe P16.');

      // Mix buses
      panes.buses.innerHTML = buses.length ? `
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Bus</th><th>Tên</th><th>Loại</th><th class="right">Master</th><th class="right">Kênh gửi</th>
            <th>Ra loa chính</th><th>Cảnh báo</th><th></th></tr></thead>
          <tbody>${buses.map(b => {
            const t = BUS_TYPE[b.bus_type] || { label: b.bus_type || '—', kind: '' };
            const warns = [
              b.talkback_leaked ? badge('Lọt talkback', 'bad') : '',
              b.feedback_risk_count > 0 ? badge(`${b.feedback_risk_count} nguy cơ hú`, 'bad') : '',
              b.tap_inconsistency_count > 0 ? badge(`${b.tap_inconsistency_count} lỗi sau fader`, 'warn') : '',
            ].filter(Boolean).join(' ');
            return `<tr>
              <td class="mono nowrap">Bus ${pad2(b.bus)}</td>
              <td><strong>${esc(b.name)}</strong></td>
              <td>${t.kind ? badge(t.label, t.kind) : badge(t.label)}</td>
              <td class="right mono">${b.master_on ? '' : '<span class="warn-text">Tắt · </span>'}${fmt.db(b.master_fader_db)}</td>
              <td class="right mono">${esc(b.active_send_count ?? 0)}</td>
              <td>${b.routes_to_st ? '<span class="warn-text">Có</span>' : '<span class="muted">Không (cách ly)</span>'}</td>
              <td>${warns || '<span class="ok-text small">Ổn</span>'}</td>
              <td class="right"><button class="btn btn-sm" data-propose="${esc(b.bus)}">${icon('wand', 'icon-sm')}Đề xuất cân bằng</button></td>
            </tr>`;
          }).join('')}</tbody>
        </table></div>`
        : emptyState('Không có bus monitor nào.');

      // Alerts
      const n = hazards.length + taps.length;
      $('[data-alert-count]', root).innerHTML = n ? badge(String(n), hazards.length ? 'bad' : 'warn') : '';
      panes.alerts.innerHTML = n ? `<div class="stack-sm">
        ${hazards.map(h => `
          <div class="callout callout-${h.risk_level === 'CRITICAL' || h.risk_level === 'HIGH' ? 'bad' : 'warn'}">${icon('alert')}
            <div class="grow">
              <div class="row-between"><strong>${h.risk_level === 'CRITICAL' ? 'Nguy cơ hú rất cao' : 'Nguy cơ hú'} · ${esc(h.bus_name)} ← ${esc(h.channel_name)}</strong>
                <span class="mono small">${fmt.db(h.send_level_db)}</span></div>
              <p class="small text-2 mt-8">${esc(h.message)}</p>
              <div class="mt-8"><button class="btn btn-sm" data-propose="${esc(h.bus)}">${icon('wand', 'icon-sm')}Đề xuất hạ mức gửi</button></div>
            </div></div>`).join('')}
        ${taps.map(t => `
          <div class="callout callout-warn">${icon('info')}
            <div class="grow">
              <div class="row-between"><strong>Điểm lấy tín hiệu chưa đúng · ${esc(t.bus_name)} ← ${esc(t.channel_name)}</strong>
                <span class="small">${esc(tapVi(t.current_tap))} → ${esc(tapVi(t.recommended_tap || 'Pre'))}</span></div>
              <p class="small text-2 mt-8">${esc(t.message)}</p>
            </div></div>`).join('')}
      </div>` : callout('ok', '<strong>Không phát hiện rủi ro nào.</strong> Mọi đường gửi monitor nằm trong giới hạn an toàn và lấy tín hiệu đúng chỗ.');
    }

    // ---------- Propose bus balance ----------
    const propCard = $('[data-proposal-card]', root);
    const propBox = $('[data-proposals]', root);
    $('[data-close-prop]', root).addEventListener('click', () => { propCard.hidden = true; propBox.innerHTML = ''; });

    root.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-propose]');
      if (!btn) return;
      const busId = parseInt(btn.dataset.propose, 10);
      const data = await withLoading(btn, () => api.post('/api/v1/monitors/propose-bus-balance', { bus_id: busId, operator: getOperator() }),
        { errorPrefix: 'Không tạo được đề xuất monitor: ' });
      if (!data || !alive) return;
      const proposals = data.proposals || [];
      propCard.hidden = false;
      const base = `Bus ${pad2(busId)}`;
      const label = data.bus_name && data.bus_name !== base ? `${base} (${data.bus_name})` : base;
      if (!proposals.length) {
        propBox.innerHTML = callout('ok', `<strong>${esc(label)}</strong> đang cân bằng an toàn, không cần điều chỉnh.`);
      } else {
        propBox.innerHTML = `${callout('info', `Đã tạo <strong>${proposals.length}</strong> đề xuất cho <strong>${esc(label)}</strong>.`)}
          ${proposals.map((_, i) => `<div class="stat" data-prop="${i}"></div>`).join('')}`;
        proposals.forEach((p, i) => renderProposal($(`[data-prop="${i}"]`, propBox), p, {
          title: `Cân bằng ${label}`,
          note: 'Chỉ chỉnh mức gửi / điểm lấy tín hiệu của bus monitor này. Không đụng tới định tuyến, P16 hay bus chính.',
          onApplied: () => load(),
        }));
        toast(`Đã tạo ${proposals.length} đề xuất cho ${label}. Hãy duyệt trước khi áp dụng.`, 'info');
      }
      propCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });

    $('[data-reload]', root).addEventListener('click', (e) => load(e.currentTarget));

    load();
    const timer = setInterval(() => load(), REFRESH_MS);

    return () => {
      alive = false;
      clearInterval(timer);
    };
  },
};
