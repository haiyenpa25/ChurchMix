/**
 * HAINGUYENCODER local server.
 * Zero dependencies: node:http serves the static UI and a small JSON API.
 * Security: binds to 127.0.0.1 only and rejects mutating requests from foreign origins,
 * because this API can write files on disk.
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { ENVIRONMENTS, PORT_LABELS, PROFILES, STACKS, TEMPLATE_VERSION } from "./src/catalog.js";
import { PUBLIC_DIR, TEMPLATES_DIR } from "./src/paths.js";
import { checkPorts } from "./src/portAllocator.js";
import { ValidationError } from "./src/projectGenerator.js";
import {
  NotFoundError, applyResync, createProject, doctorProject, installProjectVhost, openFolder,
  openProjectFolder, previewProject, previewResync, suggestProjectPorts, updateProject,
} from "./src/projectService.js";
import { detectProject } from "./src/stackDetector.js";
import { getSettings, listProjects, removeProject, saveSettings } from "./src/storage.js";
import { xamppStatus } from "./src/xampp.js";
import { TOOLS_REPORT_FILE, detectTools, launchInstaller, requiredToolIds } from "./src/toolchain.js";

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT) || 4590;
const MAX_BODY_BYTES = 1024 * 1024;

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json; charset=utf-8",
};

function sendJson(response, status, payload) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(payload));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new ValidationError("Request quá lớn"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (chunks.length === 0) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new ValidationError("Body không phải JSON hợp lệ"));
      }
    });
    request.on("error", reject);
  });
}

function isTrustedOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return request.headers["x-hnc"] === "1";
  try {
    const { hostname } = new URL(origin);
    return hostname === "127.0.0.1" || hostname === "localhost";
  } catch {
    return false;
  }
}

function listTemplateFiles() {
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(absolute);
      else files.push({ relPath: path.relative(TEMPLATES_DIR, absolute).replace(/\\/g, "/"), size: fs.statSync(absolute).size });
    }
  };
  walk(TEMPLATES_DIR);
  return files.sort((a, b) => a.relPath.localeCompare(b.relPath));
}

function readTemplateFile(relPath) {
  const absolute = path.resolve(TEMPLATES_DIR, relPath ?? "");
  if (!absolute.startsWith(TEMPLATES_DIR + path.sep) || !fs.existsSync(absolute)) throw new NotFoundError("Không tìm thấy template");
  return fs.readFileSync(absolute, "utf8");
}

/** Route table: [method, pattern, handler(params, body, url)] */
const routes = [
  ["GET", /^\/api\/catalog$/, () => ({
    stacks: Object.fromEntries(Object.entries(STACKS).map(([id, stack]) => [id, {
      label: stack.label, usesDb: stack.usesDb, supportedEnvs: stack.supportedEnvs,
    }])),
    environments: ENVIRONMENTS,
    profiles: Object.fromEntries(Object.entries(PROFILES).map(([id, profile]) => [id, {
      label: profile.label, skills: profile.skills.length, agents: profile.agents, hooks: profile.hooks,
    }])),
    portLabels: PORT_LABELS,
    templateVersion: TEMPLATE_VERSION,
  })],
  ["GET", /^\/api\/settings$/, () => ({ ...getSettings(), xampp: xamppStatus(getSettings().xamppPath) })],
  ["PUT", /^\/api\/settings$/, (_, body) => saveSettings(body)],
  ["GET", /^\/api\/projects$/, () => listProjects()],
  ["POST", /^\/api\/projects\/preview$/, (_, body) => previewProject(body)],
  ["POST", /^\/api\/projects$/, (_, body) => createProject(body)],
  ["PATCH", /^\/api\/projects\/([\w-]+)$/, ([id], body) => updateProject(id, body)],
  ["DELETE", /^\/api\/projects\/([\w-]+)$/, ([id]) => ({ removed: removeProject(id) })],
  ["POST", /^\/api\/projects\/([\w-]+)\/doctor$/, ([id]) => doctorProject(id)],
  ["POST", /^\/api\/projects\/([\w-]+)\/open$/, ([id]) => { openProjectFolder(id); return { ok: true }; }],
  ["POST", /^\/api\/projects\/([\w-]+)\/xampp$/, ([id]) => installProjectVhost(id)],
  ["POST", /^\/api\/projects\/([\w-]+)\/resync\/preview$/, ([id]) => previewResync(id)],
  ["POST", /^\/api\/projects\/([\w-]+)\/resync$/, ([id], body) => applyResync(id, body.overwrite)],
  ["POST", /^\/api\/ports\/suggest$/, (_, body) => suggestProjectPorts(body)],
  ["POST", /^\/api\/ports\/check$/, (_, body) => checkPorts(body.ports ?? {}, { excludeProjectId: body.excludeProjectId })],
  ["POST", /^\/api\/detect$/, (_, body) => {
    const folder = String(body.path ?? "").trim();
    if (!path.isAbsolute(folder) || !fs.existsSync(folder)) throw new ValidationError("Thư mục không tồn tại");
    return { ...detectProject(folder), suggestedName: path.basename(folder) };
  }],
  ["GET", /^\/api\/templates$/, () => listTemplateFiles()],
  ["GET", /^\/api\/templates\/file$/, (_, __, url) => ({ content: readTemplateFile(url.searchParams.get("path")) })],
  ["POST", /^\/api\/templates\/open$/, () => { openFolder(TEMPLATES_DIR); return { ok: true }; }],
  ["GET", /^\/api\/tools$/, async () => {
    const projects = listProjects();
    const tools = (await detectTools()).map((tool) => ({
      ...tool,
      neededBy: projects.filter((project) => requiredToolIds(project).includes(tool.id)).map((project) => project.name),
    }));
    return { tools, lastInstallReport: fs.existsSync(TOOLS_REPORT_FILE) ? fs.statSync(TOOLS_REPORT_FILE).mtime : null };
  }],
  ["POST", /^\/api\/tools\/install$/, (_, body) => launchInstaller(body.ids)],
];

async function handleApi(request, response, url) {
  if (request.method !== "GET" && !isTrustedOrigin(request)) {
    return sendJson(response, 403, { error: "Origin không được phép" });
  }
  const route = routes.find(([method, pattern]) => method === request.method && pattern.test(url.pathname));
  if (!route) return sendJson(response, 404, { error: "API không tồn tại" });

  try {
    const params = route[1].exec(url.pathname).slice(1);
    const body = ["POST", "PUT", "PATCH"].includes(request.method) ? await readBody(request) : {};
    const result = await route[2](params, body, url);
    sendJson(response, 200, result);
  } catch (error) {
    if (error instanceof ValidationError) return sendJson(response, 400, { error: error.message });
    if (error instanceof NotFoundError) return sendJson(response, 404, { error: error.message });
    console.error(`[api] ${request.method} ${url.pathname} failed:`, error);
    sendJson(response, 500, { error: error.message || "Lỗi máy chủ" });
  }
}

function serveStatic(response, url) {
  const relPath = url.pathname === "/" ? "index.html" : decodeURIComponent(url.pathname.slice(1));
  const absolute = path.resolve(PUBLIC_DIR, relPath);
  if (!absolute.startsWith(PUBLIC_DIR + path.sep) || !fs.existsSync(absolute) || fs.statSync(absolute).isDirectory()) {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    return response.end("Not found");
  }
  response.writeHead(200, { "Content-Type": MIME_TYPES[path.extname(absolute)] ?? "application/octet-stream" });
  fs.createReadStream(absolute).pipe(response);
}

const server = http.createServer((request, response) => {
  const url = new URL(request.url, `http://${HOST}:${PORT}`);
  if (url.pathname.startsWith("/api/")) return handleApi(request, response, url);
  serveStatic(response, url);
});

server.on("error", (error) => {
  if (error.code === "EADDRINUSE") {
    console.error(`Port ${PORT} đang bận. Chạy với port khác:  $env:PORT=4591; node server.js`);
    process.exit(1);
  }
  throw error;
});

server.listen(PORT, HOST, () => {
  console.log(`HAINGUYENCODER đang chạy tại http://${HOST}:${PORT}`);
});
