// Tiết mục (technical page): create / edit / save service segments.
// A segment = which microphones are ON or MUTED for one part of the service.
// Editing here never touches the mixer; only "Chuyển sang" (with preview + confirm) does.

import { api, getOperator } from '../api.js';
import { $, $$, esc, icon, pageHead, card, callout, openDialog, confirmDialog, toast, withLoading, loadingRows, errorBox, fmt } from '../ui.js';
import { SEGMENT_ICONS, switchToSegment, renderSegmentBar } from '../segments.js';

const ICON_LABEL = { mic: 'Micro', users: 'Nhóm', church: 'Nhà thờ', headphones: 'Đơn ca', volume: 'Loa', disc: 'Nhạc', broadcast: 'Thông báo', hand: 'Cầu nguyện', sliders: 'Mixer', wave: 'Sóng' };

export default {
  mount(root, ctx) {
    let alive = true;
    let data = null;       // {segments, active_id, talkback_channel}
    let channels = [];     // church channel map
    let barCleanup = null;

    root.innerHTML = `
      ${pageHead('Tiết mục', 'Mỗi tiết mục lưu micro nào BẬT, micro nào TẮT. Người không chuyên chỉ cần bấm tên tiết mục để chuyển. Không thay đổi âm lượng (fader).',
        `<button class="btn" data-reset>${icon('refresh')}Khôi phục mặc định</button>
         <button class="btn btn-primary" data-new>${icon('plus')}Tiết mục mới</button>`)}
      ${card({ title: 'Chuyển nhanh', sub: 'Bấm để xem trước và chuyển. Ô xanh = tiết mục đang khớp với mixer.', body: '<div data-bar></div>' })}
      <div class="mt-16">${callout('info', `<strong>Cách lưu nhanh:</strong> chỉnh bật/tắt micro trên mixer cho đúng một tiết mục (ví dụ lúc Mục sư giảng), rồi bấm <strong>“Lưu từ mixer”</strong> ở tiết mục đó.
        Kênh Talkback ban nhạc (DL16 #11) không bao giờ thuộc tiết mục.`)}</div>
      <div class="stack mt-16" data-list>${loadingRows(4)}</div>`;

    const list = $('[data-list]', root);

    const mountBar = () => {
      if (barCleanup) barCleanup();
      barCleanup = renderSegmentBar($('[data-bar]', root), { onChanged: load });
    };

    async function load() {
      try {
        const [segs, chans] = await Promise.all([api.get('/api/v1/segments'), api.get('/api/v1/config/church-channels')]);
        if (!alive) return;
        data = segs;
        channels = Array.isArray(chans) ? chans : (chans.channels || []);
        render();
      } catch (e) {
        if (alive) list.innerHTML = errorBox(e);
      }
    }

    const chName = (n) => channels.find(c => +c.channel === +n)?.name || `Kênh ${n}`;

    function render() {
      const segs = data.segments || [];
      if (!segs.length) { list.innerHTML = callout('warn', 'Chưa có tiết mục. Bấm "Tiết mục mới" hoặc "Khôi phục mặc định".'); return; }
      list.innerHTML = segs.map(s => {
        const on = Object.entries(s.channels || {}).filter(([, v]) => +v === 1).map(([k]) => +k);
        const off = Object.entries(s.channels || {}).filter(([, v]) => +v === 0).map(([k]) => +k);
        const active = s.id === data.active_id;
        return `
          <section class="card ${active ? 'ok' : ''}" data-seg="${esc(s.id)}">
            <header class="card-head">
              <span class="${active ? 'ok-text' : 'muted'}">${icon(SEGMENT_ICONS.includes(s.icon) ? s.icon : 'mic', 'icon-lg')}</span>
              <h3>${esc(s.name)} ${active ? '<span class="badge badge-ok">Đang khớp mixer</span>' : ''}
                <span class="card-sub">${esc(s.description || '')}</span></h3>
              <button class="btn btn-primary btn-sm" data-act="switch">${icon('arrowRight', 'icon-sm')}Chuyển sang</button>
            </header>
            <div class="card-body">
              <div class="grid-2">
                <div><div class="small strong ok-text">${icon('mic', 'icon-sm')} BẬT (${on.length})</div>
                  <div class="row mt-8">${on.length ? on.map(n => `<span class="badge badge-ok">${String(n).padStart(2, '0')} · ${esc(chName(n))}</span>`).join('') : '<span class="small muted">Không có</span>'}</div></div>
                <div><div class="small strong bad-text">${icon('micOff', 'icon-sm')} TẮT (${off.length})</div>
                  <div class="row mt-8">${off.length ? off.map(n => `<span class="badge">${String(n).padStart(2, '0')} · ${esc(chName(n))}</span>`).join('') : '<span class="small muted">Không có</span>'}</div></div>
              </div>
              <p class="tiny muted mt-16">Các kênh không liệt kê sẽ được giữ nguyên. Sửa lần cuối: ${esc(s.updated_by || '—')} · ${fmt.time(s.updated_at)}</p>
            </div>
            <footer class="card-foot">
              <button class="btn btn-sm" data-act="capture">${icon('download', 'icon-sm')}Lưu từ mixer</button>
              <button class="btn btn-sm" data-act="edit">${icon('edit', 'icon-sm')}Sửa</button>
              <button class="btn btn-sm btn-ghost" data-act="delete">${icon('trash', 'icon-sm')}Xóa</button>
            </footer>
          </section>`;
      }).join('');
    }

    list.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-act]');
      if (!btn) return;
      const seg = data.segments.find(s => s.id === btn.closest('[data-seg]').dataset.seg);
      const act = btn.dataset.act;
      if (act === 'switch') {
        if (await switchToSegment(seg)) { await load(); mountBar(); }
      } else if (act === 'capture') {
        const ok = await confirmDialog({
          title: `Lưu trạng thái mixer vào “${esc(seg.name)}”?`,
          message: `Trạng thái bật/tắt hiện tại trên mixer sẽ được lưu cho ${Object.keys(seg.channels || {}).length || 'các'} kênh của tiết mục này.
            Thao tác này <strong>chỉ đọc mixer</strong>, không thay đổi gì trên bàn.`,
          confirmText: 'Lưu',
        });
        if (!ok) return;
        const res = await withLoading(btn, () => api.post(`/api/v1/segments/${encodeURIComponent(seg.id)}/capture`, { operator_id: getOperator() }),
          { errorPrefix: 'Không lưu được: ' });
        if (res) { toast(`Đã lưu “${seg.name}” từ mixer.`, 'ok'); await load(); mountBar(); }
      } else if (act === 'edit') {
        openEditor(seg);
      } else if (act === 'delete') {
        const ok = await confirmDialog({ title: `Xóa tiết mục “${esc(seg.name)}”?`, message: 'Chỉ xóa cấu hình đã lưu, không ảnh hưởng mixer.', confirmText: 'Xóa', danger: true });
        if (!ok) return;
        const res = await withLoading(btn, () => api.del(`/api/v1/segments/${encodeURIComponent(seg.id)}`), { errorPrefix: 'Không xóa được: ' });
        if (res) { toast('Đã xóa tiết mục.', 'ok'); await load(); mountBar(); }
      }
    });

    function openEditor(seg) {
      const isNew = !seg;
      const tb = data?.talkback_channel;
      const states = { ...(seg?.channels || {}) };
      const body = document.createElement('div');
      body.className = 'stack';
      const chRows = channels.filter(c => +c.channel !== tb);
      body.innerHTML = `
        <div class="form-grid">
          <div class="field"><label>Tên tiết mục</label><input class="input" name="name" maxlength="60" value="${esc(seg?.name || '')}" placeholder="Ví dụ: Lễ Thiếu Nhi" autofocus></div>
          <div class="field"><label>Biểu tượng</label><select class="select" name="icon">
            ${SEGMENT_ICONS.map(i => `<option value="${i}" ${i === (seg?.icon || 'mic') ? 'selected' : ''}>${ICON_LABEL[i] || i}</option>`).join('')}</select></div>
        </div>
        <div class="field"><label>Mô tả cho người không chuyên</label><input class="input" name="description" maxlength="300" value="${esc(seg?.description || '')}" placeholder="Ví dụ: Chỉ mở micro Mục sư"></div>
        <div>
          <div class="row-between"><span class="label">Trạng thái từng kênh</span>
            <span class="row"><button class="btn btn-sm" type="button" data-all="1">Tất cả: Bật</button><button class="btn btn-sm" type="button" data-all="0">Tất cả: Tắt</button><button class="btn btn-sm" type="button" data-all="">Tất cả: Giữ nguyên</button></span></div>
          <p class="hint mt-8">“Giữ nguyên” = tiết mục không động tới kênh đó. Talkback (kênh ${esc(tb)}) bị khóa.</p>
          <div class="table-wrap mt-8" style="max-height:46vh;overflow:auto"><table class="table">
            <thead><tr><th>Kênh</th><th>Tên</th><th>Trong tiết mục này</th></tr></thead>
            <tbody>${chRows.map(c => `
              <tr><td class="mono">${String(c.channel).padStart(2, '0')}</td><td>${esc(c.name)}</td>
                <td><div class="segmented" data-ch="${c.channel}">
                  <button type="button" data-v="1">Bật</button><button type="button" data-v="0">Tắt</button><button type="button" data-v="">Giữ nguyên</button>
                </div></td></tr>`).join('')}</tbody></table></div>
        </div>`;

      const paint = () => $$('[data-ch]', body).forEach(g => {
        const v = states[g.dataset.ch];
        $$('button', g).forEach(b => b.classList.toggle('active', (v === undefined ? '' : String(v)) === b.dataset.v));
      });
      $$('[data-ch] button', body).forEach(b => b.addEventListener('click', () => {
        const ch = b.closest('[data-ch]').dataset.ch;
        if (b.dataset.v === '') delete states[ch]; else states[ch] = +b.dataset.v;
        paint();
      }));
      $$('[data-all]', body).forEach(b => b.addEventListener('click', () => {
        chRows.forEach(c => { if (b.dataset.all === '') delete states[String(c.channel)]; else states[String(c.channel)] = +b.dataset.all; });
        paint();
      }));
      paint();

      openDialog({
        title: isNew ? 'Tiết mục mới' : `Sửa tiết mục: ${esc(seg.name)}`,
        body, wide: true,
        actions: [
          { label: 'Hủy', kind: 'ghost' },
          { label: isNew ? 'Tạo tiết mục' : 'Lưu thay đổi', kind: 'primary', onClick: async (close, btn) => {
            const payload = {
              name: $('[name=name]', body).value, description: $('[name=description]', body).value,
              icon: $('[name=icon]', body).value, channels: states, operator_id: getOperator(),
            };
            const res = await withLoading(btn, () => isNew
              ? api.post('/api/v1/segments', payload)
              : api.put(`/api/v1/segments/${encodeURIComponent(seg.id)}`, payload), { errorPrefix: 'Không lưu được: ' });
            if (res) { toast(isNew ? 'Đã tạo tiết mục.' : 'Đã lưu tiết mục.', 'ok'); close(); await load(); mountBar(); }
          } },
        ],
      });
    }

    $('[data-new]', root).addEventListener('click', () => openEditor(null));
    $('[data-reset]', root).addEventListener('click', async (e) => {
      const ok = await confirmDialog({
        title: 'Khôi phục tiết mục mặc định?',
        message: 'Mọi tiết mục đã sửa hoặc tạo thêm sẽ bị thay bằng bộ mặc định (dựng từ sơ đồ kênh). Không ảnh hưởng mixer.',
        confirmText: 'Khôi phục', danger: true,
      });
      if (!ok) return;
      const res = await withLoading(e.currentTarget, () => api.post('/api/v1/segments/reset-defaults'), { errorPrefix: 'Không khôi phục được: ' });
      if (res) { toast('Đã khôi phục bộ tiết mục mặc định.', 'ok'); await load(); mountBar(); }
    });

    mountBar();
    load().then(() => { if (alive && ctx.params.get('new')) openEditor(null); });

    return () => { alive = false; if (barCleanup) barCleanup(); };
  },
};
