// hainguyencoder:template=hooks/stop-quality-gate.mjs version=1.0.0
// Stop hook: when the agent wants to finish, run scripts/verify.mjs.
// If required checks fail, ask the agent to continue and fix them.
// Loop guard: at most MAX_RETRIES forced continuations per conversation.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAX_RETRIES = 2;
const HOOK_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HOOK_DIR, "..", "..");
const VERIFY_SCRIPT = path.join(PROJECT_ROOT, "scripts", "verify.mjs");

function allowStop() {
  process.stdout.write("{}");
  process.exit(0);
}

function readInput() {
  try {
    const raw = fs.readFileSync(0, "utf8");
    return raw.trim() ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function retryFile(conversationId) {
  const safeId = String(conversationId || "unknown").replace(/[^a-zA-Z0-9-]/g, "");
  return path.join(os.tmpdir(), `hainguyencoder-stop-${safeId}.json`);
}

function readRetryCount(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")).count ?? 0;
  } catch {
    return 0;
  }
}

function hasUncommittedChanges() {
  const result = spawnSync("git", ["status", "--porcelain"], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    timeout: 10000,
  });
  // Not a git repo (or git missing): assume there may be changes.
  if (result.status !== 0) return true;
  return result.stdout.trim().length > 0;
}

const input = readInput();

// Only gate a normal model stop; never fight errors or step limits.
if (input.terminationReason && input.terminationReason !== "model_stop") allowStop();
if (!fs.existsSync(VERIFY_SCRIPT)) allowStop();
if (!hasUncommittedChanges()) allowStop();

const counterFile = retryFile(input.conversationId);
const retries = readRetryCount(counterFile);
if (retries >= MAX_RETRIES) {
  fs.rmSync(counterFile, { force: true });
  allowStop();
}

const result = spawnSync(process.execPath, [VERIFY_SCRIPT, "--hook"], {
  cwd: PROJECT_ROOT,
  encoding: "utf8",
  timeout: 220000,
});
if (result.stdout) process.stderr.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);

if (result.status === 0) {
  fs.rmSync(counterFile, { force: true });
  allowStop();
}

fs.writeFileSync(counterFile, JSON.stringify({ count: retries + 1 }));
const summary = (result.stdout || "").split(/\r?\n/).filter((line) => line.includes("FAIL")).join("; ");
process.stdout.write(JSON.stringify({
  decision: "continue",
  reason: `Quality gate failed (attempt ${retries + 1}/${MAX_RETRIES}): ${summary || "see verify output"}. ` +
    "Run `node scripts/verify.mjs`, fix failures caused by your change, and do not modify unrelated code. " +
    "If a failure pre-existed your change, say so explicitly instead of fixing it.",
}));
