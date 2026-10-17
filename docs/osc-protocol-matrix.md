# BẢNG MA TRẬN GIAO THỨC OSC BEHRINGER X32 / MIDAS M32

Tài liệu tham chiếu chuẩn xác các địa chỉ lệnh OSC UDP (Cổng mặc định: `10023`) được sử dụng trong hệ thống X32 AI Sound Engineer.

---

### 1. Thông Tin Mixer & Trạng Thái
| OSC Path | Kiểu dữ liệu | Mô tả | Chế độ |
|---|---|---|---|
| `/info` | Không tham số | Trả về version firmware, tên console, IP | READ-ONLY |
| `/status` | Không tham số | Trả về trạng thái hoạt động của engine | READ-ONLY |
| `/-stat/tape/state` | Int (0..3) | Trạng thái ghi âm USB | READ-ONLY |

---

### 2. Kênh Đầu Vào (Channels 01..32)
*Thay `xx` bằng số kênh định dạng 2 chữ số: `01` đến `32`.*

| OSC Path | Dải giá trị X32 | Đơn vị âm học | Ý nghĩa |
|---|---|---|---|
| `/ch/xx/config/name` | String (tối đa 12 ký tự) | Tên kênh | Tên hiển thị trên màn hình Scribble Strip |
| `/ch/xx/config/color` | Int (0..15) | Màu sắc | Màu dải màn hình kênh |
| `/ch/xx/config/source`| Int (0..63) | Nguồn input | Input socket vật lý (Local, AES50 A, USB) |
| `/ch/xx/mix/fader` | Float `0.0 .. 1.0` | $-\infty \text{ đến } +10\text{ dB}$ | Cần gạt âm lượng (0.75 = 0 dB Unity) |
| `/ch/xx/mix/on` | Int (0 hoặc 1) | MUTE (0) / ON (1) | Công tắc bật/tắt tiếng |
| `/ch/xx/preamp/hpon` | Int (0 hoặc 1) | OFF (0) / ON (1) | Bật/tắt bộ lọc thông cao High-Pass Filter |
| `/ch/xx/preamp/hpf` | Float `0.0 .. 1.0` | $20 \text{ Hz} .. 400 \text{ Hz}$ | Tần số cắt lọc trầm HPF |
| `/ch/xx/mix/lr` | Int (0 hoặc 1) | OFF (0) / ON (1) | Gửi tín hiệu ra Main Stereo FOH |

---

### 3. Bộ Cân Bằng Tham Số 4-Band (Channel PEQ)
*Thay `xx` bằng kênh `01..32`, `y` bằng band `1..4`.*

| OSC Path | Dải giá trị X32 | Đơn vị âm học | Ý nghĩa |
|---|---|---|---|
| `/ch/xx/eq/on` | Int (0 hoặc 1) | OFF (0) / ON (1) | Kích hoạt bộ xử lý EQ trên kênh |
| `/ch/xx/eq/y/type` | Int (0..5) | Kiểu lọc | 0: Low-Cut, 1: Low-Shelf, 2: PEQ, 3: VEQ, 4: High-Shelf, 5: High-Cut |
| `/ch/xx/eq/y/f` | Float `0.0 .. 1.0` | $20 \text{ Hz} .. 20 \text{ kHz}$ | Tần số trung tâm (Center Frequency) |
| `/ch/xx/eq/y/g` | Float `0.0 .. 1.0` | $-15\text{ dB} .. +15\text{ dB}$ | Độ tăng/giảm Gain (0.5 = 0.0 dB) |
| `/ch/xx/eq/y/q` | Float `0.0 .. 1.0` | $0.3 .. 10.0$ | Hệ số phẩm chất Q (bề rộng dải lọc) |

---

### 4. Định Tuyến Monitor Cá Nhân P16 & AES50
*Các lệnh dưới đây thuộc danh sách CẤM SỬA ĐỔI (Deny-list) trong suốt buổi lễ:*

| OSC Path | Mục đích | Chính sách bảo vệ |
|---|---|---|
| `/outputs/p16/11/src` | Nguồn gán cho Ultranet P16 Slot 11 | Bắt buộc phải là Direct Pre của DL16 In 11 |
| `/config/routing/AES50A` | Cấu hình nguồn từ Stagebox DL16 | Khóa cứng, cấm thay đổi |
| `/ch/11/mix/lr` | Đưa Talkback ra loa chính FOH | Khóa cứng ở mức `0` (OFF) tuyệt đối |
