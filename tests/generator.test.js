import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { runDoctor, parseFrontmatter } from "../src/doctor.js";
import { mergeProjectContext } from "../src/projectContext.js";
import {
  ValidationError, applyFileSet, buildFileSet, normalizeConfig, previewFileSet, slugify,
} from "../src/projectGenerator.js";

const SETTINGS = { projectsRoot: os.tmpdir(), replyLanguage: "Vietnamese", defaultProfile: "balanced" };

function tempRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "hnc-test-"));
}

function makeConfig(overrides = {}) {
  const root = tempRoot();
  return normalizeConfig({
    mode: "new",
    name: "Quản lý Đội nhóm",
    projectsRoot: root,
    stacks: ["laravel"],
    env: "docker",
    needsDb: true,
    ports: { web: 8123, db: 33123, dbAdmin: 9123 },
    profile: "balanced",
    sheetUrl: "https://docs.google.com/spreadsheets/d/abc",
    ...overrides,
  }, SETTINGS);
}

test("slugify strips Vietnamese diacritics", () => {
  assert.equal(slugify("Quản lý Đội nhóm Hội Thánh"), "quan-ly-doi-nhom-hoi-thanh");
  assert.equal(slugify("  ##  "), "");
});

test("normalizeConfig validates required input", () => {
  assert.throws(() => normalizeConfig({ name: "", stacks: ["php"] }, SETTINGS), ValidationError);
  assert.throws(() => normalizeConfig({ name: "x", stacks: [] }, SETTINGS), ValidationError);
  assert.throws(() => makeConfig({ sheetUrl: "javascript:alert(1)" }), ValidationError);
  assert.throws(() => makeConfig({ env: "xampp", stacks: ["node"] }), /không hỗ trợ/);
});

test("apps script needs no ports and forces env none", () => {
  const config = makeConfig({ stacks: ["appsscript"], env: "docker", ports: {} });
  assert.equal(config.env, "none");
  assert.deepEqual(config.ports, {});
});

test("balanced laravel/docker file set contains expected files", () => {
  const files = buildFileSet(makeConfig()).map((file) => file.relPath);
  for (const expected of [
    "AGENTS.md", "DESIGN.md", "PROJECT_CONTEXT.md", ".agents/rules/personal.md", ".agents/rules/laravel.md",
    ".agents/rules/database-migrations.md", ".agents/rules/docker.md", ".agents/skills/code-review/SKILL.md",
    ".agents/skills/brainstorming/SKILL.md", ".agents/skills/test-driven-development/SKILL.md",
    ".agents/skills/browser-verification/SKILL.md",
    ".agents/hooks.json", ".agents/agents/reviewer.md", "docker-compose.yml", "docker/php/Dockerfile",
    ".env", ".env.example", ".gitignore", ".ai/verify.json", "scripts/verify.mjs",
  ]) {
    assert.ok(files.includes(expected), `missing ${expected}`);
  }
  assert.ok(!files.includes("xampp/vhost.conf"));
});

test("run.bat is CRLF, cmd-safe and reads the port from .env", () => {
  const config = makeConfig({ name: "Quản lý & Báo cáo 100% (v2)", stacks: ["php"], env: "none", needsDb: false, ports: { web: 8124 } });
  const files = buildFileSet(config);
  const bat = files.find((file) => file.relPath === "run.bat").content;
  assert.ok(!/[^\r]\n/.test(bat), "every line must end with CRLF");
  assert.ok(!bat.includes("\\\\"), "paths must use single backslashes");
  assert.match(bat, /^title Quan ly  Bao cao 100 v2\r$/m, "name must be ASCII and free of & % ( )");
  assert.match(bat, /set "PORT=8124"/);
  assert.match(bat, /APP_PORT/);
  assert.match(bat, /-S 127\.0\.0\.1:%PORT% router\.php/);

  const router = files.find((file) => file.relPath === "router.php").content;
  assert.ok(router.includes("preg_match('#(^|/)\\.#', $path)"), "router must refuse dotfiles like .env");
  assert.ok(router.includes("'Quản lý &amp; Báo cáo 100% (v2)'"), "name must be HTML-escaped inside a single-quoted PHP string");
});

test("router.php only for plain PHP; laravel run.bat uses artisan", () => {
  const files = buildFileSet(makeConfig({ env: "none", needsDb: false, ports: { web: 8125 } }));
  assert.ok(!files.some((file) => file.relPath === "router.php"));
  assert.match(files.find((file) => file.relPath === "run.bat").content, /artisan serve --host=127\.0\.0\.1 --port=%PORT%/);
});

test("projects root on a missing drive gives a clear error", () => {
  assert.throws(() => makeConfig({ projectsRoot: "Q:\\nope" }), /Ổ đĩa Q:\\ không có/);
});


test("minimal profile has no hooks and only two skills", () => {
  const files = buildFileSet(makeConfig({ profile: "minimal" })).map((file) => file.relPath);
  assert.ok(!files.includes(".agents/hooks.json"));
  assert.equal(files.filter((file) => file.endsWith("SKILL.md")).length, 2);
});

test("apply writes files, never overwrites conflicts unless approved, keeps .env", () => {
  const config = makeConfig();
  const first = applyFileSet(config);
  assert.ok(first.written.includes("AGENTS.md"));

  const agentsFile = path.join(config.path, "AGENTS.md");
  fs.writeFileSync(agentsFile, "custom content");
  const envBefore = fs.readFileSync(path.join(config.path, ".env"), "utf8");

  const preview = previewFileSet(config);
  assert.equal(preview.find((file) => file.relPath === "AGENTS.md").status, "conflict");
  assert.equal(preview.find((file) => file.relPath === ".env").status, "keep");

  applyFileSet(config);
  assert.equal(fs.readFileSync(agentsFile, "utf8"), "custom content");
  assert.equal(fs.readFileSync(path.join(config.path, ".env"), "utf8"), envBefore);

  applyFileSet(config, ["AGENTS.md"]);
  assert.notEqual(fs.readFileSync(agentsFile, "utf8"), "custom content");
});

test("generated hooks.json follows the documented schema", () => {
  const config = makeConfig();
  applyFileSet(config);
  const hooks = JSON.parse(fs.readFileSync(path.join(config.path, ".agents", "hooks.json"), "utf8"));
  const spec = hooks["hainguyencoder-quality"];
  assert.ok(Array.isArray(spec.PostToolUse) && spec.PostToolUse[0].matcher);
  assert.ok(Array.isArray(spec.Stop) && spec.Stop[0].command);
});

test("hook scripts always print valid JSON", () => {
  const config = makeConfig();
  applyFileSet(config);
  const hooksDir = path.join(config.path, ".agents");
  for (const [script, input] of [
    ["hooks/post-edit-format.mjs", { toolCall: { args: { TargetFile: path.join(config.path, "AGENTS.md") } } }],
    ["hooks/post-edit-format.mjs", {}],
    ["hooks/stop-quality-gate.mjs", { conversationId: "test-1", terminationReason: "model_stop" }],
  ]) {
    const result = spawnSync(process.execPath, [script], { cwd: hooksDir, input: JSON.stringify(input), encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    assert.doesNotThrow(() => JSON.parse(result.stdout), `${script} stdout: ${result.stdout}`);
  }
});

test("stop gate asks to continue when a required check fails, with loop guard", () => {
  const config = makeConfig();
  applyFileSet(config);
  fs.writeFileSync(path.join(config.path, ".ai", "verify.json"), JSON.stringify({
    commands: [{ id: "fail", kind: "test", command: "node -e \"process.exit(1)\"", required: true }],
  }));
  const hooksDir = path.join(config.path, ".agents");
  const run = () => JSON.parse(spawnSync(process.execPath, ["hooks/stop-quality-gate.mjs"], {
    cwd: hooksDir, input: JSON.stringify({ conversationId: `loop-${Date.now()}`, terminationReason: "model_stop" }), encoding: "utf8",
  }).stdout);
  const id = `loop-${process.pid}`;
  const runWithId = () => JSON.parse(spawnSync(process.execPath, ["hooks/stop-quality-gate.mjs"], {
    cwd: hooksDir, input: JSON.stringify({ conversationId: id, terminationReason: "model_stop" }), encoding: "utf8",
  }).stdout);
  assert.equal(run().decision, "continue");
  assert.equal(runWithId().decision, "continue");
  assert.equal(runWithId().decision, "continue");
  assert.equal(runWithId().decision, undefined, "third attempt must allow stop");
});

test("PROJECT_CONTEXT merge preserves user notes", () => {
  const config = makeConfig();
  const initial = mergeProjectContext(null, config);
  const edited = `${initial}\nMy business notes here.\n`;
  const regenerated = mergeProjectContext(edited, { ...config, githubUrl: "https://github.com/a/b" });
  assert.ok(regenerated.includes("My business notes here."));
  assert.ok(regenerated.includes("https://github.com/a/b"));
  assert.equal(regenerated.match(/HNC:BEGIN/g).length, 1);
});

test("doctor reports no errors on a freshly generated project", () => {
  const config = makeConfig();
  applyFileSet(config);
  const findings = runDoctor({ id: "test", path: config.path, ports: {}, templateVersion: "1.0.0" });
  const errors = findings.filter((finding) => finding.level === "error");
  assert.deepEqual(errors, []);
});

test("every template rule and skill has valid frontmatter", () => {
  const templates = path.resolve("templates");
  for (const file of fs.readdirSync(path.join(templates, "rules"))) {
    const meta = parseFrontmatter(fs.readFileSync(path.join(templates, "rules", file), "utf8"));
    assert.ok(meta?.trigger, `${file} missing trigger`);
  }
  for (const dir of fs.readdirSync(path.join(templates, "skills"))) {
    const meta = parseFrontmatter(fs.readFileSync(path.join(templates, "skills", dir, "SKILL.md"), "utf8"));
    assert.equal(meta?.name, dir);
    assert.ok(meta.description.length > 40);
  }
});
