# ChurchMix: trợ thủ cho kỹ thuật viên và tình nguyện viên

Ngày: 13/10/2026. Đề xuất dựa trên `main` tại `c50d23c`, các phát hiện trong `main-review-2026-10-13.md` và kiểm tra trình duyệt bằng Chrome DevTools MCP.

## Vai trò phù hợp

ChurchMix nên giúp người vận hành biết **nguồn nào có vấn đề, bằng chứng gì, kiểm tra gì trước và kết quả sau khi xử lý ra sao**. Phần mềm hướng dẫn, theo dõi và chuẩn bị đề xuất; mọi thay đổi mixer cần operator phê duyệt qua SafetyGate.

Hai giao diện có thể dùng cùng nguồn dữ liệu đã xác minh, nhưng cần hai vai trò quyền hạn thực sự ở backend. Chuyển nút “Đơn giản/Kỹ thuật” chỉ đổi giao diện, chưa phải cơ chế phân quyền.

## Kỹ thuật viên

| Công việc | Trợ thủ nên cung cấp |
| --- | --- |
| Trước lễ | Sơ đồ nguồn vật lý → channel X32 → FOH/monitor/livestream; checklist dây, pin, gain, patch và talkback. Không coi tên kênh là bằng chứng nguồn vật lý. |
| Trong lễ | Một màn hình ưu tiên vấn đề: clipping, headroom thấp, nguy cơ feedback, mất nguồn đo. Mỗi cảnh báo chỉ rõ tên nguồn đã xác minh, Peak/RMS, thời gian, tap point và nguồn dữ liệu. |
| Phân tích | Biểu đồ lịch sử kênh đang chọn; phổ cho đúng kênh; bus monitor/stream đo đúng nguồn; so sánh trước/sau và A/B cân bằng âm lượng. |
| Chuyển tiết mục | Bộ tiết mục được kỹ thuật viên chuẩn bị và kiểm chứng: Mục sư, ban nhạc, MC, cầu nguyện… Xem danh sách thay đổi trước khi xác nhận; batch có rollback. |
| Xử lý feedback | Phân biệt cảnh báo ứng viên và feedback đã có nhiều bằng chứng; ưu tiên vị trí micro/loa và gain structure. Notch chỉ là đề xuất hẹp, có giới hạn và xác nhận. |
| Sau lễ | Tổng hợp các đợt vượt ngưỡng, nguồn bị ảnh hưởng, thời gian mất dữ liệu, các thay đổi đã duyệt và việc cần sửa trước buổi tiếp theo. |

Một cảnh báo hữu ích cần có:

1. **Ai/đâu:** “Đơn ca nữ — channel 3” chỉ khi mapping đã xác nhận.
2. **Dấu hiệu:** peak, RMS, headroom, số giây liên tục; không chỉ màu đỏ.
3. **Độ tin cậy:** đo thật hay demo, tap đã biết chưa, dữ liệu có bị cũ hoặc lỗi clock/buffer không.
4. **Bước kiểm tra:** kiểm tra mức nguồn, kỹ thuật micro, vị trí monitor; không tự suy ra cần EQ từ một meter lớn.
5. **Thay đổi đề xuất:** thông số trước/sau, ảnh hưởng dự kiến, giới hạn và người phê duyệt.

## Tình nguyện viên không chuyên

Giao diện chính giữ ba bước **Trước lễ → Trong lễ → Sau lễ**. Dùng tên người/nhạc cụ dễ hiểu; số channel và dBFS chỉ hiện khi mở chi tiết.

- **Trước lễ:** checklist ngắn, kết quả có ba trạng thái “Đã kiểm tra”, “Cần kiểm tra”, “Chưa có dữ liệu”. Người dùng vẫn phải nói thử/nghe thử micro; một phép kiểm tra số không xác nhận âm thanh trong phòng đã rõ.
- **Trong lễ:** hiện tiết mục đang dùng và micro chính. Đưa tối đa vài vấn đề quan trọng lên đầu, chẳng hạn “Micro MC quá lớn” hoặc “Chưa nhận được âm thanh USB”. Mỗi vấn đề có một bước kiểm tra trước và nút gọi/hướng dẫn liên hệ kỹ thuật viên.
- **Thao tác:** chỉ các micro và tiết mục được kỹ thuật viên cho phép; hiển thị rõ trước khi xác nhận bật/tắt. Không mở routing, phantom, preamp, main bus hoặc scene recall ngoài workflow bảo trì riêng.
- **Sau lễ:** lưu ghi chú và xuất báo cáo; không cần đọc các biểu đồ chuyên sâu để hoàn thành quy trình.

**STOP cần giải thích đúng:** nó khóa tự động/ghi, không tự tắt âm thanh hoặc bảo đảm tiếng hú ngừng. Người dùng vẫn cần xử lý nguồn gây hú theo quyền đã cấp hoặc gọi kỹ thuật viên.

## Biểu đồ nên giữ và biểu đồ nên ưu tiên

| Hiển thị | Kỹ thuật viên | Người không chuyên |
| --- | --- | --- |
| Peak 32 đầu vào | Có, lọc nhóm và sắp xếp theo mức cần chú ý | Chỉ các micro/nguồn được giao |
| Peak/RMS theo thời gian | Có, bấm cảnh báo để mở đúng kênh | Chỉ mở khi cần giải thích |
| Phổ/RTA | Có, nêu đúng input/tap/sample rate | Không đặt trên màn hình chính |
| Thời gian vượt ngưỡng | Có, kèm cửa sổ thời gian và khoảng mất dữ liệu | Câu dễ hiểu “Mức quá lớn kéo dài…” |
| Livestream | LUFS/true peak từ đúng bus và lịch sử phiên | “Tiếng livestream nhỏ/lớn/chưa đo được” |
| Routing/talkback | Chi tiết nguồn và đường đi, trạng thái đã xác minh/chưa xác minh/vi phạm | Cảnh báo ngắn và chuyển kỹ thuật viên |

## Ưu tiên triển khai

1. Sửa STOP vượt giao dịch, kiểm tra `from` thực và meter null đã được tái hiện trong báo cáo main.
2. Đồng nhất nguồn đo và mapping trên monitoring, gain staging, live strips và livestream; thiếu số liệu thì UNKNOWN, không lấy nhầm đầu vào khác.
3. Thêm backend permissions cho tình nguyện viên/kỹ thuật viên/quản trị, với các tiết mục và kênh được cho phép.
4. Tạo danh sách vấn đề có hành động rõ ràng và xem kết quả trước/sau, ưu tiên hơn việc bổ sung nhiều biểu đồ.
5. Thu gọn phần đầu trang trên điện thoại để người dùng thấy cảnh báo và biểu đồ chính sớm; giữ STOP luôn nhìn thấy.

## Kiểm tra trình duyệt đã thực hiện

- Chrome DevTools MCP **1.10.1** đã được cài toàn cục, cấu hình server Codex `chrome-devtools`, và chạy bằng CLI với profile riêng. Nguồn chính thức: https://github.com/ChromeDevTools/chrome-devtools-mcp . Cách cấu hình Codex: https://learn.chatgpt.com/docs/extend/mcp?surface=cli .
- Bản mock `main` chạy tại **http://127.0.0.1:8090**, trong bản sao tạm; OSC mock ở UDP **10949**. Nó độc lập với máy chủ/cơ sở dữ liệu đang dùng của người vận hành, và không phản ánh mixer thật.
- Đã xem trang Đơn giản, trang Giám sát tín hiệu và Bàn trộn trực tiếp. Không thấy console error trong các trang đã kiểm tra; chưa coi đó là kiểm thử mọi chức năng.
- Khi mô phỏng màn hình 390px, trang Giám sát có `clientWidth=390` nhưng `scrollWidth=520`: có tràn ngang. Phần KPI đầu trang cũng chiếm phần lớn chiều cao trước khi thấy biểu đồ.
- Thanh trên cùng của bản mock vẫn ghi “X32 trực tuyến” và “Talkback cách ly”, dễ bị hiểu là thiết bị thật. Nên gắn nhãn mô phỏng ở cấp toàn ứng dụng.

Ảnh đã chụp:

- [Giao diện Đơn giản](review-assets/home-desktop.png)
- [Giám sát tín hiệu trên desktop](review-assets/signals-desktop.png)
- [Bàn trộn trực tiếp](review-assets/live-desktop.png)
- [Giám sát trên màn hình nhỏ](review-assets/signals-mobile.png)

MCP dùng headless/isolated, tắt usage statistics và CrUX. Cài đặt local Codex không tự biến thành một plugin trong mọi giao diện ChatGPT; danh sách MCP trong phiên Codex mới cần được nạp lại theo cơ chế của client. Trong phiên này đã xác minh công cụ bằng CLI và thực sự chụp/xem ảnh.
