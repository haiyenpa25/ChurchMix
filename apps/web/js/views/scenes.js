// Scene & sao lưu — Scene Vault (snapshots, .scn download, compare, USB import)
// plus quick export of the current mixer state as a USB .scn file.
// Nothing on this page writes to the mixer: backups only READ the mixer,
// imports only land in the vault. Scene recall on the X32 stays a manual,
// admin-only step on the console itself.

import { $, esc, icon, badge, card, callout, pageHead, emptyState, loadingRows, errorBox, withLoading, toast, openDialog, confirmDialog, downloadText, fmt } from '../ui.js';
import { api, getOperator } from '../api.js';

function shortSha(sha) {
  return sha ? String(sha).slice(0, 8) : '—';
}

function safeFileName(name) {
  return String(name || '').trim().replace(/[^\p{L}\p{N}_-]+/gu, '_').replace(/^_+|_+$/g, '') || 'ChurchMix_Sunday';
}

export default {
  mount(root) {
    let alive = true;
    let snapshots = [];
    const selected = new Set();
    let pendingScn = { content: '', fileName: '', report: null };

    root.innerHTML = `
      ${pageHead('Scene &amp; sao lưu',
        'Lưu lại toàn bộ thiết lập bàn trộn để có thể so sánh, phục hồi hoặc chép sang bàn X32 qua USB.',
        `<button class="btn" data-act="export-now">${icon('usb')}Xuất scene hiện tại (.scn)</button>
         <button class="btn btn-primary" data-act="create">${icon('plus')}Tạo bản sao lưu</button>`)}
      <div class="stack">
        ${callout('info', `Trang này <strong>không ghi gì xuống mixer</strong>. Tạo bản sao lưu chỉ đọc trạng thái hiện tại;
          nạp file .scn chỉ lưu vào kho. Việc gọi lại (recall) scene trên bàn X32 là thao tác thủ công dành cho quản trị viên.`)}
        ${card({
          title: 'Kho bản sao lưu',
          sub: 'Chọn đúng 2 bản để so sánh sự khác nhau',
          actions: `<div class="row">
              <button class="btn btn-sm" data-act="compare" disabled>${icon('compare')}So sánh 2 bản đã chọn</button>
              <button class="btn btn-sm btn-ghost btn-icon" data-act="reload" title="Làm mới" aria-label="Làm mới">${icon('refresh')}</button>
            </div>`,
          body: `<div data-slot="list">${loadingRows(4)}</div>`,
        })}
        <div class="grid-2">
          ${card({
            title: 'Nạp file scene (.scn) từ USB hoặc máy tính',
            sub: 'Kiểm tra an toàn trước, rồi mới lưu vào kho',
            body: `
              <div class="stack-sm">
                <div class="field">
                  <label for="scnFile">Chọn file .scn</label>
                  <input id="scnFile" class="input" type="file" accept=".scn,.txt" style="padding-top:6px">
                  <span class="hint">Ngay khi chọn file, hệ thống sẽ kiểm tra Talkback kênh 11 và các thông số rủi ro.</span>
                </div>
                <div data-slot="audit"></div>
              </div>`,
            foot: `<button class="btn btn-primary" data-act="import" disabled>${icon('shieldCheck')}Nạp vào kho</button>`,
          })}
          ${card({
            title: 'Chép scene sang bàn X32 qua USB',
            sub: 'Dùng khi muốn mang thiết lập hiện tại lên bàn trộn',
            body: `
              <ol class="text-2" style="margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px">
                <li>Bấm <strong>Xuất scene hiện tại (.scn)</strong> ở trên, hoặc nút <strong>Tải .scn</strong> ở một bản sao lưu trong kho.</li>
                <li>Chép file vào <strong>thư mục gốc</strong> của USB (định dạng FAT32).</li>
                <li>Cắm USB vào <strong>cổng USB mặt trước</strong> bàn X32 / M32.</li>
                <li>Trên bàn: bấm <strong>VIEW</strong> ở khu vực <strong>SCENES</strong> (Show Control), chọn <strong>UTILITY</strong> → <strong>Import</strong> và chọn file trên USB.
                  <div class="small muted">Tên menu có thể khác đôi chút tùy phiên bản firmware — xem hướng dẫn sử dụng X32.</div></li>
                <li>Chỉ <strong>Load</strong> scene khi đã thống nhất với quản trị viên, ngoài giờ lễ. Sau khi nạp, kiểm tra lại kênh 11 (Talkback) chỉ đi P16, không ra loa FOH.</li>
              </ol>`,
            foot: `<button class="btn" data-act="export-now">${icon('download')}Xuất scene hiện tại (.scn)</button>`,
          })}
        </div>
      </div>`;

    const listEl = $('[data-slot="list"]', root);
    const auditEl = $('[data-slot="audit"]', root);
    const compareBtn = $('[data-act="compare"]', root);
    const importBtn = $('[data-act="import"]', root);
    const fileInput = $('#scnFile', root);

    // ---------- List ----------
    async function loadSnapshots() {
      listEl.innerHTML = loadingRows(4);
      try {
        const data = await api.get('/api/v1/vault/snapshots');
        if (!alive) return;
        snapshots = data?.snapshots || [];
        // Drop selections that no longer exist.
        [...selected].forEach(id => { if (!snapshots.some(s => s.id === id)) selected.delete(id); });
        renderList();
      } catch (e) {
        if (alive) listEl.innerHTML = errorBox(e);
      }
    }

    function renderList() {
      updateCompareBtn();
      if (!snapshots.length) {
        listEl.innerHTML = emptyState('Chưa có bản sao lưu nào. Bấm “Tạo bản sao lưu” để lưu thiết lập hiện tại của bàn trộn.');
        return;
      }
      listEl.innerHTML = `
        <div class="table-wrap"><table class="table">
          <thead><tr>
            <th style="width:36px" aria-label="Chọn"></th>
            <th>Tên</th><th>Ghi chú</th><th>Người lưu</th><th>Thời gian</th><th>Mã kiểm tra</th><th class="right">Thao tác</th>
          </tr></thead>
          <tbody>${snapshots.map(s => `
            <tr>
              <td><label class="check"><input type="checkbox" data-sel="${s.id}" ${selected.has(s.id) ? 'checked' : ''} aria-label="Chọn bản #${s.id}"></label></td>
              <td><div class="strong">${esc(s.name)}</div><div class="tiny muted mono">#${esc(s.id)}</div></td>
              <td class="text-2">${s.note ? esc(s.note) : '<span class="muted">—</span>'}</td>
              <td>${esc(s.author || '—')}</td>
              <td class="nowrap small">${esc(s.iso_time || fmt.time(s.captured_at))}</td>
              <td><span class="mono small" title="SHA-256: ${esc(s.sha256)}">${esc(shortSha(s.sha256))}</span></td>
              <td class="right nowrap">
                <button class="btn btn-sm" data-download="${s.id}" title="Tải file .scn để chép vào USB">${icon('download')}Tải .scn</button>
                <button class="btn btn-sm btn-ghost btn-icon" data-delete="${s.id}" title="Xóa bản sao lưu" aria-label="Xóa bản sao lưu #${s.id}">${icon('trash')}</button>
              </td>
            </tr>`).join('')}
          </tbody>
        </table></div>`;
    }

    function updateCompareBtn() {
      compareBtn.disabled = selected.size !== 2;
      compareBtn.innerHTML = `${icon('compare')}So sánh 2 bản đã chọn${selected.size ? ` (${selected.size}/2)` : ''}`;
    }

    listEl.addEventListener('change', (e) => {
      const cb = e.target.closest('[data-sel]');
      if (!cb) return;
      const id = Number(cb.dataset.sel);
      if (cb.checked) {
        if (selected.size >= 2) {
          cb.checked = false;
          toast('Chỉ so sánh được 2 bản một lúc. Bỏ chọn một bản trước.', 'warn');
          return;
        }
        selected.add(id);
      } else {
        selected.delete(id);
      }
      updateCompareBtn();
    });

    listEl.addEventListener('click', async (e) => {
      const dl = e.target.closest('[data-download]');
      const del = e.target.closest('[data-delete]');
      if (dl) {
        const id = Number(dl.dataset.download);
        await withLoading(dl, async () => {
          const data = await api.get(`/api/v1/vault/snapshots/${id}/download-scn`);
          downloadText(data.filename || `ChurchMix_Scene_${id}.scn`, data.content || '');
          toast(`Đã tải ${data.filename || 'file .scn'}. Chép vào USB để nạp lên bàn X32.`, 'ok');
        }, { errorPrefix: 'Không tạo được file .scn: ' });
      } else if (del) {
        const id = Number(del.dataset.delete);
        const snap = snapshots.find(s => s.id === id);
        const ok = await confirmDialog({
          title: 'Xóa bản sao lưu?',
          message: `Bản <strong>${esc(snap?.name || `#${id}`)}</strong> (#${id}) sẽ bị xóa vĩnh viễn khỏi kho và không thể khôi phục.<br>
            Bàn trộn không bị ảnh hưởng.`,
          confirmText: 'Xóa',
          danger: true,
        });
        if (!ok) return;
        const res = await withLoading(del, () => api.del(`/api/v1/vault/snapshots/${id}`), { errorPrefix: 'Không xóa được: ' });
        if (res) {
          selected.delete(id);
          toast('Đã xóa bản sao lưu.', 'ok');
          loadSnapshots();
        }
      }
    });

    // ---------- Create backup ----------
    function openCreateDialog() {
      const dlg = openDialog({
        title: 'Tạo bản sao lưu mới',
        body: `
          <div class="stack-sm">
            <p class="text-2">Hệ thống sẽ đọc toàn bộ thiết lập 32 kênh hiện tại của bàn trộn (chỉ đọc), tính mã kiểm tra SHA-256 và kiểm tra Talkback kênh 11.</p>
            <div class="field"><label for="vName">Tên bản sao lưu</label>
              <input id="vName" class="input" placeholder="Ví dụ: Lễ sáng Chúa Nhật" autofocus></div>
            <div class="field"><label for="vAuthor">Người lưu</label>
              <input id="vAuthor" class="input" value="${esc(getOperator())}"></div>
            <div class="field"><label for="vNote">Ghi chú (không bắt buộc)</label>
              <input id="vNote" class="input" placeholder="Ví dụ: Sau soundcheck ca đoàn"></div>
          </div>`,
        actions: [
          { label: 'Hủy', kind: 'ghost' },
          {
            label: `${icon('archive')}Lưu vào kho`, kind: 'primary',
            onClick: async (close, btn) => {
              const name = $('#vName', dlg.root).value.trim();
              const author = $('#vAuthor', dlg.root).value.trim() || getOperator();
              const note = $('#vNote', dlg.root).value.trim();
              if (!name) { toast('Vui lòng nhập tên cho bản sao lưu.', 'warn'); $('#vName', dlg.root).focus(); return; }
              const data = await withLoading(btn, () => api.post('/api/v1/vault/snapshots', { name, author, note }),
                { errorPrefix: 'Không tạo được bản sao lưu: ' });
              if (!data) return;
              close();
              const b = data.backup || {};
              if (b.talkback_safe === false) {
                toast(`Đã lưu “${name}” (#${b.id}) nhưng CẢNH BÁO: Talkback kênh 11 đang vi phạm cách ly FOH. ${b.talkback_message || ''}`, 'bad', 9000);
              } else {
                toast(`Đã lưu “${name}” (#${b.id}). Talkback kênh 11 an toàn (chỉ P16).`, 'ok');
              }
              loadSnapshots();
            },
          },
        ],
      });
      $('#vName', dlg.root).addEventListener('keydown', (e) => {
        if (e.key === 'Enter') $('.dialog-foot .btn-primary', dlg.root)?.click();
      });
    }

    // ---------- Compare ----------
    async function compareSelected(btn) {
      if (selected.size !== 2) { toast('Hãy chọn đúng 2 bản sao lưu để so sánh.', 'warn'); return; }
      // Keep list order (newest first) so A/B is predictable.
      const [idA, idB] = snapshots.filter(s => selected.has(s.id)).map(s => s.id);
      const diff = await withLoading(btn, () => api.post('/api/v1/vault/snapshots/compare', { snapshot_id_a: idA, snapshot_id_b: idB }),
        { errorPrefix: 'Không so sánh được: ' });
      if (!diff) return;
      const diffs = diff.channel_diffs || [];
      const tbA = diff.talkback_status_a, tbB = diff.talkback_status_b;
      openDialog({
        title: 'So sánh hai bản sao lưu',
        wide: true,
        body: `
          <div class="stack">
            <div class="grid-2">
              <div class="stat"><div class="stat-label">Bản A</div><div class="strong">${esc(diff.label_a)}</div>
                ${tbA ? `<div class="mt-8">${tbA.safe ? badge('Talkback an toàn', 'ok') : badge('Talkback vi phạm', 'bad')}</div>` : ''}</div>
              <div class="stat"><div class="stat-label">Bản B</div><div class="strong">${esc(diff.label_b)}</div>
                ${tbB ? `<div class="mt-8">${tbB.safe ? badge('Talkback an toàn', 'ok') : badge('Talkback vi phạm', 'bad')}</div>` : ''}</div>
            </div>
            ${callout(diff.total_channels_changed ? 'info' : 'ok',
              `<strong>${esc(diff.total_channels_changed ?? diffs.length)} kênh có thay đổi.</strong><div class="small text-2">${esc(diff.summary_vi || '')}</div>`)}
            ${diffs.length ? `
              <div class="table-wrap"><table class="table">
                <thead><tr><th>Kênh</th><th>Thay đổi</th></tr></thead>
                <tbody>${diffs.map(cd => `
                  <tr>
                    <td class="nowrap" style="vertical-align:top">
                      <div class="strong">${fmt.ch(cd.channel)}</div>
                      <div class="small muted">${esc(cd.name_a || '')}</div>
                      ${cd.is_talkback ? `<div class="mt-8">${badge('Talkback · khóa', 'warn')}</div>` : ''}
                    </td>
                    <td><ul class="small text-2" style="margin:0;padding-left:18px">${(cd.changes || []).map(c => `<li>${esc(c)}</li>`).join('')}</ul></td>
                  </tr>`).join('')}
                </tbody>
              </table></div>` : emptyState('Hai bản sao lưu giống hệt nhau về thông số.')}
          </div>`,
        actions: [{ label: 'Đóng', kind: 'primary' }],
      });
    }

    // ---------- Export current mixer ----------
    function exportNow() {
      const dlg = openDialog({
        title: 'Xuất scene hiện tại ra file .scn',
        body: `
          <div class="stack-sm">
            <p class="text-2">Đọc thiết lập hiện tại của bàn trộn và tạo file <span class="mono">.scn</span> chuẩn X32 để chép vào USB.</p>
            <div class="field"><label for="exName">Tên scene</label>
              <input id="exName" class="input" value="ChurchMix_Sunday" autofocus>
              <span class="hint">Nên dùng chữ không dấu, không khoảng trắng để bàn X32 hiển thị đúng.</span></div>
          </div>`,
        actions: [
          { label: 'Hủy', kind: 'ghost' },
          {
            label: `${icon('download')}Tải file .scn`, kind: 'primary',
            onClick: async (close, b) => {
              const name = safeFileName($('#exName', dlg.root).value);
              const data = await withLoading(b, () => api.get(`/api/v1/scenes/export?name=${encodeURIComponent(name)}`),
                { errorPrefix: 'Không xuất được file scene: ' });
              if (!data) return;
              downloadText(data.filename || `${name}.scn`, data.content || '');
              close();
              toast(`Đã xuất ${data.filename} (mã ${shortSha(data.sha256)}). Làm theo hướng dẫn để nạp qua cổng USB mặt trước.`, 'ok', 7000);
            },
          },
        ],
      });
    }

    // ---------- USB .scn import ----------
    function resetImport() {
      pendingScn = { content: '', fileName: '', report: null };
      fileInput.value = '';
      auditEl.innerHTML = '';
      importBtn.disabled = true;
    }

    fileInput.addEventListener('change', () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) { resetImport(); return; }
      pendingScn = { content: '', fileName: file.name, report: null };
      importBtn.disabled = true;
      auditEl.innerHTML = loadingRows(2);
      const reader = new FileReader();
      reader.onload = async () => {
        if (!alive) return;
        pendingScn.content = String(reader.result || '');
        await auditPending();
      };
      reader.onerror = () => {
        if (alive) auditEl.innerHTML = callout('bad', 'Không đọc được file. Hãy thử chọn lại.');
      };
      reader.readAsText(file);
    });

    async function auditPending() {
      if (!pendingScn.content.trim()) {
        auditEl.innerHTML = callout('bad', 'File trống — không có nội dung scene để kiểm tra.');
        return;
      }
      auditEl.innerHTML = `<div class="small muted">Đang kiểm tra an toàn file…</div>${loadingRows(2)}`;
      try {
        const report = await api.post('/api/v1/vault/audit-scn', { scn_content: pendingScn.content });
        if (!alive) return;
        pendingScn.report = report;
        const violations = report.violations || [];
        const warnings = report.warnings || [];
        auditEl.innerHTML = `
          <div class="stack-sm">
            <div class="row-between">
              <div><span class="strong">${esc(report.scene_name || 'Scene')}</span> <span class="small muted mono">${esc(pendingScn.fileName)}</span></div>
              ${report.invariant_passed ? badge('Talkback an toàn', 'ok') : badge('Vi phạm Talkback', 'bad')}
            </div>
            ${report.summary_vi ? `<p class="small text-2">${esc(report.summary_vi)}</p>` : ''}
            ${violations.length ? callout('bad', `<strong>Vấn đề nghiêm trọng:</strong>
              <ul class="small" style="margin:4px 0 0;padding-left:18px">${violations.map(v => `<li>${esc(v)}</li>`).join('')}</ul>
              <div class="small mt-8">Khi nạp vào kho, hệ thống sẽ <strong>tự động vá</strong> (đóng đường gửi vi phạm) trước khi lưu.</div>`) : ''}
            ${warnings.length ? callout('warn', `<strong>Lưu ý:</strong>
              <ul class="small" style="margin:4px 0 0;padding-left:18px;max-height:140px;overflow:auto">${warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>`) : ''}
            ${!violations.length && !warnings.length ? callout('ok', 'Không phát hiện vấn đề. Có thể nạp vào kho.') : ''}
          </div>`;
        importBtn.disabled = false;
      } catch (e) {
        if (!alive) return;
        auditEl.innerHTML = callout('bad', `<strong>File không hợp lệ hoặc không phân tích được.</strong><div class="small">${esc(e.message)}</div>`);
        importBtn.disabled = true;
      }
    }

    async function importPending() {
      if (!pendingScn.content) { toast('Hãy chọn một file .scn trước.', 'warn'); return; }
      const r = pendingScn.report || {};
      const nViol = (r.violations || []).length;
      const dlg = openDialog({
        title: 'Nạp scene vào kho?',
        body: `
          <div class="stack-sm">
            <p class="text-2">File <span class="mono">${esc(pendingScn.fileName)}</span> sẽ được lưu thành một bản sao lưu mới trong kho.
              <strong>Bàn trộn không bị thay đổi.</strong></p>
            ${nViol ? callout('warn', `Phát hiện <strong>${nViol}</strong> vi phạm an toàn. Hệ thống sẽ tự động vá trước khi lưu — bản trong kho sẽ khác file gốc.`) : ''}
            <div class="field"><label for="impNote">Ghi chú (không bắt buộc)</label>
              <input id="impNote" class="input" value="${esc(`Nạp từ ${pendingScn.fileName}`)}" autofocus></div>
          </div>`,
        actions: [
          { label: 'Hủy', kind: 'ghost' },
          {
            label: `${icon('upload')}Nạp vào kho`, kind: 'primary',
            onClick: async (close, b) => {
              const note = $('#impNote', dlg.root).value.trim();
              const data = await withLoading(b, () => api.post('/api/v1/vault/import-scn', {
                scn_content: pendingScn.content,
                author: getOperator(),
                note,
                auto_sanitize: true,
              }), { errorPrefix: 'Không nạp được file .scn: ' });
              if (!data) return;
              close();
              showImportResult(data);
              resetImport();
              loadSnapshots();
            },
          },
        ],
      });
    }

    function showImportResult(data) {
      const vb = data.vault_backup || {};
      const patches = data.patches_applied || [];
      openDialog({
        title: 'Đã nạp scene vào kho',
        body: `
          <div class="stack-sm">
            ${callout('ok', `Bản <strong>${esc(vb.name || 'Scene')}</strong> (#${esc(vb.id)}) đã được lưu an toàn vào kho.`)}
            ${patches.length
              ? callout('warn', `<strong>Đã áp dụng ${patches.length} bản vá an toàn:</strong>
                  <ul class="small" style="margin:4px 0 0;padding-left:18px">${patches.map(p => `<li>${esc(p)}</li>`).join('')}</ul>`)
              : '<p class="small text-2">Scene đạt chuẩn an toàn, không cần vá.</p>'}
          </div>`,
        actions: [{ label: 'Đóng', kind: 'primary' }],
      });
    }

    // ---------- Wiring ----------
    root.addEventListener('click', (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.dataset.act;
      if (act === 'create') openCreateDialog();
      else if (act === 'reload') loadSnapshots();
      else if (act === 'compare') compareSelected(b);
      else if (act === 'export-now') exportNow();
      else if (act === 'import') importPending();
    });

    loadSnapshots();

    return () => { alive = false; };
  },
};
