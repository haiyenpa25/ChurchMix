/**
 * Static catalog of supported stacks, environments and bootstrap profiles.
 * Everything the generator needs to decide WHICH templates to emit lives here,
 * so adding a new stack means editing data, not generator logic.
 */

export const TEMPLATE_VERSION = "1.0.0";

/** @typedef {"php"|"laravel"|"node"|"python"|"static"|"appsscript"} StackId */
/** @typedef {"xampp"|"docker"|"none"} EnvId */
/** @typedef {"minimal"|"balanced"|"strict"} ProfileId */

export const STACKS = {
  php: {
    label: "PHP thuần",
    rules: ["php", "frontend"],
    usesDb: true,
    documentRoot: "",
    supportedEnvs: ["xampp", "docker", "none"],
    runHint: "XAMPP: mở http://localhost:{{webPort}} sau khi cài vhost. Docker: docker compose up -d",
  },
  laravel: {
    label: "Laravel",
    rules: ["php", "laravel", "frontend"],
    usesDb: true,
    documentRoot: "public",
    supportedEnvs: ["xampp", "docker", "none"],
    runHint: "php artisan serve --port={{webPort}} (hoặc XAMPP vhost / Docker)",
    suggestedVerify: [
      { id: "format", kind: "format", command: "vendor\\bin\\pint --test" },
      { id: "test", kind: "test", command: "php artisan test" },
    ],
  },
  node: {
    label: "Node.js / React / Next.js",
    rules: ["typescript", "frontend"],
    usesDb: false,
    documentRoot: "",
    supportedEnvs: ["none", "docker"],
    runHint: "npm run dev -- --port {{webPort}}",
    suggestedVerify: [
      { id: "lint", kind: "lint", command: "npm run lint" },
      { id: "types", kind: "types", command: "npx --no-install tsc --noEmit" },
      { id: "test", kind: "test", command: "npm test" },
      { id: "build", kind: "build", command: "npm run build" },
    ],
  },
  python: {
    label: "Python (FastAPI / Django)",
    rules: ["python"],
    usesDb: true,
    documentRoot: "",
    supportedEnvs: ["none", "docker"],
    runHint: "FastAPI: uvicorn app.main:app --reload --port {{webPort}} | Django: python manage.py runserver {{webPort}}",
    suggestedVerify: [
      { id: "lint", kind: "lint", command: "ruff check ." },
      { id: "test", kind: "test", command: "pytest -q" },
    ],
  },
  static: {
    label: "HTML / CSS / JS tĩnh",
    rules: ["frontend", "typescript"],
    usesDb: false,
    documentRoot: "",
    supportedEnvs: ["xampp", "docker", "none"],
    runHint: "npx serve -l {{webPort}} (hoặc XAMPP vhost / Docker nginx)",
  },
  appsscript: {
    label: "Google Apps Script",
    rules: ["apps-script", "frontend"],
    usesDb: false,
    documentRoot: "",
    supportedEnvs: ["none"],
    runHint: "clasp push && clasp open (không cần port)",
  },
};

export const ENVIRONMENTS = {
  xampp: { label: "XAMPP" },
  docker: { label: "Docker" },
  none: { label: "Không (chạy trực tiếp)" },
};

/** Port ranges used when suggesting free ports. */
export const PORT_RANGES = {
  web: [8100, 8999],
  db: [33100, 33999],
  dbAdmin: [9100, 9999],
};

export const PORT_LABELS = {
  web: "Web / App",
  db: "Database (MySQL)",
  dbAdmin: "phpMyAdmin / Adminer",
};

export const CORE_SKILLS = [
  "code-change-verification",
  "code-review",
  "brainstorming",
  "test-driven-development",
  "targeted-refactor",
  "unit-test-generation",
  "root-cause-debugging",
  "browser-verification",
  "security-audit",
  "dependency-upgrade",
  "documentation-sync",
];


export const PROFILES = {
  minimal: {
    label: "Minimal — dự án nhỏ",
    sharedRules: [],
    skills: ["code-change-verification", "code-review"],
    agents: [],
    hooks: false,
  },
  balanced: {
    label: "Balanced — khuyến nghị",
    sharedRules: ["architecture", "security", "testing"],
    skills: CORE_SKILLS,
    agents: ["reviewer"],
    hooks: true,
  },
  strict: {
    label: "Strict — hệ thống quan trọng",
    sharedRules: ["architecture", "security", "testing"],
    skills: CORE_SKILLS,
    agents: ["reviewer", "test-engineer"],
    hooks: true,
    strictRule: true,
  },
};

/**
 * Which ports a project needs given its environment and stacks.
 * @param {EnvId} env
 * @param {StackId[]} stacks
 * @param {boolean} needsDb
 * @returns {Array<"web"|"db"|"dbAdmin">}
 */
export function requiredPortKeys(env, stacks, needsDb) {
  const onlyAppsScript = stacks.length > 0 && stacks.every((stack) => stack === "appsscript");
  if (onlyAppsScript) return [];
  if (env === "docker") return needsDb ? ["web", "db", "dbAdmin"] : ["web"];
  // XAMPP shares its own MySQL (3306) and phpMyAdmin; only the vhost port is per project.
  return ["web"];
}

/** Primary stack drives Docker images and document root. */
export function primaryStack(stacks) {
  const priority = ["laravel", "php", "python", "node", "static", "appsscript"];
  return priority.find((stack) => stacks.includes(stack)) ?? "static";
}
