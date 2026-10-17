# SỔ TAY VẬN HÀNH DÀNH CHO NHÂN SỰ ÂM THANH NHÀ THỜ
## HỆ THỐNG X32 AI SOUND ENGINEER (CHURCHMIX)

---

### Cập nhật source ngày 13/10/2026

- Có thể mở bằng `npm start -- --port 8090`; lệnh này chạy đúng API ChurchMix. Launcher Windows mặc định vẫn dùng cổng 8080.
- Meter chưa có dữ liệu hiển thị rỗng. Đầu vào USB chưa xác minh ánh xạ không được gắn vào tên kênh X32 trên bàn trộn.
- Gain staging và livestream ghi rõ nguồn mô phỏng. USB thật thiếu xác minh ánh xạ/tap point, clock lỗi hoặc buffer cũ sẽ bị từ chối phân tích; xem đầu vào USB ở **Giám sát tín hiệu**.
- LUFS là số đo buffer hiện tại, chưa tích lũy cả buổi. Không dùng số liệu demo để cân chỉnh hệ thống thật.
- STOP hủy giao dịch đang chuẩn bị và giao dịch chờ; mở lại chế độ không khôi phục quyền của giao dịch cũ. Nếu một phần đã ghi, hệ thống thử hoàn tác về giá trị trước giao dịch và xác minh đọc lại.
- Giao diện cũ và công cụ tạo dự án đã tách vào bản lưu bên ngoài. Xem `docs/source-cleanup-2026-10-13.md` để khôi phục.

---

### 1. NGUYÊN TẮC VÀNG TRƯỚC GIỜ LỄ
1. **Âm thanh phục vụ sự thờ phượng:** Chất giọng trung thực, rõ lời, êm dịu, không gây chói tai hay mệt mỏi cho hội chúng.
2. **Bất biến an toàn sống còn (Hard Invariant):** Cổng **DL16 số 11** (Micro Talkback ban nhạc) **CHỈ ĐƯỢC PHÉP ĐI VÀO P16**, **TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP RA LOA FOH**.
3. **Mặc định Chỉ Đọc (`OBSERVE`):** Khi khởi động, phần mềm luôn ở chế độ chỉ đọc. Mọi thay đổi đều phải được kỹ thuật viên bấm **Duyệt (Approve)**.
4. **Nút STOP AUTO khẩn cấp:** Nếu có bất kỳ hiện tượng âm thanh bất thường nào, bấm ngay nút **STOP AUTO** màu đỏ ở góc trên màn hình hoặc thao tác trực tiếp trên cần gạt của bàn mixer vật lý.

---

### 2. QUY TRÌNH CHUẨN BỊ TRƯỚC GIỜ LỄ (30 PHÚT TRƯỚC LỄ)

#### Bước 1: Khởi động hệ thống
1. Bật nguồn mixer **Behringer X32 Compact** và stagebox **DL16**.
2. Cắm cáp mạng LAN từ laptop vào cổng Ethernet của X32 (hoặc kết nối cùng Wi-Fi router nội bộ).
3. Nhấp đúp chuột vào file `start_church_engineer.bat` trên màn hình laptop.
4. Trình duyệt sẽ tự động mở trang điều khiển tại địa chỉ: `http://127.0.0.1:8080`.

#### Bước 2: Thực hiện Wizard 2 (Pre-Service Line Check)
1. Trên thanh Header, nhấn nút **`[Wizards Quy Trình]`**.
2. Chọn tab **`W2: Line Check Chúa Nhật`**.
3. Tiến hành kiểm tra thực tế 4 mục vật lý và tích chọn:
   * [x] **Pin micro không dây:** Kiểm tra mic Mục sư và Ban hát (pin $\ge 2$ vạch).
   * [x] **Cáp mạng AES50 A:** Đảm bảo đèn xanh kết nối DL16 sáng ổn định, không chập chờn.
   * [x] **Cáp mạng P16-D:** Kiểm tra 3 bộ mixer cá nhân P16-HQ của ban nhạc đã có tiếng.
   * [x] **Micro Talkback DL16 #11:** Bấm thử mic, xác nhận chỉ nghe trong tai nghe ban nhạc, loa lớn FOH hoàn toàn im lặng.
4. Đối chiếu bảng 32 kênh: Đảm bảo các kênh micro chính không bị Mute vô ý.
5. Khi bảng hiển thị **`READY 100%`** màu xanh $\rightarrow$ Hoàn tất chuẩn bị.

---

### 3. QUY TRÌNH HIỆU CHUẨN TRONG BUỔI TẬP (REHEARSAL)

#### Hiệu chuẩn giọng hát & bài giảng (Wizard 3):
1. Trong cửa sổ Wizards, chọn tab **`W3: Cân Chỉnh Giọng (Vocal)`**.
2. Chọn kênh tương ứng (ví dụ: Kênh 1 - Mục sư, Kênh 3 - Nữ đơn ca).
3. Yêu cầu người nói/hát phát âm tự nhiên 20–30 giây.
4. Bấm **`Lấy Mẫu 20s & Phân Tích Đề Xuất Âm Học`**.
5. Đọc hướng dẫn bố trí khoảng cách micro và thông số HPF/Compressor đề xuất.
6. Quan sát biểu đồ đáp tuyến mô phỏng A/B trước khi áp dụng.

#### Dò hú an toàn khi tập (Wizard 5):
* **Lưu ý:** Chỉ thực hiện khi hội trường không có người.
1. Chọn tab **`W5: Dò Hú Khi Tập (Ring-Out)`**.
2. Đặt micro tại vị trí ca sĩ đứng thật.
3. Làm theo 8 bước hướng dẫn SOP hiển thị trên màn hình.
4. Đẩy nhẹ fader cho tới khi xuất hiện tiếng rền chớm hú $\rightarrow$ hệ thống bắt chính xác tần số và tạo **Notch Filter phẫu thuật** cực hẹp ($Q=6.5$) để triệt tiêu mà không làm mỏng giọng.

---

### 4. VẬN HÀNH TRONG GIỜ LỄ TRỰC TIẾP
* Luôn để màn hình ở giao diện chính để quan sát:
  * Biểu đồ phổ tần số thời gian thực **1/12-Octave RTA**.
  * Cột đèn LED mức tín hiệu 32 kênh.
  * Trạng thái **Silence Hold**: Bộ điều khiển tự động khóa chặt fader khi Mục sư ngưng nói, không tự đẩy tiếng ồn nền lên.
* Nếu Mục sư nói quá lớn mấp mé ngưỡng vỡ tiếng ($\text{Peak} > -1.5\text{ dBFS}$), hệ thống kích hoạt **Anti-Clipping Guard** để bảo vệ an toàn.

---

### 5. KẾT THÚC BUỔI LỄ (WIZARD 7)
1. Nhấn nút **`[Wizards Quy Trình]`** $\rightarrow$ Chọn tab **`W7: Báo Cáo Buổi Lễ`**.
2. Nhấn nút **`Xuất Báo Cáo (.md)`** để tải về nhật ký vận hành buổi lễ lưu trữ cho ban kỹ thuật.

---

### 6. TẬP LỄ ẢO KỸ THUẬT SỐ (VIRTUAL SOUNDCHECK)
Khi ban nhạc và ca đoàn chưa có mặt đủ hoặc kỹ thuật viên cần cân chỉnh trước:
1. Nhấn nút **`[Soundcheck Ảo]`** màu xanh dương trên thanh Header.
2. Chọn 1 trong 4 phiên tập multitrack 32 track mẫu:
   - **Thờ Phượng Êm Dịu (Ballad):** Piano, Acoustic Guitar, Nữ đơn ca.
   - **Ngợi Khen Sôi Động (Uptempo):** Trống cajon/kick, Bass, Guitar, Nam đơn ca.
   - **Bài Giảng Mục Sư (Preaching):** Giọng nói Mục sư kiểm tra Silence Hold & Leveler.
   - **Cầu Nguyện Chung (Prayer):** Tiếng cầu nguyện kết hợp piano êm dịu.
3. Bấm **`Bắt Đầu Phát Đa Kênh`** để đưa luồng âm thanh vào hệ thống phân tích RTA và cân chỉnh EQ.
4. Bất biến an toàn DL16 #11 tự động kích hoạt bảo vệ: tín hiệu Talkback luôn bị cách ly ở mức an toàn -55dBFS, tuyệt đối không lọt ra Main FOH.

---

### 7. CHỌN HỒ SƠ PHÒNG & SO SÁNH BASELINE ÂM HỌC (MULTI-SANCTUARY)
Khi làm lễ ở các hội trường hoặc phòng nhóm khác nhau:
1. Nhấn nút **`[Phòng: ...]`** màu xanh ngọc trên thanh Header.
2. Chọn không gian phục vụ:
   - **Hội Trường Lớn (Main Sanctuary):** Sức chứa 800 chỗ, RT60 mục tiêu 1.60s, Line Array FOH.
   - **Phòng Giới Trẻ (Youth Chapel):** Sức chứa 150 chỗ, RT60 0.85s, Point Source.
   - **Hội Trường Thông Công (Fellowship Hall):** Sức chứa 300 chỗ, RT60 1.95s, Bê tông & kính.
   - **Sân Khấu Ngoài Trời (Outdoor Campus):** Sức chứa 1200 chỗ, RT60 0.25s, Không gian mở.
3. Nhấn **`Kích Hoạt Phòng Này`** để nạp cấu hình âm học tương ứng.
4. Nhấn **`Kiểm Tra Lệch Baseline`** để hệ thống so sánh đáp tuyến thực tế với baseline chuẩn, đưa ra khuyến nghị kỹ thuật (kiểm tra độ lệch delay, dải tần cộng hưởng phòng hoặc khóa No-Boost-in-Nulls).

---

### 8. HỎI ĐÁP VỚI TRỢ LÝ AI COPILOT TIẾNG VIỆT
1. Ở góc dưới bên phải giao diện chính, nhập câu hỏi vào ô **"Hỏi Trợ Lý Âm Học AI..."**
2. Trợ lý tích hợp cơ sở tri thức âm học nhà thờ chuẩn và ngữ cảnh thời gian thực của mixer X32:
   - *"Micro mục sư bị um ở dải trầm thì xử lý thế nào?"*
   - *"Quy tắc cách ly kênh 11 Talkback ban nhạc là gì?"*
   - *"Hệ thống có đang gặp nguy cơ hú không?"*
3. Bấm **`Gửi`** để nhận câu trả lời chi tiết bằng tiếng Việt có cấu trúc rõ ràng.

---

### 9. IN BÁO CÁO BUỔI LỄ CHỦ NHẬT (PRINTABLE REPORT)
1. Bấm nút **`[In Báo Cáo]`** trên thanh Header.
2. Trình duyệt mở trang `/api/v1/reports/sunday-service` chuẩn HTML/CSS sẵn sàng in ấn A4:
   - Bảng điểm an toàn hệ thống (100% DL16 In 11 Isolation).
   - Danh sách phân bổ kênh 1-32.
   - Nhật ký điều chỉnh và can thiệp fader.
   - Khuyến nghị âm học cho buổi lễ kế tiếp.
3. Nhấn `Ctrl + P` để in ra giấy hoặc lưu thành file PDF nộp cho Ban Trị Sự / Mục Sư.

---

### 10. TỰ CHẨN ĐOÁN TIỀN LỄ (10-POINT PRE-SERVICE HEALTH CHECK)
Trước khi bắt đầu buổi lễ 15 phút:
1. Quan sát huy hiệu **`[Khám Sức Khỏe: 10/10 OK]`** màu xanh lá ở góc trên thanh Header.
2. Bấm vào huy hiệu để mở bảng chi tiết chẩn đoán 10 tiêu chuẩn:
   - Thư viện Core Python, Cơ sở dữ liệu SQLite, Bất biến DL16 #11 Talkback.
   - Kết nối OSC X32 Read-Only, Sound Card USB, Sơ đồ 32 kênh, Hồ sơ phòng, Virtual Soundcheck, Copilot RAG, Bản in báo cáo.
3. Nếu tất cả hiển thị **`PASS`**, hệ thống hoàn toàn sẵn sàng. Có thể chạy qua dòng lệnh terminal bằng:
   ```powershell
   python diagnose_system.py
   ```

---

### 11. QUẢN LÝ SƠ ĐỒ 32 KÊNH NHÀ THỜ (CHURCH CHANNEL MAP)
1. Bấm nút **`[Sơ Đồ Kênh]`** màu tím trên thanh Header.
2. Màn hình mở lưới 32 kênh của nhà thờ:
   - Bấm **`Chỉnh Sửa`** tại bất kỳ kênh nào để đổi tên ca sĩ, vai trò âm học (Role) hoặc ghi chú phụ trách.
   - Sau khi lưu, tên kênh sẽ tự động cập nhật ngay lập tức xuống các dải fader trên màn hình chính.
   - **Bảo vệ vĩnh viễn Kênh 11:** Biểu tượng ổ khóa màu đỏ báo hiệu cổng Talkback DL16 #11 được khóa bất biến, ngăn ngừa hoàn toàn nguy cơ gán nhầm sang loa lớn FOH.
   - Nút **`Khôi Phục Mặc Định`** giúp nạp lại cấu hình chuẩn ban đầu khi cần thiết.

---

### 12. KHO LƯU TRỮ SCENE & SO SÁNH KHÁC BIỆT (SCENE VAULT & SNAPSHOT DIFF)
1. Bấm nút **`[Kho Lưu Trữ Scene]`** màu hổ phách trên thanh Header.
2. **Tạo bản sao lưu tức thì (Snapshot Live Mixer):**
   - Nhập tên bản lưu (ví dụ: *"Lễ Sáng Chúa Nhật 12/10"*), người thực hiện và ghi chú.
   - Bấm **`Lưu Bản Sao Vào Kho`**: Hệ thống sẽ chụp toàn bộ 32 kênh từ bàn mixer thật/giả lập, tự động tính toán mã toàn vẹn SHA-256 và thẩm định nghiêm ngặt bất biến Talkback DL16 #11.
3. **Xuất file USB .scn cắm bàn mixer thật:**
   - Tại danh sách bản lưu, bấm nút **`[Tải .scn USB]`** tương ứng với snapshot mong muốn.
   - Trình duyệt sẽ tải về file `.scn` chuẩn Behringer X32/M32. Người vận hành chỉ cần chép file này vào USB rồi cắm trực tiếp vào mặt trước bàn trộn cơ vật lý để nạp cảnh mà không cần máy tính.
4. **So sánh khác biệt (Snapshot Delta Diff):**
   - Tích chọn ô vuông trước **chính xác 2 bản sao lưu** muốn so sánh.
   - Bấm **`[So Sánh 2 Bản Chọn]`**: Hệ thống tự động phân tích chi tiết từng kênh bị thay đổi (tên kênh, fader tăng/giảm bao nhiêu %, trạng thái Mute/Unmute, bộ lọc HPF và các dải PEQ 1-4).
   - Kiểm định an toàn bất biến Talkback trên cả 2 bản sao lưu được hiển thị rõ ràng trên đầu kết quả.
5. **Nạp & Thẩm Định File .scn từ USB (USB Scene Importer & Pre-Flight Safety Audit):**
   - Khi có ban nhạc khách hoặc kỹ thuật viên mang file `.scn` từ nơi khác cắm USB vào máy:
   - Trong cửa sổ Kho Lưu Trữ Scene, tại mục **`Nạp File Scene (.scn) Từ USB / Máy Tính`**, chọn file `.scn`.
   - Hệ thống lập tức kích hoạt bộ kiểm định tiền thẩm tra (**Pre-Flight Safety Audit**):
     - Tự động phát hiện nếu file có cài đặt sai đưa mic Talkback DL16 #11 ra loa lớn FOH hoặc Bus Livestream.
     - Cảnh báo các fader bị đẩy quá mức danh định ($> +5\text{ dB}$) hoặc thiếu cắt tần số thấp HPF cho micro hát.
   - Bấm **`[Kiểm Định & Nạp Vào Kho]`**: Tính năng **Auto-Sanitize** sẽ tự động vá các lỗ hổng rò rỉ Talkback (`/ch/11/mix/lr = OFF`, `/outputs/p16/11/src = 11`), kích hoạt HPF bảo vệ giọng hát, và lưu bản sao lưu an toàn 100% vào Scene Vault với mã băm SHA-256.

---

### 13. THANH RADAR CẮT HÚ THỜI GIAN THỰC & BẬT/TẮT MUTE KÊNH AN TOÀN
1. **Thanh Radar Giám Sát Rủi Ro Hú (Live Feedback Radar HUD):**
   - Khi hệ thống phát hiện tần số dao động đơn lẻ bất thường (đã qua thuật toán Harmonic Rejection loại trừ nốt ngân ca sĩ), thanh cảnh báo màu đỏ sẽ xuất hiện ngay dưới biểu đồ RTA.
   - Hiển thị rõ: Tần số hú (Hz), kênh nghi vấn (Channel) và độ tin cậy.
   - Bấm **`[Tạo Đề Xuất Notch Lọc Hú]`**: Hệ thống tự động tính toán bộ lọc Notch siêu hẹp chuẩn Quy tắc 9 ($Q = 7.0$, độ sâu giới hạn $-3.5\text{ dB}$) và nạp vào khung duyệt đề xuất.
   - Bấm **`[DUYỆT & ÁP DỤNG NOTCH CẮT HÚ]`** để gửi lệnh an toàn xuống mixer qua Safety Gate (có kiểm tra readback và lưu snapshot phục hồi).
2. **Bật/Tắt Mute Kênh Trực Tiếp:**
   - Trên mỗi dải kênh (Channel Strip) hoặc trong cửa sổ Chi Tiết Kênh, nút `ON / MUTE` cho phép bấm trực tiếp để ngắt/mở tín hiệu.
   - Mọi thao tác Mute/Unmute đều được kiểm soát qua `SafetyGate` và ghi nhật ký Audit Trail.
   - Kênh 11 Talkback ban nhạc vẫn duy trì cách ly 100% khỏi loa chính FOH kể cả khi bật hay tắt Mute.

---

### 14. GIÁM SÁT ÂM LƯỢNG LIVESTREAM & BẢO VỆ PHÁT TRỰC TIẾP (LUFS & STREAMING GUARD)
1. **Nút Giám Sát Trên Thanh Header:**
   - Trên thanh điều khiển trên cùng có nút **`[Live: -xx.x LUFS]`** màu hồng.
   - Nhãn hiển thị cập nhật thời gian thực chỉ số âm lượng ngắn hạn (Short-Term LUFS).
   - Nếu phát hiện rò rỉ kênh Talkback DL16 #11 vào đường livestream, nút sẽ chuyển sang nhấp nháy đỏ báo động: **`Live: 🚨 LỘ TALKBACK!`**.
2. **Mở Bảng Điều Khiển Livestream:**
   - Bấm trực tiếp vào nút **`[Live: ...]`** trên Header để mở cửa sổ đo đạc chi tiết.
3. **Các Chỉ Số Đo Chuẩn ITU-R BS.1770-4 / EBU R128:**
   - **Momentary Loudness (M) (400ms):** Đo mức năng lượng tức thời của tín hiệu sau bộ lọc K-weighting.
   - **Short-Term Loudness (S) (3.0s):** Chỉ số chính để đánh giá độ to khi phát trực tiếp lên mạng xã hội.
   - **Integrated Loudness (I):** Độ to tích lũy cả chương trình lễ có bộ lọc cổng kép (Gate tuyệt đối $-70\text{ LUFS}$ và Gate tương đối $-10\text{ dB}$).
   - **True Peak (dBTP):** Mức đỉnh siêu mẫu nội suy $4\times$ (Polyphase Oversampling) giúp phát hiện đỉnh tín hiệu tiềm ẩn, ngăn ngừa hiện tượng vỡ tiếng méo hài khi thuật toán nén AAC của YouTube/Facebook tái mã hóa âm thanh.
4. **Các Hồ Sơ Phát Thanh Chuẩn:**
   - **YouTube / Facebook Live:** Mục tiêu $-14.0\text{ LUFS}$ (±1.0 dB), True Peak $\le -1.0\text{ dBTP}$. Tránh bị thuật toán nén hạ âm lượng tự động (penalty compression).
   - **Hội Trường / FOH Acoustic:** Mục tiêu $-18.0\text{ LUFS}$ (±1.5 dB), True Peak $\le -0.5\text{ dBTP}$. Duy trì dynamic range thoáng đãng cho dàn nhạc sống.
   - **Truyền Hình EBU R128:** Mục tiêu $-23.0\text{ LUFS}$ (±0.5 dB), True Peak $\le -1.0\text{ dBTP}$. Tiêu chuẩn đài truyền hình chuẩn quốc tế.
5. **Kiểm Soát Bất Biến Cách Ly Talkback Tuyệt Đối:**
   - Banner an toàn ở đầu bảng điều khiển liên tục kiểm tra định tuyến của Kênh 11 (Band Talkback).
   - Đảm bảo micro trao đổi nội bộ của ban nhạc chỉ đi vào hệ thống cá nhân Ultranet P16, tuyệt đối không bị gửi nhầm vào Bus Livestream (MixBus 05) hay Main Stereo Bus.

---

### 15. CÂN CHỈNH HEADROOM & GAIN STAGING CHUẨN NHÀ THỜ (DIGITAL TRIM CALIBRATOR)
1. **Nguyên Tắc Headroom Trên Mixer Kỹ Thuật Số (Digital Headroom):**
   - Khác với mixer analog (có thể chớm đỏ $+3\text{ dB}$ mà vẫn nghe ấm), mixer kỹ thuật số như Behringer X32/M32 bị **vỡ tiếng tuyệt đối (Harsh Digital Clipping)** khi tín hiệu chạm $0\text{ dBFS}$.
   - Chuẩn âm thanh nhà thờ quy định mức dự trữ an toàn (Headroom):
     - **Micro Mục Sư / Lời Nói / Cầu Nguyện:** Đỉnh danh định **$-18.0\text{ dBFS}$** (Dự trữ sạch $18\text{ dB}$ cho những đoạn giảng cao trào hoặc nhấn giọng).
     - **Ca Đoàn / Đơn Ca Hát Thờ Phượng:** Đỉnh danh định **$-14.0\text{ dBFS}$**.
     - **Ban Nhạc / Trống / Bass:** Đỉnh danh định **$-12.0\text{ dBFS}$**.
2. **Ưu Tiên Sử Dụng Digital Trim Thay Vì Preamp Analog Gain:**
   - Khi thay đổi Gain cơ học của Preamp trên hộp DL16, tín hiệu gửi sang tai nghe in-ear **Ultranet P16** của ban nhạc sẽ bị to/nhỏ đột ngột, gây giật mình cho nhạc công.
   - Tính năng **Digital Trim Calibrator** sử dụng bộ chiết áp số (`/ch/xx/preamp/trim`, phạm vi $\pm 18\text{ dB}$) độc lập trên từng kênh. Nhạc công P16 vẫn nghe ổn định trong khi kỹ thuật viên FOH có thể làm chủ headroom hoàn toàn.
3. **Thao Tác Cân Chỉnh Trong Giờ Lễ & Tập Dượt:**
   - Bấm vào bất kỳ dải kênh nào trên màn hình chính để mở **Cửa Sổ Chi Tiết Kênh**.
   - Mục **`Cân Chỉnh Headroom & Gain Staging`** sẽ đo đạc thời gian thực các chỉ số: Peak dBFS, RMS dBFS, Crest Factor và mức Headroom hiện có.
   - Nếu tín hiệu vào quá nhỏ hoặc có nguy cơ vỡ tiếng, hệ thống sẽ đưa ra khuyến nghị $\Delta\text{ dB}$ cụ thể.
   - Bấm nút **`[Tạo Đề Xuất Cân Bằng Trim]`**: Hệ thống tạo một đề xuất an toàn, kiểm tra Whitelist và nạp vào khung duyệt Proposal để kỹ thuật viên phê duyệt áp dụng.
4. **Bảo Lưu Bất Biến Silence Hold:**
   - Khi micro không có người nói hoặc ca sĩ nghỉ hát, hệ thống **tuyệt đối không tự động tăng Gain/Trim** nhằm tránh kéo tiếng xì xào và tiếng ồn nền của hội trường.

---

### 16. DUGAN SPEECH AUTOMIXER & BỘ CHIA SẺ GAIN TỰ ĐỘNG (NOM = 1 INVARIANT)
1. **Nguyên Lý Dugan Speech Automixer & Bất Biến NOM = 1:**
   - Trong giờ lễ, khi có nhiều micro nói mở cùng lúc (Mục sư giảng luận, người hướng dẫn chương trình, đọc Kinh Thánh, cầu nguyện, micro bục giảng), tổng ồn nền của hội trường và nguy cơ hú dội tăng theo cấp số nhân ($3\text{ dB}$ cho mỗi lần nhân đôi số micro mở). Đồng thời, hiện tượng lọc lược (comb filtering) xảy ra do cùng một giọng nói lọt vào nhiều micro ở các khoảng cách khác nhau.
   - Thuật toán **Dugan Speech Automixer** áp dụng nguyên lý chia sẻ mức tăng ích (**Gain Sharing Formula**):
     $$g_k = \frac{P_k}{\sum_{i} P_i}$$
     với $P_k = 10^{(L_k + w_k) / 10}$.
   - **Bất biến $\text{NOM} = 1$ (Number of Open Microphones = 1):** Tổng độ khuếch đại âm học của toàn bộ các micro trong nhóm luôn được chuẩn hóa $\sum g_k \le 1.0$ ($0.0\text{ dB}$), tương đương như khi chỉ có duy nhất 1 micro mở.
   - Khi Mục sư cất tiếng nói, hệ thống lập tức ưu tiên toàn bộ gain cho micro Mục sư ($0\text{ dB}$), đồng thời tự động nén dìm các micro còn lại xuống mức sàn $-18\text{ dB}$, triệt tiêu hoàn toàn tiếng vang dội và tiết kiệm từ $4.8$ đến $9.5\text{ dB}$ độ ồn nền (SNR).
2. **Bảo Vệ Bất Biến Silence Hold:**
   - Khi hội trường chùng xuống trong sự cầu nguyện hoặc lúc Mục sư tạm dừng giữa các câu giảng (mức tín hiệu $< -50\text{ dBFS}$), trạng thái **Silence Hold** lập tức kích hoạt:
   - Các mức gain được khóa chặt nguyên trạng thái, tuyệt đối không tự ý đẩy fader hay tăng gain âm thanh nền (tiếng quạt, máy lạnh, tiếng cử tọa cựa quậy).
3. **Bảo Vệ Bất Biến An Toàn Tuyệt Đối Kênh 11 (Band Talkback):**
   - Kênh 11 (Talkback ban nhạc) bị **nghiêm cấm tuyệt đối** không được tham gia vào bất kỳ nhóm Automixer nào.
   - Bất kỳ cấu hình hay yêu cầu đưa Kênh 11 vào nhóm Automix đều bị SafetyGate chặn đứng ngay lập tức với lỗi `InvariantViolationError`.
4. **Sử Dụng Giao Diện Điều Khiển:**
   - Trên thanh công cụ trên cùng, nút **`[AutoMix: NOM=1]`** màu lục lam hiển thị số micro đang kết nối và trạng thái hoạt động.
   - Bấm nút để mở cửa sổ **Dugan Speech Automixer & Bộ Chia Sẻ Gain**.
   - Cửa sổ hiển thị thời gian thực: Tổng Gain âm học ($0.0\text{ dB}$), Mức tiết kiệm ồn nền, Người đang nói chính, Trạng thái Silence Hold, và dải thanh hiển thị tỷ lệ chia sẻ gain của từng kênh micro.
5. **Đồng Bộ Vào Phần Cứng Mixer Behringer X32 DSP:**
   - Bàn mixer X32 / M32 tích hợp sẵn 8 kênh xử lý Automix DSP phần cứng không độ trễ (Zero Latency) trên Kênh 1 đến Kênh 8.
   - Bấm nút **`[Áp Dụng AutoMix Vào Phần Cứng X32]`**: Hệ thống tự động tạo 4 đề xuất thiết lập Native AutoMix (`/ch/xx/automix/group` và `/ch/xx/automix/weight`), chuyển sang Bảng Đề Xuất để kỹ thuật viên xem xét và duyệt nạp an toàn xuống mixer.

---

### 17. THẨM ĐỊNH THÍNH GIÁC MÙ A/B & BỘ 7 TIÊU CHÍ CHẤM ĐIỂM CHUẨN NHÀ THỜ (ITU-R BS.1284 / MP 3.4)
1. **Nguyên Lý Bù Trừ Âm Lượng Đồng Nhất (Equal-Loudness Normalization):**
   - Theo hiệu ứng tâm lý âm học Fletcher-Munson, tai người luôn có xu hướng đánh giá một tín hiệu "to hơn" là "hay hơn". Để đánh giá khách quan một bản cân chỉnh EQ/Dynamics, hệ thống tự động đo RMS của tín hiệu gốc (Dry) và tín hiệu đề xuất (Tuning), sau đó áp dụng mức bù trừ âm lượng ($\Delta\text{ dB}$) chính xác.
   - Khi chuyển đổi qua lại giữa Lựa chọn A và Lựa chọn B, âm lượng giữ nguyên mức tuyệt đối, giúp kỹ thuật viên chỉ tập trung lắng nghe chất âm thật.
2. **Quy Trình Kiểm Thử Mù Kép (Double-Blind Protocol):**
   - Hệ thống hoán đổi ngẫu nhiên vị trí của bản Gốc (Dry) và bản Đề Xuất (Tuning) vào Lựa chọn A hoặc B.
   - Kỹ thuật viên không thể biết trước A hay B là bản nào, loại bỏ hoàn toàn định kiến tâm lý xác nhận (confirmation bias).
   - Nút **`[Mở Khóa Danh Tính Thực (Reveal)]`** chỉ được bấm sau khi kỹ thuật viên đã hoàn tất quá trình nghe thử để đối chiếu kết quả.
3. **Bộ 7 Tiêu Chí Đánh Giá Âm Học Chuẩn Nhà Thờ (Trọng số 100%):**
   - **1. Độ Rõ Lời (Speech Intelligibility) [20%]:** Từng phụ âm, từ ngữ phát ra rõ ràng, sáng sủa và dễ hiểu cho toàn bộ tín hữu.
   - **2. Độ Tự Nhiên Chất Giọng (Natural Timbre) [20%]:** Giữ trọn vẹn bản sắc giọng mộc của Mục sư hoặc ca sĩ, không bị bóp méo hay nhân tạo.
   - **3. Độ Ấm & Thân Giọng (Warmth & Body) [15%]:** Bảo tồn đầy đặn dải low-mid (200 - 400 Hz), không bị gọt quá tay làm mỏng hoặc rỗng giọng.
   - **4. Kiểm Soát Chói Gắt & Âm Xì (Harshness & Sibilance Control) [15%]:** Khử triệt để tiếng xì xào khó chịu (5 - 8 kHz) và hiện tượng chát tai khi hát nốt cao.
   - **5. Hòa Quyện Với Ban Nhạc (Band Balance) [10%]:** Giọng hát nổi bật trên nền nhạc sống nhưng không đè bẹp các nhạc cụ khác.
   - **6. Độ Phủ Đều Hội Trường (Hall Coverage Uniformity) [10%]:** Chất âm đồng đều giữa các hàng ghế đầu, giữa và cuối nhà thờ.
   - **7. Biên Độ Dự Trữ Chống Hú (Feedback Safety Margin) [10%]:** Khoảng cách an toàn trước ngưỡng phát sinh hú (Gain-Before-Feedback).
4. **Quy Tắc Phủ Quyết An Toàn (Safety Veto Rule):**
   - Nếu bất kỳ tiêu chí cốt lõi nào (Độ rõ lời, Độ tự nhiên, hoặc Biên độ chống hú) bị chấm dưới **$2.5 / 5.0$**, hệ thống lập tức ra khuyến nghị **`REJECT_OR_REFINE`**, bất kể điểm trung bình MOS tổng thể cao đến đâu.
   - Đảm bảo không bao giờ commit một bản EQ có nguy cơ phá vỡ sự tôn nghiêm hoặc gây hú micro trong giờ lễ.
5. **Thao Tác Trên Web Console:**
   - Bấm nút **`[A/B Listening (7 Tiêu Chí)]`** màu tím trên thanh Header để mở cửa sổ thẩm định.
   - Bấm chuyển đổi giữa **LỰA CHỌN A** và **LỰA CHỌN B** để nghe so sánh.
   - Kéo 7 thanh trượt để chấm điểm trực quan (1.0 đến 5.0). Chỉ số MOS và lời khuyên chiến thuật sẽ cập nhật thời gian thực.
   - Bấm **`[Lưu & Duyệt Áp Dụng Proposal]`** để vừa lưu hồ sơ thẩm định vào cơ sở dữ liệu SQLite vừa gửi lệnh an toàn xuống mixer X32 qua SafetyGate.

### 18. KIỂM SOÁT RÒ RỈ SÂN KHẤU (STAGE BLEED) & CÂN CHỈNH DOWNWARD EXPANDER CHO VOCAL
1. **Bản Chất Của Rò Rỉ Sân Khấu (Stage Bleed) & Nguy Cơ Lọc Lược (Comb Filtering):**
   - Trong không gian thánh đường có ban nhạc sống, tiếng trống Snare, Cymbals, amply đàn guitar và loa monitor sân khấu thường xuyên tràn vào các micro đơn ca, micro hướng dẫn và micro bục đọc.
   - Khi tín hiệu từ một nguồn âm lọt vào nhiều micro ở các khoảng cách khác nhau, độ lệch pha về thời gian gây ra hiện tượng **Comb Filtering (Lọc lược)**: triệt tiêu các dải tần số quan trọng, làm mỏng giọng ca sĩ, tạo cảm giác âm thanh rỗng và thiếu tự nhiên.
2. **Tại Sao Phải Dùng Downward Expander Thay Vì Noise Gate Cắt Cụt:**
   - **Noise Gate thông thường:** Ngắt hoàn toàn tín hiệu khi âm lượng dưới ngưỡng. Điều này gây hiện tượng "chém đuôi chữ" (clipping word endings), làm mất tiếng thở tự nhiên, cắt đột ngột không gian vang thánh đường (reverb tail) tạo cảm giác giật cục, thiếu tôn nghiêm.
   - **Downward Expander (Nén Mở Rộng Xuống):** Khi ca sĩ ngừng hát, hệ thống chỉ hạ nhẹ âm lượng nền xuống **8 dB đến 12 dB** (Range). Không khí phòng và đuôi vang tự nhiên vẫn được bảo toàn trọn vẹn, nhưng tiếng rò rỉ của trống và amply bị làm mờ đi đáng kể.
3. **Chiến Lược Tối Ưu Thông Số Expander Trên X32:**
   - **Ngưỡng Kích Hoạt (Threshold):** Tự động đo mức ồn nền thực tế (ambient noise floor) và thiết lập ngưỡng cao hơn ồn nền **+3 dB**.
   - **Biên Độ Nén (Range):** Khống chế nghiêm ngặt trong khoảng **6 dB - 14 dB** (tối đa cho phép qua SafetyGate là 24 dB). Không bao giờ đặt range quá sâu để tránh hiện tượng bơm hút âm thanh (noise pumping).
   - **Thời Gian Đóng/Mở (Envelope):** Attack mở cực nhanh (2 ms) để bắt trọn phụ âm đầu; Hold (80 ms) và Release dịu (350 ms) để âm đuôi ngân nga mượt mà.
   - **Lọc Khóa Sidechain (Key Filter HPF 250 Hz):** Cắt bỏ toàn bộ dải trầm dưới 250 Hz trên đường kích hoạt detector, ngăn chặn tiếng rung sàn, tiếng chân bước và tiếng bass guitar vô tình mở micro giọng nói.
4. **Bất Biến An Toàn Sống Còn (Hard Safety Invariant):**
   - Kênh 11 (Band Talkback) tuyệt đối **KHÔNG BAO GIỜ** được áp dụng Expander hay Gate cho FOH, nhằm bảo đảm tín hiệu chỉ dẫn nội bộ của ban nhạc luôn thông suốt 100% trong in-ear P16.
5. **Thao Tác Trên Web Console:**
   - Trên bảng mixer, bấm vào bất kỳ kênh Micro nào (ví dụ Kênh 1 Pastor, Kênh 2 Lead Vocal).
   - Trong cửa sổ **Chi Tiết Kênh (Channel Detail)**, cuộn xuống mục **"Kiểm Soát Rò Rỉ Sân Khấu & Vocal Expander"**.
   - Quan sát Nguồn rò rỉ, Mức độ rò rỉ, Nhiễu nền và Huy hiệu mức độ rủi ro pha (Comb Risk).
   - Bấm nút **`[Tạo Đề Xuất Downward Expander]`**. Hệ thống sẽ tính toán bộ thông số dịu nhẹ và tạo một Proposal chuẩn 5 bước lên Bảng điều khiển để kỹ thuật viên phê duyệt.

### 19. HỆ THỐNG 4 CHẾ ĐỘ QUYỀN HẠN (OPERATING MODES) & TỰ ĐỘNG KHÓA CỨNG (AUTO-DISENGAGE / PANIC FREEZE)
1. **Bốn Cấp Độ Quyền Hạn Safety Engine (Master Plan 8.1):**
   - **`OBSERVE` (Chỉ Đọc — Mặc Định Trong Lễ):**
     * Toàn bộ kênh giao tiếp OSC write xuống mixer bị khóa cứng 100%. Hệ thống chỉ lắng nghe telemetry và RTA để hiển thị trực quan.
     * Đây là chế độ mặc định khi khởi động ứng dụng, khi kết nối lại mạng hoặc sau khi đổi scene để bảo đảm an toàn tuyệt đối.
   - **`ASSIST` (Bán Tự Động — Duyệt Từng Lệnh):**
     * Dùng trong buổi tổng duyệt (rehearsal) hoặc cân chỉnh trước lễ.
     * Mọi đề xuất (EQ, Digital Trim, Notch hú, Downward Expander) chỉ được ghi xuống bàn mixer sau khi kỹ thuật viên nhấn nút **`[Duyệt Áp Dụng]`** và vượt qua bộ lọc kiểm tra SafetyGate.
   - **`LIMITED_AUTO` (Tự Động Bị Giới Hạn):**
     * Cho phép các thuật toán vi chỉnh tự động hoạt động trong biên độ cho phép: Dugan Speech Automixer chia sẻ gain $NOM=1 \le 0.0\text{ dB}$, Silence Hold chống trôi fader, và Downward Expander làm sạch tiếng ồn nền.
     * Tuyệt đối không cho phép tự động đẩy fader âm lượng lên cao.
   - **`ADMIN_MAINTENANCE` (Bảo Trì Cấp Cao — Yêu Cầu PIN):**
     * Dành riêng cho kỹ thuật viên trưởng hoặc chuyên gia âm thanh thực hiện kiểm tra định tuyến hoặc kiểm thử scene.
     * Bắt buộc nhập mã PIN bảo mật (mặc định: `7777`).
     * *Lưu ý sống còn:* Ngay cả trong chế độ ADMIN, Bất biến an toàn cách ly Kênh 11 Band Talkback khỏi Main FOH vẫn được bảo vệ bất khả xâm phạm.
2. **Cơ Chế Tự Động Ngắt Khẩn Cấp (Auto-Disengage Watchdog — MP 8.4):**
   - Hệ thống liên tục giám sát sức khỏe tín hiệu thời gian thực. Nếu phát hiện bất kỳ sự cố nào dưới đây, chế độ lập tức rơi tự do về **`OBSERVE` (Chỉ đọc)** và đóng băng toàn bộ lệnh ghi:
     * **Mất nhịp tim telemetry (Heartbeat Lost / Stale Meters):** Không nhận được dữ liệu đo đạc quá 2.5 giây.
     * **Vỡ tiếng liên tục (Excessive Clipping):** Tín hiệu chạm ngưỡng 0 dBFS liên tiếp trên 5 khung thời gian.
     * **Tăng đột biến nguy cơ hú (Feedback Risk Spike):** Xuất hiện tần số hú cấp độ Báo Động (Alarm).
     * **Nút bấm khẩn cấp (Emergency Stop Auto):** Kỹ thuật viên nhấn nút STOP AUTO màu đỏ.
3. **Thao Tác Trên Web Console:**
   - Trên thanh Header trên cùng, bấm vào huy hiệu **`[Chế độ: OBSERVE]`**.
   - Hộp thoại **Chế Độ Quyền Hạn Safety Engine** xuất hiện.
   - Chọn chế độ mong muốn (nếu chọn ADMIN, nhập mã PIN 7777).
   - Bấm **`[Áp Dụng Chế Độ]`** để chuyển đổi an toàn.
   - Trong trường hợp khẩn cấp, có thể bấm nút **`[NGẮT KHẨN CẤP TOÀN BỘ (PANIC AUTO-DISENGAGE)]`** ngay trong hộp thoại để đóng băng mixer lập tức.

### 20. MA TRẬN MONITOR SÂN KHẤU (AUX MIXBUSES) & BẤT BIẾN TAI NGHE IN-EAR ULTRANET P16 (SPRINT 26)
1. **Kiến Trúc Hệ Thống Monitor Trong Nhà Thờ:**
   - **16 Đường Gửi Phụ (MixBuses 1-16):**
     * **Bus 1-4 (Loa Sàn Stage Wedges):** Dành cho Mục sư, Ban Hát Dẫn, Ca đoàn và Nhạc cụ sân khấu. Loa hướng trực tiếp vào micro nên tiềm ẩn rủi ro hú âm học lớn nhất.
     * **Bus 5-8 (Tai Nghe In-Ear Monitors - IEMs):** Dành cho ca sĩ chính, trưởng ban nhạc và tay trống. Cần sự ổn định tối đa về âm lượng.
     * **Bus 9-12 (Subgroups / Livestream Broadcast):** Gom nhóm nhạc cụ hoặc đường gửi âm thanh phát sóng trực tiếp.
     * **Bus 13-16 (Bộ Hiệu Ứng Nội Bộ FX):** Reverb Hall, Delay, Chorus, Plate Reverb.
   - **16 Kênh Giám Sát Cá Nhân Ultranet P16 (P16-M / P16-D):**
     * Truyền 16 kênh âm thanh số qua cáp mạng Cat5 đến mixer cá nhân của từng nhạc công trên bục thờ phượng.
2. **Bất Biến An Toàn Sống Còn (Hard Safety Invariant - Rule 5):**
   - **DL16 Input 11 (Band Talkback):**
     * **CHỈ ĐƯỢC PHÉP** định tuyến duy nhất vào **Ultranet P16 Slot 11** (`/outputs/p16/11/src = 11`).
     * **TUYỆT ĐỐI CẤM** rò rỉ vào bất kỳ khe P16 nào khác (Slots 1-10, 12-16).
     * **TUYỆT ĐỐI CẤM** gửi ra bất kỳ MixBus nào đi ra FOH (`/bus/xx/mix/st = 1`) hoặc các loa monitor sàn Stage Wedges (Bus 1-4). Nếu Talkback phát ra loa sàn, tiếng nhắc nhở nội bộ của ban nhạc sẽ phát thẳng ra toàn bộ hội chúng trong nhà thờ và gây nguy cơ hú micro nghiêm trọng.
3. **Phát Hiện Nguy Cơ Hú Loa Sàn & Chuẩn Hóa Điểm Lấy Tín Hiệu (Tap-Point):**
   - **Cảnh Báo Hú (Feedback Hazard):** Bất kỳ micro giọng nói/hát nào (Pastors, Vocals, Choir) có mức gửi vào loa sàn Stage Wedge vượt quá **0.80 (+2.5 dB)** hoặc **0.85 (+5 dB)** sẽ lập tức bị hệ thống gắn cờ cảnh báo rủi ro `HIGH` hoặc `CRITICAL`.
   - **Lỗi Cấu Hình Tap-Point (Post-Fader Hazard):** Loa sàn và tai nghe IEM bắt buộc phải lấy tín hiệu **Pre-Fader** (hoặc Pre-EQ / Post-EQ). Nếu cấu hình nhầm sang **Post-Fader**, mỗi lần kỹ thuật viên đẩy fader FOH cho hội chúng nghe thì âm lượng monitor của ca sĩ sẽ bị biến động đột ngột, dễ gây giật mình hát lệch nhịp và bùng nổ tiếng hú tức thì.
4. **Tạo Đề Xuất Cân Bằng Monitor An Toàn (Safe Proposals):**
   - Tuân thủ nguyên tắc số 7: *"Đề xuất không bao giờ là mệnh lệnh"*.
   - Khi kỹ thuật viên yêu cầu kiểm tra hoặc nhấn nút **`[Tạo Đề Xuất Chống Hú & Cân Bằng]`**:
     * Nếu phát hiện Talkback vô tình bị mở vào loa sàn: Tạo đề xuất MUTE ngay lập tức (`/ch/11/mix/xx/on = 0`, level = 0.0).
     * Nếu phát hiện send micro quá lớn (> 0.80): Tạo đề xuất hạ nhẹ về mức danh định Unity 0.75 (0 dB) để khôi phục biên dự phòng an toàn (Headroom 4-6 dB).
     * Nếu phát hiện lỗi Post-Fader: Đề xuất chuyển về điểm Pre-Fader.
5. **Thao Tác Trên Web Console:**
   - Trên thanh điều khiển trên cùng, nhấn nút màu xanh lá **`[Monitor & P16 IEM]`**.
   - Hộp thoại **Ma Trận Monitor Aux & Ultranet P16 IEM** hiển thị với 3 tab:
     * **Tab 1: Ultranet P16 (16 Slots):** Xem sơ đồ 16 khe P16; Khe số 11 được viền vàng nổi bật khẳng định Talkback được cách ly an toàn.
     * **Tab 2: MixBuses (Wedges / IEMs / FX):** Xem tổng quan 16 bus, mức Master, số kênh gửi và huy hiệu cảnh báo rủi ro hú. Bấm nút **`[Tạo Đề Xuất Chống Hú & Cân Bằng]`** cho từng bus để AI tối ưu hóa.
     * **Tab 3: Cảnh Báo Hú & Tap-Point:** Liệt kê chi tiết mọi micro gửi quá ngưỡng hoặc sai cấu hình Tap-Point, kèm nút một chạm để tạo đề xuất khắc phục.

---

### 21. TIẾT MỤC — CHUYỂN MICRO BẰNG MỘT NÚT (MỤC SƯ GIẢNG, BAN HÁT, ĐƠN CA…)

**Dành cho người không chuyên.** Chế độ *Đơn giản* → bước **2. Trong lễ** → khung **"Đang diễn ra tiết mục nào?"**.

1. Bấm tên tiết mục đang diễn ra, ví dụ **Mục sư giảng**.
2. Máy hiện danh sách **Sẽ BẬT** / **Sẽ TẮT**. Kiểm tra nhanh rồi bấm **Chuyển sang "Mục sư giảng"**.
   Nếu hệ thống đang ở chế độ *Chỉ quan sát*, nút sẽ ghi **"Bật chế độ Hỗ trợ & chuyển"**.
3. Máy tắt các micro trước, rồi mới mở micro cần dùng (tránh hú lúc chuyển). Ô tiết mục chuyển sang **xanh – Đang dùng**.

Bộ mặc định: Mục sư giảng · Ban hát thờ phượng · Ban ngành · Đơn ca · Tốp ca · Thông báo / MC · Cầu nguyện. Bộ này được dựng theo **vai trò kênh** trong *Sơ đồ kênh*.

**An toàn:**
- Tiết mục **chỉ bật/tắt micro**, không bao giờ đẩy fader — âm lượng vẫn do người vận hành quyết định.
- Kênh **Talkback ban nhạc (DL16 #11)** không bao giờ thuộc tiết mục.
- Nếu mixer vừa bị chỉnh tay sau khi xem trước, máy từ chối và yêu cầu xem trước lại.
- Có lỗi đọc lại ở bất kỳ kênh nào → toàn bộ lần chuyển được hoàn tác.

**Kỹ thuật viên — lưu tiết mục:** chế độ *Kỹ thuật* → **Tiết mục**.
- Cách nhanh: chỉnh bật/tắt micro trên mixer cho đúng một tiết mục, rồi bấm **Lưu từ mixer** ở tiết mục đó (chỉ đọc mixer).
- Hoặc **Sửa**: chọn từng kênh *Bật / Tắt / Giữ nguyên* ("Giữ nguyên" = tiết mục không động tới kênh đó).
- **Tiết mục mới**, **Xóa**, **Khôi phục mặc định** đều không ảnh hưởng mixer.
- Cấu hình được lưu ở `data/service_segments.json` trên máy chủ ChurchMix.

---

### 22. TẬP XỬ LÝ HÚ (FEEDBACK DRILL — MÔ PHỎNG)

*Kỹ thuật* → **Soundcheck ảo** → chọn **Tập xử lý hú**. Micro ca sĩ (Kênh 3) sẽ "hú" giả lập ở khoảng 3,15 kHz: tăng dần, kéo dài khoảng 10 giây rồi tắt, lặp lại mỗi 24 giây.

Mở **Bàn trộn trực tiếp**: màn hình tự nhảy tới kênh gây hú, đánh dấu tần số trên biểu đồ, hiện các bước xử lý nhanh và đề xuất cắt hẹp. Bấm **Đồng ý cắt** để luyện thao tác duyệt. Đây là tín hiệu mô phỏng — không phải tiếng hú thật.

---

### 23. LÁI TỰ ĐỘNG (AUTOPILOT) — MÁY TỰ LÀM VIỆC LẶP LẠI TRONG GIỜ LỄ

**Bật:** chế độ *Đơn giản* → bước **2. Trong lễ** → **Bật lái tự động**, hoặc *Kỹ thuật* → **Lái tự động**. Bật = bạn **duyệt trước** cho máy tự chỉnh trong các giới hạn dưới đây (hệ thống chuyển sang chế độ *Tự động có giới hạn*).

| Tính năng | Máy làm gì | Giới hạn |
| --- | --- | --- |
| Tự cân giọng nói | Giữ giọng Mục sư/MC đều | ±3 dB quanh mức chuẩn, bước 0,5 dB, ≥ 2 giây/lần; đứng yên khi im lặng; không tăng khi có hú |
| Tự chống hú | Cắt hẹp −3,5 dB, Q 7 đúng tần số hú | Tối đa 2 lần/kênh/buổi; chỉ vào dải EQ còn trống; không bao giờ tăng EQ |
| Tự cân livestream | Giữ bus livestream gần −16 LUFS | Chỉ bus 5, ±6 dB, bước 0,5 dB/5 giây; cần nguồn đo của chính bus livestream |
| Cảnh báo vỡ tiếng | Báo kênh sát 0 dBFS | Chỉ cảnh báo — máy không chỉnh preamp |

**Giữ chất âm:** máy không tự thiết kế âm thanh. Mức chuẩn lấy từ **bản mix chuẩn** của tiết mục (*Tiết mục → Lưu từ mixer* lưu cả vị trí fader) hoặc từ vị trí fader lúc bật. Bạn **kéo fader tay bất cứ lúc nào** — máy sẽ theo mức mới của bạn, không giành lại.

**Máy không bao giờ:** chỉnh preamp, routing, Main LR, Talkback; tăng EQ; ghi đè EQ đang dùng; tăng âm lượng khi im lặng.

**Dừng:** bấm **STOP**, bấm **Tắt lái tự động**, hoặc đổi chế độ. Hệ thống cũng tự dừng khi dữ liệu đo không hợp lệ, khi vỡ tiếng liên tục hoặc khi có hú mạnh (CRITICAL) — lúc đó người xử lý.

**Sau lễ:** xem *Các lần cắt hú tự động* và *Cần người xử lý*. **Hoàn tác mọi thay đổi của máy** đưa fader và bus livestream về mức chuẩn, trả các dải EQ đã cắt về như trước.

**Nguồn đo:** khi nối X32 thật, máy đọc **meter kênh của X32** (chỉ đọc). Dữ liệu mô phỏng chỉ được dùng với mixer giả lập — không bao giờ điều khiển bàn thật.
