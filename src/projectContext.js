/**
 * PROJECT_CONTEXT.md: the single file an agent reads to understand the project
 * (links, stack, ports, run commands). The block between HNC markers is managed
 * by HAINGUYENCODER; anything outside it is preserved on regeneration.
 */
import { ENVIRONMENTS, PORT_LABELS, primaryStack, STACKS, TEMPLATE_VERSION } from "./catalog.js";
import { databaseName } from "./envFiles.js";

export const BEGIN_MARKER = "<!-- HNC:BEGIN managed by HAINGUYENCODER — edit via the app, not by hand -->";
export const END_MARKER = "<!-- HNC:END -->";

function linkOrDash(url) {
  return url ? `<${url}>` : "_(chưa có — cập nhật trong HAINGUYENCODER)_";
}

function fillPort(text, ports) {
  return text.replace(/\{\{webPort\}\}/g, ports.web ?? "<port>");
}

function runSection(config) {
  const lines = [];
  if (config.env === "docker") {
    lines.push("```powershell", "docker compose up -d        # khởi động", "docker compose logs -f app   # xem log", "docker compose down          # dừng (KHÔNG dùng -v: sẽ xóa dữ liệu DB)", "```");
  } else if (config.env === "xampp") {
    lines.push(
      "1. Bật Apache (và MySQL nếu cần) trong XAMPP Control Panel.",
      "2. Cài vhost bằng nút **Cài vhost XAMPP** trong HAINGUYENCODER (hoặc copy `xampp/vhost.conf` vào `apache/conf/extra/httpd-vhosts.conf`), rồi restart Apache.",
      `3. Mở http://localhost:${config.ports.web}`,
    );
  }
  for (const stack of config.stacks) {
    lines.push(`- **${STACKS[stack].label}:** ${fillPort(STACKS[stack].runHint, config.ports)}`);
  }
  return lines.join("\n");
}

export function renderManagedBlock(config) {
  const portRows = Object.entries(config.ports)
    .filter(([, port]) => port)
    .map(([key, port]) => `| ${PORT_LABELS[key] ?? key} | \`${port}\` |`);
  if (config.env === "xampp" && config.needsDb) portRows.push("| MySQL (XAMPP, dùng chung) | `3306` |");

  const lines = [
    BEGIN_MARKER,
    `# ${config.name}`,
    "",
    "## Liên kết",
    "",
    `- **Google Trang tính (yêu cầu / quản lý):** ${linkOrDash(config.sheetUrl)}`,
    `- **GitHub:** ${linkOrDash(config.githubUrl)}`,
    "",
    "## Stack",
    "",
    `- **Ngôn ngữ / framework:** ${config.stacks.map((stack) => STACKS[stack].label).join(", ") || "_(chưa xác định)_"}`,
    `- **Môi trường chạy:** ${ENVIRONMENTS[config.env].label}`,
    `- **Profile cấu hình AI:** ${config.profile}`,
    `- **Thư mục:** \`${config.path}\``,
  ];
  if (STACKS[primaryStack(config.stacks)].documentRoot) {
    lines.push(`- **Document root:** \`${STACKS[primaryStack(config.stacks)].documentRoot}/\``);
  }
  if (config.needsDb) lines.push(`- **Database:** \`${databaseName(config.slug)}\` (thông tin đăng nhập trong \`.env\`)`);

  lines.push("", "## Port (đã cấp riêng — không đổi tùy tiện)", "");
  if (portRows.length) {
    lines.push("| Dịch vụ | Port |", "|---|---|", ...portRows);
  } else {
    lines.push("_Không cần port._");
  }

  lines.push(
    "",
    "## Cách chạy",
    "",
    runSection(config),
    "",
    "## Kiểm chứng",
    "",
    "- Lệnh kiểm chứng nằm trong `.ai/verify.json`; chạy tất cả: `node scripts/verify.mjs`.",
    "- Chỉ bật (`\"enabled\": true`) những lệnh thực sự tồn tại trong dự án.",
    "",
    `_Cập nhật lần cuối: ${new Date().toISOString().slice(0, 10)} · template v${TEMPLATE_VERSION}_`,
    END_MARKER,
  );
  return lines.join("\n");
}

const DEFAULT_NOTES = `

## Ghi chú dự án

<!-- Phần dưới đây do bạn tự viết: nghiệp vụ, thuật ngữ, quyết định quan trọng, người liên hệ...
     HAINGUYENCODER sẽ KHÔNG ghi đè phần này. -->
`;

/** Merge a fresh managed block into existing file content (or create new content). */
export function mergeProjectContext(existingText, config) {
  const block = renderManagedBlock(config);
  if (!existingText) return `${block}${DEFAULT_NOTES}`;
  const start = existingText.indexOf("<!-- HNC:BEGIN");
  const end = existingText.indexOf(END_MARKER);
  if (start === -1 || end === -1) return `${block}\n\n${existingText}`;
  return existingText.slice(0, start) + block + existingText.slice(end + END_MARKER.length);
}
