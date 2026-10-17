# BẢN QUYỀN MÃ NGUỒN VÀ BẢNG KÊ THÀNH PHẦN (SBOM)

## Công cụ kiểm tra trình duyệt — 13/10/2026

- **ChromeDevTools/chrome-devtools-mcp**, phiên bản npm **1.10.1**, giấy phép **Apache-2.0**. Nguồn chính thức: https://github.com/ChromeDevTools/chrome-devtools-mcp . npm `gitHead`: `e52c6b59b476c5e04d8dd9fd4bd017ba3b3d65df`.
- npm integrity: `sha512-Klw6HWDqHC/XS1JwZldd2r49aUhbUJN9m9Mvcx4SEueIPXtzuQX+QelxAViobv8YUkDZ7HWDrmViR6LeYK0wAw==`.
- Cài ở môi trường công cụ người dùng, không thêm vào dependency runtime ChurchMix và không sao chép mã công cụ vào repository. Giấy phép/notice của gói cài đặt được giữ nguyên.
- Cấu hình Codex MCP tên `chrome-devtools`; Chrome headless và isolated, tắt usage statistics và performance CrUX. Đã xác minh CLI daemon hoạt động và chụp ảnh bản mock `main` trên cổng 8090.

## Bổ sung dashboard giám sát — 12/10/2026

`apps/web/monitoring.js`, `apps/web/monitoring.css` và `packages/monitoring/` được viết mới trong dự án. Biểu đồ dùng Canvas API có sẵn của trình duyệt; xử lý mức tín hiệu dùng NumPy đã có. Không thêm thư viện biểu đồ, CDN, mã sao chép hoặc tham chiếu bên thứ ba trong phần bổ sung này. Giữ nguyên các giấy phép và ghi công của thành phần hiện có bên dưới.

Hệ thống **X32 AI Sound Engineer** tôn trọng nghiêm ngặt bản quyền mã nguồn mở và quy định pháp lý của các thư viện tích hợp.

---

### 1. Bảng Kê Thành Phần Mã Mở (Open-Source SBOM)

| Thành phần / Repo | Vai trò trong hệ thống | Giấy phép | Tình trạng tích hợp |
|---|---|---|---|
| **pmaillot/X32-Behringer** | Tham khảo cú pháp giao thức OSC của X32/M32 | Tài liệu kỹ thuật | Tham chiếu giao thức; toàn bộ adapter được viết mới bằng Python type-safe |
| **wrodie/behringer-mixer** | Tham khảo mô hình điều khiển fader/mute/gain | MIT License | Tham chiếu kiến trúc; không copy code trực tiếp |
| **CristianMoresi/M32LiveConsoleTool** | Tham khảo nguyên lý Auto-Level và Anti-Clip | MIT License | Port thuật toán VAD & Silence Hold có kiểm thử nghiêm ngặt |
| **psmokotnin/osm (Open Sound Meter)** | Phần mềm đo âm học hội trường độc lập | GPL-3.0 | Tích hợp qua định dạng xuất file CSV/FRD chuẩn công nghiệp; không liên kết mã nguồn động |
| **HEnquist/camilladsp** | Mô phỏng bộ lọc IIR/FIR | Dual GPL-3.0 / MPL-2.0 | Công cụ nghiên cứu ngoại tuyến trong phòng thí nghiệm (Offline Lab) |
| **jaakkopasanen/AutoEq** | Tối ưu hóa bộ lọc đáp tuyến PEQ | MIT License | Tham khảo công thức toán học bộ lọc Biquad Peaking EQ |

---

### 2. Các Thư Viện Python Cốt Lõi
* **FastAPI (MIT):** Web framework hiện đại, hiệu năng cao với ASGI và OpenAPI schema.
* **Uvicorn (BSD-3-Clause):** Lightning-fast ASGI server.
* **NumPy (BSD-3-Clause):** Tính toán ma trận và đại số tuyến tính cho mảng âm thanh số.
* **SciPy (BSD-3-Clause):** Xử lý tín hiệu số (DSP), biến đổi Welch PSD và bộ lọc biquad.
* **SoundDevice (MIT):** Giao tiếp PortAudio thời gian thực với Windows WASAPI/ASIO.
* **python-osc (Public Domain / CC0):** Giải mã và đóng gói binary OSC UDP packets.

### 3. Công cụ kiểm tra và bản lưu source (13/10/2026)

- **ChromeDevTools/chrome-devtools-mcp**, Apache-2.0, bản npm `1.10.1`, git SHA `e52c6b59b476c5e04d8dd9fd4bd017ba3b3d65df`: cài ngoài dự án để kiểm tra trình duyệt; không thêm dependency cho ChurchMix. Nguồn: https://github.com/ChromeDevTools/chrome-devtools-mcp.
- `community-skills/`, `templates/` và công cụ tạo dự án được chuyển nguyên thư mục, kèm các tệp license, notice và metadata Git có sẵn, vào `C:\xampp\htdocs\ChurchMix-archive-20261013-132721`. Không phân phối các thành phần này cùng runtime ChurchMix. Đường dẫn tham chiếu cũ và bản quyền được giữ trong bản lưu; xem manifest ở `docs/source-cleanup-2026-10-13.md`.
