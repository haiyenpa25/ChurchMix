// App shell: top bar, sidebar, hash router and the Simple / Technical mode switch.

import { ROUTES, routeById } from './routes.js';
import { store } from './store.js';
import { getOperator, setOperator } from './api.js';
import { $, $$, esc, icon, openDialog, errorBox } from './ui.js';
import { triggerStopAuto, resumeFromStop, openSafetyModeDialog, modeLabel } from './safety-actions.js';

const MODE_KEY = 'churchmix.mode';
const app = $('#app');
const viewRoot = $('#view');
let cleanup = null;
let currentRouteId = null;

function getMode() {
  try { return localStorage.getItem(MODE_KEY) || 'simple'; } catch { return 'simple'; }
}
function setMode(mode) {
  try { localStorage.setItem(MODE_KEY, mode); } catch { /* storage blocked */ }
  app.dataset.mode = mode;
  $$('[data-set-mode]').forEach(b => b.classList.toggle('active', b.dataset.setMode === mode));
  if (mode === 'simple') navigate('home'); else render();
}

// ---------- Top bar ----------
function renderTopbar() {
  $('#topbar').innerHTML = `
    <button class="btn btn-ghost btn-icon nav-toggle" data-nav-toggle aria-label="Mở menu">${icon('menu')}</button>
    <a class="brand" href="#/home" style="text-decoration:none;color:inherit">
      <span class="brand-logo">${icon('sliders')}</span>
      <span class="brand-text"><span class="brand-name">ChurchMix</span><br><span class="brand-sub">Trợ lý âm thanh X32</span></span>
    </a>
    <div class="topbar-status">
      <span class="status-chip" id="chipMixer" title="Kết nối mixer"><span class="dot"></span><span>Đang kết nối…</span></span>
      <button class="status-chip" id="chipMode" title="Bấm để đổi chế độ quyền hạn">${icon('shield', 'icon-sm')}<span>—</span></button>
      <span class="status-chip" id="chipTalkback" title="Talkback ban nhạc (DL16 #11) phải cách ly khỏi loa chính">${icon('shieldCheck', 'icon-sm')}<span>Talkback</span></span>
    </div>
    <div class="topbar-spacer"></div>
    <div class="topbar-actions">
      <div class="segmented" role="tablist" aria-label="Chế độ giao diện">
        <button data-set-mode="simple" title="Cho người không chuyên: 3 bước Trước – Trong – Sau lễ">Đơn giản</button>
        <button data-set-mode="tech" title="Đầy đủ công cụ cho kỹ thuật viên">Kỹ thuật</button>
      </div>
      <button class="btn btn-ghost" id="btnOperator" title="Người đang vận hành (ghi vào nhật ký)">${icon('user')}<span class="op-name"></span></button>
      <button class="btn-stop btn" id="btnStop">${icon('hand')}<span>STOP</span></button>
    </div>`;

  $$('[data-set-mode]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.setMode)));
  $('[data-nav-toggle]').addEventListener('click', () => app.classList.toggle('nav-open'));
  $('#chipMode').addEventListener('click', openSafetyModeDialog);
  $('#btnOperator').addEventListener('click', editOperator);
  $('#btnStop').addEventListener('click', (e) => {
    const engaged = store.status?.stop_auto;
    engaged ? resumeFromStop(e.currentTarget) : triggerStopAuto(e.currentTarget);
  });
  $('.op-name').textContent = getOperator();
  $$('[data-set-mode]').forEach(b => b.classList.toggle('active', b.dataset.setMode === getMode()));
}

function editOperator() {
  const dlg = openDialog({
    title: 'Người vận hành',
    body: `<div class="field"><label for="opName">Tên của bạn (ghi vào nhật ký mỗi lần duyệt lệnh)</label>
      <input id="opName" class="input" value="${esc(getOperator())}" autofocus></div>`,
    actions: [
      { label: 'Hủy', kind: 'ghost' },
      { label: 'Lưu', kind: 'primary', onClick: (close) => { setOperator($('#opName').value); $('.op-name').textContent = getOperator(); close(); } },
    ],
  });
  $('#opName', dlg.root).addEventListener('keydown', (e) => { if (e.key === 'Enter') dlg.root.querySelector('.btn-primary').click(); });
}

let lastChipState = '';
function updateChips() {
  const s = store.status;
  const t = store.telemetry;
  const online = !!s && s.status === 'ONLINE';
  const safety = (t && t.safety_mode) || s?.safety_mode;
  const stop = (t && t.stop_auto) || s?.stop_auto;
  const tbSafe = s?.dl16_talkback_invariant?.safe;
  const key = [online, safety?.current_mode, safety?.is_disengaged, safety?.read_only, stop, tbSafe, store.wsState].join('|');
  if (key === lastChipState) return;
  lastChipState = key;

  const mixer = $('#chipMixer');
  mixer.innerHTML = `<span class="dot ${online ? 'dot-ok' : 'dot-bad'}"></span><span>${online ? `X32 trực tuyến${store.wsState === 'open' ? '' : ' · mất luồng đo'}` : 'Mất kết nối mixer'}</span>`;

  const mode = $('#chipMode');
  const disengaged = safety?.is_disengaged;
  mode.innerHTML = `${icon(disengaged ? 'alert' : safety?.read_only === false ? 'unlock' : 'lock', 'icon-sm')}<span>${disengaged ? 'Đã tự ngắt an toàn' : esc(modeLabel(safety?.current_mode))}</span>`;
  mode.style.borderColor = disengaged ? 'var(--bad)' : safety?.read_only === false ? 'var(--warn)' : '';

  const tb = $('#chipTalkback');
  tb.innerHTML = `${icon(tbSafe === false ? 'alert' : 'shieldCheck', 'icon-sm')}<span>${tbSafe === false ? 'Talkback RÒ RA FOH!' : 'Talkback cách ly'}</span>`;
  tb.style.borderColor = tbSafe === false ? 'var(--bad)' : '';
  tb.style.color = tbSafe === false ? '#ff8a8a' : '';

  const stopBtn = $('#btnStop');
  stopBtn.classList.toggle('engaged', !!stop);
  stopBtn.innerHTML = stop ? `${icon('unlock')}<span>ĐANG KHÓA · Mở</span>` : `${icon('hand')}<span>STOP</span>`;
  stopBtn.title = stop ? 'Hệ thống đang khóa khẩn cấp. Bấm để mở khóa (cần xác nhận).' : 'Dừng ngay mọi tự động, khóa mixer chỉ đọc (Ctrl+Shift+S)';
}

// ---------- Sidebar ----------
function renderSidebar() {
  const groups = [];
  ROUTES.forEach(r => {
    const g = r.group || '';
    let grp = groups.find(x => x.name === g);
    if (!grp) groups.push(grp = { name: g, items: [] });
    grp.items.push(r);
  });
  $('#sidebar').innerHTML = groups.map(g => `
    <div class="nav-group">
      ${g.name ? `<div class="nav-group-title">${esc(g.name)}</div>` : ''}
      ${g.items.map(r => `<a class="nav-link" href="#/${r.id}" data-route="${r.id}">${icon(r.icon)}<span>${esc(r.title)}</span></a>`).join('')}
    </div>`).join('') + `
    <div class="nav-group">
    </div>`;
}

// ---------- Router ----------
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [id, query = ''] = raw.split('?');
  return { id: id || 'home', params: new URLSearchParams(query) };
}

export function navigate(id, params) {
  const q = params ? `?${new URLSearchParams(params)}` : '';
  const target = `#/${id}${q}`;
  if (location.hash === target) render(); else location.hash = target;
}

async function render() {
  const { id, params } = parseHash();
  if (getMode() === 'simple' && id !== 'home') {
    // Simple mode is a single guided screen; deep links switch to technical mode.
    app.dataset.mode = 'tech';
    try { localStorage.setItem(MODE_KEY, 'tech'); } catch { /* storage blocked */ }
    $$('[data-set-mode]').forEach(b => b.classList.toggle('active', b.dataset.setMode === 'tech'));
  }
  const route = routeById(id) || routeById('home');
  app.classList.remove('nav-open');
  $$('.nav-link[data-route]').forEach(a => a.classList.toggle('active', a.dataset.route === route.id));

  if (typeof cleanup === 'function') { try { cleanup(); } catch (e) { console.error(e); } }
  cleanup = null;
  currentRouteId = route.id;
  document.title = `${route.title} · ChurchMix`;
  viewRoot.innerHTML = '<div class="page"><div class="stack-sm"><div class="skeleton" style="height:28px;width:40%"></div><div class="skeleton"></div></div></div>';
  window.scrollTo(0, 0);

  try {
    const mod = await route.load();
    if (currentRouteId !== route.id) return; // user navigated away while loading
    viewRoot.innerHTML = '';
    const page = document.createElement('div');
    page.className = 'page';
    viewRoot.appendChild(page);
    cleanup = mod.default.mount(page, { params, navigate, mode: app.dataset.mode });
  } catch (e) {
    console.error(e);
    viewRoot.innerHTML = `<div class="page">${errorBox(e)}</div>`;
  }
}

// ---------- Boot ----------
app.dataset.mode = getMode();
renderTopbar();
renderSidebar();
store.on('status', updateChips);
store.on('connection', updateChips);
store.on('telemetry', updateChips);
store.start();
window.addEventListener('hashchange', render);
render();

// Keyboard: Ctrl+Shift+S = STOP (works from any page)
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.shiftKey && (e.key === 'S' || e.key === 's')) {
    e.preventDefault();
    if (!store.status?.stop_auto) triggerStopAuto($('#btnStop'));
  }
});
