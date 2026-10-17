/**
 * JSON-file persistence for app settings and the project registry.
 * Writes are atomic (temp file + rename) so a crash never leaves half-written JSON.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { APP_ROOT } from "./paths.js";

const DATA_DIR = path.join(APP_ROOT, "data");
const SETTINGS_FILE = path.join(DATA_DIR, "settings.json");
const PROJECTS_FILE = path.join(DATA_DIR, "projects.json");

const XAMPP_CANDIDATES = ["C:\\xampp", "D:\\xampp", "E:\\xampp"];

function detectXamppPath() {
  return XAMPP_CANDIDATES.find((candidate) => fs.existsSync(path.join(candidate, "apache"))) ?? "C:\\xampp";
}

/** D:\HAINGUYEN\PROJECTS on the original machine; %USERPROFILE%\Projects where there is no D: drive. */
function defaultProjectsRoot() {
  return fs.existsSync("D:\\") ? "D:\\HAINGUYEN\\PROJECTS" : path.join(os.homedir(), "Projects");
}

const DEFAULT_SETTINGS = {
  projectsRoot: defaultProjectsRoot(),
  xamppPath: null,
  replyLanguage: "Vietnamese",
  defaultProfile: "balanced",
};

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") console.error(`[storage] cannot read ${file}:`, error.message);
    return fallback;
  }
}

function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tempFile = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tempFile, JSON.stringify(value, null, 2), "utf8");
  fs.renameSync(tempFile, file);
}

export function getSettings() {
  const stored = readJson(SETTINGS_FILE, {});
  const settings = { ...DEFAULT_SETTINGS, ...stored };
  if (!settings.xamppPath) settings.xamppPath = detectXamppPath();
  return settings;
}

export function saveSettings(partial) {
  const allowedKeys = Object.keys(DEFAULT_SETTINGS);
  const next = { ...getSettings() };
  for (const key of allowedKeys) {
    if (typeof partial[key] === "string" && partial[key].trim()) next[key] = partial[key].trim();
  }
  writeJsonAtomic(SETTINGS_FILE, next);
  return next;
}

export function listProjects() {
  return readJson(PROJECTS_FILE, []);
}

export function getProject(id) {
  return listProjects().find((project) => project.id === id) ?? null;
}

export function findProjectByPath(projectPath) {
  const normalized = path.resolve(projectPath).toLowerCase();
  return listProjects().find((project) => path.resolve(project.path).toLowerCase() === normalized) ?? null;
}

/** Insert or update a project record; returns the stored record. */
export function upsertProject(record) {
  const projects = listProjects();
  const now = new Date().toISOString();
  const index = projects.findIndex((project) => project.id === record.id);
  if (index === -1) {
    const created = { ...record, id: record.id ?? crypto.randomUUID(), createdAt: now, updatedAt: now };
    projects.push(created);
    writeJsonAtomic(PROJECTS_FILE, projects);
    return created;
  }
  projects[index] = { ...projects[index], ...record, updatedAt: now };
  writeJsonAtomic(PROJECTS_FILE, projects);
  return projects[index];
}

export function removeProject(id) {
  const projects = listProjects();
  const remaining = projects.filter((project) => project.id !== id);
  writeJsonAtomic(PROJECTS_FILE, remaining);
  return remaining.length !== projects.length;
}
