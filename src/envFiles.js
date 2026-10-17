/**
 * Generates environment files (Docker, XAMPP vhost, .env, .gitignore) from a
 * normalized project config. Ports are referenced through .env variables so a
 * port change only needs an .env update.
 */
import crypto from "node:crypto";
import path from "node:path";
import { primaryStack, STACKS } from "./catalog.js";

function randomSecret(length = 20) {
  return crypto.randomBytes(length).toString("base64url").slice(0, length);
}

export function databaseName(slug) {
  return slug.replace(/-/g, "_").slice(0, 60);
}

/** Lines that must exist in .gitignore. */
export function gitignoreLines(config) {
  const lines = [".env", ".env.local", "*.log"];
  if (config.stacks.includes("node") || config.stacks.includes("static")) lines.push("node_modules/", "dist/");
  if (config.stacks.includes("laravel") || config.stacks.includes("php")) lines.push("vendor/");
  if (config.stacks.includes("python")) lines.push(".venv/", "__pycache__/");
  if (config.stacks.includes("appsscript")) lines.push(".clasprc.json");
  return lines;
}

function envEntries(config, { withSecrets }) {
  const entries = [["APP_NAME", JSON.stringify(config.name)]];
  if (config.ports.web) entries.push(["APP_PORT", String(config.ports.web)]);
  if (config.needsDb) {
    const isXampp = config.env === "xampp";
    const dbPort = config.env === "none" && config.ports.db ? String(config.ports.db) : "3306";
    entries.push(
      ["DB_HOST", config.env === "docker" ? "db" : "127.0.0.1"],
      ["DB_PORT", dbPort],
      ["DB_DATABASE", databaseName(config.slug)],
      ["DB_USERNAME", isXampp ? "root" : "app"],
      ["DB_PASSWORD", isXampp ? "" : withSecrets ? randomSecret() : "change_me"],
    );
    if (config.env === "docker") {
      entries.push(["DB_ROOT_PASSWORD", withSecrets ? randomSecret() : "change_me"]);
      if (config.ports.db) entries.push(["DB_HOST_PORT", String(config.ports.db)]);
      if (config.ports.dbAdmin) entries.push(["DB_ADMIN_PORT", String(config.ports.dbAdmin)]);
    }
  }
  return entries;
}

export function renderEnv(config, { withSecrets }) {
  const header = withSecrets
    ? "# Local secrets — NEVER commit this file.\n"
    : "# Copy to .env and fill in real values. Safe to commit.\n";
  return header + envEntries(config, { withSecrets }).map(([key, value]) => `${key}=${value}`).join("\n") + "\n";
}

/** Replace KEY=value lines in an existing .env text, appending missing keys. */
export function updateEnvText(text, updates) {
  let result = text;
  for (const [key, value] of Object.entries(updates)) {
    const pattern = new RegExp(`^${key}=.*$`, "m");
    result = pattern.test(result) ? result.replace(pattern, `${key}=${value}`) : `${result.trimEnd()}\n${key}=${value}\n`;
  }
  return result;
}

function phpDockerfile(documentRoot) {
  const lines = [
    "FROM php:8.3-apache",
    "RUN docker-php-ext-install pdo_mysql mysqli && a2enmod rewrite",
  ];
  if (documentRoot) {
    lines.push(
      `ENV APACHE_DOCUMENT_ROOT=/var/www/html/${documentRoot}`,
      "RUN sed -ri -e 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/sites-available/*.conf \\",
      "    && sed -ri -e 's!/var/www/!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/apache2.conf /etc/apache2/conf-available/*.conf",
    );
  }
  lines.push("WORKDIR /var/www/html", "");
  return lines.join("\n");
}

function appService(config) {
  const stack = primaryStack(config.stacks);
  switch (stack) {
    case "php":
    case "laravel":
      return {
        files: [{ relPath: "docker/php/Dockerfile", content: phpDockerfile(STACKS[stack].documentRoot) }],
        yaml: [
          "  app:",
          "    build: ./docker/php",
          "    ports:",
          '      - "${APP_PORT}:80"',
          "    volumes:",
          "      - ./:/var/www/html",
        ],
      };
    case "node":
      return {
        files: [],
        yaml: [
          "  app:",
          "    image: node:22-alpine",
          "    working_dir: /app",
          '    command: sh -c "npm install && npm run dev -- --host 0.0.0.0 --port 3000"',
          "    environment:",
          "      - PORT=3000",
          "    ports:",
          '      - "${APP_PORT}:3000"',
          "    volumes:",
          "      - ./:/app",
          "      - node_modules:/app/node_modules",
        ],
        volumes: ["node_modules"],
      };
    case "python":
      return {
        files: [],
        yaml: [
          "  app:",
          "    image: python:3.12-slim",
          "    working_dir: /app",
          "    # Adjust the command to your framework (FastAPI shown; Django: python manage.py runserver 0.0.0.0:8000)",
          '    command: sh -c "pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"',
          "    ports:",
          '      - "${APP_PORT}:8000"',
          "    volumes:",
          "      - ./:/app",
        ],
      };
    default:
      return {
        files: [],
        yaml: [
          "  app:",
          "    image: nginx:1.27-alpine",
          "    ports:",
          '      - "${APP_PORT}:80"',
          "    volumes:",
          "      - ./:/usr/share/nginx/html:ro",
        ],
      };
  }
}

/** docker-compose.yml + supporting files. */
export function dockerFiles(config) {
  const app = appService(config);
  const volumes = [...(app.volumes ?? [])];
  const yaml = [`name: ${config.slug}`, "", "services:", ...app.yaml];

  if (config.needsDb) {
    yaml.push("    depends_on:", "      - db");
    yaml.push(
      "",
      "  db:",
      "    image: mysql:8.4",
      "    environment:",
      "      MYSQL_DATABASE: ${DB_DATABASE}",
      "      MYSQL_USER: ${DB_USERNAME}",
      "      MYSQL_PASSWORD: ${DB_PASSWORD}",
      "      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}",
      "    ports:",
      '      - "${DB_HOST_PORT}:3306"',
      "    volumes:",
      "      - db_data:/var/lib/mysql",
      "",
      "  phpmyadmin:",
      "    image: phpmyadmin:5",
      "    environment:",
      "      PMA_HOST: db",
      "    ports:",
      '      - "${DB_ADMIN_PORT}:80"',
      "    depends_on:",
      "      - db",
    );
    volumes.push("db_data");
  }

  if (volumes.length) {
    yaml.push("", "volumes:", ...volumes.map((volume) => `  ${volume}:`));
  }

  return [
    { relPath: "docker-compose.yml", content: `${yaml.join("\n")}\n` },
    ...app.files,
  ];
}

/** Apache vhost block for XAMPP; idempotent markers allow safe install/uninstall. */
export function xamppVhost(config) {
  const stack = primaryStack(config.stacks);
  const documentRoot = path.join(config.path, STACKS[stack].documentRoot).replace(/\\/g, "/");
  const port = config.ports.web;
  return [
    `# HNC:BEGIN ${config.slug}`,
    `Listen ${port}`,
    `<VirtualHost *:${port}>`,
    `    ServerName localhost`,
    `    DocumentRoot "${documentRoot}"`,
    `    <Directory "${documentRoot}">`,
    "        Options Indexes FollowSymLinks",
    "        AllowOverride All",
    "        Require all granted",
    "    </Directory>",
    `    ErrorLog "logs/${config.slug}-error.log"`,
    `    CustomLog "logs/${config.slug}-access.log" common`,
    "</VirtualHost>",
    `# HNC:END ${config.slug}`,
    "",
  ].join("\n");
}

/**
 * cmd.exe treats & | < > ^ % ! " ( ) specially and mis-decodes non-ASCII text
 * depending on the console code page, so names shown by run.bat are reduced to
 * plain ASCII ("Quản lý & Báo cáo" -> "Quan ly  Bao cao").
 */
function batSafeText(text) {
  const ascii = String(text)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .replace(/[^\x20-\x7E]/g, "")
    .replace(/[&|<>^%!"()]/g, "")
    .trim();
  return ascii || "Project";
}

const PHP_DETECT_LINES = [
  'set "PHP_CMD="',
  'where php >nul 2>nul && set "PHP_CMD=php"',
  'if not defined PHP_CMD if exist "C:\\xampp\\php\\php.exe" set "PHP_CMD=C:\\xampp\\php\\php.exe"',
  'if not defined PHP_CMD if exist "D:\\xampp\\php\\php.exe" set "PHP_CMD=D:\\xampp\\php\\php.exe"',
  'if not defined PHP_CMD if exist "E:\\xampp\\php\\php.exe" set "PHP_CMD=E:\\xampp\\php\\php.exe"',
  "if not defined PHP_CMD (",
  "  echo [LOI] Khong tim thay PHP tren may nay.",
  "  echo Chay setup.bat cua HAINGUYENCODER va chon cai PHP, roi chay lai file nay.",
  "  pause",
  "  exit /b 1",
  ")",
];

function stopWith(message) {
  return [`  echo [LOI] ${message}`, "  pause", "  exit /b 1", ")"];
}

function launchLines(primary, config) {
  switch (primary) {
    case "php":
      return [...PHP_DETECT_LINES, 'echo PHP: %PHP_CMD%', '"%PHP_CMD%" -S 127.0.0.1:%PORT% router.php'];
    case "laravel":
      return [
        ...PHP_DETECT_LINES,
        "if not exist artisan (",
        ...stopWith("Chua co ma nguon Laravel trong thu muc nay. Xem HUONG_DAN muc 'Laravel'."),
        "if not exist vendor (",
        ...stopWith("Chua cai thu vien. Chay: composer install"),
        '"%PHP_CMD%" artisan serve --host=127.0.0.1 --port=%PORT%',
      ];
    case "node":
      return [
        "if not exist package.json (",
        ...stopWith("Chua co package.json. Tao du an Node/React/Next truoc."),
        "if not exist node_modules call npm install",
        "call npm run dev -- --port %PORT%",
      ];
    case "python":
      return [
        'set "PY_CMD=python"',
        'if exist ".venv\\Scripts\\python.exe" set "PY_CMD=.venv\\Scripts\\python.exe"',
        'if exist manage.py ("%PY_CMD%" manage.py runserver 127.0.0.1:%PORT%) else ("%PY_CMD%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %PORT%)',
      ];
    default:
      return [`call npx -y serve -l %PORT%`];
  }
}

/**
 * One-click launcher for projects run without XAMPP. The port is read from
 * .env (APP_PORT) at runtime, so changing the port in HAINGUYENCODER does not
 * require regenerating this file. Written with CRLF: cmd.exe misparses
 * parenthesised blocks in LF-only batch files.
 */
export function runBat(config) {
  const primary = primaryStack(config.stacks);
  const name = batSafeText(config.name);
  const lines = [
    "@echo off",
    `REM hainguyencoder:template=run.bat - double-click to start ${name}`,
    "setlocal",
    'cd /d "%~dp0"',
    `title ${name}`,
    `set "PORT=${config.ports.web}"`,
    'if exist ".env" for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="APP_PORT" set "PORT=%%B"',
    "echo ========================================================",
    `echo   ${name}`,
    "echo   http://127.0.0.1:%PORT%   (dong cua so nay de tat server)",
    "echo ========================================================",
    'start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:%PORT%"',
    ...launchLines(primary, config),
    "pause",
    "",
  ];
  return lines.join("\r\n");
}

function phpSingleQuoted(text) {
  const html = String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  return `'${html.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

/**
 * Router for `php -S` (used by run.bat). Serves existing files as-is, sends
 * everything else to index.php, and refuses dotfiles such as .env and .git.
 * Apache/XAMPP ignore this file.
 */
export function routerPhp(config) {
  return `<?php
// hainguyencoder:template=router.php - router for the PHP built-in server started by run.bat.
$path = rawurldecode(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/');

// Never expose secrets or tooling folders (.env, .git, .agents, .ai, vendor ...).
if (preg_match('#(^|/)\\.#', $path) || preg_match('#^/(vendor|node_modules|scripts)(/|$)#i', $path)) {
    http_response_code(404);
    exit('Not found');
}

$target = __DIR__ . $path;
if ($path !== '/' && is_file($target)) {
    return false; // static asset or a .php script: let the built-in server handle it
}
if ($path !== '/' && is_dir($target) && is_file(rtrim($target, '/') . '/index.php')) {
    return false;
}
if (is_file(__DIR__ . '/index.php')) {
    require __DIR__ . '/index.php';
    return true;
}

header('Content-Type: text/html; charset=utf-8');
echo '<h1>' . ${phpSingleQuoted(config.name)} . '</h1>';
echo '<p>PHP server dang chay (khong can XAMPP). Tao file <code>index.php</code> de bat dau.</p>';
`;
}

