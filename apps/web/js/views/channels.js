// Sơ đồ kênh — the church's 32-channel map (name, acoustic role, notes).
// This is ChurchMix configuration only: it never writes to the mixer.
// Channel 11 (Band Talkback, DL16 In 11) is permanently locked: P16 only,
// never FOH. The backend forces its role; this page makes it read-only.

import { $, esc, icon, badge, card, callout, pageHead, emptyState, loadingRows, errorBox, withLoading, toast, openDialog, confirmDialog, fmt } from '../ui.js';
import { api } from '../api.js';

const TALKBACK_CH = 11;

const ROLES = [
  { id: 'PASTOR_SPEECH', label: 'Mục sư / giảng luận' },
  { id: 'LEAD_VOCAL_FEMALE', label: 'Nữ đơn ca' },
  { id: 'LEAD_VOCAL_MALE', label: 'Nam đơn ca' },
  { id: 'CHOIR_OVERHEAD', label: 'Ca đoàn' },
  { id: 'ACOUSTIC_GUITAR', label: 'Guitar mộc' },
  { id: 'PIANO_KEYS', label: 'Piano / keyboard' },
  { id: 'BASS_GUITAR', label: 'Guitar bass' },
  { id: 'DRUMS', label: 'Trống / bộ gõ' },
  { id: 'GENERAL_INPUT', label: 'Đường vào chung' },
];
const ROLE_LABEL = Object.fromEntries([...ROLES.map(r => [r.id, r.label]), ['TALKBACK_BAND', 'Talkback ban nhạc']]);
const roleLabel = (id) => ROLE_LABEL[id] || id || '—';

const isLocked = (ch) => ch.channel === TALKBACK_CH || ch.is_protected;

export default {
  mount(root, ctx) {
    let alive = true;
    let channels = [];
    let filter = '';

    root.innerHTML = `
      ${pageHead('Sơ đồ kênh',
        'Đặt tên, vai trò và ghi chú cho 32 kênh của nhà thờ để các trang khác hiểu đúng từng micro, nhạc cụ.',
        `<button class="btn btn-ghost" data-act="reset">${icon('refresh')}Khôi phục mặc định</button>`)}
      <div class="stack">
        ${callout('info', `${icon('lock', 'icon-sm')} <strong>Kênh 11 — Talkback ban nhạc</strong> được khóa cố định: chỉ đi vào tai nghe P16 của ban nhạc,
          không bao giờ ra loa hội trường (FOH). Không thể đổi tên hay vai trò kênh này.
          <div class="small text-2 mt-8">Số kênh ở đây là kênh trên bàn X32 — không nhất thiết trùng số cổng trên stagebox DL16.</div>`)}
        ${card({
          title: '32 kênh của nhà thờ',
          sub: 'Thay đổi chỉ lưu trong ChurchMix, không ghi xuống bàn trộn',
          actions: `<input class="input" style="max-width:220px;height:32px" type="search" placeholder="Tìm tên, vai trò…" data-filter aria-label="Lọc kênh">`,
          body: `<div data-slot="list">${loadingRows(6)}</div>`,
        })}
      </div>`;

    const listEl = $('[data-slot="list"]', root);

    async function load() {
      listEl.innerHTML = loadingRows(6);
      try {
        const data = await api.get('/api/v1/config/church-channels');
        if (!alive) return;
        channels = (data?.channels || []).slice().sort((a, b) => a.channel - b.channel);
        render();
        const want = Number(ctx?.params?.get('ch'));
        if (want) {
          const ch = channels.find(c => c.channel === want);
          if (ch) openEditor(ch);
        }
      } catch (e) {
        if (alive) listEl.innerHTML = errorBox(e);
      }
    }

    function render() {
      const q = filter.trim().toLowerCase();
      const rows = !q ? channels : channels.filter(c =>
        [c.channel, c.name, c.notes, roleLabel(c.role), c.role].some(v => String(v ?? '').toLowerCase().includes(q)));
      if (!channels.length) { listEl.innerHTML = emptyState('Chưa có sơ đồ kênh. Bấm “Khôi phục mặc định” để tạo sơ đồ chuẩn.'); return; }
      if (!rows.length) { listEl.innerHTML = emptyState('Không có kênh nào khớp với từ khóa.'); return; }
      listEl.innerHTML = `
        <div class="table-wrap"><table class="table">
          <thead><tr><th style="width:90px">Kênh</th><th>Tên</th><th>Vai trò</th><th>Ghi chú</th><th class="right" style="width:110px"></th></tr></thead>
          <tbody>${rows.map(c => {
            const locked = isLocked(c);
            return `
            <tr ${locked ? 'style="background:var(--warn-soft)"' : ''}>
              <td class="mono nowrap">${esc(String(c.channel).padStart(2, '0'))}</td>
              <td class="strong">${esc(c.name)}</td>
              <td>${locked ? badge('Chỉ P16 · khóa', 'warn') : esc(roleLabel(c.role))}</td>
              <td class="small text-2">${c.notes ? esc(c.notes) : '<span class="muted">—</span>'}</td>
              <td class="right">
                ${locked
                  ? `<button class="btn btn-sm btn-ghost" data-edit="${c.channel}">${icon('lock')}Xem</button>`
                  : `<button class="btn btn-sm" data-edit="${c.channel}">${icon('edit')}Sửa</button>`}
              </td>
            </tr>`;
          }).join('')}
          </tbody>
        </table></div>`;
    }

    function openEditor(ch) {
      if (isLocked(ch)) {
        openDialog({
          title: `${fmt.ch(ch.channel)} — ${esc(ch.name)}`,
          drawer: true,
          body: `
            <div class="stack">
              ${callout('warn', `<strong>Kênh được bảo vệ, không thể chỉnh sửa.</strong>
                <div class="small mt-8">Đây là micro nói chuyện nội bộ của ban nhạc (DL16 cổng 11). Tín hiệu chỉ được gửi vào tai nghe P16,
                tuyệt đối không ra loa hội trường hay Matrix FOH. Mọi thay đổi định tuyến kênh này đều bị hệ thống chặn.</div>`, 'lock')}
              <dl class="kv">
                <dt>Tên</dt><dd>${esc(ch.name)}</dd>
                <dt>Vai trò</dt><dd>${esc(roleLabel(ch.role))}</dd>
                <dt>Ghi chú</dt><dd>${esc(ch.notes || '—')}</dd>
              </dl>
            </div>`,
          actions: [{ label: 'Đóng', kind: 'primary' }],
        });
        return;
      }

      const knownRole = ROLES.some(r => r.id === ch.role);
      const dlg = openDialog({
        title: `Sửa ${fmt.ch(ch.channel)}`,
        drawer: true,
        body: `
          <div class="stack">
            <div class="field"><label for="chName">Tên kênh</label>
              <input id="chName" class="input" value="${esc(ch.name)}" maxlength="40" autofocus>
              <span class="hint">Tên ngắn gọn, dễ nhận ra khi nhìn nhanh, ví dụ “Mic bục giảng”.</span></div>
            <div class="field"><label for="chRole">Vai trò âm thanh</label>
              <select id="chRole" class="select">
                ${!knownRole ? `<option value="${esc(ch.role)}" selected>${esc(ch.role)}</option>` : ''}
                ${ROLES.map(r => `<option value="${r.id}" ${r.id === ch.role ? 'selected' : ''}>${esc(r.label)}</option>`).join('')}
                <option value="TALKBACK_BAND" disabled>Talkback ban nhạc (chỉ dành cho kênh 11)</option>
              </select>
              <span class="hint">Vai trò giúp trợ lý chọn mẫu EQ, automix và kiểm tra phù hợp cho kênh này.</span></div>
            <div class="field"><label for="chNotes">Ghi chú</label>
              <textarea id="chNotes" class="textarea" rows="3" placeholder="Ví dụ: Micro không dây số 2, pin thay mỗi Chúa Nhật">${esc(ch.notes || '')}</textarea></div>
          </div>`,
        actions: [
          { label: 'Hủy', kind: 'ghost' },
          {
            label: `${icon('check')}Lưu thay đổi`, kind: 'primary',
            onClick: async (close, btn) => {
              const name = $('#chName', dlg.root).value.trim();
              const role = $('#chRole', dlg.root).value;
              const notes = $('#chNotes', dlg.root).value.trim();
              if (!name) { toast('Tên kênh không được để trống.', 'warn'); $('#chName', dlg.root).focus(); return; }
              const res = await withLoading(btn, () => api.post(`/api/v1/config/church-channels/${ch.channel}`, { name, role, notes }),
                { errorPrefix: 'Không lưu được: ' });
              if (!res) return;
              const updated = res.channel || { ...ch, name, role, notes };
              channels = channels.map(c => c.channel === ch.channel ? updated : c);
              render();
              close();
              toast(`Đã lưu ${fmt.ch(ch.channel)}: ${updated.name}.`, 'ok');
            },
          },
        ],
      });
    }

    async function reset(btn) {
      const ok = await confirmDialog({
        title: 'Khôi phục sơ đồ kênh mặc định?',
        message: `Toàn bộ tên, vai trò và ghi chú của 32 kênh sẽ trở về cấu hình chuẩn ban đầu.
          <strong>Mọi tùy chỉnh đã lưu sẽ bị mất</strong> và không thể hoàn tác.<br>
          Bàn trộn không bị thay đổi. Kênh 11 vẫn giữ khóa Talkback.`,
        confirmText: 'Khôi phục',
        danger: true,
      });
      if (!ok) return;
      const res = await withLoading(btn, () => api.post('/api/v1/config/church-channels/reset'), { errorPrefix: 'Không khôi phục được: ' });
      if (!res) return;
      toast('Đã khôi phục sơ đồ 32 kênh về mặc định.', 'ok');
      if (Array.isArray(res.channels)) {
        channels = res.channels.slice().sort((a, b) => a.channel - b.channel);
        render();
      } else {
        load();
      }
    }

    root.addEventListener('click', (e) => {
      const edit = e.target.closest('[data-edit]');
      if (edit) {
        const ch = channels.find(c => c.channel === Number(edit.dataset.edit));
        if (ch) openEditor(ch);
        return;
      }
      const act = e.target.closest('[data-act]');
      if (act?.dataset.act === 'reset') reset(act);
    });
    $('[data-filter]', root).addEventListener('input', (e) => { filter = e.target.value; render(); });

    load();
    return () => { alive = false; };
  },
};
