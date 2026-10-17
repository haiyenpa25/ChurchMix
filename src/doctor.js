/**
 * "Doctor": static health check of a project's AI configuration.
 * Each finding is { level: "ok"|"info"|"warn"|"error", area, message }.
 */
import fs from "node:fs";
import path from "node:path";
import { TEMPLATE_VERSION } from "./catalog.js";
import { getReservedPorts } from "./portAllocator.js";

const VALID_TRIGGERS = new Set(["always_on", "glob", "model_decision", "manual"]);
const MAX_AGENTS_MD_BYTES = 12 * 1024;

/** Minimal YAML frontmatter parser: scalar `key: value` and `- item` lists. */
export function parseFrontmatter(text) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
  if (!match) return null;
  const data = {};
  let currentKey = null;
  for (const line of match[1].split(/\r?\n/)) {
    const listItem = /^\s+-\s+(.*)$/.exec(line);
    if (listItem && currentKey) {
      if (!Array.isArray(data[currentKey])) data[currentKey] = [];
      data[currentKey].push(listItem[1].replace(/^["']|["']$/g, ""));
      continue;
    }
    const pair = /^([\w-]+):\s*(.*)$/.exec(line);
    if (pair) {
      currentKey = pair[1];
      const value = pair[2].trim();
      data[currentKey] = value === ">-" || value === "|" || value === "" ? "" : value.replace(/^["']|["']$/g, "");
    } else if (currentKey && line.trim() && typeof data[currentKey] === "string") {
      data[currentKey] = `${data[currentKey]} ${line.trim()}`.trim();
    }
  }
  return data;
}

function listFiles(dir, predicate) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).filter(predicate).map((entry) => path.join(dir, entry.name));
}

function checkRules(root, findings) {
  const rulesDir = path.join(root, ".agents", "rules");
  const rules = listFiles(rulesDir, (entry) => entry.isFile() && entry.name.endsWith(".md"));
  if (rules.length === 0) findings.push({ level: "warn", area: "Rules", message: "Không có rule nào trong .agents/rules/" });
  for (const file of rules) {
    const name = path.basename(file);
    const meta = parseFrontmatter(fs.readFileSync(file, "utf8"));
    if (!meta) {
      findings.push({ level: "warn", area: "Rules", message: `${name}: thiếu frontmatter (trigger)` });
      continue;
    }
    if (!VALID_TRIGGERS.has(meta.trigger)) {
      findings.push({ level: "error", area: "Rules", message: `${name}: trigger "${meta.trigger}" không hợp lệ` });
    } else if (meta.trigger === "glob" && !(Array.isArray(meta.globs) && meta.globs.length)) {
      findings.push({ level: "error", area: "Rules", message: `${name}: trigger glob nhưng thiếu globs` });
    } else if (meta.trigger === "model_decision" && !meta.description) {
      findings.push({ level: "error", area: "Rules", message: `${name}: model_decision cần description` });
    }
  }
  findings.push({ level: "ok", area: "Rules", message: `${rules.length} rule đã kiểm tra` });
}

function checkSkills(root, findings) {
  const skillsDir = path.join(root, ".agents", "skills");
  const skills = listFiles(skillsDir, (entry) => entry.isDirectory());
  for (const dir of skills) {
    const folder = path.basename(dir);
    const skillFile = path.join(dir, "SKILL.md");
    if (!fs.existsSync(skillFile)) {
      findings.push({ level: "error", area: "Skills", message: `${folder}: thiếu SKILL.md` });
      continue;
    }
    const meta = parseFrontmatter(fs.readFileSync(skillFile, "utf8"));
    if (!meta?.name || !meta?.description) {
      findings.push({ level: "error", area: "Skills", message: `${folder}: SKILL.md cần name và description` });
    } else if (meta.name !== folder) {
      findings.push({ level: "warn", area: "Skills", message: `${folder}: name "${meta.name}" khác tên thư mục` });
    }
  }
  findings.push({ level: "ok", area: "Skills", message: `${skills.length} skill đã kiểm tra` });
}

function checkHooks(root, findings) {
  const hooksFile = path.join(root, ".agents", "hooks.json");
  if (!fs.existsSync(hooksFile)) {
    findings.push({ level: "info", area: "Hooks", message: "Không dùng hooks (profile minimal?)" });
    return;
  }
  let config;
  try {
    config = JSON.parse(fs.readFileSync(hooksFile, "utf8"));
  } catch (error) {
    findings.push({ level: "error", area: "Hooks", message: `hooks.json không phải JSON hợp lệ: ${error.message}` });
    return;
  }
  const commands = JSON.stringify(config).match(/node [^"]+?\.mjs/g) ?? [];
  for (const command of commands) {
    const script = path.join(root, ".agents", command.replace(/^node\s+/, ""));
    if (!fs.existsSync(script)) findings.push({ level: "error", area: "Hooks", message: `Thiếu script: ${command}` });
  }
  if (Array.isArray(config.hooks)) {
    findings.push({ level: "error", area: "Hooks", message: "hooks.json dùng schema cũ (mảng \"hooks\"); cần PreToolUse/PostToolUse/Stop" });
  }
  findings.push({ level: "ok", area: "Hooks", message: `hooks.json hợp lệ, ${commands.length} script` });
}

function checkVerify(root, findings) {
  const manifest = path.join(root, ".ai", "verify.json");
  if (!fs.existsSync(manifest)) {
    findings.push({ level: "warn", area: "Verify", message: "Thiếu .ai/verify.json" });
    return;
  }
  try {
    const { commands = [] } = JSON.parse(fs.readFileSync(manifest, "utf8"));
    const enabled = commands.filter((command) => command.enabled !== false);
    if (enabled.length === 0) {
      findings.push({ level: "info", area: "Verify", message: "Chưa bật lệnh kiểm chứng nào — bật khi dự án đã có lint/test/build" });
    } else {
      findings.push({ level: "ok", area: "Verify", message: `${enabled.length} lệnh kiểm chứng: ${enabled.map((command) => command.id).join(", ")}` });
    }
  } catch (error) {
    findings.push({ level: "error", area: "Verify", message: `verify.json lỗi: ${error.message}` });
  }
}

function checkSecrets(root, findings) {
  if (!fs.existsSync(path.join(root, ".env"))) return;
  const gitignore = fs.existsSync(path.join(root, ".gitignore")) ? fs.readFileSync(path.join(root, ".gitignore"), "utf8") : "";
  if (!/^\.env$/m.test(gitignore)) {
    findings.push({ level: "error", area: "Bảo mật", message: ".env tồn tại nhưng chưa nằm trong .gitignore" });
  } else {
    findings.push({ level: "ok", area: "Bảo mật", message: ".env đã được .gitignore" });
  }
}

function checkPorts(project, findings) {
  const reserved = getReservedPorts(project.id);
  for (const [key, port] of Object.entries(project.ports ?? {})) {
    if (reserved.has(port)) {
      findings.push({ level: "error", area: "Port", message: `${key}=${port} trùng với dự án "${reserved.get(port)}"` });
    }
  }
  const envFile = path.join(project.path, ".env");
  if (project.ports?.web && fs.existsSync(envFile)) {
    const match = /^APP_PORT=(\d+)/m.exec(fs.readFileSync(envFile, "utf8"));
    if (match && Number(match[1]) !== project.ports.web) {
      findings.push({ level: "warn", area: "Port", message: `.env APP_PORT=${match[1]} khác port đã cấp ${project.ports.web}` });
    }
  }
  findings.push({ level: "ok", area: "Port", message: "Đã kiểm tra xung đột port" });
}

/** Run every check for a registered project. */
export function runDoctor(project) {
  const root = project.path;
  const findings = [];
  if (!fs.existsSync(root)) {
    return [{ level: "error", area: "Thư mục", message: `Không tìm thấy ${root}` }];
  }

  const agentsFile = path.join(root, "AGENTS.md");
  if (!fs.existsSync(agentsFile)) {
    findings.push({ level: "error", area: "AGENTS.md", message: "Thiếu AGENTS.md" });
  } else if (fs.statSync(agentsFile).size > MAX_AGENTS_MD_BYTES) {
    findings.push({ level: "warn", area: "AGENTS.md", message: "AGENTS.md lớn hơn 12KB — nên tách bớt vào .agents/rules/" });
  } else {
    findings.push({ level: "ok", area: "AGENTS.md", message: "OK" });
  }

  const contextFile = path.join(root, "PROJECT_CONTEXT.md");
  if (!fs.existsSync(contextFile) || !fs.readFileSync(contextFile, "utf8").includes("HNC:BEGIN")) {
    findings.push({ level: "warn", area: "Context", message: "PROJECT_CONTEXT.md thiếu hoặc mất khối HNC — bấm Đồng bộ lại" });
  } else {
    findings.push({ level: "ok", area: "Context", message: "PROJECT_CONTEXT.md OK" });
  }

  checkRules(root, findings);
  checkSkills(root, findings);
  checkHooks(root, findings);
  checkVerify(root, findings);
  checkSecrets(root, findings);
  checkPorts(project, findings);

  if (project.templateVersion && project.templateVersion !== TEMPLATE_VERSION) {
    findings.push({ level: "info", area: "Template", message: `Dự án dùng template v${project.templateVersion}, hiện có v${TEMPLATE_VERSION}` });
  }
  return findings;
}
