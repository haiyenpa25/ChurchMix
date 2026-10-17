# HƯỚNG DẪN SỬ DỤNG CHI TIẾT HỆ THỐNG CHURCHMIX
## X32 AI Sound Engineer — Trợ Lý Kỹ Thuật Âm Thanh Nhà Thờ Thông Minh & An Toàn

> Tài liệu hướng dẫn từng bước dành cho Ban Kỹ Thuật Âm Thanh & Nhân sự phụng vụ nhà thờ.  
> Tương thích tối ưu với: **Behringer X32 Compact / Producer / Full / Midas M32**, stagebox **Midas DL16 / S16**, và hệ thống monitor cá nhân **Ultranet P16-M / P16-HQ**.

---

## MỤC LỤC

1. [Tổng Quan & Các Bất Biến An Toàn Sống Còn](#1-tổng-quan--các-bất-biến-an-toàn-sống-còn)
2. [Sơ Đồ Đấu Nối Vật Lý & Chuẩn Bị Thiết Bị](#2-sơ-đồ-đấu-nối-vật-lý--chuẩn-bị-thiết-bị)
3. [Khởi Động Nhanh Với 1 Click Chuột](#3-khởi-động-nhanh-với-1-click-chuột)
4. [Khám Phá Giao Diện Bàn Điều Khiển Web (Console Dashboard)](#4-khám-phá-giao-diện-bàn-điều-khiển-web-console-dashboard)
5. [Hướng Dẫn Chi Tiết 7 Quy Trình Chuẩn (SOP Wizards W1 – W7)](#5-hướng-dẫn-chi-tiết-7-quy-trình-chuẩn-sop-wizards-w1--w7)
6. [Xuất File Scene USB Cắm Trực Tiếp Mặt Trước X32 (.scn)](#6-xuất-file-scene-usb-cắm-trực-tiếp-mặt-trước-x32-scn)
7. [Tự Động Dò Tìm Bàn Trộn Qua Mạng LAN (Auto-Discovery)](#7-tự-động-dò-tìm-bàn-trộn-qua-mạng-lan-auto-discovery)
8. [Xử Lý Tình Huống Khẩn Cấp & Nút STOP AUTO](#8-xử-lý-tình-huống-khẩn-cấp--nút-stop-auto)
9. [Giải Đáp Thắc Mắc & Xử Lý Sự Cố Thường Gặp (FAQs)](#9-giải-đáp-thắc-mắc--xử-lý-sự-cố-thường-gặp-faqs)

---

## 1. TỔNG QUAN & CÁC BẤT BIẾN AN TOÀN SỐNG CÒN

Hệ thống **ChurchMix** hoạt động như một "kỹ sư âm thanh phụ tá" luôn túc trực bên cạnh người vận hành. Phần mềm tuân thủ nghiêm ngặt các nguyên tắc bất biến:

* **Bất biến DL16 #11 (Band Talkback):**
  * Tín hiệu từ cổng mic số 11 trên stagebox DL16 được dành riêng cho micro nội bộ của ban nhạc.
  * **Hệ thống luôn khóa cứng**, tuyệt đối không bao giờ cho phép âm thanh từ mic này lọt ra hệ thống loa lớn FOH (Main LR, Matrix, Center). Nó chỉ được phép dẫn truyền vào Ultranet P16 Slot 11.
* **Nguyên tắc "Read-Only First" (Chỉ đọc trước):**
  * Khi mới bật phần mềm hoặc kết nối với bàn mixer, hệ thống luôn hoạt động ở chế độ `OBSERVE` (chỉ đọc dữ liệu đo lường, không gửi bất kỳ lệnh ghi nào xuống bàn mixer).
* **Một Đề Xuất Không Phải Là Một Mệnh Lệnh:**
  * Trí tuệ nhân tạo chỉ đưa ra đề xuất âm học (EQ, cắt hú, cân mức) và giải thích lý do bằng tiếng Việt.
  * Kỹ thuật viên phải nhấp nút **"Duyệt & Áp Dụng"** thì tham số mới được gửi xuống mixer.
* **Silence Hold (Chống trôi Fader):**
  * Khi Mục sư tạm ngừng nói hoặc micro im lặng, hệ thống khóa chặt fader, không bao giờ tự động đẩy gain/fader lên làm kéo ồn nền phòng thờ phượng.
* **No-Boost-in-Nulls:**
  * Không bù boost EQ vào các điểm triệt tiêu pha do âm học phòng gây ra ($Coherence < 0.65$).
* **Chống Hú Đa Bằng Chứng:**
  * Kiểm tra hài âm tự nhiên ($2f..5f$) để không cắt nhầm nốt ca sĩ ngân dài.

---

## 2. SƠ ĐỒ ĐẤU NỐI VẬT LÝ & CHUẨN BỊ THIẾT BỊ

### 2.1 Các kết nối cáp cần thiết

```text
[Sân Khấu]
   │
   └── Midas DL16 Stagebox
         ├── Cổng AES50 A ──────── (Cáp mạng Cat5e/Cat6) ────────┐
         └── Cổng ULTRANET ─────── (Cáp mạng Cat5e) ──> Bộ chia P16-D ──> 3x P16-HQ In-Ear
                                                                 │
[Bàn Trộn Âm Thanh FOH]                                          │
   │                                                             │
   └── Behringer X32 Compact <───────────────────────────────────┘
         ├── Cổng Mạng ETHERNET ── (Cáp mạng LAN) ──┐
         ├── Cổng USB X-USB ────── (Cáp USB Type-B) ┼──> [Laptop / Máy Tính Điều Khiển]
         └── Cổng MAIN OUT L/R ──> Loa Hội Trường ──┘    (Chạy ChurchMix Server & UI)
```

1. **Cáp mạng LAN (Ethernet):**
   * Nối từ cổng `REMOTE / ETHERNET` phía sau bàn mixer X32 vào cổng mạng của Laptop hoặc cắm chung vào Router Wi-Fi nội bộ của nhà thờ.
   * Giao thức truyền thông: OSC qua cổng UDP `10023`.
2. **Cáp USB (Card X-USB / X-LIVE):**
   * Cắm từ cổng USB phía sau bàn X32 vào Laptop để thu nhận 32 kênh multitrack thời gian thực cho bộ phân tích phổ RTA và phát hiện hú.
3. **Cáp AES50 A:**
   * Cắm từ cổng AES50 A của X32 đến cổng AES50 A của DL16 trên sân khấu.
4. **Cáp Ultranet:**
   * Cắm từ cổng Ultranet của DL16 vào bộ chia P16-D cấp cho 3 mixer cá nhân P16-HQ của ban nhạc.

---

## 3. KHỞI ĐỘNG NHANH VỚI 1 CLICK CHUỘT

Trên máy tính điều khiển (Windows 10 hoặc 11):

1. Nhấp đúp chuột vào tệp:
   ```text
   start_church_engineer.bat
   ```
2. Cửa sổ dòng lệnh sẽ tự động:
   * Kiểm tra và kết nối với bàn mixer X32 (hoặc bộ giả lập Mock X32 nếu chưa cắm phần cứng).
   * Khởi chạy máy chủ API & Web Dashboard.
   * Tự động mở trình duyệt web tại địa chỉ: **`http://127.0.0.1:8080`**.

> **Mẹo:** Bạn có thể tạo lối tắt (Shortcut) của tệp `start_church_engineer.bat` ra ngoài màn hình Desktop để các bạn trong ban âm thanh dễ dàng bấm mở mỗi Chúa Nhật.

---

## 4. KHÁM PHÁ GIAO DIỆN BÀN ĐIỀU KHIỂN WEB (CONSOLE DASHBOARD)

Giao diện gồm các khu vực trực quan:

1. **Thanh Tiêu Đề (Header Bar):**
   * **Trạng thái X32:** Hiển thị `X32 Compact: ONLINE` (xanh lá).
   * **Chế độ:** `OBSERVE (Chỉ đọc)` bảo vệ an toàn.
   * **Huy hiệu DL16 #11:** `DL16 #11: P16 ONLY` xác nhận bất biến an toàn đang được kiểm soát 100%.
   * **Nút bấm Wizards:** Mở bảng 7 quy trình SOP.
   * **Nút Mixer Hardware:** Đổi IP LAN của mixer thật hoặc chuyển sang chế độ giả lập.
   * **Nút Card USB:** Chọn soundcard thu âm (X-USB ASIO/WASAPI).
   * **NÚT ĐỎ STOP AUTO:** Nút bấm khẩn cấp khóa mọi tác vụ ghi dưới 50ms.
2. **Phổ Âm Học 1/12-Octave RTA (60 FPS Canvas):**
   * Hiển thị năng lượng âm thanh từ 20 Hz đến 20.000 Hz theo thời gian thực.
   * Vạch đỏ: Cảnh báo nguy cơ hú (Feedback Risk).
   * Vạch xanh lá: Hài âm tự nhiên của giọng hát (Harmonic Safe).
3. **Bàn Trộn 32 Kênh (Channel Strips):**
   * Hiển thị đầy đủ 32 kênh với tên gợi nhớ (Pastor, Lead Voc, Piano, Bass, Drums...).
   * Cột đèn LED Peak meter hiển thị mức âm lượng sống động.
   * Kênh 11 (Band Talkback) được ghim nhãn xanh đậm `P16 Only`.
   * **Chạm vào bất kỳ kênh nào** để mở cửa sổ **Channel Inspector**: Xem chi tiết 4 dải PEQ, HPF, Mute, Routing và bấm nút **"Tạo Đề Xuất PEQ Cho Kênh Này"** với 7 cấu hình âm thanh tùy chọn.
4. **Trợ Lý AI Sound Copilot (Tiếng Việt):**
   * Hỏi đáp nhanh kỹ thuật âm thanh nhà thờ.
   * Nhấp vào các gợi ý: *"Tiếng Mục sư rõ lời"*, *"Xử lý hú an toàn"*, *"Kiểm tra cổng Talkback DL16 #11"*.
5. **Cửa Sổ Đề Xuất Cân Chỉnh PEQ (A/B Curve Preview):**
   * **Bộ tạo đề xuất đa vai trò:** Chọn bất kỳ Kênh nào (CH 1–32) và Vai trò âm thanh phù hợp (Mục Sư, Nữ Đơn Ca, Nam Đơn Ca, Ca Đoàn, Acoustic Guitar, Piano / Keys, Bass Guitar) $\rightarrow$ Bấm nút **"Tạo"** để tạo ngay đề xuất PEQ tối ưu.
   * **Bản xem trước A/B:** Xem trước đường cong đáp tuyến tần số mô phỏng trước và sau khi can thiệp trên Canvas HTML5.
   * **Phê duyệt an toàn:** Bấm nút **"DUYỆT & ÁP DỤNG QUA SAFETY GATE"** khi đồng ý.
6. **Nhật Ký Giao Dịch Bất Biến (Audit Trail):**
   * Ghi nhận lịch sử mọi thao tác kèm mã băm SHA-256 chống chỉnh sửa giả mạo.

---

## 5. HƯỚNG DẪN CHI TIẾT 7 QUY TRÌNH CHUẨN (SOP WIZARDS W1 – W7)

Nhấp vào nút **`[Wizards Quy Trình]`** trên thanh tiêu đề để mở bảng điều khiển quy trình:

### W1: Kiểm Kê & Xác Thực Định Tuyến An Toàn (Inventory & Routing)
* **Khi nào dùng:** Đầu buổi tập hoặc khi vừa cắm dây hệ thống mới.
* **Mục đích:** Tự động rà soát toàn bộ 32 kênh, phân loại theo vai trò và kiểm tra xem cổng DL16 #11 có bị route nhầm ra FOH không.
* **Thao tác:** Bấm **"Quét Kiểm Kê Ngay"** $\rightarrow$ Hệ thống xuất báo cáo trạng thái chi tiết.

### W2: Line Check Chúa Nhật (Sunday Pre-Service Check)
* **Khi nào dùng:** 30 phút trước giờ thánh lễ.
* **Mục đích:** Kiểm tra thực địa 4 yếu tố vật lý sống còn:
  1. Pin micro không dây (Mục sư, Ca trưởng $\ge 2$ vạch).
  2. Đèn tín hiệu cáp mạng AES50 A stagebox DL16.
  3. Cáp mạng P16-D và tiếng trong tai nghe 3 bộ P16-HQ của ban nhạc.
  4. Bấm thử mic Talkback DL16 #11 (xác nhận chỉ kêu trong tai nghe ban nhạc, FOH im lặng).
* **Thao tác:** Tích chọn 4 ô $\rightarrow$ Khi đạt **`READY 100%`** là sẵn sàng vào lễ.

### W3: Cân Chỉnh Giọng Nói & Bài Giảng (Vocal Calibration)
* **Khi nào dùng:** Trong buổi tập âm thanh trước lễ.
* **Mục đích:** Cân chỉnh PEQ cho micro Mục sư hoặc người hướng dẫn thờ phượng.
* **Thao tác:**
  1. Chọn kênh micro cần cân (ví dụ: Ch 01 - Pastor Mic).
  2. Chọn vai trò (Mục Sư, Nữ Đơn Ca, Nam Đơn Ca, Ca Đoàn).
  3. Yêu cầu ca sĩ/Mục sư hát hoặc nói tự nhiên vào micro khoảng 20 giây.
  4. Bấm **"Lấy Mẫu 20s & Phân Tích Đề Xuất Âm Học"**.
  5. Hệ thống sẽ hiển thị bảng PEQ, thông số compressor và hướng dẫn bố trí micro vật lý.
  6. Bấm **"Nạp Sang Bản Xem Trước A/B & Duyệt Áp Dụng (Safety Gate)"** để xem trước và nạp xuống mixer.

### W4: Cân Chỉnh Hệ Thống Loa Hội Trường (Room / PA Tuning H1)
* **Khi nào dùng:** Khi thiết lập âm thanh tại không gian phòng mới hoặc định kỳ 6 tháng.
* **Mục đích:** Đo hàm truyền hai kênh ($H_1$), căn thời gian trễ loa (Time-of-flight Delay) và kích hoạt nguyên tắc bảo vệ loa **No-Boost-in-Nulls**.
* **Thao tác:** Bấm **"Chạy Đo Hàm Truyền H1"** hoặc nhập file CSV từ Open Sound Meter / REW.

### W5: Dò Hú An Toàn Khi Tập (Safe Feedback Ring-Out)
* **Khi nào dùng:** Buổi tập ban nhạc khi **hội trường hoàn toàn không có khán giả**.
* **Mục đích:** Tìm trước các điểm tần số có nguy cơ hú của phòng để cắt notch filter hẹp dự phòng.
* **Thao tác:** Làm theo 8 bước hướng dẫn chi tiết trên màn hình. Hệ thống sẽ tự động bắt tần số hú và tạo bộ lọc notch cực hẹp ($Q \ge 6.0$, cắt tối đa $-3.5\text{ dB}$).
* Bấm **"Nạp Notch Filter Sang Safety Gate Để Duyệt Áp Dụng (Q=7.0)"** để áp dụng an toàn xuống bàn mixer.

### W6: Trợ Lý Trực Tiếp Buổi Lễ (Live Service Tactical Assistant)
* **Khi nào dùng:** Mở xuyên suốt trong suốt buổi lễ thờ phượng.
* **Mục đích:**
  * Giám sát mức âm lượng Master và Headroom.
  * Hiển thị trạng thái **Silence Hold**: Khóa fader khi Mục sư ngưng nói.
  * Cảnh báo nguy cơ quá tải (Clipping Guard).
  * Nhắc nhở bất biến cổng Talkback DL16 #11.

### W7: Báo Cáo Tổng Kết Buổi Lễ (Post-Service Debrief)
* **Khi nào dùng:** Sau khi kết thúc buổi lễ.
* **Mục đích:** Thống kê các sự cố phát sinh, số lần can thiệp EQ, mức âm lượng trung bình và xuất file báo cáo Markdown (.md) lưu trữ cho ban kỹ thuật.

---

## 6. XUẤT FILE SCENE USB CẮM TRỰC TIẾP MẶT TRƯỚC X32 (.SCN)

Nếu bạn không muốn kết nối máy tính trong giờ lễ, bạn có thể xuất toàn bộ cấu hình tối ưu thành file Scene vật lý của Behringer X32:

1. Trên bảng điều khiển (Panel Nhật Ký Giao Dịch), nhấn nút **`[Xuất File Scene USB (.scn) Cho X32]`**.
2. Trình duyệt sẽ tải về tệp tin có tên: `ChurchMix_FOH.scn`.
3. Cắm một chiếc USB định dạng **FAT32** vào máy tính và chép tệp `ChurchMix_FOH.scn` vào thư mục gốc của USB.
4. Rút USB và cắm vào cổng USB trên mặt trước bàn trộn X32 Compact.
5. Trên màn hình X32: Nhấn nút **Scenes** $\rightarrow$ Chọn tab **Utility** $\rightarrow$ Chọn **Load Scene** $\rightarrow$ Chọn tệp `ChurchMix_FOH.scn`.

> **Đảm bảo an toàn tuyệt đối:** File scene này đã được lập trình sẵn dòng lệnh khóa cứng kênh 11:
> `/ch/11/mix/lr OFF` và `/outputs/p16/11/src 11` để bảo vệ 100% không cho tiếng talkback lọt ra loa lớn FOH ngay cả khi chạy độc lập từ USB!

---

## 7. TỰ ĐỘNG DÒ TÌM BÀN TRỘN QUA MẠNG LAN (AUTO-DISCOVERY)

Khi kết nối với hệ thống mạng LAN tại nhà thờ:

1. Nhấn vào nút **`Mixer: Simulator`** trên thanh Header.
2. Cửa sổ Hardware Switcher hiện ra.
3. Nhấn nút **"Tự Động Quét Mạng (UDP Discovery)"**.
4. Hệ thống sẽ phát gói tin OSC `/info` broadcast trên cổng UDP `10023` và tự động tìm thấy bàn mixer Behringer X32 / Midas M32 trong mạng nội bộ kèm địa chỉ IP và phiên bản Firmware.
5. Nhấn vào bàn mixer tìm được để kết nối trực tiếp.

---

## 8. XỬ LÝ TÌNH HUỐNG KHẨN CẤP & NÚT STOP AUTO

Khi đang trong buổi lễ trực tiếp nếu xảy ra hiện tượng âm thanh bất thường:

1. **Bấm Nút STOP AUTO màu đỏ:**
   * Nhấp chuột vào nút **STOP AUTO** to màu đỏ ở góc trên bên phải màn hình (hoặc bấm phím tắt nếu được thiết lập).
   * Trong vòng **dưới 50 mili-giây**, hệ thống sẽ:
     * Hủy bỏ mọi tác vụ tự động đang chạy.
     * Khóa chặt luồng gửi lệnh ghi OSC (trả về lỗi HTTP 403 nếu có lệnh can thiệp).
     * Đưa trạng thái về `OBSERVE` (Chỉ đọc).
2. **Xử lý cơ học trên bàn mixer vật lý:**
   * Cơ chế **Fail-Safe** của X32 đảm bảo: Dù máy tính tắt, phần mềm dừng hay đứt cáp mạng, bàn mixer X32 vẫn giữ nguyên trạng thái hoạt động bình thường, không làm ngắt quãng âm thanh buổi lễ. Bạn có thể kéo cần gạt fader vật lý trên mixer bất kỳ lúc nào.

---

## 9. GIẢI ĐÁP THẮC MẮC & XỬ LÝ SỰ CỐ THƯỜNG GẶP (FAQS)

### Q1: Vì sao màn hình hiển thị "X32: OFFLINE"?
* **Nguyên nhân:** Dây mạng LAN chưa cắm chặt hoặc địa chỉ IP giữa máy tính và X32 không cùng lớp mạng (Subnet).
* **Cách khắc phục:**
  1. Kiểm tra cáp mạng cắm vào cổng `REMOTE / ETHERNET` phía sau X32.
  2. Trên bàn X32, bấm nút **Setup** $\rightarrow$ chọn tab **Network** để xem địa chỉ IP (ví dụ: `192.168.1.50`).
  3. Mở cửa sổ Hardware Switcher trên ChurchMix và nhập đúng địa chỉ IP đó, sau đó bấm Kết nối.

### Q2: Vì sao mic Talkback DL16 #11 không được mở ra loa lớn FOH?
* **Trả lời:** Đây là **Bất biến an toàn sống còn số 1** của hệ thống. Micro Talkback là kênh trao đổi nội bộ riêng tư giữa người điều phối âm thanh và các nhạc công trong ban nhạc. Nếu mở ra loa FOH, tiếng trao đổi nội bộ sẽ lọt ra toàn bộ hội chúng, gây gián đoạn không khí trang nghiêm của buổi lễ.

### Q3: Tôi có thể sử dụng ChurchMix khi không có máy tính nối với mixer không?
* **Trả lời:** Có! Bạn chỉ cần dùng ChurchMix để tinh chỉnh trong các buổi tập, sau đó xuất ra file `ChurchMix_FOH.scn` cắm vào USB theo hướng dẫn ở Mục 6 để tải vào bàn mixer.

### Q4: Tiếng micro Mục sư bị hú rít thì xử lý thế nào nhanh nhất?
1. Kéo nhẹ fader mic Mục sư xuống khoảng 2–3 dB trên bàn mixer.
2. Mở tab **W3: Vocal Calibration** hoặc xem phổ RTA để AI định vị tần số hú.
3. Kích hoạt bộ lọc Notch Filter hẹp tại đúng tần số được gợi ý ($Q=6.5$, cắt $-3\text{ dB}$).
4. Nhắc người nói đưa micro lại gần miệng hơn (khoảng 3–5 cm) và hướng đầu mic chếch về khóe miệng để tăng tỷ lệ tín hiệu trên nhiễu.

---


*Tài liệu được biên soạn bởi Ban Kỹ Thuật ChurchMix — Phục vụ vì sự trang nghiêm và sống động trong thánh vụ thờ phượng.*

