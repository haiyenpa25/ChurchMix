# Rà soát và tối ưu ChurchMix — 12/10/2026

Phạm vi: backend Python của ChurchMix, truy vấn trạng thái OSC, xử lý phổ âm thanh và whitelist SafetyGate. Phần Node.js tạo dự án cũng được chạy bộ kiểm thử hiện có. Không kết nối hoặc ghi tới mixer thật; kiểm thử Python chạy trong bản sao tạm, với mock X32 và dữ liệu riêng.

## Thay đổi đã thực hiện

| Thành phần | Trước | Sau |
| --- | --- | --- |
| `GET /api/v1/channels` | Snapshot 649 truy vấn, rồi đọc lại 640 tham số kênh | Dùng 649 truy vấn của snapshot mới; giảm khoảng 49,7% lượt đọc OSC |
| Hồ sơ 32 kênh | Đọc và giải mã JSON 32 lần mỗi yêu cầu | Đọc một lần, tra cứu bằng dictionary |
| RTA | Tạo mặt nạ cho từng dải ở mỗi khung | Cache tối đa 16 cấu hình lưới tần số; dùng lát cắt trên lưới tăng dần |
| Feedback detector | Tính median noise floor cho từng peak | Tính một lần mỗi khung có peak |
| SafetyGate | Cho phép mọi đường dẫn con EQ/gate/automix | Chỉ cho phép các tham số cụ thể đang được hỗ trợ |

RTA chỉ cache hình học dải và vị trí bin, không cache mức tín hiệu. Kết quả vẫn lấy peak của từng dải như trước, giữ nguyên cách làm tròn và mức -120 dBFS cho dải trống. Có đường xử lý cho lưới không được sắp xếp.

API dùng cùng snapshot cho thông tin kênh và đánh giá routing. Hàm đọc một kênh vẫn hỗ trợ truy vấn trực tiếp; khi được truyền snapshot thiếu tham số, nó báo lỗi thay vì âm thầm đọc mạng hoặc dùng mirror cũ. Luồng lấy SHA-256 trước giao dịch vẫn lấy snapshot mới.

SafetyGate từ chối đường dẫn không rõ, số kênh ngoài 1–32, bus ID không đúng dạng hai chữ số và giá trị NaN/Infinity hoặc không phải số. Các thay đổi này không mở thêm quyền ghi OSC.

## Đo hiệu năng

Máy hiện tại: Python 3.12.10 trên Windows. Mỗi phép đo chạy 300 lần, lặp 5 lượt, lấy trung vị, cache đã được làm nóng. So sánh RTA mới với bản tham chiếu thuật toán cũ trong `tests/test_performance_regressions.py`.

| Số bin phổ | Trước | Sau | Tốc độ tương đối |
| --- | ---: | ---: | ---: |
| 513 | 0,715 ms | 0,162 ms | 4,40× |
| 1.025 | 0,910 ms | 0,204 ms | 4,46× |
| 2.049 | 1,131 ms | 0,256 ms | 4,42× |

Đây là phép đo riêng hàm RTA, không phải mức tăng tốc toàn ứng dụng. Số lượt OSC giảm được tính từ các tham số thực tế trong mã, chưa phải phép đo độ trễ trên mixer thật.

## Kiểm thử

- Bản gốc: 169 bài Python đạt.
- Bản tối ưu: 178 bài Python đạt, gồm 9 bài hồi quy mới.
- Node.js: 19/19 bài đạt bằng `npm test`.
- Kiểm thử mới đối chiếu RTA với bản tham chiếu ở nhiều độ phân giải, mức tín hiệu thay đổi, dải trống, tần số biên và lưới không sắp xếp; kiểm tra snapshot không phát sinh đọc OSC dư; kiểm tra whitelist từ chối trước mọi I/O.

Các cảnh báo có sẵn trong môi trường kiểm thử: Starlette cảnh báo về tích hợp httpx của TestClient; `report_generator.py` có escape sequence không hợp lệ. Không đổi thư viện trong đợt tối ưu này.

## Những điểm còn cần xử lý

1. **Ánh xạ DL16 và xác minh FOH:** `RoutingGraph._analyze_routing()` hiện cố định input DL16 11 vào channel 11. Snapshot chưa lấy đầy đủ nguồn vào, các send/bus và matrix để chứng minh bất biến trên cấu hình phần cứng bất kỳ. Cần ánh xạ thực tế và từ chối xác nhận an toàn khi dữ liệu routing thiếu.
2. **Giao dịch và rollback:** snapshot chưa chứa một số tham số được whitelist như trim, gate, automix và bus send. Giá trị gốc có thể bị thiếu khi rollback; rollback hiện chưa có pacing/readback đầy đủ. Cần mở rộng snapshot giao dịch và kiểm thử lỗi giữa các lần ghi, với mock.
3. **Telemetry:** vòng gửi WebSocket hiện gửi tuần tự; client chậm có thể làm chậm cập nhật cho các client khác. Luồng audio cũng cần kiểm chứng tap point, clock, overflow và nguồn đo trước khi dùng cho suy luận DSP từ phần cứng.
4. **Đóng gói và tài liệu:** package Node.js vẫn mang tên công cụ tạo dự án cũ; README ghi số test cũ và có tuyên bố tuyệt đối về chống hú. Cần phân biệt công cụ tạo dự án với ChurchMix, cập nhật hướng dẫn vận hành theo chức năng đã xác minh.

Các kết quả kiểm thử mock trong đợt này chưa chứng minh an toàn vận hành trên phần cứng hoặc không có nguy cơ feedback.
