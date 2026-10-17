// HAINGUYENCODER client. Vanilla JS, no build step.
// All user-provided values are escaped with esc() before being inserted as HTML.

const state = {
  catalog: null,
  settings: null,
  projects: [],
  form: { mode: "new", stacks: new Set(), env: "xampp", needsDb: true, profile: "balanced", ports: {} },
  tools: [],
  selectedTools: new Set(),
  toolPoll: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function api(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", "X-HNC": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Lỗi ${response.status}`);
  return data;
}

function toast(message, type = "info") {
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.textContent = message;
  $("#toasts").append(element);
  setTimeout(() => element.remove(), 4500);
}

function debounce(fn, delay = 350) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function withBusy(button, task) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span>${original}`;
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

/* ===== Navigation ===== */
function showView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  if (name === "templates") loadTemplates();
  if (name === "dashboard") loadProjects();
  if (name === "tools") loadTools();
}

/* ===== Modal ===== */
function openModal(title, bodyHtml, buttons = []) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHtml;
  const foot = $("#modal-foot");
  foot.innerHTML = "";
  for (const { label, className = "btn-ghost", onClick, id } of buttons) {
    const button = document.createElement("button");
    button.className = `btn ${className}`;
    button.textContent = label;
    if (id) button.id = id;
    button.addEventListener("click", () => onClick(button));
    foot.append(button);
  }
  $("#modal").showModal();
}
const closeModal = () => $("#modal").close();

/* ===== Domain helpers (mirror server catalog rules) ===== */
const STACK_PRIORITY = ["laravel", "php", "python", "node", "static", "appsscript"];
const primaryStack = (stacks) => STACK_PRIORITY.find((stack) => stacks.includes(stack)) ?? "static";

function requiredPortKeys(env, stacks, needsDb) {
  if (stacks.length && stacks.every((stack) => stack === "appsscript")) return [];
  if (env === "docker") return needsDb ? ["web", "db", "dbAdmin"] : ["web"];
  return ["web"];
}

const stackLabel = (id) => state.catalog?.stacks[id]?.label ?? id;
const envLabel = (id) => state.catalog?.environments[id]?.label ?? id;

/* ===== Dashboard ===== */
async function loadProjects() {
  try {
    state.projects = await api("GET", "/api/projects");
    renderStats();
    renderProjects();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderStats() {
  const ports = state.projects.flatMap((project) => Object.values(project.ports ?? {}));
  const stacks = new Set(state.projects.flatMap((project) => project.stacks));
  const withSheet = state.projects.filter((project) => project.sheetUrl).length;
  const stats = [
    [state.projects.length, "Dự án"],
    [ports.length, "Port đã cấp"],
    [stacks.size, "Stack khác nhau"],
    [withSheet, "Có liên kết Trang tính"],
  ];
  $("#stats").innerHTML = stats.map(([value, label]) => `
    <div class="card stat"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`).join("");
}

function projectMatches(project, term) {
  if (!term) return true;
  const haystack = [project.name, project.path, ...project.stacks.map(stackLabel), ...Object.values(project.ports ?? {})]
    .join(" ").toLowerCase();
  return haystack.includes(term.toLowerCase());
}

function renderProjects() {
  const term = $("#project-search").value.trim();
  const projects = state.projects.filter((project) => projectMatches(project, term));
  const grid = $("#project-grid");

  if (state.projects.length === 0) {
    grid.innerHTML = `
      <div class="card empty-state" style="grid-column: 1 / -1">
        <div class="orbit" aria-hidden="true"><span></span><span></span><span></span></div>
        <h3>Chưa có dự án nào</h3>
        <p class="muted">Tạo dự án đầu tiên — app sẽ sinh AGENTS.md, rules, skills, hooks và cấp port riêng.</p>
        <button class="btn btn-primary" id="btn-empty-create">+ Tạo dự án mới</button>
      </div>`;
    $("#btn-empty-create").addEventListener("click", () => showView("create"));
    return;
  }

  grid.innerHTML = projects.map((project) => {
    const ports = Object.entries(project.ports ?? {})
      .map(([key, port]) => `<span class="chip port" title="${esc(state.catalog.portLabels[key] ?? key)}">${esc(key)}:${esc(port)}</span>`).join("");
    const link = (url, label) => url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`
      : `<span class="missing">${label}: chưa có</span>`;
    return `
      <article class="card project-card" data-id="${esc(project.id)}">
        <div class="project-top">
          <div>
            <h3 class="project-name">${esc(project.name)}</h3>
            <div class="project-path">${esc(project.path)}</div>
          </div>
          <span class="chip env">${esc(envLabel(project.env))}</span>
        </div>
        <div class="chips">
          ${project.stacks.map((stack) => `<span class="chip">${esc(stackLabel(stack))}</span>`).join("")}
          <span class="chip">profile: ${esc(project.profile)}</span>
        </div>
        <div class="chips">${ports || '<span class="muted" style="font-size:12px">Không cần port</span>'}</div>
        <div class="links">${link(project.sheetUrl, "Trang tính")} ${link(project.githubUrl, "GitHub")}</div>
        <div class="actions">
          <button class="btn btn-ghost btn-sm" data-action="open">📂 Mở</button>
          <button class="btn btn-ghost btn-sm" data-action="edit">✎ Sửa</button>
          <button class="btn btn-ghost btn-sm" data-action="doctor">🩺 Doctor</button>
          <button class="btn btn-ghost btn-sm" data-action="resync">↻ Đồng bộ template</button>
          ${project.env === "xampp" ? '<button class="btn btn-ghost btn-sm" data-action="xampp">⚙ Cài vhost XAMPP</button>' : ""}
          <button class="btn btn-danger btn-sm" data-action="remove">Gỡ</button>
        </div>
      </article>`;
  }).join("") || '<p class="muted">Không có dự án khớp.</p>';
}

const projectActions = {
  async open(project) {
    await api("POST", `/api/projects/${project.id}/open`);
  },

  async doctor(project) {
    const findings = await api("POST", `/api/projects/${project.id}/doctor`);
    const counts = findings.reduce((acc, finding) => ({ ...acc, [finding.level]: (acc[finding.level] ?? 0) + 1 }), {});
    const summary = counts.error
      ? `<div class="alert error">${counts.error} lỗi cần sửa</div>`
      : `<div class="alert ok">Không có lỗi nghiêm trọng${counts.warn ? ` · ${counts.warn} cảnh báo` : ""}</div>`;
    openModal(`Doctor — ${project.name}`, summary + findings.map((finding) => `
      <div class="finding">
        <span class="level ${esc(finding.level)}">${esc(finding.level)}</span>
        <span class="area">${esc(finding.area)}</span>
        <span>${esc(finding.message)}</span>
      </div>`).join(""));
  },

  edit(project) {
    const portInputs = Object.entries(project.ports ?? {}).map(([key, port]) => `
      <label class="field port-field">
        <span>${esc(state.catalog.portLabels[key] ?? key)}</span>
        <input class="input mono" type="number" data-port="${esc(key)}" value="${esc(port)}" min="1024" max="65535">
        <span class="status" data-port-status="${esc(key)}"></span>
      </label>`).join("");
    openModal(`Sửa — ${project.name}`, `
      <label class="field"><span>Tên dự án</span><input class="input" id="e-name" value="${esc(project.name)}" maxlength="80"></label>
      <label class="field"><span>Link Google Trang tính</span><input class="input" id="e-sheet" type="url" value="${esc(project.sheetUrl)}"></label>
      <label class="field"><span>GitHub</span><input class="input" id="e-github" type="url" value="${esc(project.githubUrl)}"></label>
      ${portInputs ? `<div class="section-title">Port</div><div class="ports">${portInputs}</div>` : ""}
      <p class="hint">Lưu sẽ cập nhật PROJECT_CONTEXT.md, .env, .env.example${project.env === "xampp" ? " và xampp/vhost.conf (cần cài lại vhost)" : ""}.</p>`,
    [
      { label: "Hủy", onClick: closeModal },
      {
        label: "Lưu", className: "btn-primary", id: "btn-save-edit",
        onClick: (button) => withBusy(button, async () => {
          const ports = {};
          $$("#modal-body [data-port]").forEach((input) => { ports[input.dataset.port] = Number(input.value); });
          try {
            const result = await api("PATCH", `/api/projects/${project.id}`, {
              name: $("#e-name").value, sheetUrl: $("#e-sheet").value, githubUrl: $("#e-github").value,
              ...(Object.keys(ports).length ? { ports } : {}),
            });
            closeModal();
            toast(`Đã lưu · cập nhật ${result.changedFiles.join(", ") || "registry"}`, "ok");
            loadProjects();
          } catch (error) {
            toast(error.message, "error");
          }
        }),
      },
    ]);
    const check = debounce(async () => {
      const ports = {};
      $$("#modal-body [data-port]").forEach((input) => { ports[input.dataset.port] = input.value; });
      const report = await api("POST", "/api/ports/check", { ports, excludeProjectId: project.id }).catch(() => ({}));
      renderPortStatus(report, $("#modal-body"));
    });
    $$("#modal-body [data-port]").forEach((input) => input.addEventListener("input", check));
  },

  async resync(project) {
    const { files } = await api("POST", `/api/projects/${project.id}/resync/preview`);
    const pending = files.filter((file) => file.status !== "same" && file.status !== "keep");
    openModal(`Đồng bộ template — ${project.name}`, `
      <p class="muted">Áp dụng template hiện tại vào dự án. File xung đột (bạn đã sửa) chỉ bị ghi đè nếu bạn tick.</p>
      ${pending.length === 0 ? '<div class="alert ok">Dự án đã đồng bộ với template hiện tại.</div>' : renderFileList(pending, true)}`,
    pending.length === 0 ? [{ label: "Đóng", onClick: closeModal }] : [
      { label: "Hủy", onClick: closeModal },
      {
        label: "Áp dụng", className: "btn-primary",
        onClick: (button) => withBusy(button, async () => {
          const overwrite = $$("#modal-body [data-overwrite]:checked").map((input) => input.dataset.overwrite);
          const { summary } = await api("POST", `/api/projects/${project.id}/resync`, { overwrite });
          closeModal();
          toast(`Đã ghi ${summary.written.length} file, bỏ qua ${summary.skipped.length}`, "ok");
          loadProjects();
        }),
      },
    ]);
  },

  async xampp(project) {
    openModal("Cài vhost vào XAMPP", `
      <p>App sẽ <b>sao lưu</b> rồi thêm khối vhost của dự án vào <code>${esc(state.settings.xampp.vhostsFile)}</code>.</p>
      <p class="muted">Khối được đánh dấu <code># HNC:BEGIN ${esc(project.slug)}</code> nên cài lại sẽ thay thế, không bị nhân đôi.</p>`,
    [
      { label: "Hủy", onClick: closeModal },
      {
        label: "Cài vhost", className: "btn-primary",
        onClick: (button) => withBusy(button, async () => {
          try {
            const result = await api("POST", `/api/projects/${project.id}/xampp`);
            closeModal();
            result.warnings.forEach((warning) => toast(warning, "info"));
            toast(`Đã cài. Backup: ${result.backupFile}`, "ok");
          } catch (error) {
            toast(error.message, "error");
          }
        }),
      },
    ]);
  },

  remove(project) {
    openModal("Gỡ khỏi danh sách", `
      <p>Gỡ <b>${esc(project.name)}</b> khỏi HAINGUYENCODER và giải phóng các port đã cấp?</p>
      <div class="alert warn">Thư mục và file của dự án <b>không bị xóa</b>.</div>`,
    [
      { label: "Hủy", onClick: closeModal },
      {
        label: "Gỡ", className: "btn-danger",
        onClick: async () => {
          await api("DELETE", `/api/projects/${project.id}`);
          closeModal();
          toast("Đã gỡ khỏi danh sách", "ok");
          loadProjects();
        },
      },
    ]);
  },
};

/* ===== Create form ===== */
function renderOption({ name, value, title, desc, type, checked, disabled }) {
  return `
    <label class="option${checked ? " selected" : ""}${disabled ? " disabled" : ""}">
      <input type="${type}" name="${name}" value="${esc(value)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} id="opt-${name}-${esc(value)}">
      <span class="title">${esc(title)}</span>
      ${desc ? `<span class="desc">${esc(desc)}</span>` : ""}
    </label>`;
}

function renderStackOptions() {
  $("#stack-options").innerHTML = Object.entries(state.catalog.stacks).map(([id, stack]) => renderOption({
    name: "stack", value: id, title: stack.label, type: "checkbox", checked: state.form.stacks.has(id),
    desc: stack.usesDb ? "Thường dùng database" : "",
  })).join("");
}

function supportedEnvs() {
  const stacks = [...state.form.stacks];
  if (stacks.length === 0) return Object.keys(state.catalog.environments);
  return state.catalog.stacks[primaryStack(stacks)].supportedEnvs;
}

function renderEnvOptions() {
  const supported = supportedEnvs();
  if (!supported.includes(state.form.env)) state.form.env = supported[0];
  const descriptions = { xampp: "Apache + MySQL dùng chung, vhost riêng port", docker: "docker-compose riêng, DB riêng", none: "npm/php artisan/uvicorn trực tiếp" };
  $("#env-options").innerHTML = Object.entries(state.catalog.environments).map(([id, env]) => renderOption({
    name: "env", value: id, title: env.label, desc: descriptions[id], type: "radio",
    checked: state.form.env === id, disabled: !supported.includes(id),
  })).join("");
}

function renderProfileOptions() {
  $("#profile-options").innerHTML = Object.entries(state.catalog.profiles).map(([id, profile]) => renderOption({
    name: "profile", value: id, title: profile.label, type: "radio", checked: state.form.profile === id,
    desc: `${profile.skills} skills · ${profile.hooks ? "có hooks" : "không hooks"}${profile.agents.length ? ` · agents: ${profile.agents.join(", ")}` : ""}`,
  })).join("");
}

function currentPortKeys() {
  return requiredPortKeys(state.form.env, [...state.form.stacks], state.form.needsDb);
}

function renderPortFields() {
  const keys = currentPortKeys();
  $("#btn-suggest-ports").classList.toggle("hidden", keys.length === 0);
  if (keys.length === 0) {
    $("#port-fields").innerHTML = '<p class="muted" style="margin:0;font-size:13px">Không cần port cho cấu hình này.</p>';
    return;
  }
  const xamppNote = state.form.env === "xampp" && state.form.needsDb
    ? '<p class="hint" style="grid-column:1/-1">XAMPP dùng chung MySQL 3306 và phpMyAdmin; mỗi dự án chỉ cần port web riêng.</p>' : "";
  $("#port-fields").innerHTML = keys.map((key) => `
    <label class="field port-field">
      <span>${esc(state.catalog.portLabels[key])}</span>
      <input class="input mono" type="number" min="1024" max="65535" data-port="${key}" id="port-${key}" value="${esc(state.form.ports[key] ?? "")}">
      <span class="status" data-port-status="${key}"></span>
    </label>`).join("") + xamppNote;
  $$("#port-fields [data-port]").forEach((input) => input.addEventListener("input", () => {
    state.form.ports[input.dataset.port] = Number(input.value);
    checkFormPorts();
  }));
}

function renderPortStatus(report, root = document) {
  for (const [key, entry] of Object.entries(report)) {
    const element = $(`[data-port-status="${key}"]`, root);
    if (element) element.innerHTML = `<span class="dot ${esc(entry.status)}"></span>${esc(entry.message)}`;
  }
}

const checkFormPorts = debounce(async () => {
  const ports = Object.fromEntries(currentPortKeys().map((key) => [key, state.form.ports[key]]));
  if (Object.keys(ports).length === 0) return;
  try {
    renderPortStatus(await api("POST", "/api/ports/check", { ports }), $("#port-fields"));
  } catch (error) {
    toast(error.message, "error");
  }
});

async function suggestFormPorts() {
  const keys = currentPortKeys();
  if (keys.length === 0) return renderPortFields();
  const suggested = await api("POST", "/api/ports/suggest", {
    env: state.form.env, stacks: [...state.form.stacks], needsDb: state.form.needsDb,
  });
  state.form.ports = { ...suggested };
  renderPortFields();
  checkFormPorts();
}

function refreshEnvironmentSection({ suggest = true } = {}) {
  renderEnvOptions();
  const stacks = [...state.form.stacks];
  const onlyAppsScript = stacks.length > 0 && stacks.every((stack) => stack === "appsscript");
  $("#field-db").classList.toggle("hidden", onlyAppsScript);
  if (suggest) suggestFormPorts().catch((error) => toast(error.message, "error"));
  else renderPortFields();
}

function setMode(mode) {
  state.form.mode = mode;
  $$(".seg").forEach((seg) => seg.classList.toggle("active", seg.dataset.mode === mode));
  $("#field-root").classList.toggle("hidden", mode !== "new");
  $("#field-path").classList.toggle("hidden", mode !== "existing");
  $("#field-autodetect").classList.toggle("hidden", mode !== "existing");
}

function updateSlugHint() {
  const name = $("#f-name").value;
  const slug = name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[đĐ]/g, "d").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  $("#slug-hint").textContent = slug && state.form.mode === "new"
    ? `Thư mục: ${$("#f-root").value.replace(/[\\/]+$/, "")}\\${slug}` : "";
}

async function detectFolder() {
  const folder = $("#f-path").value.trim();
  if (!folder) return toast("Nhập đường dẫn thư mục trước", "error");
  try {
    const result = await api("POST", "/api/detect", { path: folder });
    $("#detect-result").textContent = result.details.length ? `Phát hiện: ${result.details.join(" · ")}` : "Không nhận diện được stack — hãy chọn thủ công.";
    if (!$("#f-name").value) $("#f-name").value = result.suggestedName;
    if (result.stacks.length) {
      state.form.stacks = new Set(result.stacks);
      renderStackOptions();
      if (result.hasDocker) state.form.env = "docker";
      refreshEnvironmentSection();
    }
  } catch (error) {
    $("#detect-result").textContent = error.message;
  }
}

function buildPayload() {
  return {
    mode: state.form.mode,
    name: $("#f-name").value,
    projectsRoot: $("#f-root").value,
    path: $("#f-path").value,
    sheetUrl: $("#f-sheet").value,
    githubUrl: $("#f-github").value,
    stacks: [...state.form.stacks],
    autoDetect: state.form.mode === "existing" && $("#f-autodetect").checked,
    env: state.form.env,
    needsDb: state.form.needsDb,
    ports: state.form.ports,
    profile: state.form.profile,
  };
}

function renderFileList(files, withOverwrite) {
  const legend = `<div class="legend">
    <span><span class="badge new">mới</span> tạo mới</span>
    <span><span class="badge update">cập nhật</span> gộp an toàn</span>
    <span><span class="badge conflict">xung đột</span> đã tồn tại & khác</span>
    <span><span class="badge keep">giữ</span> không đụng tới</span></div>`;
  const labels = { new: "mới", update: "cập nhật", conflict: "xung đột", same: "giống", keep: "giữ" };
  return legend + `<ul class="file-list">${files.map((file) => `
    <li>
      <span class="path">${esc(file.relPath)}</span>
      ${withOverwrite && file.status === "conflict" ? `<label class="check" title="Ghi đè file này"><input type="checkbox" data-overwrite="${esc(file.relPath)}"> ghi đè</label>` : ""}
      <span class="badge ${esc(file.status)}">${labels[file.status] ?? esc(file.status)}</span>
    </li>`).join("")}</ul>`;
}

async function previewForm() {
  const preview = await api("POST", "/api/projects/preview", buildPayload());
  const { files, portReport, warnings, config } = preview;
  const blocking = Object.values(portReport).filter((entry) => ["invalid", "duplicate", "reserved"].includes(entry.status));
  const counts = files.reduce((acc, file) => ({ ...acc, [file.status]: (acc[file.status] ?? 0) + 1 }), {});

  $("#preview-body").className = "";
  $("#preview-body").innerHTML = `
    ${warnings.map((warning) => `<div class="alert warn">${esc(warning)}</div>`).join("")}
    ${blocking.map((entry) => `<div class="alert error">Port ${esc(entry.port)}: ${esc(entry.message)}</div>`).join("")}
    ${config.detection ? `<div class="alert ok">Detect: ${esc(config.detection.details.join(" · ") || "không rõ")}</div>` : ""}
    <div class="section-title">Đích</div>
    <div class="mono" style="font-size:12.5px;word-break:break-all">${esc(config.path)}</div>
    <div class="section-title">Port</div>
    <div class="chips">${Object.entries(portReport).map(([key, entry]) => `<span class="chip port"><span class="dot ${esc(entry.status)}"></span> ${esc(key)}:${esc(entry.port)}</span>`).join("") || '<span class="muted">Không cần</span>'}</div>
    <div class="section-title">${files.length} file · ${counts.new ?? 0} mới · ${counts.conflict ?? 0} xung đột</div>
    ${renderFileList(files, true)}`;
  renderPortStatus(portReport, $("#port-fields"));
  return preview;
}

async function createFromForm() {
  const overwrite = $$("#preview-body [data-overwrite]:checked").map((input) => input.dataset.overwrite);
  const { project, summary } = await api("POST", "/api/projects", { ...buildPayload(), overwrite });
  openModal("🎉 Đã tạo dự án", `
    <div class="alert ok">Đã ghi <b>${summary.written.length}</b> file vào <code>${esc(project.path)}</code>${summary.skipped.length ? ` · bỏ qua ${summary.skipped.length} file xung đột` : ""}.</div>
    <div class="section-title">Bước tiếp theo</div>
    <ol style="margin:0;padding-left:20px;line-height:1.9;font-size:14px">
      <li>Mở thư mục dự án bằng Antigravity IDE (File → Open Folder).</li>
      <li>Mở <code>PROJECT_CONTEXT.md</code>, viết thêm phần <b>Ghi chú dự án</b> (nghiệp vụ, thuật ngữ).</li>
      ${project.env === "xampp" ? "<li>Bấm <b>Cài vhost XAMPP</b> ở trang Dự án rồi restart Apache.</li>" : ""}
      ${project.env === "docker" ? "<li>Chạy <code>docker compose up -d</code> trong thư mục dự án.</li>" : ""}
      <li>Khi đã có lint/test/build, bật lệnh tương ứng trong <code>.ai/verify.json</code>.</li>
      <li>Chạy <b>Doctor</b> để kiểm tra cấu hình.</li>
    </ol>`,
  [
    { label: "Mở thư mục", onClick: () => api("POST", `/api/projects/${project.id}/open`) },
    { label: "Về danh sách dự án", className: "btn-primary", onClick: () => { closeModal(); showView("dashboard"); } },
  ]);
  resetCreateForm();
}

function resetCreateForm() {
  $("#create-form").reset();
  $("#f-root").value = state.settings.projectsRoot;
  state.form = { mode: state.form.mode, stacks: new Set(), env: "xampp", needsDb: true, profile: state.settings.defaultProfile, ports: {} };
  $("#f-db").checked = true;
  $("#detect-result").textContent = "";
  $("#preview-body").className = "preview-empty";
  $("#preview-body").innerHTML = '<div class="orbit" aria-hidden="true"><span></span><span></span><span></span></div><p>Bấm <b>Xem trước</b> để thấy cây file, trạng thái port và cảnh báo trước khi ghi ra đĩa.</p>';
  renderStackOptions();
  renderProfileOptions();
  refreshEnvironmentSection();
  updateSlugHint();
}

/* ===== Machine tools ===== */
async function loadTools({ silent = false } = {}) {
  if (!silent) $("#tool-grid").innerHTML = '<p class="muted">Đang kiểm tra công cụ trên máy…</p>';
  try {
    const { tools } = await api("GET", "/api/tools");
    state.tools = tools;
    for (const id of [...state.selectedTools]) {
      if (tools.find((tool) => tool.id === id)?.installed) state.selectedTools.delete(id);
    }
    renderTools();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderTools() {
  const missingNeeded = state.tools.filter((tool) => !tool.installed && (tool.required || tool.neededBy.length));
  const badge = $("#tools-badge");
  badge.textContent = missingNeeded.length;
  badge.classList.toggle("hidden", missingNeeded.length === 0);

  const notice = $("#tools-needed");
  notice.classList.toggle("hidden", missingNeeded.length === 0);
  notice.textContent = missingNeeded.length
    ? `Còn thiếu ${missingNeeded.map((tool) => tool.label).join(", ")} — đã tự chọn sẵn, bấm "Cài mục đã chọn".` : "";
  if (!state.toolsAutoSelected) {
    missingNeeded.forEach((tool) => state.selectedTools.add(tool.id));
    state.toolsAutoSelected = true;
  }

  $("#tool-grid").innerHTML = state.tools.map((tool) => {
    const selected = state.selectedTools.has(tool.id);
    const tags = [
      tool.required ? '<span class="tag req">bắt buộc</span>' : "",
      tool.neededBy.length ? `<span class="tag need" title="${esc(tool.neededBy.join(", "))}">${tool.neededBy.length} dự án cần</span>` : "",
      tool.heavy ? '<span class="tag">cần Admin</span>' : "",
      tool.dependsOn.length ? `<span class="tag">cần ${esc(tool.dependsOn.join(", "))}</span>` : "",
    ].join("");
    return `
      <label class="card tool-card ${tool.installed ? "installed" : "missing"}${selected ? " selected" : ""}" id="tool-${esc(tool.id)}">
        ${tool.installed ? "" : `<input type="checkbox" data-tool="${esc(tool.id)}" ${selected ? "checked" : ""}>`}
        <span class="tool-icon">${tool.installed ? "✓" : "!"}</span>
        <span class="tool-body">
          <span class="tool-name">${esc(tool.label)} ${tags}</span>
          <span class="tool-version ${tool.installed ? "" : "none"}">${esc(tool.installed ? tool.version : "Chưa cài / chưa có trong PATH")}</span>
          <span class="tool-purpose">${esc(tool.purpose)}</span>
        </span>
      </label>`;
  }).join("");
  $("#btn-install-tools").disabled = state.selectedTools.size === 0;
  $("#btn-install-tools").textContent = state.selectedTools.size ? `Cài ${state.selectedTools.size} mục đã chọn` : "Cài mục đã chọn";
}

function confirmInstallTools() {
  const ids = [...state.selectedTools];
  const labels = state.tools.filter((tool) => ids.includes(tool.id)).map((tool) => tool.label);
  const heavy = state.tools.some((tool) => ids.includes(tool.id) && tool.heavy);
  openModal("Cài công cụ", `
    <p>Sẽ mở một cửa sổ PowerShell để cài: <b>${esc(labels.join(", "))}</b>.</p>
    <ul style="margin:0;padding-left:20px;line-height:1.8;font-size:14px">
      <li>Trước khi tải, script tìm bản đã cài sẵn (VD PHP của XAMPP) và chỉ thêm vào PATH.</li>
      <li>Cài bằng <code>winget</code>; Composer được tải từ getcomposer.org và kiểm tra SHA-256.</li>
      <li>PATH được ghi vào biến môi trường User (không cắt ngắn như <code>setx</code>).</li>
      <li>Windows có thể hỏi quyền (UAC) — hãy bấm Đồng ý.</li>
    </ul>
    ${heavy ? '<div class="alert warn">XAMPP / Docker cần quyền Admin; Docker có thể yêu cầu khởi động lại máy.</div>' : ""}
    <p class="hint">Sau khi cài xong, mở lại terminal / Antigravity IDE để nhận PATH mới. Trang này tự kiểm tra lại mỗi 10 giây.</p>`,
  [
    { label: "Hủy", onClick: closeModal },
    {
      label: "Mở trình cài", className: "btn-primary",
      onClick: async () => {
        try {
          await api("POST", "/api/tools/install", { ids });
          closeModal();
          toast("Đã mở cửa sổ cài đặt PowerShell", "ok");
          startToolPolling();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
  ]);
}

function startToolPolling() {
  clearInterval(state.toolPoll);
  let rounds = 0;
  state.toolPoll = setInterval(() => {
    rounds += 1;
    if (rounds > 60) clearInterval(state.toolPoll);
    loadTools({ silent: true });
  }, 10000);
}

/* ===== Templates ===== */
async function loadTemplates() {
  const files = await api("GET", "/api/templates");
  const groups = files.reduce((acc, file) => {
    const group = file.relPath.split("/")[0];
    (acc[group] ??= []).push(file);
    return acc;
  }, {});
  $("#template-list").innerHTML = Object.entries(groups).map(([group, items]) => `
    <div class="template-group">${esc(group)} (${items.length})</div>
    ${items.map((file) => `<button class="template-item" data-path="${esc(file.relPath)}">${esc(file.relPath.slice(group.length + 1))}</button>`).join("")}`).join("");
}

async function viewTemplate(button) {
  $$(".template-item").forEach((item) => item.classList.toggle("active", item === button));
  const { content } = await api("GET", `/api/templates/file?path=${encodeURIComponent(button.dataset.path)}`);
  $("#template-viewer-title").textContent = `templates/${button.dataset.path}`;
  $("#template-viewer").textContent = content;
}

/* ===== Settings ===== */
function renderSettings() {
  const { settings } = state;
  $("#s-root").value = settings.projectsRoot;
  $("#s-xampp").value = settings.xamppPath;
  $("#s-lang").value = settings.replyLanguage;
  $("#s-profile").innerHTML = Object.entries(state.catalog.profiles)
    .map(([id, profile]) => `<option value="${id}" ${settings.defaultProfile === id ? "selected" : ""}>${esc(profile.label)}</option>`).join("");
  const xampp = settings.xampp;
  $("#xampp-status").textContent = xampp.installed
    ? `✓ Tìm thấy ${xampp.vhostsFile}${xampp.includesVhosts ? "" : " — nhưng httpd.conf chưa Include httpd-vhosts.conf"}`
    : "✗ Không tìm thấy XAMPP tại đường dẫn này (chỉ cần nếu bạn dùng XAMPP)";
}

async function saveSettingsForm(event) {
  event.preventDefault();
  await api("PUT", "/api/settings", {
    projectsRoot: $("#s-root").value, xamppPath: $("#s-xampp").value,
    replyLanguage: $("#s-lang").value, defaultProfile: $("#s-profile").value,
  });
  state.settings = await api("GET", "/api/settings");
  renderSettings();
  $("#f-root").value = state.settings.projectsRoot;
  toast("Đã lưu cài đặt", "ok");
}

/* ===== Wiring ===== */
function bindEvents() {
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => showView(item.dataset.view)));
  $("#btn-go-create").addEventListener("click", () => showView("create"));
  $("#project-search").addEventListener("input", renderProjects);
  $("#modal-close").addEventListener("click", closeModal);

  $("#project-grid").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const project = state.projects.find((item) => item.id === button.closest("[data-id]").dataset.id);
    try {
      await projectActions[button.dataset.action](project);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $$(".seg").forEach((seg) => seg.addEventListener("click", () => { setMode(seg.dataset.mode); updateSlugHint(); }));
  $("#f-name").addEventListener("input", updateSlugHint);
  $("#f-root").addEventListener("input", updateSlugHint);
  $("#btn-detect").addEventListener("click", detectFolder);

  $("#stack-options").addEventListener("change", (event) => {
    const { value, checked } = event.target;
    if (checked) state.form.stacks.add(value); else state.form.stacks.delete(value);
    const usesDb = [...state.form.stacks].some((stack) => state.catalog.stacks[stack].usesDb);
    state.form.needsDb = usesDb;
    $("#f-db").checked = usesDb;
    renderStackOptions();
    refreshEnvironmentSection();
  });
  $("#env-options").addEventListener("change", (event) => {
    state.form.env = event.target.value;
    refreshEnvironmentSection();
  });
  $("#profile-options").addEventListener("change", (event) => {
    state.form.profile = event.target.value;
    renderProfileOptions();
  });
  $("#f-db").addEventListener("change", (event) => {
    state.form.needsDb = event.target.checked;
    refreshEnvironmentSection();
  });
  $("#btn-suggest-ports").addEventListener("click", () => suggestFormPorts().catch((error) => toast(error.message, "error")));

  $("#btn-preview").addEventListener("click", (event) =>
    withBusy(event.currentTarget, previewForm).catch((error) => toast(error.message, "error")));
  $("#create-form").addEventListener("submit", (event) => {
    event.preventDefault();
    withBusy($("#btn-create"), createFromForm).catch((error) => toast(error.message, "error"));
  });

  $("#template-list").addEventListener("click", (event) => {
    const button = event.target.closest(".template-item");
    if (button) viewTemplate(button).catch((error) => toast(error.message, "error"));
  });
  $("#btn-open-templates").addEventListener("click", () => api("POST", "/api/templates/open"));
  $("#btn-refresh-tools").addEventListener("click", (event) => withBusy(event.currentTarget, () => loadTools()));
  $("#btn-install-tools").addEventListener("click", confirmInstallTools);
  $("#tool-grid").addEventListener("change", (event) => {
    const id = event.target.dataset.tool;
    if (!id) return;
    if (event.target.checked) state.selectedTools.add(id); else state.selectedTools.delete(id);
    renderTools();
  });
  $("#settings-form").addEventListener("submit", (event) => saveSettingsForm(event).catch((error) => toast(error.message, "error")));
}

async function init() {
  try {
    [state.catalog, state.settings] = await Promise.all([api("GET", "/api/catalog"), api("GET", "/api/settings")]);
  } catch (error) {
    toast(`Không kết nối được server: ${error.message}`, "error");
    return;
  }
  $("#template-version").textContent = `v${state.catalog.templateVersion}`;
  state.form.profile = state.settings.defaultProfile;
  bindEvents();
  renderSettings();
  setMode("new");
  resetCreateForm();
  loadProjects();
  loadTools({ silent: true });
}

init();
