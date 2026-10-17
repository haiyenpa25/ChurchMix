// Chương trình lễ (technical page): the order of service. Each item points at a
// segment (Tiết mục). Editing here never touches the mixer. "Chuyển sang" uses the
// normal segment preview + confirm (switchToSegment) and only then marks the item
// as current via POST /api/v1/program/current (a marker, never a mixer write).
//
// API (apps/api/program_routes.py):
//   GET  /api/v1/program                  PUT /api/v1/program {items, operator_id}
//   POST /api/v1/program/current {index, segment_id, operator_id}
//   POST /api/v1/program/reset            POST /api/v1/program/restore-default
//   GET  /api/v1/segment-suggestion       (what the segment detector currently thinks)

import { api, getOperator } from '../api.js';
import { $, $$, esc, icon, pageHead, card, callout, confirmDialog, toast, withLoading, loadingRows, errorBox, fmt } from '../ui.js';
import { switchToSegment } from '../segments.js';

const MAX_TITLE = 80;
const MAX_NOTE = 200;

export default {
  mount(root) {
    let alive = true;
    let program = null;   // last server state
    let segments = [];    // [{id, name, ...}]
    let items = [];       // editable copy
    let dirty = false;

    root.innerHTML = `
      ${pageHead('Chương trình lễ', 'Thứ tự các phần trong buổi lễ. Mỗi phần gắn với một tiết mục (micro nào bật/tắt). Trong lễ, người trực chỉ cần bấm “Tiếp theo”. Sửa ở đây không thay đổi mixer.',
        `<button class="btn" data-default>${icon('refresh')}Chương trình mẫu</button>
         <button class="btn" data-restart>${icon('history')}Bắt đầu lại từ đầu</button>`)}
      <div data-summary></div>
      <div class="mt-16">${card({
        title: 'Các phần của buổi lễ',
        sub: 'Đổi tiết mục, đặt tên, ghi chú; dùng mũi tên để đổi thứ tự. Bấm “Lưu chương trình” khi xong.',
        body: `<div data-list>${loadingRows(4)}</div>
          <div class="row mt-16" style="flex-wrap:wrap;gap:8px">
            <select class="select" data-add-seg style="flex:1 1 200px;min-width:0" aria-label="Tiết mục để thêm"></select>
            <button class="btn" data-add>${icon('plus')}Thêm phần</button>
          </div>`,
        foot: `<span class="small muted grow" data-dirty></span>
          <button class="btn btn-primary" data-save>${icon('check')}Lưu chương trình</button>`,
      })}</div>
      <div class="mt-16">${card({
        title: 'Tự nhận diện tiết mục',
        sub: 'Máy đoán tiết mục đang diễn ra từ micro nào đang có tiếng (8 giây gần nhất). Chỉ gợi ý — không tự chuyển.',
        body: '<div data-detect>' + loadingRows(2) + '</div>',
      })}</div>`;

    const list = $('[data-list]', root);
    const summary = $('[data-summary]', root);
    const dirtyBox = $('[data-dirty]', root);
    const addSel = $('[data-add-seg]', root);
    const detectBox = $('[data-detect]', root);

    const segName = (id) => segments.find(s => s.id === id)?.name;
    const segOptions = (selected) => segments.map(s =>
      `<option value="${esc(s.id)}" ${s.id === selected ? 'selected' : ''}>${esc(s.name)}</option>`).join('');

    const markDirty = (v = true) => {
      dirty = v;
      dirtyBox.textContent = dirty ? 'Có thay đổi chưa lưu.' : (program?.is_default ? 'Đang dùng chương trình mẫu (chưa lưu).' : `Lưu lần cuối: ${program?.updated_by || '—'} · ${fmt.time(program?.updated_at)}`);
      dirtyBox.className = `small grow ${dirty ? 'warn-text' : 'muted'}`;
    };

    async function load() {
      try {
        const [p, s] = await Promise.all([api.get('/api/v1/program'), api.get('/api/v1/segments')]);
        if (!alive) return;
        program = p;
        segments = s.segments || [];
        items = p.items.map(({ id, segment_id, title, note }) => ({ id, segment_id, title, note }));
        addSel.innerHTML = segOptions(segments[0]?.id);
        markDirty(false);
        renderSummary();
        renderList();
      } catch (e) {
        if (alive) list.innerHTML = errorBox(e);
      }
    }

    function renderSummary() {
      const cur = program?.current;
      const nxt = program?.next;
      summary.innerHTML = callout(cur ? 'ok' : 'info', `
        <div><strong>Đang:</strong> ${cur ? `${program.current_index + 1}. ${esc(cur.title)} <span class="muted">(${esc(cur.segment_name || 'tiết mục đã xóa')})</span>` : 'chưa bắt đầu'}</div>
        <div class="mt-8"><strong>Tiếp theo:</strong> ${nxt ? `${program.next_index + 1}. ${esc(nxt.title)} <span class="muted">(${esc(nxt.segment_name || 'tiết mục đã xóa')})</span>` : 'hết chương trình'}</div>`, 'clipboard');
    }

    function renderList() {
      if (!items.length) {
        list.innerHTML = '<p class="muted">Chưa có phần nào. Chọn tiết mục bên dưới và bấm “Thêm phần”.</p>';
        return;
      }
      const curId = program?.current?.id;
      const nextId = program?.next?.id;
      list.innerHTML = `<div class="stack-sm">${items.map((it, i) => {
        const missing = !segName(it.segment_id);
        const tag = it.id && it.id === curId ? '<span class="badge badge-ok">Đang</span>'
          : it.id && it.id === nextId ? '<span class="badge badge-info">Tiếp theo</span>' : '';
        return `
        <div class="card tight ${it.id && it.id === curId ? 'ok' : ''}" data-row="${i}"><div class="card-body">
          <div class="row" style="flex-wrap:wrap;gap:8px;align-items:flex-end">
            <div class="strong" style="width:28px;padding-bottom:10px">${i + 1}.</div>
            <div class="field" style="flex:1 1 180px">
              <label>Tên phần ${tag}</label>
              <input class="input" data-f="title" maxlength="${MAX_TITLE}" value="${esc(it.title)}" placeholder="${esc(segName(it.segment_id) || '')}">
            </div>
            <div class="field" style="flex:1 1 160px">
              <label>Tiết mục (micro)</label>
              <select class="select" data-f="segment_id">${missing ? `<option value="${esc(it.segment_id)}" selected>⚠ Tiết mục đã xóa</option>` : ''}${segOptions(it.segment_id)}</select>
            </div>
            <div class="field" style="flex:2 1 220px">
              <label>Ghi chú</label>
              <input class="input" data-f="note" maxlength="${MAX_NOTE}" value="${esc(it.note || '')}" placeholder="Ví dụ: Mục sư dùng micro không dây">
            </div>
            <div class="row" style="gap:4px;flex-wrap:nowrap">
              <button class="btn btn-sm btn-ghost" data-act="up" ${i === 0 ? 'disabled' : ''} aria-label="Lên trên" title="Lên trên">▲</button>
              <button class="btn btn-sm btn-ghost" data-act="down" ${i === items.length - 1 ? 'disabled' : ''} aria-label="Xuống dưới" title="Xuống dưới">▼</button>
              <button class="btn btn-sm btn-ghost" data-act="delete" aria-label="Xóa" title="Xóa">${icon('trash', 'icon-sm')}</button>
              <button class="btn btn-sm" data-act="switch" ${missing ? 'disabled' : ''} title="Xem trước rồi chuyển mixer sang tiết mục này">${icon('arrowRight', 'icon-sm')}Chuyển sang</button>
            </div>
          </div>
        </div></div>`;
      }).join('')}</div>`;

      $$('[data-row]', list).forEach(row => {
        const i = +row.dataset.row;
        $$('[data-f]', row).forEach(inp => inp.addEventListener(inp.tagName === 'SELECT' ? 'change' : 'input', () => {
          items[i][inp.dataset.f] = inp.value;
          markDirty();
        }));
        $$('[data-act]', row).forEach(b => b.addEventListener('click', () => act(b.dataset.act, i, b)));
      });
    }

    async function act(kind, i, btn) {
      if (kind === 'up' || kind === 'down') {
        const j = kind === 'up' ? i - 1 : i + 1;
        [items[i], items[j]] = [items[j], items[i]];
        markDirty(); renderList();
      } else if (kind === 'delete') {
        items.splice(i, 1);
        markDirty(); renderList();
      } else if (kind === 'switch') {
        if (dirty) { toast('Hãy lưu chương trình trước khi chuyển.', 'warn'); return; }
        const it = program.items[i];
        const res = await switchToSegment({ id: it.segment_id, name: it.segment_name, description: it.note });
        if (!res) return;
        const p = await withLoading(btn, () => api.post('/api/v1/program/current', { index: i, segment_id: it.segment_id, operator_id: getOperator() }),
          { errorPrefix: 'Đã chuyển mixer nhưng không đánh dấu được chương trình: ' });
        if (p) { program = p; renderSummary(); renderList(); }
      }
    }

    $('[data-add]', root).addEventListener('click', () => {
      if (!addSel.value) return;
      if (items.length >= (program?.max_items || 60)) { toast('Chương trình đã đủ số phần tối đa.', 'warn'); return; }
      items.push({ id: null, segment_id: addSel.value, title: '', note: '' });
      markDirty(); renderList();
    });

    $('[data-save]', root).addEventListener('click', async (e) => {
      const p = await withLoading(e.currentTarget, () => api.put('/api/v1/program', { items, operator_id: getOperator() }),
        { errorPrefix: 'Không lưu được: ' });
      if (!p) return;
      toast('Đã lưu chương trình lễ.', 'ok');
      program = p;
      items = p.items.map(({ id, segment_id, title, note }) => ({ id, segment_id, title, note }));
      markDirty(false); renderSummary(); renderList();
    });

    $('[data-restart]', root).addEventListener('click', async (e) => {
      const p = await withLoading(e.currentTarget, () => api.post('/api/v1/program/reset', { operator_id: getOperator() }));
      if (p) { program = p; toast('Đã đặt lại: chưa bắt đầu phần nào. Mixer không thay đổi.', 'info'); renderSummary(); renderList(); }
    });

    $('[data-default]', root).addEventListener('click', async (e) => {
      const ok = await confirmDialog({ title: 'Dùng chương trình mẫu?', message: 'Chương trình đã lưu sẽ bị thay bằng chương trình mẫu. Mixer không thay đổi.', confirmText: 'Dùng chương trình mẫu', danger: true });
      if (!ok) return;
      const p = await withLoading(e.currentTarget, () => api.post('/api/v1/program/restore-default', { operator_id: getOperator() }));
      if (p) { toast('Đã chuyển về chương trình mẫu.', 'ok'); load(); }
    });

    // Detector status — read-only.
    async function loadDetect() {
      if (document.hidden || !alive) return;
      let d;
      try { d = await api.get('/api/v1/segment-suggestion'); } catch (e) { detectBox.innerHTML = errorBox(e); return; }
      if (!alive) return;
      const s = d.suggestion;
      const scores = (d.scores || []).slice(0, 4);
      detectBox.innerHTML = `
        ${s ? callout('info', `<strong>Gợi ý: ${esc(s.name)}</strong> (độ khớp ${fmt.pct(s.confidence)}). ${esc(s.reason_vi)}`, 'eye')
            : `<p class="small muted">${esc(d.reason || 'Chưa có gợi ý.')}</p>`}
        ${(d.active_channels || []).length ? `<div class="row mt-8" style="flex-wrap:wrap;gap:6px">${d.active_channels.map(c =>
          `<span class="badge badge-ok">${String(c.channel).padStart(2, '0')} · ${esc(c.name)}</span>`).join('')}</div>` : ''}
        ${scores.length ? `<p class="tiny muted mt-8">Độ khớp: ${scores.map(x => `${esc(x.name)} ${fmt.pct(x.score)}`).join(' · ')}</p>` : ''}
        <p class="tiny muted mt-8">Giới hạn: meter X32 đo trước nút Mute nên micro đã tắt vẫn có tiếng lọt; máy so mức tương đối giữa các kênh.
          Không phân biệt được hai tiết mục mở cùng một bộ micro, và không đoán khi im lặng.</p>`;
    }

    load();
    loadDetect();
    const timer = setInterval(loadDetect, 2000);
    const beforeUnload = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', beforeUnload);
    return () => { alive = false; clearInterval(timer); window.removeEventListener('beforeunload', beforeUnload); };
  },
};
