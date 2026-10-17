/**
 * Detects the stack of an existing folder and the verification commands
 * that actually exist (we never invent `npm run lint` if there is no lint script).
 */
import fs from "node:fs";
import path from "node:path";

const IGNORED_DIRS = new Set(["node_modules", "vendor", ".git", ".venv", "venv", "__pycache__", "dist", "build"]);

function readJsonSafe(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function exists(root, relative) {
  return fs.existsSync(path.join(root, relative));
}

/** Shallow scan (depth 2) for file extensions, skipping heavy dirs. */
function collectExtensions(root, depth = 2) {
  const extensions = new Set();
  const walk = (dir, level) => {
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (level < depth && !IGNORED_DIRS.has(entry.name) && !entry.name.startsWith(".")) {
          walk(path.join(dir, entry.name), level + 1);
        }
      } else {
        extensions.add(path.extname(entry.name).toLowerCase());
      }
    }
  };
  walk(root, 0);
  return extensions;
}

/**
 * @param {string} root absolute folder path
 * @returns {{stacks: string[], details: string[], verifyCommands: object[], hasDocker: boolean, hasGit: boolean}}
 */
export function detectProject(root) {
  const stacks = new Set();
  const details = [];
  const verifyCommands = [];

  const packageJson = readJsonSafe(path.join(root, "package.json"));
  const composerJson = readJsonSafe(path.join(root, "composer.json"));
  const extensions = collectExtensions(root);

  if (composerJson) {
    const requires = { ...composerJson.require, ...composerJson["require-dev"] };
    if (requires["laravel/framework"] || exists(root, "artisan")) {
      stacks.add("laravel");
      details.push("Laravel (composer.json)");
      verifyCommands.push({ id: "test", kind: "test", command: "php artisan test", required: true });
      if (exists(root, "vendor/bin/pint")) {
        verifyCommands.push({ id: "format", kind: "format", command: "vendor\\bin\\pint --test", required: false });
      }
    } else {
      stacks.add("php");
      details.push("PHP + Composer");
    }
    if (composerJson.scripts?.test && !stacks.has("laravel")) {
      verifyCommands.push({ id: "test", kind: "test", command: "composer test", required: true });
    }
  } else if (extensions.has(".php")) {
    stacks.add("php");
    details.push("PHP thuần (file .php)");
  }

  if (packageJson) {
    const deps = { ...packageJson.dependencies, ...packageJson.devDependencies };
    const framework = ["next", "react", "vue", "vite", "express", "@nestjs/core"].filter((name) => deps[name]);
    // A Laravel app's package.json is only for asset bundling; don't treat it as a Node project.
    if (!stacks.has("laravel") || framework.includes("next")) stacks.add("node");
    details.push(`Node.js${framework.length ? ` (${framework.join(", ")})` : ""}`);
    if (deps.typescript || exists(root, "tsconfig.json")) details.push("TypeScript");

    const scripts = packageJson.scripts ?? {};
    const scriptMap = [
      ["format", "format", ["format:check", "prettier:check"]],
      ["lint", "lint", ["lint"]],
      ["types", "types", ["typecheck", "type-check", "tsc"]],
      ["test", "test", ["test"]],
      ["build", "build", ["build"]],
    ];
    for (const [id, kind, candidates] of scriptMap) {
      const found = candidates.find((name) => scripts[name]);
      if (!found) continue;
      if (found === "test" && /no test specified/i.test(scripts.test)) continue;
      const command = found === "test" ? "npm test" : `npm run ${found}`;
      verifyCommands.push({ id, kind, command, required: kind !== "build" });
    }
  }

  const pyproject = exists(root, "pyproject.toml") ? fs.readFileSync(path.join(root, "pyproject.toml"), "utf8") : "";
  const requirements = exists(root, "requirements.txt") ? fs.readFileSync(path.join(root, "requirements.txt"), "utf8") : "";
  if (pyproject || requirements || exists(root, "manage.py") || extensions.has(".py")) {
    stacks.add("python");
    const text = `${pyproject}\n${requirements}`.toLowerCase();
    const framework = ["fastapi", "django", "flask"].filter((name) => text.includes(name));
    details.push(`Python${framework.length ? ` (${framework.join(", ")})` : ""}`);
    if (text.includes("pytest")) verifyCommands.push({ id: "test", kind: "test", command: "pytest -q", required: true });
    if (text.includes("ruff")) verifyCommands.push({ id: "lint", kind: "lint", command: "ruff check .", required: true });
  }

  if (exists(root, "appsscript.json") || exists(root, ".clasp.json") || extensions.has(".gs")) {
    stacks.add("appsscript");
    details.push("Google Apps Script");
  }

  if (stacks.size === 0 && (extensions.has(".html") || extensions.has(".css"))) {
    stacks.add("static");
    details.push("HTML/CSS/JS tĩnh");
  }

  const hasDocker = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "Dockerfile"]
    .some((file) => exists(root, file));
  if (hasDocker) details.push("Docker");

  return { stacks: [...stacks], details, verifyCommands, hasDocker, hasGit: exists(root, ".git") };
}
