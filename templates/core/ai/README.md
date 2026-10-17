# .ai — Artifact protocol

Thư mục này chứa các tài liệu trao đổi giữa người và AI (hoặc giữa các model):

| Thư mục | Nội dung |
|---|---|
| `plans/` | Kế hoạch cho thay đổi lớn/rủi ro (dùng `PLAN_TEMPLATE.md`) |
| `reviews/` | Kết quả review độc lập (dùng `REVIEW_TEMPLATE.md`) |
| `verification/` | Bằng chứng kiểm chứng (dùng `VERIFICATION_TEMPLATE.md`) |
| `decisions/` | Quyết định kiến trúc (ADR ngắn) |

`verify.json` liệt kê các lệnh kiểm chứng thật của dự án. Hook `Stop` và `scripts/verify.mjs` đọc file này.
Chỉ thêm lệnh khi lệnh đó thực sự tồn tại trong dự án.

Quy tắc: kết quả công cụ (test, lint, build) luôn thắng ý kiến của model.
