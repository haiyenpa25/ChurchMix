/**
 * Installs/uninstalls a project's vhost block into XAMPP's httpd-vhosts.conf.
 * Always backs up the file first and uses HNC markers so the operation is idempotent.
 */
import fs from "node:fs";
import path from "node:path";

function vhostsFile(xamppPath) {
  return path.join(xamppPath, "apache", "conf", "extra", "httpd-vhosts.conf");
}

function stripBlock(text, slug) {
  const pattern = new RegExp(`\\r?\\n?# HNC:BEGIN ${slug}\\r?\\n[\\s\\S]*?# HNC:END ${slug}\\r?\\n?`, "g");
  return text.replace(pattern, "\n");
}

function backup(file) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backupFile = `${file}.hnc-backup-${stamp}`;
  fs.copyFileSync(file, backupFile);
  return backupFile;
}

export function xamppStatus(xamppPath) {
  const file = vhostsFile(xamppPath);
  const httpdConf = path.join(xamppPath, "apache", "conf", "httpd.conf");
  const includesVhosts = fs.existsSync(httpdConf)
    && /^\s*Include\s+conf\/extra\/httpd-vhosts\.conf/m.test(fs.readFileSync(httpdConf, "utf8"));
  return { installed: fs.existsSync(file), vhostsFile: file, includesVhosts };
}

/** @returns {{vhostsFile: string, backupFile: string, warnings: string[]}} */
export function installVhost(xamppPath, slug, block) {
  const status = xamppStatus(xamppPath);
  if (!status.installed) throw new Error(`Không tìm thấy ${status.vhostsFile}. Kiểm tra đường dẫn XAMPP trong Cài đặt.`);
  const warnings = [];
  if (!status.includesVhosts) warnings.push("httpd.conf chưa Include conf/extra/httpd-vhosts.conf — hãy bỏ dấu # ở dòng đó.");

  const current = fs.readFileSync(status.vhostsFile, "utf8");
  const backupFile = backup(status.vhostsFile);
  const next = `${stripBlock(current, slug).trimEnd()}\n\n${block}`;
  fs.writeFileSync(status.vhostsFile, next, "utf8");
  warnings.push("Restart Apache trong XAMPP Control Panel để áp dụng.");
  return { vhostsFile: status.vhostsFile, backupFile, warnings };
}

export function uninstallVhost(xamppPath, slug) {
  const status = xamppStatus(xamppPath);
  if (!status.installed) return { removed: false };
  const current = fs.readFileSync(status.vhostsFile, "utf8");
  if (!current.includes(`# HNC:BEGIN ${slug}`)) return { removed: false };
  const backupFile = backup(status.vhostsFile);
  fs.writeFileSync(status.vhostsFile, stripBlock(current, slug), "utf8");
  return { removed: true, backupFile };
}
