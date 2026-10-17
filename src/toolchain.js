/**
 * Toolchain detection & installation trigger.
 * Detection re-reads PATH from the registry on every check so tools installed
 * after the server started are recognized without restarting the app.
 * Installation is delegated to setup/install-tools.ps1 in a visible PowerShell
 * window (the user sees progress and any UAC prompt).
 */
import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { APP_ROOT } from "./paths.js";

const execFileAsync = promisify(execFile);
const SETUP_DIR = path.join(APP_ROOT, "setup");
const MANIFEST_FILE = path.join(SETUP_DIR, "tools.json");
const INSTALL_SCRIPT = path.join(SETUP_DIR, "install-tools.ps1");
export const TOOLS_REPORT_FILE = path.join(APP_ROOT, "data", "tools-report.json");
const PATH_CACHE_MS = 3000;

let cachedPath = { value: null, at: 0 };

export function loadToolManifest() {
  return JSON.parse(fs.readFileSync(MANIFEST_FILE, "utf8"));
}

function expandVariables(value) {
  return value.replace(/%([^%]+)%/g, (match, name) => process.env[name] ?? match);
}

/** Machine + User PATH straight from the registry (falls back to the process PATH). */
async function getFreshPath() {
  if (process.platform !== "win32") return process.env.PATH;
  if (cachedPath.value && Date.now() - cachedPath.at < PATH_CACHE_MS) return cachedPath.value;
  try {
    const script = "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')";
    const { stdout } = await execFileAsync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
      windowsHide: true, timeout: 10000,
    });
    cachedPath = { value: stdout.trim(), at: Date.now() };
  } catch (error) {
    console.error("[toolchain] cannot read registry PATH:", error.message);
    cachedPath = { value: process.env.Path ?? process.env.PATH, at: Date.now() };
  }
  return cachedPath.value;
}

function environmentWithPath(freshPath) {
  const env = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (key.toUpperCase() !== "PATH") env[key] = value;
  }
  env.Path = freshPath;
  return env;
}

async function detectTool(tool, env) {
  if (tool.detectPaths) {
    const found = tool.detectPaths.map(expandVariables).find((candidate) => fs.existsSync(candidate));
    return { installed: Boolean(found), version: found ? "đã cài" : null, source: found ?? null };
  }
  try {
    // cmd /c resolves .exe, .cmd and .bat shims (npm, composer.bat, clasp.cmd) the same way a terminal does.
    const { stdout, stderr } = await execFileAsync("cmd.exe", ["/d", "/c", tool.command, ...tool.versionArgs], {
      env, windowsHide: true, timeout: 15000,
    });
    const output = `${stdout}${stderr}`.trim();
    return { installed: Boolean(output), version: output.split(/\r?\n/)[0] || null, source: null };
  } catch {
    return { installed: false, version: null, source: null };
  }
}

/** Status of every tool in the manifest. */
export async function detectTools() {
  const manifest = loadToolManifest();
  const env = environmentWithPath(await getFreshPath());
  const statuses = await Promise.all(manifest.tools.map((tool) => detectTool(tool, env)));
  return manifest.tools.map((tool, index) => ({
    id: tool.id,
    label: tool.label,
    purpose: tool.purpose,
    required: Boolean(tool.required),
    heavy: Boolean(tool.heavy),
    dependsOn: tool.dependsOn ?? [],
    ...statuses[index],
  }));
}

/** Tool ids a project needs, based on its stacks and environment. */
export function requiredToolIds({ stacks = [], env = "none" }) {
  const manifest = loadToolManifest();
  const ids = new Set(["node", "git"]);
  for (const stack of stacks) (manifest.stackRequirements[stack] ?? []).forEach((id) => ids.add(id));
  (manifest.envRequirements[env] ?? []).forEach((id) => ids.add(id));
  // With XAMPP, PHP comes from XAMPP; a separate PHP install is not needed if XAMPP is present.
  return [...ids];
}

/** Missing tools for a project config, each with whether it blocks running the project. */
export async function missingToolsFor(config) {
  const needed = new Set(requiredToolIds(config));
  const statuses = await detectTools();
  return statuses.filter((tool) => needed.has(tool.id) && !tool.installed);
}

/** Launch the installer in a new, visible PowerShell window. */
export function launchInstaller(ids) {
  const manifest = loadToolManifest();
  const known = new Set(manifest.tools.map((tool) => tool.id));
  const selected = (Array.isArray(ids) ? ids : []).filter((id) => known.has(id));
  if (selected.length === 0) throw new Error("Chưa chọn công cụ hợp lệ nào");

  fs.mkdirSync(path.dirname(TOOLS_REPORT_FILE), { recursive: true });
  const child = spawn("powershell.exe", [
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", INSTALL_SCRIPT,
    "-Tools", selected.join(","), "-ReportPath", TOOLS_REPORT_FILE, "-PauseAtEnd",
  ], { detached: true, stdio: "ignore", windowsHide: false });
  child.on("error", (error) => console.error("[toolchain] installer failed to start:", error.message));
  child.unref();
  cachedPath = { value: null, at: 0 };
  return { started: selected };
}
