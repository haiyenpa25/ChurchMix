/**
 * Turns a normalized project config into a concrete file set, previews it
 * against the disk (new / same / conflict / keep / update), and writes it.
 * Never silently overwrites: conflicting files are skipped unless the caller
 * explicitly lists them in `overwrite`.
 */
import fs from "node:fs";
import path from "node:path";
import { ENVIRONMENTS, PROFILES, STACKS, TEMPLATE_VERSION, primaryStack, requiredPortKeys } from "./catalog.js";
import { dockerFiles, gitignoreLines, renderEnv, routerPhp, runBat, xamppVhost } from "./envFiles.js";
import { TEMPLATES_DIR } from "./paths.js";
import { mergeProjectContext } from "./projectContext.js";
import { detectProject } from "./stackDetector.js";

export class ValidationError extends Error {}

const URL_PATTERN = /^https?:\/\/\S+$/i;

/** "Quản lý Đội nhóm" -> "quan-ly-doi-nhom" */
export function slugify(name) {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function readTemplate(relativePath) {
  return fs.readFileSync(path.join(TEMPLATES_DIR, relativePath), "utf8");
}

function renderTemplate(text, variables) {
  return text.replace(/\{\{(\w+)\}\}/g, (match, key) => (key in variables ? String(variables[key]) : match));
}

function optionalUrl(value, label) {
  const trimmed = (value ?? "").trim();
  if (trimmed && !URL_PATTERN.test(trimmed)) throw new ValidationError(`${label} phải là URL bắt đầu bằng http(s)://`);
  return trimmed;
}

/**
 * Validate raw form input and produce a normalized config.
 * @param {object} input raw request body
 * @param {object} settings app settings
 */
export function normalizeConfig(input, settings) {
  const mode = input.mode === "existing" ? "existing" : "new";
  const name = String(input.name ?? "").trim();
  if (!name) throw new ValidationError("Tên dự án là bắt buộc");
  if (name.length > 80) throw new ValidationError("Tên dự án tối đa 80 ký tự");
  const slug = slugify(input.slug || name);
  if (!slug) throw new ValidationError("Tên dự án phải chứa ít nhất một chữ hoặc số");

  let projectPath;
  if (mode === "existing") {
    projectPath = String(input.path ?? "").trim();
    if (!path.isAbsolute(projectPath)) throw new ValidationError("Đường dẫn thư mục phải là đường dẫn tuyệt đối");
    if (!fs.existsSync(projectPath) || !fs.statSync(projectPath).isDirectory()) {
      throw new ValidationError("Thư mục không tồn tại");
    }
  } else {
    const root = String(input.projectsRoot || settings.projectsRoot).trim();
    if (!path.isAbsolute(root)) throw new ValidationError("Thư mục gốc chứa dự án phải là đường dẫn tuyệt đối");
    if (!fs.existsSync(path.parse(root).root)) {
      throw new ValidationError(`Ổ đĩa ${path.parse(root).root} không có trên máy này — đổi "Thư mục gốc chứa dự án" trong Cài đặt`);
    }
    projectPath = path.join(root, slug);
  }
  projectPath = path.resolve(projectPath);

  const detection = mode === "existing" ? detectProject(projectPath) : null;
  let stacks = Array.isArray(input.stacks) ? input.stacks.filter((stack) => stack in STACKS) : [];
  if (input.autoDetect && detection) stacks = detection.stacks;
  if (stacks.length === 0) throw new ValidationError("Chọn ít nhất một ngôn ngữ/stack (hoặc dùng tự detect với thư mục có sẵn)");

  const onlyAppsScript = stacks.every((stack) => stack === "appsscript");
  const env = onlyAppsScript ? "none" : input.env in ENVIRONMENTS ? input.env : "none";
  const primary = primaryStack(stacks);
  if (!STACKS[primary].supportedEnvs.includes(env)) {
    throw new ValidationError(`${STACKS[primary].label} không hỗ trợ môi trường ${ENVIRONMENTS[env].label}`);
  }

  const needsDb = Boolean(input.needsDb) && !onlyAppsScript;
  const ports = {};
  for (const key of requiredPortKeys(env, stacks, needsDb)) {
    const port = Number(input.ports?.[key]);
    if (!Number.isInteger(port)) throw new ValidationError(`Thiếu port cho ${key}`);
    ports[key] = port;
  }

  const profile = input.profile in PROFILES ? input.profile : settings.defaultProfile;

  const verifyCommands = detection?.verifyCommands?.length
    ? detection.verifyCommands.map((command) => ({ ...command, enabled: true }))
    : stacks.flatMap((stack) => STACKS[stack].suggestedVerify ?? [])
      .map((command) => ({ ...command, required: true, enabled: false }));

  return {
    mode,
    name,
    slug,
    path: projectPath,
    sheetUrl: optionalUrl(input.sheetUrl, "Link Google Trang tính"),
    githubUrl: optionalUrl(input.githubUrl, "Link GitHub"),
    stacks,
    env,
    needsDb,
    ports,
    profile,
    replyLanguage: settings.replyLanguage,
    verifyCommands,
    detection,
  };
}

function personalRule() {
  const raw = readTemplate("personal/personal.md").replace(/<!--[\s\S]*?-->\s*/g, "");
  return `---\ntrigger: always_on\n---\n<!-- hainguyencoder:template=personal version=${TEMPLATE_VERSION} — edit templates/personal/personal.md in HAINGUYENCODER to change it for future projects -->\n\n${raw.trim()}\n`;
}

function strictRule() {
  return `---
trigger: always_on
---
<!-- hainguyencoder:template=rules/strict.md version=${TEMPLATE_VERSION} -->

# Strict Mode

- Every change touching more than one file, a public contract, authentication, or the database requires a written plan in \`.ai/plans/\` and user confirmation before implementation.
- After implementation, request an independent review (reviewer subagent or a different model) and record it in \`.ai/reviews/\`.
- Record verification evidence in \`.ai/verification/\` before declaring a task done.
- Architectural decisions are recorded as short ADRs in \`.ai/decisions/\`.
`;
}

/**
 * Build the list of files to generate.
 * strategy: "template" | "createOnly" | "managed" | "appendLines"
 */
export function buildFileSet(config) {
  const profile = PROFILES[config.profile];
  const variables = { projectName: config.name, replyLanguage: config.replyLanguage };
  const files = [];
  const add = (relPath, content, strategy = "template") => files.push({ relPath, content, strategy });

  add("AGENTS.md", renderTemplate(readTemplate("core/AGENTS.md"), variables));
  add("DESIGN.md", renderTemplate(readTemplate("core/DESIGN.md.template"), variables));
  add("PROJECT_CONTEXT.md", null, "managed");
  add(".agents/rules/personal.md", personalRule());

  const ruleNames = new Set([...profile.sharedRules, ...config.stacks.flatMap((stack) => STACKS[stack].rules)]);
  if (config.needsDb) ruleNames.add("database-migrations");
  if (config.env === "docker") ruleNames.add("docker");
  for (const rule of ruleNames) add(`.agents/rules/${rule}.md`, readTemplate(`rules/${rule}.md`));
  if (profile.strictRule) add(".agents/rules/strict.md", strictRule());

  for (const skill of profile.skills) add(`.agents/skills/${skill}/SKILL.md`, readTemplate(`skills/${skill}/SKILL.md`));
  for (const agent of profile.agents) add(`.agents/agents/${agent}.md`, readTemplate(`agents/${agent}.md`));

  if (profile.hooks) {
    add(".agents/hooks.json", readTemplate("hooks/hooks.json"));
    add(".agents/hooks/post-edit-format.mjs", readTemplate("hooks/post-edit-format.mjs"));
    add(".agents/hooks/stop-quality-gate.mjs", readTemplate("hooks/stop-quality-gate.mjs"));
  }
  add("scripts/verify.mjs", readTemplate("scripts/verify.mjs"));

  add(".ai/README.md", readTemplate("core/ai/README.md"));
  add(".ai/PLAN_TEMPLATE.md", readTemplate("core/ai/PLAN_TEMPLATE.md"));
  add(".ai/REVIEW_TEMPLATE.md", readTemplate("core/ai/REVIEW_TEMPLATE.md"));
  add(".ai/VERIFICATION_TEMPLATE.md", readTemplate("core/ai/VERIFICATION_TEMPLATE.md"));
  for (const folder of ["plans", "reviews", "verification", "decisions"]) add(`.ai/${folder}/.gitkeep`, "");
  add(".ai/verify.json", `${JSON.stringify({
    $comment: "Verification commands run by scripts/verify.mjs and the Stop hook. Set enabled=true only for commands that exist.",
    commands: config.verifyCommands,
  }, null, 2)}\n`, "createOnly");

  if (config.env === "docker") {
    for (const file of dockerFiles(config)) add(file.relPath, file.content);
  }
  if (config.env === "xampp" && config.ports.web) add("xampp/vhost.conf", xamppVhost(config));
  if (Object.keys(config.ports).length || config.needsDb) {
    add(".env.example", renderEnv(config, { withSecrets: false }));
    add(".env", renderEnv(config, { withSecrets: true }), "createOnly");
  }
  if (config.ports.web) {
    add("run.bat", runBat(config), "createOnly");
    if (primaryStack(config.stacks) === "php") {
      add("router.php", routerPhp(config), "createOnly");
    }
  }
  add(".gitignore", gitignoreLines(config).join("\n"), "appendLines");

  return files;
}

function resolveInside(root, relPath) {
  const base = path.resolve(root);
  const absolute = path.resolve(base, relPath);
  if (!absolute.startsWith(base + path.sep)) throw new ValidationError(`Đường dẫn không hợp lệ: ${relPath}`);
  return absolute;
}

function readIfExists(file) {
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
}

/** Compute final content + status for each file without touching disk. */
export function previewFileSet(config) {
  return buildFileSet(config).map((file) => {
    const absolute = resolveInside(config.path, file.relPath);
    const existing = readIfExists(absolute);

    if (file.strategy === "managed") {
      const content = mergeProjectContext(existing, config);
      return { ...file, content, status: existing === null ? "new" : "update" };
    }
    if (file.strategy === "createOnly") {
      return { ...file, status: existing === null ? "new" : "keep" };
    }
    if (file.strategy === "appendLines") {
      const present = new Set((existing ?? "").split(/\r?\n/).map((line) => line.trim()));
      const missing = file.content.split("\n").filter((line) => !present.has(line));
      if (existing === null) return { ...file, status: "new" };
      if (missing.length === 0) return { ...file, content: existing, status: "same" };
      const header = "\n# Added by HAINGUYENCODER\n";
      return { ...file, content: `${existing.trimEnd()}\n${header}${missing.join("\n")}\n`, status: "update" };
    }
    if (existing === null) return { ...file, status: "new" };
    return { ...file, status: existing.replace(/\r\n/g, "\n") === file.content ? "same" : "conflict" };
  });
}

/**
 * Write the previewed file set.
 * @param {object} config normalized config
 * @param {string[]} overwrite relPaths the user explicitly approved to overwrite
 */
export function applyFileSet(config, overwrite = []) {
  const approved = new Set(overwrite);
  const summary = { written: [], skipped: [], unchanged: [] };
  fs.mkdirSync(config.path, { recursive: true });

  for (const file of previewFileSet(config)) {
    const shouldWrite =
      file.status === "new" || file.status === "update" || (file.status === "conflict" && approved.has(file.relPath));
    if (!shouldWrite) {
      (file.status === "same" || file.status === "keep" ? summary.unchanged : summary.skipped).push(file.relPath);
      continue;
    }
    const absolute = resolveInside(config.path, file.relPath);
    fs.mkdirSync(path.dirname(absolute), { recursive: true });
    fs.writeFileSync(absolute, file.content, "utf8");
    summary.written.push(file.relPath);
  }
  return summary;
}

/** Fields persisted in the registry (no detection noise, no secrets). */
export function toRegistryRecord(config) {
  const { name, slug, path: projectPath, sheetUrl, githubUrl, stacks, env, needsDb, ports, profile } = config;
  return { name, slug, path: projectPath, sheetUrl, githubUrl, stacks, env, needsDb, ports, profile, templateVersion: TEMPLATE_VERSION };
}
