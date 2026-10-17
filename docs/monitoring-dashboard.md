# Dashboard giám sát tín hiệu ChurchMix

Mở ChurchMix bằng `start_church_engineer.bat`, sau đó vào `http://127.0.0.1:8080`. Nếu máy chủ đang chạy, khởi động lại để nạp backend mới; tải lại trang để nhận giao diện mới.

## Xem nhanh đầu vào cần chú ý

1. Đọc thanh **nguồn đo** trước: Demo, Soundcheck ảo và USB mô phỏng đều được ghi rõ **MÔ PHỎNG**. Không coi các mức này là số đo trên mixer thật.
2. Xem **Mức Peak của 32 đầu vào**. Chọn một cột, dòng trong bảng hoặc đầu vào trong danh sách để xem lịch sử tương ứng.
3. Đọc **diễn biến Peak/RMS**: Peak là đỉnh của khung đo; RMS là mức trung bình năng lượng của khung đó. Hai đường khác nhau cho biết tín hiệu có nhiều đỉnh ngắn hay duy trì mức lớn.
4. Xem **headroom**, peak cao nhất phiên, thời gian vượt ngưỡng và số đợt sát clipping. Bảng phân tích đưa đầu vào cần chú ý lên trước và kèm bước kiểm tra.
5. Dùng bộ lọc **Chỉ xem vượt ngưỡng / chưa đo được** và nút **Xuất báo cáo CSV** để lưu kết quả cùng nguồn đo, ngưỡng và lịch sử đầu vào đang chọn.

## Các ngưỡng mặc định

| Trạng thái | Điều kiện Peak | Ý nghĩa |
| --- | --- | --- |
| Dưới ngưỡng | Dưới -12 dBFS, từ -60 dBFS trở lên | Chưa vượt ngưỡng theo dõi mức số |
| Cảnh báo | Từ -12 đến dưới -6 dBFS | Cần theo dõi các đỉnh lớn và gain nguồn |
| Nguy hiểm | Từ -6 đến dưới -0,5 dBFS | Headroom ít, cần kiểm tra đoạn lớn nhất |
| Sát clipping | Từ -0,5 dBFS trở lên | Gần giới hạn số; kiểm tra gain và nghe méo tiếng |
| Ít tín hiệu / nghỉ | Dưới -60 dBFS | Có thể là khoảng nghỉ bình thường; không tự tăng fader |
| Chưa đo được | Thiếu đầu vào, buffer cũ hoặc dữ liệu không hợp lệ | Không đủ cơ sở kết luận tín hiệu đang im lặng hoặc bình thường |

Ngưỡng là mốc quan sát có thể chỉnh trong mục **Ngưỡng theo dõi**; không phải giới hạn nhiệt độ, điện áp hoặc SPL của thiết bị. Điều kiện hợp lệ: `-60 ≤ cảnh báo < nguy hiểm < sát clipping ≤ 0 dBFS`. Chỉnh ngưỡng không gửi OSC và không thay đổi mixer. Ngưỡng giữ trong phiên máy chủ; thay đổi ngưỡng bắt đầu lại thống kê.

Ví dụ: Peak -3 dBFS tương ứng headroom 3 dB so với giới hạn số 0 dBFS. Một đỉnh ngắn ở mức này chưa chứng minh thiết bị hỏng. Hãy xem RMS, lịch sử, kỹ thuật micro và gain tại nguồn trước khi quyết định điều chỉnh.

## Đo đầu vào thật

Chọn thiết bị audio trong **Công cụ & quy trình → Card USB**. Mỗi đầu vào USB thật chưa có ánh xạ được ghi **USB Input 01, 02… • chưa ánh xạ**. Số thứ tự này không chứng minh đó là channel X32 tương ứng, cổng DL16 tương ứng hay slot P16 tương ứng.

Nếu mở card thật thất bại và capture chuyển về mô phỏng, thanh nguồn báo rõ lỗi và trạng thái mô phỏng. Không có buffer hoặc buffer quá 0,5 giây thì phép đo bị vô hiệu. Với capture thật, mất tính liên tục timestamp ADC, status lỗi/overflow hoặc clock chưa đủ dữ liệu kiểm tra cũng làm dữ liệu không hợp lệ. Sau khi xử lý lỗi, dừng rồi khởi động capture lại.

Kiểm tra clock hiện là kiểm tra tính liên tục timestamp ADC qua các block, không phải đo sai lệch clock tuyệt đối bằng thiết bị chuẩn. Tap point thật mặc định `UNKNOWN`; suy luận feedback/DSP của luồng telemetry tạm dừng cho nguồn này. Biểu đồ mức số không xác nhận tín hiệu là pre-EQ hay post-EQ.

Không suy ra trạng thái mixer từ dữ liệu demo. Trạng thái kết nối OSC và nguồn audio là hai lớp độc lập. API status ghi rõ phạm vi mô phỏng; với phần cứng thật, không tuyên bố bất biến DL16 đã xác minh từ cấu hình mẫu cố định.

## Lịch sử và giới hạn

- Thu thập tiếp tục khi không có tab dashboard, miễn là máy chủ đang chạy.
- Lịch sử tối đa 120 giây, lấy mẫu tối đa khoảng 4 lần/giây, giữ tối đa 480 khung và 200 sự kiện chuyển ngưỡng trong RAM.
- Thời gian vượt ngưỡng là ước lượng giữa các khung quan sát liên tiếp; khoảng mất dữ liệu không được cộng thành thời gian overload.
- “Số đợt sát clipping” là số lần chuyển vào vùng sát clipping, không phải số sample bị clipping hoặc số thiết bị hỏng.
- Peak hold, thời gian và số đợt tính theo phiên. Đổi nguồn, đổi ngưỡng hoặc mất tính hợp lệ sẽ bắt đầu phiên thống kê mới.
- Nếu telemetry quá 1 giây không cập nhật, API đánh dấu dữ liệu cũ. Giao diện cũng hủy trạng thái hiện tại khi mất dữ liệu mới; các mức cũ không được hiển thị như số đo hiện tại.
- CSV gồm thống kê hiện tại và lịch sử đầu vào đang chọn. Dữ liệu trong RAM không thay thế kho báo cáo dài hạn của buổi lễ.

## Rà soát toàn dự án

| Khu vực | Đã cải thiện / xác minh | Việc còn cần làm |
| --- | --- | --- |
| Giám sát audio | Biểu đồ Peak/RMS, headroom, thời gian vượt ngưỡng, nguồn rõ ràng | Ánh xạ USB ↔ kênh ↔ nguồn vật lý do operator xác nhận |
| Capture | Công bố buffer và meter cùng block; báo fallback, overflow và tình trạng clock | Kiểm chứng tap point, clock chuẩn và drop với phần cứng thật |
| WebSocket | Gửi đồng thời; giới hạn chờ client chậm; không chặn client khác vô hạn | Đo tải dài hạn với nhiều client trên mạng triển khai |
| API / OSC | Dùng chung snapshot cho danh sách kênh; từ chối nối vào listener lạ khi mock không mở được | Snapshot đầy đủ routing/matrix; khóa giao dịch xuyên suốt các luồng ghi |
| SafetyGate | Whitelist cụ thể; kiểm tra giá trị hữu hạn; reconnect trở lại OBSERVE và giữ mode gate | Đầy đủ snapshot các tham số trim/gate/automix/bus send, rollback có pacing/readback |
| Wizards / DSP / broadcast | Các bộ kiểm thử mock hiện có đạt; telemetry không gán tổng nhiều tín hiệu vào channel 3 | Các endpoint phân tích cũ ngoài telemetry còn dùng mẫu mô phỏng/fallback; cần chuẩn hóa nguồn và độ tin cậy đồng nhất |
| UI / đóng gói | Thanh công cụ thu gọn; STOP AUTO bên ngoài menu; biểu đồ dùng Canvas cục bộ | CSS/font của giao diện cũ còn dùng CDN; công cụ Node tạo dự án vẫn nằm chung repository |

Launcher Windows cũng đã được sửa để ưu tiên Python đã cài trước alias Microsoft Store, chuyển về thư mục dự án và báo thư viện thiếu trước khi chạy máy chủ.

Các mục “còn cần làm” chưa được coi là đã hoàn tất hoặc đã an toàn trên phần cứng. Đặc biệt, graph routing hiện dùng cấu hình mẫu channel 11; chưa đủ để chứng minh bất biến DL16 trên mọi scene thật. Hướng dẫn kiểm tra và mọi đề xuất vẫn cần operator xác nhận; dashboard không phát lệnh điều chỉnh.

## Kiểm thử đợt bổ sung

200 bài Python đạt trong bản sao tạm với mock/fixture; 23 bài JavaScript đạt. Đã kiểm tra HTTP cho trang và asset, REST lịch sử đầu vào chọn, WebSocket payload có nguồn và dữ liệu phân tích. Các bài mới kiểm tra ngưỡng, số liệu thiếu/NaN, nguồn thay đổi, buffer cũ/overflow/clock, lịch sử hữu hạn, thống kê thời gian, reconnect, client chậm, render canvas giả lập ở kích thước rộng/hẹp và xuất CSV.

Phiên công cụ hiện tại không có browser để kiểm tra ảnh giao diện thực tế. Kiểm thử DOM/canvas là giả lập; không thay thế kiểm tra bố cục trực quan trong trình duyệt hoặc kiểm thử mixer thật.
