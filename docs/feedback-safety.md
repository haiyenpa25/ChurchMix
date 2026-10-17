# NGUYÊN LÝ PHÁT HIỆN HÚ VÀ TRIỆT TIÊU BẢO TOÀN ÂM SẮC

---

### 1. Bản Chất Vật Lý Của Tiếng Hú (Acoustic Feedback Loop)
Tiếng hú trong nhà thờ xảy ra khi tín hiệu phát ra từ hệ thống loa (FOH hoặc loa Monitor sân khấu) quay trở lại màng rung của micro với **độ lợi vòng lặp (Loop Gain) lớn hơn hoặc bằng 1.0 (0 dB)** và **cùng pha (Positive Feedback)** tại một tần số xác định.

$$\text{Loop Gain}(f) = G_{\text{preamp}} \cdot G_{\text{eq}} \cdot G_{\text{fader}} \cdot H_{\text{speaker}}(f) \cdot H_{\text{room}}(f) \cdot H_{\text{mic}}(f) \ge 1$$

---

### 2. Thuật Toán Phát Hiện Đa Bằng Chứng (Multi-Evidence Detector)
Một thuật toán chỉ dựa trên việc phát hiện đỉnh biên độ (Peak FFT) sẽ **thường xuyên báo động giả** khi:
- Ca sĩ hát ngân dài một nốt cao (ví dụ: Nốt La 440 Hz hoặc Mi 660 Hz).
- Tiếng đàn Piano, Organ hoặc Guitar duy trì âm sắc (*sustain*).

Hệ thống X32 AI Sound Engineer áp dụng bộ lọc **4 tiêu chí kết hợp**:

1. **Độ sắc nhọn (Tonality & Narrow Peak):**
   - Đỉnh tần số phải nhô cao ít nhất $12\text{ dB}$ so với nền năng lượng âm thanh xung quanh trong phạm vi $\pm 50\text{ Hz}$.
2. **Độ bền vững thời gian (Persistence):**
   - Tần số không được trôi dạt quá $2\%$ và phải tồn tại liên tục qua ít nhất 3 khung phân tích ($> 150\text{ ms}$).
3. **Bộ lọc kiểm tra Hài Âm Tự Nhiên (Harmonic Rejection Filter - Sống còn):**
   - Giọng hát con người và nhạc cụ acoustic **luôn luôn** đi kèm dãy bồi âm tự nhiên theo tỷ lệ nguyên bội:
     $$2f_0, \quad 3f_0, \quad 4f_0, \quad 5f_0$$
   - Nếu phát hiện đỉnh tần số $f_0$ có xuất hiện các hài âm $2f_0$ hoặc $3f_0$ tương ứng trong phổ $\rightarrow$ **Xác nhận là giọng hát của ca sĩ $\rightarrow$ BỎ QUA, KHÔNG BÁO ĐỘNG HÚ**.
   - Tiếng hú là cộng hưởng đơn tần độc lập nên **hoàn toàn không có dãy hài âm tự nhiên**.
4. **Tốc độ tăng trưởng biên độ (Anomalous Growth Rate):**
   - Năng lượng tăng nhanh theo cấp số nhân trong khi mức âm thanh tổng thể của phòng không thay đổi.

---

### 3. Quy Tắc Cắt Notch Filter Phẫu Thuật (Surgical Notch)
Khi đã xác nhận tần số hú với độ tin cậy $\text{Confidence} \ge 0.70$:
* **Hệ số phẩm chất (Q Factor):** Đặt ở mức rất cao $Q = 6.0 \text{ đến } 7.5$ (bề rộng dải cắt chỉ khoảng $1/10$ đến $1/12$ octave).
* **Độ sâu cắt (Cut Depth):** Giới hạn tối đa $-3.0\text{ dB} \text{ đến } -4.5\text{ dB}$.
* **Hệ quả âm học:**
  * Giảm Loop Gain tại đúng điểm cộng hưởng xuống dưới 1.0 $\rightarrow$ Dập tắt vòng lặp hú ngay lập tức.
  * Giữ nguyên $98\%$ năng lượng các dải tần lân cận $\rightarrow$ Người nghe và ca sĩ không nhận ra bất kỳ sự thay đổi nào về độ dày hay ấm của giọng hát.
  * **Tuyệt đối không cắt rộng (Low Q)** hoặc cắt quá sâu ($-15\text{ dB}$) vì sẽ làm giọng hát bị "thủng", nghẹt mũi và biến dạng.
