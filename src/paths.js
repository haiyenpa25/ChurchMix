import path from "node:path";
import { fileURLToPath } from "node:url";

export const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const TEMPLATES_DIR = path.join(APP_ROOT, "templates");
export const PUBLIC_DIR = path.join(APP_ROOT, "public");
