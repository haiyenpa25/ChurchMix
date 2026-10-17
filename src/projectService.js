/**
 * Application service layer: orchestrates validation, ports, generation,
 * registry and side effects. The HTTP layer only maps requests to these calls.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { TEMPLATE_VERSION, requiredPortKeys } from "./catalog.js";
import { runDoctor } from "./doctor.js";
import { updateEnvText, xamppVhost } from "./envFiles.js";
import { checkPorts, hasBlockingPortIssue, suggestPorts } from "./portAllocator.js";
import { mergeProjectContext } from "./projectContext.js";
import {
  ValidationError, applyFileSet, normalizeConfig, previewFileSet, toRegistryRecord,
} from "./projectGenerator.js";
import { findProjectByPath, getProject, getSettings, upsertProject } from "./storage.js";
import { installVhost } from "./xampp.js";
import { missingToolsFor } from "./toolchain.js";

export class NotFoundError extends Error {}

function requireProject(id) {
  const project = getProject(id);
  if (!project) throw new NotFoundError("Không tìm thấy dự án");
  return project;
}

function summarizePreview(files) {
  return files.map(({ relPath, status, strategy, content }) => ({
    relPath, status, strategy, size: content ? Buffer.byteLength(content) : 0,
  }));
}

async function assertPortsUsable(ports, excludeProjectId) {
  const report = await checkPorts(ports, { excludeProjectId });
  if (hasBlockingPortIssue(report)) {
    const problems = Object.entries(report)
      .filter(([, entry]) => ["invalid", "duplicate", "reserved"].includes(entry.status))
      .map(([key, entry]) => `${key} ${entry.port}: ${entry.message}`);
    throw new ValidationError(`Port không hợp lệ — ${problems.join("; ")}`);
  }
  return report;
}

export async function previewProject(input) {
  const config = normalizeConfig(input, getSettings());
  const existing = findProjectByPath(config.path);
  const portReport = await checkPorts(config.ports, { excludeProjectId: existing?.id });
  const files = previewFileSet(config);
  const warnings = [];
  if (config.mode === "new" && fs.existsSync(config.path)) warnings.push("Thư mục đích đã tồn tại — file trùng sẽ được đánh dấu xung đột.");
  if (existing) warnings.push(`Thư mục này đã được đăng ký là dự án "${existing.name}" — sẽ cập nhật bản ghi.`);
  const missingTools = await missingToolsFor(config);
  if (missingTools.length) {
    warnings.push(`Máy này chưa có: ${missingTools.map((tool) => tool.label).join(", ")} — vào trang "Môi trường máy" để cài.`);
  }
  return {
    config: { ...toRegistryRecord(config), detection: config.detection },
    files: summarizePreview(files), portReport, warnings, missingTools: missingTools.map((tool) => tool.id),
  };
}

export async function createProject(input) {
  const config = normalizeConfig(input, getSettings());
  const existing = findProjectByPath(config.path);
  await assertPortsUsable(config.ports, existing?.id);
  const summary = applyFileSet(config, Array.isArray(input.overwrite) ? input.overwrite : []);
  const project = upsertProject({ ...(existing ?? {}), ...toRegistryRecord(config) });
  return { project, summary };
}

export async function suggestProjectPorts({ env, stacks = [], needsDb, excludeProjectId }) {
  const keys = requiredPortKeys(env, stacks, Boolean(needsDb));
  return suggestPorts(keys, { excludeProjectId });
}

function rebuildConfig(project) {
  const settings = getSettings();
  return { ...project, mode: "existing", replyLanguage: settings.replyLanguage, verifyCommands: [], detection: null };
}

/** Update links / ports / name, then refresh the generated context and env files. */
export async function updateProject(id, patch) {
  const project = requireProject(id);
  const urlPattern = /^https?:\/\/\S+$/i;
  const next = { ...project };

  for (const key of ["sheetUrl", "githubUrl"]) {
    if (key in patch) {
      const value = String(patch[key] ?? "").trim();
      if (value && !urlPattern.test(value)) throw new ValidationError(`${key} phải là URL http(s)`);
      next[key] = value;
    }
  }
  if (typeof patch.name === "string" && patch.name.trim()) next.name = patch.name.trim().slice(0, 80);
  if (patch.ports && typeof patch.ports === "object") {
    const ports = {};
    for (const key of Object.keys(project.ports ?? {})) ports[key] = Number(patch.ports[key] ?? project.ports[key]);
    await assertPortsUsable(ports, id);
    next.ports = ports;
  }

  const changedFiles = [];
  if (fs.existsSync(project.path)) {
    const config = rebuildConfig(next);
    const contextFile = path.join(project.path, "PROJECT_CONTEXT.md");
    const existing = fs.existsSync(contextFile) ? fs.readFileSync(contextFile, "utf8") : null;
    fs.writeFileSync(contextFile, mergeProjectContext(existing, config), "utf8");
    changedFiles.push("PROJECT_CONTEXT.md");

    const envUpdates = {};
    if (next.ports.web) envUpdates.APP_PORT = next.ports.web;
    if (next.ports.db) envUpdates.DB_HOST_PORT = next.ports.db;
    if (next.ports.dbAdmin) envUpdates.DB_ADMIN_PORT = next.ports.dbAdmin;
    for (const envName of [".env", ".env.example"]) {
      const envFile = path.join(project.path, envName);
      if (Object.keys(envUpdates).length && fs.existsSync(envFile)) {
        fs.writeFileSync(envFile, updateEnvText(fs.readFileSync(envFile, "utf8"), envUpdates), "utf8");
        changedFiles.push(envName);
      }
    }
    if (next.env === "xampp" && next.ports.web) {
      const vhostFile = path.join(project.path, "xampp", "vhost.conf");
      fs.mkdirSync(path.dirname(vhostFile), { recursive: true });
      fs.writeFileSync(vhostFile, xamppVhost(config), "utf8");
      changedFiles.push("xampp/vhost.conf");
    }
  }

  return { project: upsertProject(next), changedFiles };
}

/** Preview re-applying current templates to a registered project. */
export function previewResync(id) {
  const project = requireProject(id);
  return { files: summarizePreview(previewFileSet(rebuildConfig(project))) };
}

export function applyResync(id, overwrite = []) {
  const project = requireProject(id);
  const summary = applyFileSet(rebuildConfig(project), overwrite);
  const updated = upsertProject({ ...project, templateVersion: TEMPLATE_VERSION });
  return { project: updated, summary };
}

export async function doctorProject(id) {
  const project = requireProject(id);
  const findings = runDoctor(project);
  const missing = await missingToolsFor(project);
  if (missing.length === 0) {
    findings.push({ level: "ok", area: "Công cụ", message: "Máy này đã có đủ công cụ cho dự án" });
  }
  for (const tool of missing) {
    const level = tool.id === "node" || tool.required ? "error" : "warn";
    findings.push({ level, area: "Công cụ", message: `Thiếu ${tool.label} — ${tool.purpose}` });
  }
  return findings;
}

export function openProjectFolder(id) {
  const project = requireProject(id);
  if (!fs.existsSync(project.path)) throw new NotFoundError("Thư mục dự án không tồn tại");
  openFolder(project.path);
}

export function openFolder(folder) {
  // explorer.exe returns exit code 1 even on success; fire and forget, no shell.
  const child = spawn("explorer.exe", [folder], { detached: true, stdio: "ignore", windowsHide: false });
  child.on("error", (error) => console.error("[open] explorer failed:", error.message));
  child.unref();
}

export function installProjectVhost(id) {
  const project = requireProject(id);
  if (project.env !== "xampp") throw new ValidationError("Dự án không dùng XAMPP");
  const config = rebuildConfig(project);
  return installVhost(getSettings().xamppPath, project.slug, xamppVhost(config));
}
