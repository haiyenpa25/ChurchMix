// hainguyencoder:template=scripts/verify.mjs version=1.0.0
// Unified verification entry point. Runs every command listed in .ai/verify.json.
// Usage: node scripts/verify.mjs [--hook]
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANIFEST = path.join(PROJECT_ROOT, ".ai", "verify.json");
const isHookMode = process.argv.includes("--hook");

function loadCommands() {
  if (!fs.existsSync(MANIFEST)) return [];
  try {
    const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    return Array.isArray(manifest.commands) ? manifest.commands.filter((entry) => entry.enabled !== false) : [];
  } catch (error) {
    console.log(`FAIL manifest: cannot parse .ai/verify.json (${error.message})`);
    process.exit(1);
  }
}

const commands = loadCommands();
if (commands.length === 0) {
  console.log("SKIP no verification commands configured in .ai/verify.json");
  process.exit(0);
}

let hasRequiredFailure = false;
for (const { id, command, required = true } of commands) {
  const started = Date.now();
  const result = spawnSync(command, {
    cwd: PROJECT_ROOT,
    shell: true,
    encoding: "utf8",
    stdio: isHookMode ? "pipe" : "inherit",
    timeout: 180000,
  });
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  const passed = result.status === 0;
  if (!passed && required) hasRequiredFailure = true;

  const label = passed ? "PASS" : required ? "FAIL" : "WARN";
  console.log(`${label} ${id} (${seconds}s): ${command}`);
  if (!passed && isHookMode) {
    const tail = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim().split(/\r?\n/).slice(-15).join("\n");
    if (tail) console.log(tail);
  }
}

process.exit(hasRequiredFailure ? 1 : 0);
