# Kiến Trúc Hệ Thống X32 AI Sound Engineer (System Architecture)

Tài liệu mô tả chi tiết kiến trúc kỹ thuật của hệ thống **X32 AI Sound Engineer** cho Nhà thờ, kiểm soát bàn trộn số **Behringer X32 Compact**, hộp mở rộng **DL16 stagebox**, và hệ thống kiểm âm cá nhân **Ultranet P16-D / P16-HQ**.

---

## 1. Sơ Đồ Khối Tổng Thể (System Block Diagram)

```
                            MẠNG LAN NỘI BỘ (UDP Port 10023)
  [Laptop Kỹ Thuật Viên] <====================================> [Behringer X32 Compact]
            │                                                              │
            ├─ OSC Control (Client + State Mirror)                         ├─ AES50 A ── [DL16 Stagebox]
            ├─ Multitrack USB Capture (ASIO / WASAPI / MME)                │                 │
            │   (Card X-USB / X-LIVE 32 kênh)                              │                 └─ ULTRANET ── [P16-D] ── 3x P16-HQ
            ├─ FastAPI Service (REST API + WS Telemetry 60fps)             │
            ├─ Safety Gate & Transaction Executor                          └─ Main Out L/R ── Amp / DSP ── Loa FOH
            ├─ SQLite Vault (`data/churchmix.db`)
            └─ Web Dashboard (HTML5 Canvas + Tailwind Dark)
```

---

## 2. Các Lớp Kiến Trúc (Architectural Layers)

### Lớp 1: Giao Thức Điều Khiển OSC (`packages/x32_osc_adapter/`)
- **`osc_codec.py`:** Bộ giải mã và mã hóa nhị phân OSC theo chuẩn 4-byte padding cho string, int32, float32, blob.
- **`client.py`:** X32Client với cơ chế one-writer, quản lý heartbeat `/xremote` định kỳ mỗi 7s, State Mirror bộ nhớ đệm, tự động băm SHA-256 cho snapshot.
- **`scene_exporter.py`:** Bộ trích xuất file `.scn` chuẩn native Behringer để nạp qua USB stick ở mặt trước bàn trộn.
- **`x32-discovery`:** Quét broadcast UDP port 10023 để tự động tìm kiếm console trên mạng LAN.

### Lớp 2: Bộ An Toàn Sống Còn (`packages/safety_controller/`)
- **`routing.py`:** Phân tích đồ thị định tuyến (Routing Graph). Kiểm tra và bảo vệ bất biến sống còn:
  $$\text{DL16 Input 11} \longrightarrow \text{Ultranet P16 Only} \quad (\text{Main FOH} = \text{OFF}, \text{Matrix} = \text{OFF})$$
- **`transaction.py`:** TransactionExecutor thực thi giao dịch tham số theo 5 bước:
  1. Kiểm tra mã băm SHA-256 snapshot trước khi sửa.
  2. Bắt buộc có sự chấp thuận của kỹ thuật viên (`operator_id`).
  3. Giới hạn tốc độ gửi lệnh (tối thiểu 20ms giữa các lệnh OSC).
  4. Đọc lại (readback) đối chiếu giá trị xác nhận trên mixer.
  5. Tự động Rollback về trạng thái cũ nếu phát hiện sai lệch.

### Lớp 3: Xử Lý Tín Hiệu Âm Thanh DSP (`packages/signal_analysis/` & `packages/feedback_detector/`)
- **`dsp.py`:** Biến đổi Fourier nhanh (FFT), ước lượng mật độ phổ Welch PSD, tính toán RTA 1/12-Octave (61 dải tần số logarit từ 20 Hz đến 20 kHz).
- **`detector.py`:** Bộ phát hiện rủi ro hú đa bằng chứng:
  - Phân tích độ nhọn băng hẹp (narrowband prominence $\ge 12\text{ dB}$).
  - Độ bền vững thời gian (persistence $\ge 3$ khung liên tiếp).
  - Tỷ lệ tăng trưởng năng lượng bất thường.
  - Loại trừ hài âm tự nhiên $2f, 3f, 4f, 5f$ từ giọng hát ca sĩ ngân dài.

### Lớp 4: Tối Ưu Âm Học & Đo Loa (`packages/acoustic_measurement/` & `packages/eq_optimizer/`)
- **`transfer_function.py`:** Ước lượng hàm truyền hai kênh $H_1(f) = \frac{S_{yx}(f)}{S_{xx}(f)}$ và độ tin cậy Coherence $\gamma^2(f)$.
- **`osm_importer.py`:** Nhập và xuất dữ liệu tương thích Open Sound Meter / REW CSV.
- **`recommender.py`:** Chuyển đổi hai chiều $Hz \leftrightarrow dB \leftrightarrow Q \leftrightarrow X32\ float$, mô phỏng đường cong đáp tuyến biquad A/B.
- **Bất biến No-Boost-in-Nulls:** Tuyệt đối không cho phép boost gain ($Gain \le 0\text{ dB}$) tại các vùng triệt tiêu pha âm học ($Coherence < 0.65$ và $Magnitude < -6\text{ dB}$).

### Lớp 5: Hỗ Trợ Trộn & Giữ Mức (`packages/mix_assistant/`)
- **`leveler.py`:** SpeechLeveler với bộ phát hiện tiếng nói (VAD).
- **Bất biến Silence Hold:** Khi diễn giả hoặc Mục sư dừng nói, fader được **khóa đóng băng**; tuyệt đối không tự động trôi fader lên làm khuếch đại tiếng ồn phòng.
- **Anti-Clipping Guard:** Tự động ghìm fader khi mức đỉnh vượt quá $-1.5\text{ dBFS}$.

### Lớp 6: Quy Trình Vận Hành 7 Bước (`packages/wizards/`)
- Cung cấp trọn vẹn 7 Wizards chuẩn hóa:
  1. **W1:** Kiểm kê thiết bị & bảo vệ Talkback DL16 #11.
  2. **W2:** Bảng kiểm vật lý trước giờ lễ + Line Check 32 kênh.
  3. **W3:** Hiệu chuẩn giọng hát & bài giảng (HPF + PEQ + Soft-knee comp + Mic placement).
  4. **W4:** Cân chỉnh loa PA hội trường (H1 + Coherence + Delay Alignment).
  5. **W5:** Dò hú an toàn khi tập dượt (Surgical notch filter $Q \ge 6.5$).
  6. **W6:** Trợ lý trực tiếp buổi lễ (Giám sát 1 màn hình + Chỉ đạo tiếng Việt).
  7. **W7:** Báo cáo tổng kết buổi lễ và lưu vết lịch sử giao dịch.

### Lớp 7: Lưu Trữ Bất Biến & Giao Diện Web (`packages/storage/` & `apps/web/`)
- **`database.py`:** Lưu trữ SQLite (`data/churchmix.db`) cho audit log có mã băm mật mã SHA-256, lịch sử đo âm học và kho lưu trữ snapshot.
- **`index.html`:** Dashboard Dark Mode hiện đại hiển thị canvas RTA 60fps, 32 dải LED meter kênh, nút khẩn cấp STOP AUTO, USB Scene Export, modal SOP Wizards 7 tabs và kết nối phần cứng.
