# X32 AI SOUND ENGINEER — KẾ HOẠCH THỰC HIỆN CHI TIẾT (ACTION PLAN)

> **Mục tiêu:** Xây dựng hệ thống trợ lý kỹ thuật âm thanh nhà thờ thông minh, an toàn tuyệt đối, hỗ trợ kỹ thuật viên kiểm soát mixer Behringer X32 Compact, stagebox DL16, hệ thống monitor cá nhân P16, phân tích âm thanh multitrack qua USB và tối ưu chất âm mà không làm biến dạng giọng hát.

---

## 1. TỔNG QUAN HIỆN TRẠNG & CÁC NGUYÊN TẮC BẤT BIẾN

### 1.1 Sơ đồ đấu nối thực tế
*   **Mixer trung tâm:** Behringer X32 Compact (điều khiển qua mạng LAN - cổng UDP 10023).
*   **Stagebox trên sân khấu:** Midas/Behringer DL16 kết nối qua cổng **AES50 A**.
*   **Hệ thống Monitor cá nhân:** Cổng ULTRANET từ DL16 $\rightarrow$ bộ chia **P16-D** $\rightarrow$ cấp cho 3 mixer cá nhân **P16-HQ** (hiện đang hoạt động ổn định).
*   **Máy tính điều khiển (Host):**
    *   Cáp mạng LAN: gửi/nhận lệnh OSC UDP với X32.
    *   Cáp USB: kết nối card USB X32 (X-USB / X-LIVE) để thu multitrack 32 kênh thời gian thực.
    *   (Tùy chọn) Micro đo kiểm âm học (USB measurement mic có calibration file hoặc mic XLR qua audio interface).
*   **Hệ thống FOH:** Đầu ra Main L/R $\rightarrow$ Crossover/DSP/Cục đẩy $\rightarrow$ Hệ thống loa hội trường.

### 1.2 Các bất biến an toàn sống còn (Hard Invariants)
1.  **Bất biến cổng DL16 số 11 (Talkback ban nhạc):** Tín hiệu từ cổng này **CHỈ ĐƯỢC PHÉP đi về hệ thống P16 monitor**, **TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP lọt ra loa FOH** (Main LR, Mono/Center, hay Matrix). Hệ thống phải tự động verify và chặn đứng mọi đề xuất có thể mở đường tín hiệu này ra FOH.
2.  **Bảo toàn hệ thống P16 & AES50:** Không tự ý thay đổi cấu hình routing AES50 hay ULTRANET P16. Mọi thiết lập này thuộc danh sách cấm sửa đổi (`Deny-list`).
3.  **Read-Only First (Mặc định chỉ đọc):** Trạng thái khởi động luôn là `OBSERVE` (chỉ đọc dữ liệu meter, EQ, fader; không gửi lệnh ghi).
4.  **Cơ chế Fail-Safe:** Nếu máy tính tắt, phần mềm crash hoặc đứt cáp mạng, mixer X32 vẫn giữ nguyên trạng thái và tiếp tục phát âm thanh bình thường mà không bị gián đoạn.
5.  **Không tự động đẩy Gain khi im lặng:** Tuyệt đối không auto-boost âm lượng khi micro không có tiếng (tránh kéo ồn nền và gây rít hú).

---

## 2. KIẾN TRÚC KỸ THUẬT & CÔNG NGHỆ LỰA CHỌN

```text
x32-ai-sound-engineer/
├── apps/
│   ├── api/                    # Python 3.11+ / FastAPI (REST + WebSocket)
│   ├── web/                    # React 18+ / TypeScript / Vite / TailwindCSS
│   └── capture-agent/          # Native Audio Capture (WASAPI/ASIO qua sounddevice)
├── packages/
│   ├── mock-x32/               # UDP Simulator giả lập X32 trên cổng 10023
│   ├── x32-osc-adapter/        # Bộ giao tiếp OSC type-safe, Snapshot & State Mirror
│   ├── safety-controller/      # Whitelist, Transaction, Invariant Check & Rollback
│   ├── signal-analysis/        # FFT, Welch PSD, RTA 1/12-octave, Peak/RMS
│   ├── feedback-detector/      # Phát hiện hú đa bằng chứng (loại trừ nốt ca sĩ ngân dài)
│   ├── eq-optimizer/           # Đề xuất PEQ bảo toàn giọng hát (chuẩn giới hạn X32)
│   └── ai-copilot/             # Trợ lý RAG tiếng Việt hướng dẫn kỹ thuật viên
└── tests/                      # Bộ test Unit, Integration & Fuzzing
```

*   **Ngôn ngữ Backend & DSP:** Python 3.11+ (FastAPI, NumPy, SciPy, sounddevice, python-osc).
*   **Frontend:** React, TypeScript, Vite, TailwindCSS, Canvas API / WebGL (vẽ RTA phổ mượt mà 60fps).
*   **Môi trường chạy:** Windows 10/11 (chạy trực tiếp để nhận driver USB X-USB ASIO/WASAPI với độ trễ thấp).

---

## 3. LỘ TRÌNH 6 SPRINT THỰC HIỆN CỤ THỂ

### SPRINT 1: X32 MOCK SIMULATOR & BỘ KẾT NỐI OSC (READ-ONLY)
*Mục tiêu:* Cho phép lập trình và kiểm thử toàn diện mọi chức năng đọc/ghi trên máy tính mà không cần kết nối với mixer thật, ngăn chặn 100% rủi ro thao tác nhầm trên phần cứng.

*   **Task 1.1 - X32 UDP Mock Server (`packages/mock-x32`):**
    *   Tạo UDP socket server lắng nghe trên cổng `10023`.
    *   Mô phỏng phản hồi thông tin mixer: `/info`, `/status`, `/ch/01..32/*`, `/bus/01..16/*`, `/main/st/*`.
    *   Sinh dữ liệu meter định kỳ theo giao thức `/meters`.
*   **Task 1.2 - OSC Adapter Type-Safe (`packages/x32-osc-adapter`):**
    *   Xây dựng client kết nối X32 với cơ chế duy trì nhịp tim (Heartbeat/Keep-alive).
    *   Khởi tạo ở chế độ ép buộc: `READ_ONLY_MODE = True`.
    *   State Mirror: Lưu trữ cache toàn bộ tham số của mixer thời gian thực.
    *   Snapshot Service: Chụp toàn bộ trạng thái hiện tại của mixer ra file JSON kèm mã băm SHA-256 để kiểm chứng toàn vẹn.
*   **Tiêu chí nghiệm thu (DoD):** Chạy unit test kiểm tra Mock Server và Adapter kết nối thành công, đọc trọn vẹn 32 kênh, không có bất kỳ lệnh write nào lọt ra ngoài.

---

### SPRINT 2: PHÂN TÍCH ROUTING & BẢO VỆ CỔNG DL16 #11 (SAFETY GATE)
*Mục tiêu:* Giải mã toàn bộ sơ đồ đường đi của tín hiệu âm thanh và khóa cứng các cổng an toàn.

*   **Task 2.1 - Ma trận Routing Graph (`packages/safety-controller/routing.py`):**
    *   Bóc tách mối quan hệ: `Physical Preamp (Local/AES50 A DL16)` $\rightarrow$ `Channel Inputs` $\rightarrow$ `Mix Buses` $\rightarrow$ `Outputs / Ultranet P16` $\rightarrow$ `Main FOH`.
    *   Hiển thị rõ ràng định tuyến của từng line dưới dạng đồ thị có hướng (Directed Graph).
*   **Task 2.2 - Kiểm tra Bất biến Cổng DL16 #11:**
    *   Quét toàn bộ đường tín hiệu của DL16 In 11.
    *   Báo lỗi đỏ ngay lập tức nếu phát hiện bất kỳ route nào dẫn tới `Main LR`, `Mono`, hoặc các `Matrix` đưa ra FOH.
    *   Chỉ chấp nhận khi DL16 In 11 chỉ trỏ vào Bus Monitor / Ultranet slot cho P16.
*   **Task 2.3 - Bộ kiểm soát giao dịch an toàn (Safety Transaction Manager):**
    *   `Whitelist`: Chỉ cho phép chỉnh tham số Channel EQ (Gain, Freq, Q, HPF) trên các kênh được chỉ định rõ.
    *   `Deny-list`: Cấm tuyệt đối đụng vào Routing AES50, Ultranet P16, Phantom Power 48V, Main FOH Mute/Fader, Scene Recall.
    *   Quy trình Transaction 5 bước: `Snapshot` $\rightarrow$ `Verify Revision` $\rightarrow$ `Operator Approve` $\rightarrow$ `Write Rate-Limited` $\rightarrow$ `Readback Verify` (Nếu sai lệch $\rightarrow$ tự động `Rollback` về Snapshot cũ).
*   **Tiêu chí nghiệm thu (DoD):** Chạy test cố tình gửi lệnh can thiệp vào P16 hoặc DL16 #11 $\rightarrow$ Safety Gate chặn 100% và ghi cảnh báo vào Audit Log.

---

### SPRINT 3: AUDIO DSP ENGINE & PHÁT HIỆN RỦI RO HÚ (FEEDBACK DETECTOR)
*Mục tiêu:* Thu nhận âm thanh multitrack và phân tích tần số thời gian thực mà không nhầm nốt nhạc ca sĩ thành tiếng hú.

*   **Task 3.1 - Multitrack Audio Capture (`apps/capture-agent`):**
    *   Đọc âm thanh từ Soundcard USB của X32 qua WASAPI/ASIO (hỗ trợ đọc file WAV test offline để phục vụ phát triển).
    *   Đo lường các thông số kỹ thuật: RMS, Peak dBFS, Crest Factor, phát hiện Clipping (quá tải) và xrun (mất gói).
*   **Task 3.2 - Real-time RTA Spectrum (`packages/signal-analysis`):**
    *   Thuật toán FFT và Welch Power Spectral Density với cửa sổ Hann.
    *   Chuyển đổi sang biểu đồ phổ thời gian thực (RTA) theo thang 1/12 hoặc 1/24 octave từ 20 Hz đến 20.000 Hz.
*   **Task 3.3 - Feedback Candidate Detector đa bằng chứng:**
    *   *Tiêu chí 1 (Tonality):* Năng lượng tập trung đột biến tại dải tần rất hẹp so với nền âm thanh xung quanh.
    *   *Tiêu chí 2 (Persistence):* Tần số đứng yên liên tục qua nhiều frame phân tích mà không trôi.
    *   *Tiêu chí 3 (Growth Rate):* Biên độ có xu hướng tăng theo hàm mũ (dấu hiệu vòng lặp âm thanh).
    *   *Tiêu chí 4 (Harmonic Check - Sống còn):* Phân tích dãy bồi âm để **loại trừ nốt ca sĩ ngân dài hoặc tiếng đàn organ** (tiếng hát luôn có các dải hài âm tự nhiên $2f, 3f, 4f$, trong khi tiếng hú là cộng hưởng đơn tần độc lập).
*   **Tiêu chí nghiệm thu (DoD):** Thử nghiệm với file âm thanh giả lập (tiếng hát ngân nốt A4 440Hz vs tiếng hú thật 2.5kHz) $\rightarrow$ Thuật toán nhận diện chính xác tiếng hú, không báo động giả khi ca sĩ ngân nốt.

---

### SPRINT 4: ĐỀ XUẤT PEQ BẢO TỒN GIỌNG HÁT & CÁC WIZARD HƯỚNG DẪN
*Mục tiêu:* Đưa ra gợi ý thông số EQ chuẩn xác cho X32, tôn trọng chất âm tự nhiên của người nói/hát.

*   **Task 4.1 - Thuật toán đề xuất PEQ (`packages/eq-optimizer`):**
    *   Quy tắc bảo tồn chất âm:
        *   HPF (Low-cut): Đề xuất vùng 70 – 120 Hz tùy giọng nam/nữ để khử tiếng lộp cộp, ù gió mà không làm mỏng giọng.
        *   Low-mid: Cắt nhẹ rộng (Low Q) ở vùng 200 – 400 Hz nếu phát hiện tiếng bị đục/om phòng.
        *   Feedback Notch: Nếu xác nhận tần số hú, chỉ đề xuất cắt cực hẹp (Q cao $\ge 5.0$, độ sâu giới hạn $-3\text{dB}$ đến $-6\text{dB}$), tuyệt đối không cắt rộng làm méo tiếng.
    *   Ràng buộc phần cứng: Đảm bảo đề xuất khớp chính xác với 4 band PEQ vật lý của X32 (Low, Low-Mid, High-Mid, High).
*   **Task 4.2 - Xây dựng các quy trình Wizard:**
    *   *Wizard 1 (Inventory & Routing Check):* Tự động kiểm kê 32 line và xác nhận trạng thái DL16 #11.
    *   *Wizard 2 (Pre-service Line Check):* Kiểm tra dây micro, pin mic không dây, mức gain trước giờ lễ.
    *   *Wizard 3 (Vocal/Speech Calibration):* Thu mẫu 20s giọng nói/hát tự nhiên, đề xuất HPF/EQ, cung cấp giao diện nghe A/B so sánh.
    *   *Wizard 5 (Safe Feedback Ring-Out):* Hướng dẫn dò tìm tần số hú an toàn trong buổi tập khi không có khán giả.
*   **Tiêu chí nghiệm thu (DoD):** Mọi đề xuất EQ đều hiển thị biểu đồ mô phỏng trước/sau (A/B), kèm lời giải thích lý do âm học bằng tiếng Việt.

---

### SPRINT 5: GIAO DIỆN WEB DASHBOARD & NÚT KHẨN CẤP "STOP AUTO"
*Mục tiêu:* Xây dựng giao diện web trực quan, mượt mà, giúp người vận hành dễ theo dõi và nắm quyền kiểm soát tối cao.

*   **Task 5.1 - Giao diện Live Console Dashboard (`apps/web`):**
    *   Hiển thị 32 dải kênh (Channel Strips) với đầy đủ: Tên kênh, màu sắc, role (Lead Vocal, Pastor, Piano...), Mute status, Peak meter sống động.
    *   Biểu đồ RTA Spectrum hiển thị mượt mà 60fps bằng HTML5 Canvas.
    *   Cột cảnh báo bên phải: Hiển thị tối đa 3 ưu tiên cần xử lý (ví dụ: *"Mic Mục sư đang mấp mé ngưỡng clip"*, *"Kênh 4 có nguy cơ hú ở tần số 3.15 kHz"*).
*   **Task 5.2 - Cơ chế An toàn Khẩn cấp:**
    *   Nút bấm **STOP AUTO** to màu đỏ luôn ghim cố định ở góc trên màn hình: Bấm một chạm sẽ lập tức hủy toàn bộ lệnh tự động, khóa chặt OSC write và đưa hệ thống về chế độ `OBSERVE`.
    *   Cửa sổ duyệt Proposal: Kỹ thuật viên phải tích chọn xác nhận mới được phép áp dụng thông số xuống mixer.
*   **Tiêu chí nghiệm thu (DoD):** Giao diện chạy mượt mà trên trình duyệt máy tính và máy tính bảng qua mạng LAN nội bộ; nút STOP AUTO phản hồi ngay lập tức dưới 50ms.

---

### SPRINT 6: TRỢ LÝ AI COPILOT TIẾNG VIỆT & THỬ NGHIỆM THỰC ĐỊA
*Mục tiêu:* Tích hợp trí tuệ nhân tạo giải thích nguyên nhân, tư vấn kỹ thuật và nghiệm thu trên hệ thống phần cứng thật.

*   **Task 6.1 - AI Copilot RAG (`packages/ai-copilot`):**
    *   Trợ lý tư vấn bằng tiếng Việt dựa trên tài liệu âm học và hướng dẫn sử dụng X32.
    *   Trả lời các câu hỏi thực tế của nhân sự âm thanh (ví dụ: *"Làm sao để tiếng hát rõ lời hơn mà không bị rít treble?"*, *"Vì sao micro số 3 cứ lại gần loa trái là bị hú?"*).
    *   AI chỉ đóng vai trò tư vấn, giải thích, **không có quyền trực tiếp gửi lệnh OSC**.
*   **Task 6.2 - Kịch bản nghiệm thu thực tế tại nhà thờ:**
    1.  Cắm cáp LAN và cáp USB từ laptop vào X32 Compact.
    2.  Chạy Wizard 1: Chụp Snapshot sao lưu toàn bộ Scene gốc của nhà thờ.
    3.  Kiểm tra xác thực Routing: Đảm bảo DL16 #11 không đi ra FOH.
    4.  Chạy chế độ `OBSERVE` trong suốt một buổi tập dượt (rehearsal) để ghi nhận dữ liệu âm thanh và kiểm tra độ ổn định.

---

## 4. BẢNG CHECKLIST SẴN SÀNG CHO GEMINI / AI THỰC HIỆN

| Bước | Lệnh / Nhiệm vụ thực hiện | Trạng thái |
| :---: | :--- | :---: |
| **B1** | Tạo cấu trúc thư mục monorepo & Mock X32 UDP Server cổng 10023 |  Đã xong (Sprint 1) |
| **B2** | Viết OSC Adapter kết nối Mock X32 (Mặc định Read-Only + Snapshot JSON SHA-256) |  Đã xong (Sprint 1) |
| **B3** | Viết Routing Graph Parser & Kiểm tra Invariant bảo vệ DL16 #11 → P16 only |  Đã xong (Sprint 2) |
| **B4** | Xây dựng Safety Gate (Whitelist Channel EQ, cấm Routing/P16, Rollback) |  Đã xong (Sprint 2) |
| **B5** | Viết Audio DSP Engine & Realtime RTA 1/12-Octave FFT Spectrum |  Đã xong (Sprint 3) |
| **B6** | Viết Feedback Candidate Detector (Loại trừ nốt ca sĩ ngân dài) |  Đã xong (Sprint 3) |
| **B7** | Xây dựng PEQ Recommendation Engine (Chuẩn 4-band X32 & A/B curve) |  Đã xong (Sprint 4) |
| **B8** | Phát triển Web UI Live Dashboard (Canvas RTA 60fps + Nút STOP AUTO) |  Đã xong (Sprint 5) |
| **B9** | Xây dựng API Server FastAPI, WebSocket Telemetry & Trợ lý Copilot tiếng Việt |  Đã xong (Sprint 5) |
| **B10**| Đo Âm Học Hội Trường H1 (Open Sound Meter / REW) + Quy tắc No-Boost-in-Nulls |  Đã xong (Sprint 6) |
| **B11**| Bộ Điều Khiển Mức Giọng Nói VAD & Silence Hold (M32 Live Pilot) |  Đã xong (Sprint 6) |
| **B12**| SOP Wizards Service (W1 Kiểm Kê, W2 Line Check, W3 Vocal Calib, W5 Ring-Out, W7 Báo Cáo) |  Đã xong (Sprint 7) |
| **B13**| Bộ Chuyển Đổi Phần Cứng (Hardware Switcher LAN IP ↔ Mock Simulator) |  Đã xong (Sprint 7) |
| **B14**| Native Audio Capture Agent qua SoundDevice (X-USB Card ASIO/WASAPI) & Live Multi-Channel |  Đã xong (Sprint 8) |
| **B15**| Modal Giao Diện 7 Tabs Đầy Đủ Cả 7 SOP Wizards (W1, W2, W3, W4, W5, W6, W7), Switcher & Audio Device |  Đã xong (Sprint 8, 9 & 10) |
| **B16**| Xuất File Scene Chuẩn X32 (.scn) Cho Ổ Cắm USB Mặt Trước Bàn Trộn |  Đã xong (Sprint 9) |
| **B17**| Bộ Tài Liệu Vận Hành Tiếng Việt, Ma Trận OSC, An Toàn Hú & SBOM trong docs/ |  Đã xong (Sprint 9) |
| **B18**| SQLite Database Storage (`churchmix.db`) cho Audit Log Bất Biến & Lịch Sử Đo Âm Học H1 |  Đã xong (Sprint 10) |
| **B19**| Cân Chỉnh Hệ Thống Loa Hội Trường (W4 Room/PA Dual-Channel H1 Transfer Function UI) |  Đã xong (Sprint 10) |
| **B20**| Tự Động Quét Mạng Dò Tìm X32 / M32 (`x32-discovery` UDP 10023 Broadcast Probe) & UI Auto-Fill |  Đã xong (Sprint 10) |
| **B21**| Trợ Lý Trực Tiếp Buổi Lễ (W6 Live Service Assistant Tactical Dashboard & Key Channel Highlights) |  Đã xong (Sprint 10) |
| **B22**| Cấu Hình Phân Quyền RBAC (`configs/roles-example.yaml`) & Triển Khai (`deploy/` Docker, Windows Service, Systemd) |  Đã xong (Sprint 10) |
| **B23**| Mô Phỏng Vòng Đời Buổi Lễ Chúa Nhật Toàn Diện (Sprint 11 E2E Lifecycle Simulation & Invariant Integration) |  Đã xong (Sprint 11) |
| **B24**| Virtual Soundcheck Rehearsal Engine (4 Sessions: Ballad, Uptempo, Preaching, Prayer) & DL16 #11 Whisper Isolation |  Đã xong (Sprint 12) |
| **B25**| Quản Lý Profile Kênh Nhà Thờ (32-Ch Profile Manager) & Báo Cáo Buổi Lễ In Ấn/PDF Chuẩn A4 |  Đã xong (Sprint 12) |
| **B26**| Phòng Thí Nghiệm Kiểm Thử Hỗn Loạn, Fault-Injection & Khả Năng Chống Chịu Sự Cố (Chaos & Resilience Test Suite) |  Đã xong (Sprint 13) |
| **B27**| Gói Trí Tuệ Nhân Tạo AI Copilot RAG (`packages/ai_copilot/`) & Truy Vấn Trực Tiếp Theo Thời Gian Thực |  Đã xong (Sprint 14) |
| **B28**| Quản Lý Profile Phòng Nhóm & So Sánh Baseline Âm Học Hội Trường (Multi-Sanctuary Hall Profiles & Baseline Comparator) |  Đã xong (Sprint 15) |
| **B29**| Bộ Tự Chẩn Đoán Hệ Thống Tiền Lễ 10 Tiêu Chuẩn (`diagnose_system.py` & REST API `/api/v1/system/diagnostics`) |  Đã xong (Sprint 16) |
| **B30**| Giao Diện Sơ Đồ 32 Kênh Nhà Thờ (`#churchChannelsModal`), Khóa Cứng Kênh 11 & Tự Động Đồng Bộ Tên Kênh |  Đã xong (Sprint 16) |
| **B31**| Kho Lưu Trữ Scene (`SceneVaultManager`), Khóa Bất Biến DL16 #11 khi Lưu Snapshot, Xuất USB .scn Gốc & So Sánh Vi Sai Snapshot Delta |  Đã xong (Sprint 17) |
| **B32**| Giao Thức Phản Ứng Dò Hú Thời Gian Thực (Feedback Radar HUD), Đề Xuất Notch Lọc Hú (Rule 9) & Bật/Tắt Mute Kênh Qua SafetyGate |  Đã xong (Sprint 18) |
| **B33**| Giám Sát Âm Lượng Phát Thanh Trực Tiếp (ITU-R BS.1770-4 / EBU R128 LUFS & True Peak 4x Polyphase) + Bảo Vệ Bất Biến Livestream Talkback Guard |  Đã xong (Sprint 19) |
| **B34**| Bộ Nạp File Scene Behringer X32 (.scn) Từ USB, Thẩm Định Tiền Kiểm Tra Pre-Flight Safety Audit & Tự Động Vá Lỗi Invariant (Auto-Sanitize) |  Đã xong (Sprint 20) |
| **B35**| Cân Chỉnh Headroom & Gain Staging Chuẩn Nhà Thờ (Phân Tích Peak/RMS, Digital Trim Whitelist /ch/xx/preamp/trim & Đề Xuất An Toàn) |  Đã xong (Sprint 21) |
| **B36**| Dugan Speech Automixer & Bộ Chia Sẻ Gain Tự Động (NOM=1 Invariant <= 0.0 dB, Silence Hold, Cách Ly Kênh 11, X32 Native Automix DSP Proposals & UI Modal) |  Đã xong (Sprint 22) |
| **B37**| Thẩm Định Thính Giác Mù A/B & Chấm Điểm 7 Tiêu Chí Âm Học (ITU-R BS.1284 / MP 3.4, Bù Trừ Equal-Loudness, Quy Tắc Phủ Quyết MOS Veto Rule & SQLite) |  Đã xong (Sprint 23) |
| **B38**| Kiểm Soát Rò Rỉ Sân Khấu (Stage Bleed) & Cân Chỉnh Downward Expander Cho Vocal (Cross-Correlation, Comb-Filtering Detection, Gentle Expander <= 12 dB, Sidechain Key HPF 250 Hz, Khóa Bất Biến Kênh 11 & Web UI Card) |  Đã xong (Sprint 24) |
| **B39**| Hệ Thống 4 Chế Độ Quyền Hạn Safety Engine (OBSERVE, ASSIST, LIMITED_AUTO, ADMIN_MAINTENANCE) & Tự Động Khóa Cứng (Auto-Disengage / Panic Freeze Watchdog: Vỡ tiếng liên tục, Tăng vọt hú, Mất telemetry, Khóa PIN 7777, Modal UI `#safetyModeModal` & REST API) |  Đã xong (Sprint 25) |
| **B40**| Ma Trận Monitor Aux & Kiểm Tra Bất Biến Ultranet P16 Personal IEM (Thẩm Định 16 Khe P16, Khóa Chặt DL16 #11 Talkback -> P16 Slot 11 ONLY, Phân Loại Bus Wedges/IEMs/FX, Dò Nguy Cơ Hú Loa Sàn > 0.80 Fader Send, Khắc Phục Lỗi Post-Fader Tap-Point, Modal UI `#monitorMatrixModal` & REST API) |  Đã xong (Sprint 26) |
| **Tổng**| **240 / 240 Automated Python Tests + 23 / 23 Node Tests PASSING (263 Tests Total)** |  **100% HOÀN TẤT TOÀN BỘ 40 HẠNG MỤC** |







