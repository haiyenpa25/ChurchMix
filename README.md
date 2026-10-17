# ChurchMix — X32 AI Sound Engineer

> **Hệ Thống Trợ Lý Kỹ Thuật Âm Thanh Nhà Thờ — Giám Sát Tín Hiệu & Đề Xuất Có Kiểm Soát**
> Dành cho mixer **Behringer X32 Compact / Midas M32**, stagebox **Midas DL16** và hệ thống monitor cá nhân **Ultranet P16**.

[![Mock Tested](https://img.shields.io/badge/Safety-Mock%20Tested-blue.svg)](docs/monitoring-dashboard.md)
[![Tests Passing](https://img.shields.io/badge/Tests-256%20Python%20%2B%202%20JS-brightgreen.svg)](#kiểm-thử-tự-động)
[![OSC Read-Only First](https://img.shields.io/badge/Mode-READ__ONLY__MODE%20First-blue.svg)](#chế-độ-vận-hành)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11%20%7C%20Linux-lightgrey.svg)](#yêu-cầu-môi-trường)

---

## 1. Giới Thiệu & Mục Tiêu

**ChurchMix (X32 AI Sound Engineer)** được thiết kế chuyên biệt cho môi trường thờ phượng tại nhà thờ, hỗ trợ đội âm thanh theo dõi và cân chỉnh với các mục tiêu:
* Giọng nói Mục sư rõ lời, tròn vành, không om bí, không mỏng gắt.
* Ban nhạc và ca đoàn hòa quyện, âm trường sân khấu sống động.
* **Giảm nguy cơ hú rít** bằng theo dõi tín hiệu và kỹ thuật micro phù hợp; vẫn có rủi ro feedback.
* **Đề xuất có kiểm soát:** Trợ lý AI chỉ đưa ra đề xuất âm học và giải thích bằng tiếng Việt; chỉ thực thi lệnh ghi sau khi kỹ thuật viên xác nhận.

---

## 2. Sơ Đồ Đấu Nối Thực Tế

```text
[Sân khấu] Midas DL16 (AES50 A) ──────────┐
                                          │
[Monitor] DL16 Ultranet ──> P16-D ──> 3x P16-HQ In-Ear
                                          │
[FOH Console] Behringer X32 Compact ──────┤
   │                                      │
   ├── [Cáp LAN / UDP 10023] ─────────────┼──> [Máy tính điều khiển Laptop/PC]
   └── [Cáp USB / X-USB Audio 32-ch] ─────┘    (Chạy ChurchMix Server & UI)
```

---

## 3. Các Bất Biến Sống Còn (Hard Invariants)

1. **Bất Biến Cổng DL16 #11 (Band Talkback):**
   * Tín hiệu từ cổng này **CHỈ ĐƯỢC PHÉP** đi vào hệ thống Ultranet P16 của ban nhạc.
   * **TUYỆT ĐỐI CẤM** định tuyến ra loa FOH (Main LR, Mono/Center, hay Matrix). Bất kỳ giao dịch nào vi phạm sẽ bị hủy bỏ ngay lập tức với lỗi `InvariantViolationError`.
   * Hệ thống kiểm tra **mọi** đường ra FOH: Main LR, Mono/Center, Bus → Main/Mono và Bus → Matrix. Một send đang bật được tính là đường rò rỉ dù level đang ở −∞.
   * Kênh X32 nhận DL16 #11 **được cấu hình**, không mặc định bằng số cổng: `configs/safety-defaults.yaml` → `talkback_protection.x32_channel`. Nếu tên kênh trên mixer cho thấy patch đã đổi (một kênh khác tên "Talkback"), mọi lệnh ghi bị khóa cho tới khi cập nhật cấu hình.
   * Snapshot thiếu bất kỳ tham số routing nào → khóa ghi (fail-closed).
2. **Khởi Động Read-Only (Mặc định chỉ đọc):**
   * Mọi kết nối đến phần cứng luôn khởi đầu ở trạng thái `READ_ONLY_MODE = True`.
3. **Nút Khẩn Cấp STOP AUTO:**
   * Luôn ghim trên thanh tiêu đề và phím tắt; phản hồi dưới 50ms để khóa cứng toàn bộ luồng ghi tham số khi có sự cố.
4. **Silence Hold (Chống trôi Fader):**
   * Tuyệt đối không tự động đẩy fader lên khi micro im lặng hoặc người nói tạm ngừng để tránh kéo ồn nền hội trường.
5. **No-Boost-in-Nulls:**
   * Không bao giờ tăng dải EQ vào các điểm triệt tiêu pha âm học phòng ($Coherence < 0.65$ & $Magnitude < -6\text{ dB}$).
6. **Chống Hú Đa Bằng Chứng:**
   * Phân tích dãy hài âm tự nhiên ($2f, 3f, 4f$) để loại trừ nốt ca sĩ ngân dài hoặc tiếng đàn organ, chỉ can thiệp notch hẹp ($Q \ge 6.0$, độ sâu giới hạn $-3\text{dB}$ đến $-4.5\text{dB}$) vào đúng tần số cộng hưởng hú thật.

---

## Giao diện: 2 chế độ

Chuyển ở góc trên bên phải. Lựa chọn được nhớ trên từng máy.

* **Đơn giản** — cho tình nguyện viên không chuyên: một câu trạng thái lớn ("Mọi thứ sẵn sàng" / "Có dấu hiệu hú ở kênh 3"), rồi 3 bước **Trước lễ → Trong lễ → Sau lễ** với nút to và hướng dẫn bằng lời thường.
* **Kỹ thuật** — menu bên trái theo nhóm: *Trong buổi lễ* (bàn trộn trực tiếp, giám sát tín hiệu, giọng nói & automix, livestream, monitor & P16), *Chuẩn bị* (kiểm tra trước lễ, SOP W1–W7, soundcheck ảo, âm học hội trường, nghe thử A/B), *Hệ thống* (scene & sao lưu, sơ đồ kênh, kết nối thiết bị, an toàn & nhật ký, trợ lý AI).
* **Tiết mục** (Mục sư giảng · Ban hát thờ phượng · Ban ngành · Đơn ca · Tốp ca · Thông báo/MC · Cầu nguyện): bấm một nút để mở đúng micro và tắt các micro khác — luôn xem trước và xác nhận, chỉ bật/tắt (không đẩy fader), Talkback không bao giờ bị động tới. Kỹ thuật viên lưu cấu hình bằng **Lưu từ mixer**.
* **Bàn trộn trực tiếp** kiểu X32-Edit: 32 kênh (2 layer 1–16, 17–32) với màu, EQ thu nhỏ, meter, fader; biểu đồ EQ + RTA của kênh đang chọn. Khi có hú, trang tự nhảy tới kênh gây hú, hiện cách xử lý nhanh và đề xuất **Đồng ý cắt**. Luyện tập bằng Soundcheck ảo → **Tập xử lý hú**.
* **Lái tự động** (chế độ Tự động có giới hạn): máy tự cân giọng nói (±3 dB quanh bản mix chuẩn, đứng yên khi im lặng), tự cắt hú hẹp có ngân sách (chỉ vào dải EQ trống), tự cân bus livestream và cảnh báo vỡ tiếng. Bật = duyệt trước trong giới hạn ở `configs/safety-defaults.yaml`; kéo fader tay thì máy theo người; STOP dừng ngay; có nút hoàn tác mọi thay đổi của máy. Xem mục 23 sổ tay vận hành.
* **Meter thật từ X32** qua OSC `/meters` (chỉ đọc): mức từng kênh đúng kênh X32, không còn phụ thuộc dữ liệu mô phỏng.
* Nút **STOP** đỏ luôn hiện ở mọi trang (phím tắt `Ctrl+Shift+S`); bấm lại để mở khóa có xác nhận. Mọi thay đổi trên mixer đều hiện bảng "trước → sau" và cần bấm duyệt.
* Giao diện tự chứa, không tải CDN — chạy được khi máy FOH không có Internet. Giao diện cũ đã được chuyển vào bản lưu ngoài dự án.

## Dashboard giám sát tín hiệu

Trong giao diện mới: **Kỹ thuật → Giám sát tín hiệu**.

Dashboard có biểu đồ Peak 32 đầu vào, lịch sử Peak/RMS 2 phút, xếp hạng thời gian vượt ngưỡng, headroom, bảng phân tích và xuất CSV. Nguồn demo/USB mô phỏng được ghi rõ; USB thật chưa ánh xạ không bị gán nhầm thành kênh X32 hay cổng DL16.

Xem [hướng dẫn đọc biểu đồ và rà soát toàn dự án](docs/monitoring-dashboard.md). Kiểm thử mock chưa chứng minh an toàn routing trên mọi scene thật. `npm start` hiện mở đúng ChurchMix; dùng `npm start -- --port 8090` để chọn cổng 8090.

Gain staging và livestream ghi rõ nguồn mô phỏng, dùng sample rate của capture và từ chối USB thật chưa xác minh ánh xạ/tap point. LUFS hiện là phép đo buffer, chưa tích lũy cả buổi. Xem [báo cáo tối ưu source](docs/source-cleanup-2026-10-13.md).

## 4. Khởi Động Nhanh (Quick Start)

### 4.1 Khởi động bằng 1 cú nhấp chuột (Windows)
Double-click vào tệp:
```text
start_church_engineer.bat
```
Ứng dụng sẽ tự khởi chạy máy chủ backend và mở giao diện tại địa chỉ:
👉 **`http://127.0.0.1:8080`**

> **Bảo vệ API:** chỉ chính giao diện ChurchMix (cùng origin) hoặc `localhost` mới được gửi lệnh thay đổi mixer; trang web lạ mở trên cùng máy sẽ bị chặn (HTTP 403). Nếu dùng máy tính bảng trong mạng LAN nhà thờ với origin khác, khai báo: `$env:CHURCHMIX_ALLOWED_ORIGINS = "http://192.168.1.50:8080"`.

### 4.2 Khởi động thủ công qua PowerShell
```powershell
# 1. Cài đặt thư viện phụ thuộc
pip install -r requirements.txt

# 2. Khởi động Web & API Server
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080
```

---

## 5. Quy Trình Chuẩn 7 Bước (SOP Wizards)

Hệ thống tích hợp sẵn 7 Wizards chuẩn hóa toàn diện quy trình âm thanh nhà thờ:

| Wizard | Tên Quy Trình | Mục Đích Sử Dụng |
| :---: | :--- | :--- |
| **W1** | **Inventory & Safety Routing** | Quét kiểm kê 32 line và xác thực cách ly cổng DL16 #11. |
| **W2** | **Sunday Pre-Service Line Check** | Kiểm tra dây dẫn, pin micro không dây, gain cấu trúc trước giờ lễ. |
| **W3** | **Vocal & Speech Calibration** | Thu mẫu 20s giọng Mục sư/Ca trưởng, đề xuất 4-band PEQ và nghe thử A/B. |
| **W4** | **Room & PA Tuning (H1)** | Cân chỉnh đáp tuyến loa hội trường qua hàm truyền 2 kênh & căn delay. |
| **W5** | **Safe Feedback Ring-Out** | Dò tìm tần số hú an toàn trong buổi tập khi không có khán giả. |
| **W6** | **Live Service Tactical Assistant** | Giám sát trực tiếp buổi lễ: Headroom, VAD, Silence Hold, cảnh báo clipping. |
| **W7** | **Post-Service Debrief** | Tổng kết thống kê sự cố, mức âm lượng trung bình và xuất báo cáo Markdown. |

---

## 6. Xuất File Cắm USB Mặt Trước X32 (.scn)

Không cần máy tính trực tiếp trong giờ lễ, bạn có thể xuất toàn bộ cấu hình tối ưu thành file Scene chuẩn Behringer X32:
1. Nhấn nút **"Xuất File Scene USB (.scn) Cho X32"** trên dashboard.
2. Sao chép tệp `ChurchMix_FOH.scn` vào thư mục gốc của USB định dạng FAT32.
3. Cắm vào cổng USB trên mặt bàn trộn X32 và chọn **Scenes $\rightarrow$ Utility $\rightarrow$ Load Scene**.

---

## 7. Kiểm Thử Tự Động (Automated Testing)

Hệ thống có **256 bài kiểm thử Python** chạy với mock X32 hoặc fixture cô lập:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest discover -s tests -p "test_*.py"
```

* Thời gian chạy phụ thuộc máy và môi trường; khoảng 16 giây trong lần kiểm tra gần nhất.
* Kết quả: **256 bài Python và 2 bài JavaScript đạt** (mock/fixture; JavaScript chạy bằng `npm test`). 23 bài JavaScript của công cụ tạo dự án và giao diện cũ được lưu cùng phần source đã tách.
* Nếu đang chạy sẵn một ChurchMix khác (chiếm UDP 10023), đặt cổng mock riêng cho test: `$env:CHURCHMIX_X32_PORT = "10923"`.

---

## 8. Cấu Trúc Mã Nguồn

```text
ChurchMix/
├── apps/
│   ├── api/                    # FastAPI REST & WebSocket Telemetry Server
│   ├── capture_agent/          # Native Audio Capture qua SoundDevice (X-USB ASIO/WASAPI)
│   └── web/                    # Giao diện: index.html + js/ (ES modules) + assets/app.css
├── packages/
│   ├── mock_x32/               # UDP Simulator giả lập X32 trên cổng 10023
│   ├── x32_osc_adapter/        # Binary OSC Codec, Snapshot SHA-256, UDP Discovery
│   ├── safety_controller/      # Whitelist, Routing Graph, Safety Transactions & Rollback
│   ├── signal_analysis/        # 1/12-Octave RTA, Welch PSD, Peak/RMS
│   ├── feedback_detector/      # Dò hú đa bằng chứng loại trừ hài âm ca sĩ (2f..5f)
│   ├── eq_optimizer/           # Đề xuất 4-Band PEQ chuẩn phần cứng X32
│   ├── acoustic_measurement/   # Đo hàm truyền H1, Coherence, Parser OSM CSV
│   ├── mix_assistant/          # Speech Leveler & Silence Hold chống trôi fader
│   ├── storage/                # SQLite DB (Snapshots, Audit Logs, Acoustic history)
│   └── wizards/                # Nghiệp vụ 7 quy trình chuẩn SOP (W1-W7)
├── configs/                    # Whitelist OSC, Phân quyền RBAC, Safety defaults
├── deploy/                     # Dockerfile, Docker Compose, Windows Service, Systemd
├── docs/                       # Toàn bộ 7 tài liệu kỹ thuật & quy chuẩn vận hành
└── tests/                      # Unit, Integration và UI fixture tests
```

---

## 9. Làm việc cùng AI coding agent

Codex, Gemini CLI và Claude Code dùng chung một bộ quy tắc trong [`AGENTS.md`](AGENTS.md) (an toàn bắt buộc + hướng dẫn phát triển). `CLAUDE.md` và `GEMINI.md` chỉ trỏ về file này.

---

## 10. Giấy Phép & Đóng Góp

* Phát triển cho cộng đồng âm thanh nhà thờ phục vụ phụng vụ thánh.
* Chi tiết bản quyền và ghi công thư viện nguồn mở xem tại [docs/licensing-SBOM.md](docs/licensing-SBOM.md).

