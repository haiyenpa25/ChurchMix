// Trợ lý AI: hỏi đáp tiếng Việt dựa trên tài liệu âm học + trạng thái mixer hiện tại.
// Chỉ giải thích và hướng dẫn — không bao giờ tự gửi lệnh xuống mixer.

import { api } from '../api.js';
import { $, esc, icon, pageHead, renderMarkdown, callout, withLoading } from '../ui.js';

const SUGGESTIONS = [
  'Làm sao để tiếng Mục sư rõ lời hơn?',
  'Đang bị hú, xử lý an toàn thế nào?',
  'Vì sao Talkback DL16 #11 không được ra loa chính?',
  'Gain staging trước lễ cần kiểm tra gì?',
  'Livestream bị nhỏ thì chỉnh ở đâu?',
];

export function renderCopilotBox(root, { compact = false } = {}) {
  root.innerHTML = `
    <div class="stack">
      <div class="row">${SUGGESTIONS.slice(0, compact ? 3 : SUGGESTIONS.length).map(s => `<button class="btn btn-sm" data-q="${esc(s)}">${esc(s)}</button>`).join('')}</div>
      <form class="row" data-form style="flex-wrap:nowrap">
        <input class="input" name="q" placeholder="Nhập câu hỏi về âm thanh…" autocomplete="off">
        <label class="check small nowrap" title="Kèm trạng thái mixer hiện tại (hú, Talkback, STOP)"><input type="checkbox" name="ctx" checked>Dùng dữ liệu trực tiếp</label>
        <button class="btn btn-primary" type="submit">${icon('send')}Hỏi</button>
      </form>
      <div data-answers class="stack"></div>
    </div>`;

  const form = $('[data-form]', root);
  const answers = $('[data-answers]', root);

  async function ask(question) {
    const q = question.trim();
    if (!q) return;
    form.q.value = q;
    const btn = $('button[type=submit]', form);
    const data = await withLoading(btn, () => api.post('/api/v1/copilot/ask', { question: q, include_live_context: form.ctx.checked }),
      { errorPrefix: 'Trợ lý không trả lời được: ' });
    if (!data) return;
    const item = document.createElement('article');
    item.className = 'card';
    item.innerHTML = `
      <header class="card-head"><h3>${icon('bot')} ${esc(q)}</h3>
        ${data.category ? `<span class="badge">${esc(data.category)}</span>` : ''}</header>
      <div class="card-body stack-sm">
        ${renderMarkdown(data.answer || '')}
        ${data.citations?.length ? `<div class="small muted">Nguồn: ${data.citations.map(c => esc(typeof c === 'string' ? c : (c.title || c.id || JSON.stringify(c)))).join(' · ')}</div>` : ''}
        ${data.is_authoritative === false ? callout('warn', 'Không tìm thấy tài liệu khớp chính xác — câu trả lời mang tính tham khảo chung.') : ''}
        ${data.disclaimer ? `<div class="small muted">${esc(data.disclaimer)}</div>` : ''}
      </div>`;
    answers.prepend(item);
    while (answers.children.length > (compact ? 1 : 10)) answers.lastElementChild.remove();
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); ask(form.q.value); });
  root.querySelectorAll('[data-q]').forEach(b => b.addEventListener('click', () => ask(b.dataset.q)));
}

export default {
  mount(root) {
    root.innerHTML = `
      ${pageHead('Trợ lý AI', 'Hỏi bằng tiếng Việt về âm thanh nhà thờ. Trợ lý chỉ giải thích và gợi ý — mọi thay đổi trên mixer vẫn do bạn duyệt.')}
      <div class="card"><div class="card-body" data-box></div></div>`;
    renderCopilotBox($('[data-box]', root));
    return () => {};
  },
};
