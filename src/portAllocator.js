/**
 * Port allocation: combines ports already reserved by registered projects with
 * ports currently LISTENING on this machine, then suggests free ones.
 */
import { execFile } from "node:child_process";
import net from "node:net";
import { promisify } from "node:util";
import { PORT_RANGES } from "./catalog.js";
import { listProjects } from "./storage.js";

const execFileAsync = promisify(execFile);

export const MIN_PORT = 1024;
export const MAX_PORT = 65535;

/** Ports in LISTENING state according to netstat (Windows) or an empty set elsewhere. */
export async function getListeningPorts() {
  if (process.platform !== "win32") return new Set();
  try {
    const { stdout } = await execFileAsync("netstat", ["-ano", "-p", "tcp"], { windowsHide: true, timeout: 8000 });
    const ports = new Set();
    for (const line of stdout.split(/\r?\n/)) {
      if (!/LISTENING/i.test(line)) continue;
      const localAddress = line.trim().split(/\s+/)[1] ?? "";
      const port = Number(localAddress.slice(localAddress.lastIndexOf(":") + 1));
      if (Number.isInteger(port)) ports.add(port);
    }
    return ports;
  } catch (error) {
    console.error("[ports] netstat failed:", error.message);
    return new Set();
  }
}

/** Fallback probe: can we bind the port right now? */
function canBind(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, "0.0.0.0");
  });
}

/** Map of port -> project name for every port reserved in the registry. */
export function getReservedPorts(excludeProjectId) {
  const reserved = new Map();
  for (const project of listProjects()) {
    if (project.id === excludeProjectId) continue;
    for (const port of Object.values(project.ports ?? {})) {
      if (Number.isInteger(port)) reserved.set(port, project.name);
    }
  }
  return reserved;
}

/**
 * Suggest one free port per requested key.
 * @param {string[]} keys e.g. ["web","db"]
 * @param {{excludeProjectId?: string, preferred?: Record<string, number>}} options
 */
export async function suggestPorts(keys, { excludeProjectId, preferred = {} } = {}) {
  const listening = await getListeningPorts();
  const reserved = getReservedPorts(excludeProjectId);
  const taken = new Set([...listening, ...reserved.keys()]);
  const result = {};

  for (const key of keys) {
    const wanted = preferred[key];
    if (Number.isInteger(wanted) && !taken.has(wanted)) {
      result[key] = wanted;
      taken.add(wanted);
      continue;
    }
    const [start, end] = PORT_RANGES[key];
    for (let port = start; port <= end; port += 1) {
      if (taken.has(port)) continue;
      if (!(await canBind(port))) {
        taken.add(port);
        continue;
      }
      result[key] = port;
      taken.add(port);
      break;
    }
  }
  return result;
}

/**
 * Validate user-chosen ports.
 * Returns per-key status: "ok" | "invalid" | "reserved" (other project) | "busy" (listening now) | "duplicate".
 */
export async function checkPorts(ports, { excludeProjectId } = {}) {
  const listening = await getListeningPorts();
  const reserved = getReservedPorts(excludeProjectId);
  const seen = new Map();
  const report = {};

  for (const [key, value] of Object.entries(ports)) {
    const port = Number(value);
    if (!Number.isInteger(port) || port < MIN_PORT || port > MAX_PORT) {
      report[key] = { port: value, status: "invalid", message: `Port phải trong khoảng ${MIN_PORT}-${MAX_PORT}` };
    } else if (seen.has(port)) {
      report[key] = { port, status: "duplicate", message: `Trùng với ${seen.get(port)}` };
    } else if (reserved.has(port)) {
      report[key] = { port, status: "reserved", message: `Đã cấp cho dự án "${reserved.get(port)}"` };
    } else if (listening.has(port)) {
      report[key] = { port, status: "busy", message: "Đang có tiến trình chiếm port này" };
    } else {
      report[key] = { port, status: "ok", message: "Trống" };
    }
    if (Number.isInteger(port)) seen.set(port, key);
  }
  return report;
}

export function hasBlockingPortIssue(report) {
  return Object.values(report).some((entry) => ["invalid", "duplicate", "reserved"].includes(entry.status));
}
