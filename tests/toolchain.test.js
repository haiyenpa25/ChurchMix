import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { ENVIRONMENTS, STACKS } from "../src/catalog.js";
import { detectTools, loadToolManifest, requiredToolIds } from "../src/toolchain.js";

test("tool manifest covers every stack and environment with known tool ids", () => {
  const manifest = loadToolManifest();
  const ids = new Set(manifest.tools.map((tool) => tool.id));
  for (const stack of Object.keys(STACKS)) assert.ok(stack in manifest.stackRequirements, `missing stack ${stack}`);
  for (const env of Object.keys(ENVIRONMENTS)) assert.ok(env in manifest.envRequirements, `missing env ${env}`);
  const referenced = [
    ...Object.values(manifest.stackRequirements).flat(),
    ...Object.values(manifest.envRequirements).flat(),
    ...manifest.tools.flatMap((tool) => tool.dependsOn ?? []),
  ];
  for (const id of referenced) assert.ok(ids.has(id), `unknown tool ${id}`);
  for (const tool of manifest.tools) {
    assert.ok(tool.command || tool.detectPaths, `${tool.id} has no detection method`);
    assert.ok(tool.install?.type, `${tool.id} has no install method`);
  }
});

test("requiredToolIds combines stack and environment requirements", () => {
  assert.deepEqual(new Set(requiredToolIds({ stacks: ["laravel"], env: "docker" })), new Set(["node", "git", "php", "composer", "docker"]));
  assert.deepEqual(new Set(requiredToolIds({ stacks: ["appsscript"], env: "none" })), new Set(["node", "git", "clasp"]));
});

test("detectTools finds node on this machine", { skip: process.platform !== "win32" }, async () => {
  const tools = await detectTools();
  const node = tools.find((tool) => tool.id === "node");
  assert.equal(node.installed, true);
  assert.match(node.version, /^v\d+/);
});

test("root launchers are CRLF + ASCII so cmd.exe parses them on any machine", () => {
  for (const file of ["setup.bat", "start.bat", "pack.bat", "start_church_engineer.bat"]) {
    const bytes = fs.readFileSync(file);
    const text = bytes.toString("latin1");
    assert.ok(!/[^\r]\n/.test(text), `${file} has LF-only line endings`);
    assert.ok(!bytes.some((byte) => byte > 127), `${file} must be ASCII-only`);
  }
  const bom = fs.readFileSync("setup/install-tools.ps1").subarray(0, 3).toString("hex");
  assert.equal(bom, "efbbbf", "install-tools.ps1 needs a UTF-8 BOM for Windows PowerShell 5.1");
});
