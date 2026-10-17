// "Kiểm tra trước lễ" — 10-point pre-service diagnostics + Sunday line check
// (W2) with a manual physical checklist. Read-only: nothing here writes to the mixer.
//
// Ported from legacy.html: runPreServiceDiagnosticsUI, fetchLineCheckData,
// togglePhysicalCheck, updateLineCheckOverallReadiness.

import { api } from '../api.js';
import { $, $$, esc, icon, badge, statusKind, card, callout, pageHead, emptyState, loadingRows, errorBox, withLoading, fmt } from '../ui.js';

// Fallback list if the server returns no physical checklist.
const DEFAULT_PHYSICAL = [
  { task: 'Kiểm tra pin micro không dây', detail: 'Mic Mục sư và giọng chính còn ít nhất 2/3 vạch pin.' },
  { task: 'Kiểm tra dây cáp & tai nghe P16', detail: 'Cáp mạng Cat5e cắm chắc vào P16-D và từng bộ P16-HQ.' },
  { task: 'Kiểm tra Talkback DL16 #11', detail: 'Mic giao tiếp ban nhạc chỉ nghe trong tai nghe ban nhạc, không ra loa chính.' },
  { task: 'Thử micro bục giảng', detail: 'Người nói thử giọng tự nhiên, nghe độ ấm, không ù gió.' },
  { task: 'Sao lưu Scene mixer', detail: 'Lưu một bản Snapshot vào USB mixer trước giờ lễ.' },
];

// Ticks survive navigating away and back during the same browser session.
const physicalState = new Map();

const itemTitle = (it) => it.task || it.item || it.name || '';
const itemDetail = (it) => it.detail || it.action || '';
const itemKey = (it, i) => `${i}:${itemTitle(it)}`;

export default {
  mount(root, ctx) {
    let diag = null;
    let diagErr = null;
    let line = null;
    let lineErr = null;
    let alive = true;

    root.innerHTML = `
      ${pageHead('Kiểm tra trước lễ',
        'Làm lần lượt 3 bước: chạy tự chẩn đoán hệ thống, đối chiếu trạng thái các kênh, rồi tự tay đánh dấu các mục kiểm tra tại chỗ. Trang này chỉ đọc mixer, không thay đổi gì.',
        `<button class="btn btn-primary" data-run-all>${icon('refresh')}Kiểm tra lại tất cả</button>`)}
      <div class="stack">
        <div data-summary>${loadingRows(2)}</div>
        <div class="grid-2">
          <div data-diag></div>
          <div data-physical></div>
        </div>
        <div data-line></div>
      </div>`;

    const summaryEl = $('[data-summary]', root);
    const diagEl = $('[data-diag]', root);
    const physEl = $('[data-physical]', root);
    const lineEl = $('[data-line]', root);

    // ---------- Readiness summary ----------
    function physicalItems() {
      const list = line?.physical_checklist;
      return Array.isArray(list) && list.length ? list : DEFAULT_PHYSICAL;
    }

    function renderSummary() {
      const items = physicalItems();
      const ticked = items.filter((it, i) => physicalState.get(itemKey(it, i))).length;
      const physOk = ticked === items.length;
      const diagOk = diag ? diag.overall_status === 'PASS' : false;
      const tbOk = line ? !!line.talkback_isolated : false;
      const mutedCount = line ? (line.items || []).filter(c => c.status !== 'OK').length : 0;
      const loading = (!diag && !diagErr) || (!line && !lineErr);

      const passed = diag?.passed_count ?? 0;
      const total = diag?.total_count ?? 10;
      const failed = diag ? total - passed : 0;

      let kind, title, desc, ic;
      if (loading) {
        kind = ''; ic = 'clock'; title = 'Đang kiểm tra…'; desc = 'Đang chạy tự chẩn đoán và quét trạng thái mixer.';
      } else if (!tbOk && line) {
        kind = 'bad'; ic = 'xCircle'; title = 'KHÔNG SẴN SÀNG — Talkback chưa được cách ly';
        desc = 'Mic Talkback DL16 #11 có thể lọt ra loa chính. Không mở loa FOH cho đến khi quản trị viên xử lý định tuyến.';
      } else if (diagErr || lineErr || !diagOk) {
        kind = 'bad'; ic = 'xCircle'; title = 'Chưa sẵn sàng — có mục kiểm tra lỗi';
        desc = 'Xem các mục đánh dấu đỏ bên dưới và xử lý trước khi mở tín hiệu ra loa.';
      } else if (!physOk || mutedCount) {
        kind = 'warn'; ic = 'alert'; title = 'Gần xong — còn vài việc cần làm';
        desc = !physOk
          ? `Còn ${items.length - ticked} mục kiểm tra tại chỗ chưa đánh dấu.`
          : `${mutedCount} kênh đang tắt tiếng (Mute). Kiểm tra lại nếu kênh đó cần dùng.`;
      } else {
        kind = 'ok'; ic = 'checkCircle'; title = 'Sẵn sàng cho buổi lễ';
        desc = 'Tự chẩn đoán đạt, Talkback được cách ly và mọi mục tại chỗ đã được kiểm tra.';
      }

      const stat = (label, value, sub, k) => `
        <div class="stat"><div class="stat-label">${label}</div>
          <div class="stat-value ${k ? `${k}-text` : ''}">${value}</div>
          ${sub ? `<div class="stat-sub">${sub}</div>` : ''}</div>`;

      summaryEl.innerHTML = `
        <div class="stack">
          <div class="hero ${kind}">
            <div class="hero-icon">${icon(ic, 'icon-lg')}</div>
            <div class="grow"><h2>${esc(title)}</h2><p>${esc(desc)}</p></div>
          </div>
          <div class="grid-4">
            ${stat('Tự chẩn đoán', diag ? `${passed}/${total}` : (diagErr ? 'Lỗi' : '…'),
              diag ? (failed ? `${failed} mục KHÔNG ĐẠT` : 'Tất cả ĐẠT') : '', diag ? (failed ? 'bad' : 'ok') : (diagErr ? 'bad' : ''))}
            ${stat('Talkback DL16 #11', line ? (tbOk ? 'Cách ly' : 'VI PHẠM') : (lineErr ? 'Lỗi' : '…'),
              line ? (tbOk ? 'Chỉ vào tai nghe P16' : 'Có thể lọt ra loa chính') : '', line ? (tbOk ? 'ok' : 'bad') : (lineErr ? 'bad' : ''))}
            ${stat('Kênh đang Mute', line ? String(mutedCount) : '…',
              line ? `trên ${(line.items || []).length} kênh` : '', line ? (mutedCount ? 'warn' : 'ok') : '')}
            ${stat('Kiểm tra tại chỗ', `${ticked}/${items.length}`, physOk ? 'Đã xong' : 'Bạn tự đánh dấu', physOk ? 'ok' : 'warn')}
          </div>
        </div>`;
    }

    // ---------- Step 1: 10-point diagnostics ----------
    function renderDiag() {
      let body;
      if (diagErr) body = errorBox(diagErr);
      else if (!diag) body = loadingRows(6);
      else if (!(diag.checks || []).length) body = emptyState('Máy chủ không trả về mục kiểm tra nào.');
      else {
        body = `<div class="checklist">${diag.checks.map(c => {
          const ok = c.passed === true || c.status === 'PASS';
          return `
            <div class="check-item">
              <span class="${ok ? 'ok-text' : 'bad-text'}">${icon(ok ? 'checkCircle' : 'xCircle')}</span>
              <div class="grow">
                <div class="strong">${esc(c.name)}</div>
                ${c.message ? `<div class="small text-2">${esc(c.message)}</div>` : ''}
              </div>
              ${badge(ok ? 'ĐẠT' : 'KHÔNG ĐẠT', ok ? 'ok' : 'bad')}
            </div>`;
        }).join('')}</div>`;
        if (diag.overall_status !== 'PASS') {
          body = callout('bad', 'Có mục không đạt. Cần xử lý các mục đỏ trước khi mở tín hiệu âm thanh ra loa FOH.') + `<div class="mt-8">${body}</div>`;
        }
      }
      diagEl.innerHTML = card({
        title: `${icon('stethoscope')} Bước 1 · Tự chẩn đoán hệ thống`,
        sub: '10 tiêu chuẩn: phần mềm, cơ sở dữ liệu, kết nối OSC và các bất biến an toàn',
        actions: `<button class="btn btn-sm" data-run-diag>${icon('refresh', 'icon-sm')}Chạy lại</button>`,
        body,
      });
      $('[data-run-diag]', diagEl).addEventListener('click', (e) => withLoading(e.currentTarget, loadDiag));
    }

    async function loadDiag() {
      diag = null; diagErr = null;
      renderDiag(); renderSummary();
      try { diag = await api.get('/api/v1/system/diagnostics'); }
      catch (e) { diagErr = e; }
      if (!alive) return;
      renderDiag(); renderSummary();
    }

    // ---------- Step 3: manual physical checklist ----------
    function renderPhysical() {
      const items = physicalItems();
      const ticked = items.filter((it, i) => physicalState.get(itemKey(it, i))).length;
      physEl.innerHTML = card({
        title: `${icon('clipboard')} Bước 3 · Kiểm tra tại chỗ`,
        sub: 'Bạn tự đi kiểm tra rồi đánh dấu. Chỉ lưu trên máy này.',
        actions: badge(`${ticked}/${items.length}`, ticked === items.length ? 'ok' : 'warn'),
        body: `<div class="checklist">${items.map((it, i) => {
          const key = itemKey(it, i);
          const on = !!physicalState.get(key);
          return `
            <label class="check-item check" style="cursor:pointer">
              <input type="checkbox" data-key="${esc(key)}" ${on ? 'checked' : ''}>
              <div class="grow">
                <div class="strong" ${on ? 'style="text-decoration:line-through;opacity:.7"' : ''}>${esc(itemTitle(it))}</div>
                ${itemDetail(it) ? `<div class="small text-2">${esc(itemDetail(it))}</div>` : ''}
              </div>
              ${on ? `<span class="ok-text">${icon('check')}</span>` : ''}
            </label>`;
        }).join('')}</div>`,
        foot: `<button class="btn btn-ghost btn-sm" data-reset-phys>Bỏ đánh dấu tất cả</button>`,
      });
      $$('input[type=checkbox]', physEl).forEach(cb => cb.addEventListener('change', () => {
        physicalState.set(cb.dataset.key, cb.checked);
        renderPhysical(); renderSummary();
      }));
      $('[data-reset-phys]', physEl).addEventListener('click', () => {
        physicalState.clear();
        renderPhysical(); renderSummary();
      });
    }

    // ---------- Step 2: line check per channel ----------
    function pathLabel(ch) {
      if (ch.is_foh && ch.is_p16) return 'Loa chính + P16';
      if (ch.is_p16) return 'Chỉ P16 (tai nghe)';
      if (ch.is_foh) return 'Loa chính (FOH)';
      return 'Không ra đâu';
    }

    function renderLine() {
      let body;
      if (lineErr) body = errorBox(lineErr);
      else if (!line) body = loadingRows(8);
      else if (!(line.items || []).length) body = emptyState('Không có dữ liệu kênh.');
      else {
        const rows = line.items.map(ch => {
          const isTB = ch.channel_id === 11;
          const tbViolation = isTB && ch.is_foh;
          const kind = tbViolation ? 'bad' : statusKind(ch.status === 'OK' ? 'OK' : 'WARN');
          const label = tbViolation ? 'VI PHẠM' : (ch.status === 'OK' ? 'Sẵn sàng' : (ch.status === 'MUTED' ? 'Đang Mute' : ch.status));
          return `
            <tr ${isTB ? 'style="background:var(--accent-soft)"' : ''}>
              <td class="mono nowrap">${esc(fmt.ch(ch.channel_id))}</td>
              <td class="${isTB ? 'strong' : ''}">${esc(ch.name)}${isTB ? ` ${badge('Talkback', 'info')}` : ''}</td>
              <td>${ch.is_muted ? '<span class="warn-text strong">Tắt tiếng</span>' : '<span class="ok-text">Bật</span>'}</td>
              <td class="${tbViolation ? 'bad-text strong' : ''}">${esc(pathLabel(ch))}</td>
              <td class="right mono">${esc(ch.fader_pct)}%</td>
              <td>${badge(label, kind)}</td>
              <td class="small text-2">${esc(ch.notes || '')}</td>
            </tr>`;
        }).join('');
        body = `
          ${line.talkback_isolated
            ? callout('ok', '<strong>Talkback DL16 #11 đã cách ly.</strong> Tín hiệu chỉ vào tai nghe P16 của ban nhạc, không ra loa chính hay Matrix.')
            : callout('bad', '<strong>Talkback DL16 #11 KHÔNG được cách ly!</strong> Đây là lỗi an toàn nghiêm trọng — báo quản trị viên kiểm tra định tuyến (quy trình bảo trì riêng). Không tự sửa routing tại đây.')}
          <div class="table-wrap mt-16"><table class="table">
            <thead><tr><th>Kênh</th><th>Tên</th><th>Mute</th><th>Đường ra</th><th class="right">Fader</th><th>Đánh giá</th><th>Ghi chú</th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>
          ${line.iso_time ? `<p class="small muted mt-8">Quét lúc ${esc(fmt.time(line.timestamp || line.iso_time))}</p>` : ''}`;
      }
      lineEl.innerHTML = card({
        title: `${icon('listCheck')} Bước 2 · Line check từng kênh`,
        sub: 'Đối chiếu trạng thái Mute, đường ra và fader của 32 kênh trên mixer',
        actions: `<button class="btn btn-sm" data-run-line>${icon('refresh', 'icon-sm')}Quét lại mixer</button>`,
        body,
      });
      $('[data-run-line]', lineEl).addEventListener('click', (e) => withLoading(e.currentTarget, loadLine));
    }

    async function loadLine() {
      line = null; lineErr = null;
      renderLine(); renderSummary();
      try { line = await api.get('/api/v1/wizards/line-check'); }
      catch (e) { lineErr = e; }
      if (!alive) return;
      renderLine(); renderPhysical(); renderSummary();
    }

    $('[data-run-all]', root).addEventListener('click', (e) =>
      withLoading(e.currentTarget, () => Promise.all([loadDiag(), loadLine()])));

    renderPhysical();
    loadDiag();
    loadLine();

    return () => { alive = false; };
  },
};
