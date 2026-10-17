# Quy Trình Đo Âm Học Hội Trường & Loa FOH (Acoustic Measurement SOP)

Tài liệu quy trình chuẩn (SOP) dành cho kỹ thuật viên âm thanh khi thực hiện đo đạc đáp tuyến phòng và cân chỉnh hệ thống loa chính (FOH / PA) tại Nhà thờ.

---

## 1. Thiết Bị & Chuẩn Bị Trước Khi Đo

1. **Microphone Đo (Measurement Mic):**
   - Sử dụng micro đo có đáp tuyến phẳng omnidirectional (ví dụ: Dayton Audio EMM-6, Beyerdynamic MM1, Behringer ECM8000, hoặc miniDSP UMIK-1).
   - Nạp file hiệu chuẩn (calibration file `.cal` hoặc `.frd`) tương ứng số serial của micro nếu có.
2. **Tín Hiệu Kiểm Tra (Test Signal):**
   - Sử dụng **Pink Noise** đồng bộ (48 kHz, mức danh định $-18\text{ dBFS}$ đến $-12\text{ dBFS}$).
   - Mức âm lượng trong phòng chỉ cần đạt khoảng $75 - 80\text{ dBA}$ (vừa đủ vượt mức ồn nền phòng khoảng $15 - 20\text{ dB}$).
3. **Điều Kiện Hiện Trường Bắt Buộc:**
   - Hội trường hoàn toàn vắng người (thực hiện ngoài giờ lễ, trong buổi bảo trì kỹ thuật).
   - Đóng toàn bộ cửa sổ và cửa ra vào hội trường.
   - Giữ nguyên hệ thống rèm và ghế ngồi như trong giờ lễ thật.

---

## 2. Đo Hàm Truyền Hai Kênh (Dual-Channel H1 Transfer Function)

Hệ thống sử dụng kỹ thuật đo hai kênh để loại bỏ hoàn toàn đặc tính của tín hiệu kích thích và chỉ giữ lại đáp tuyến âm học thực của phòng:

1. **Kênh Tham Chiếu (Reference Channel $x[n]$):** Tín hiệu Pink Noise kỹ thuật số trực tiếp từ nguồn phát trước khi đi ra loa.
2. **Kênh Đo (Measurement Channel $y[n]$):** Tín hiệu thu được từ micro đo đặt tại vị trí người ngồi nghe.
3. **Ước Lượng Hàm Truyền $H_1(f)$:**
   $$H_1(f) = \frac{S_{yx}(f)}{S_{xx}(f)}$$
   Trong đó $S_{yx}(f)$ là phổ tương quan chéo (cross-spectral density) và $S_{xx}(f)$ là tự tương quan của tín hiệu tham chiếu.
4. **Hàm Coherence $\gamma^2(f)$ (Độ Tin Cậy Âm Học):**
   $$\gamma^2(f) = \frac{|S_{yx}(f)|^2}{S_{xx}(f) \cdot S_{yy}(f)}, \quad 0 \le \gamma^2(f) \le 1$$
   - $\gamma^2 \ge 0.8$: Dữ liệu âm học có độ tin cậy rất cao, phản ánh trực tiếp âm thanh từ loa tới micro.
   - $\gamma^2 < 0.6$: Khu vực bị ảnh hưởng nặng bởi tiếng ồn nền hoặc hiện tượng triệt tiêu pha do sóng dội (comb filtering).

---

## 3. Căn Chỉnh Thời Gian & Độ Trễ (Delay Alignment)

Trước khi phân tích đáp tuyến pha (phase) và biên độ (magnitude):
1. Tính toán hàm tương quan chéo thời gian thực giữa kênh tham chiếu và kênh đo để xác định **thời gian bay của âm thanh (Time-of-Flight / Delay)**:
   $$\tau = \text{argmax}_t (R_{xy}(t))$$
2. Bù chính xác độ trễ $\tau$ (tính bằng mili-giây) vào kênh tham chiếu trước khi tính toán FFT.
3. Việc căn độ trễ chính xác ngăn ngừa hiện tượng xoắn pha (phase wrapping) giả tạo.

---

## 4. Bất Biến Sống Còn: No-Boost-in-Nulls (Cấm Bù Dải Triệt Tiêu)

### Nguyên Lý Vật Lý
Nhiều hố lõm sâu trên đáp tuyến tần số (đặc biệt ở dải $100 - 400\text{ Hz}$) sinh ra do hiện tượng dội sàn (floor bounce) hoặc phản xạ từ trần/tường tạo nên giao thoa triệt tiêu pha (acoustic phase cancellation / comb filtering).
Tại tần số triệt tiêu, sóng âm phản xạ ngược pha $180^\circ$ với sóng trực tiếp. 

> **CẢNH BÁO NGUY HIỂM:**
> Nếu kỹ thuật viên cố tình đẩy PEQ tăng $+6\text{ dB}$ hay $+9\text{ dB}$ vào hố lõm triệt tiêu pha:
> - Sóng dội cũng sẽ tăng tương ứng và tiếp tục triệt tiêu sóng trực tiếp.
> - Hố lõm **vẫn không phẳng ra**.
> - Củ loa trầm/loa trung bị ép hoạt động quá công suất cực hạn, gây méo tiếng và có nguy cơ **cháy cuộn cảm loa (blown voice coil)**!

### Quy Tắc Thuật Toán Của Hệ Thống
Hệ thống ChurchMix áp dụng bộ lọc cưỡng bức `filter_no_boost_nulls`:
- Khi phát hiện một hố lõm có $Magnitude < -6.0\text{ dB}$ và $Coherence < 0.65$:
  $$\text{Safe Target EQ}(f) = \min(0.0\text{ dB}, \text{Target EQ}(f))$$
- Tất cả các đề xuất tăng gain dương tại điểm này đều bị khóa cứng về $\le 0.0\text{ dB}$.

---

## 5. Các Vị Trí Đo Đại Diện (Multi-Position Sampling)

Không bao giờ cân chỉnh hệ thống loa chỉ dựa trên duy nhất một vị trí ghế ngồi:
1. **Vị Trí 1 (Center Hall):** Chính giữa hội trường (cự ly FOH tiêu chuẩn).
2. **Vị Trí 2 (Front Row Center):** Hàng ghế đầu, kiểm tra góc phủ loa chính và loa front-fill.
3. **Vị Trí 3 (Under Balcony):** Khu vực dưới gầm ban công (kiểm tra độ suy giảm dải cao do che chắn vật lý).
4. **Vị Trí 4 (Rear Hall):** Hàng ghế cuối cùng của hội trường.

Sau khi đo đủ các vị trí, hệ thống sẽ tính toán đường cong trung bình năng lượng (Spatial Average) và chỉ đưa ra các bộ lọc PEQ giải quyết các vấn đề chung của toàn bộ không gian phòng.
