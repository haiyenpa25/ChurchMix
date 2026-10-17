// hainguyencoder:template=hooks/post-edit-format.mjs version=1.0.0
// PostToolUse hook: formats the file the agent just wrote, using ONLY formatters
// already installed in the project. Never downloads packages.
// Contract: read JSON from stdin, write JSON ({}) to stdout, logs go to stderr.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HOOK_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HOOK_DIR, "..", "..");

function finish() {
  process.stdout.write("{}");
  process.exit(0);
}

function readInput() {
  try {
    const raw = fs.readFileSync(0, "utf8");
    return raw.trim() ? JSON.parse(raw) : {};
  } catch (error) {
    console.error("[post-edit-format] cannot parse hook input:", error.message);
    return {};
  }
}

function resolveTargetFile(input) {
  const args = input?.toolCall?.args ?? input?.toolInput ?? {};
  const candidate = args.TargetFile ?? args.targetFile ?? args.filePath ?? args.path ?? null;
  if (!candidate) return null;
  const absolute = path.resolve(PROJECT_ROOT, candidate);
  // Only touch files inside this project.
  if (!absolute.toLowerCase().startsWith(PROJECT_ROOT.toLowerCase())) return null;
  return fs.existsSync(absolute) ? absolute : null;
}

function runLocalBinary(relativeBinary, args) {
  const isWindows = process.platform === "win32";
  const candidates = isWindows
    ? [`${relativeBinary}.cmd`, `${relativeBinary}.bat`, relativeBinary]
    : [relativeBinary];
  const binary = candidates
    .map((candidate) => path.join(PROJECT_ROOT, candidate))
    .find((candidate) => fs.existsSync(candidate));
  if (!binary) return false;

  const result = spawnSync(binary, args, {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    shell: isWindows,
    timeout: 15000,
  });
  if (result.stdout) process.stderr.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  return result.status === 0;
}

function runPathBinary(binary, args) {
  const result = spawnSync(binary, args, {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    shell: process.platform === "win32",
    timeout: 15000,
  });
  if (result.stdout) process.stderr.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  return result.status === 0;
}

const PRETTIER_EXTENSIONS = new Set([
  ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".css", ".scss", ".html", ".vue", ".md",
]);

const targetFile = resolveTargetFile(readInput());
if (!targetFile) finish();

const extension = path.extname(targetFile).toLowerCase();
const quoted = process.platform === "win32" ? `"${targetFile}"` : targetFile;

if (PRETTIER_EXTENSIONS.has(extension)) {
  runLocalBinary(path.join("node_modules", ".bin", "prettier"), ["--write", quoted]);
} else if (extension === ".php") {
  runLocalBinary(path.join("vendor", "bin", "pint"), [quoted]);
} else if (extension === ".py") {
  // Ruff is a single binary; only used if it is already on PATH.
  runPathBinary("ruff", ["format", quoted]);
}

finish();
