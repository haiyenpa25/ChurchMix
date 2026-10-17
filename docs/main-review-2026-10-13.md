# Đánh giá nhánh main — 13/10/2026

Commit được rà soát: `c50d23c`. Working tree sạch khi bắt đầu. Phạm vi: đọc kiến trúc, frontend đang dùng, các đường API đo/ghi, chạy bộ kiểm thử và tái hiện các trường hợp lỗi bằng fixture. Không gửi OSC tới mixer thật; không sửa logic sản phẩm trong đợt đánh giá này.

## Kết luận

ChurchMix hiện là một prototype có cấu trúc tốt và chức năng phong phú để mô phỏng, hướng dẫn quy trình và hỗ trợ kỹ thuật viên. Giao diện đã chia đúng hai nhóm người dùng, có trang giám sát, bàn trộn, tiết mục và bài tập feedback. Chưa đủ cơ sở coi toàn bộ số đo và luồng ghi là đáng tin cậy trong một buổi lễ thật: còn lỗi STOP, kiểm tra mức thay đổi và nhận diện nguồn audio có thể gây quyết định sai.

Đánh giá định tính: khoảng **7/10 cho mức hoàn thiện của prototype**. Đây là nhận xét kỹ thuật, không phải chứng nhận an toàn phần cứng hoặc chấm điểm thẩm mỹ từ ảnh giao diện.

## Những điểm tốt

- Frontend hiện dùng ES modules, CSS và icon cục bộ, có một WebSocket dùng chung. Việc chia trang và hàm cleanup giúp bảo trì tốt hơn bản HTML nguyên khối.
- Có chế độ Đơn giản cho tình nguyện viên và Kỹ thuật cho người vận hành; xác nhận các hành động ghi, nút STOP, trang tín hiệu và báo cáo CSV.
- Bảo vệ talkback đã mở rộng sang Mono, Bus và Matrix. Snapshot lấy các tham số cần thiết, giao dịch yêu cầu routing đầy đủ và có khóa theo client.
- Rollback đã đọc lại giá trị gốc, đảo thứ tự ghi và có pacing/readback; giao dịch tiết mục dùng batch, mute trước unmute.
- Có bộ kiểm thử tương đối rộng cho DSP, safety, API, storage, monitoring, notch và tiết mục.

## Các phát hiện cần ưu tiên

### P0 — STOP có thể bị giao dịch đang chuẩn bị ghi vượt qua

Vị trí: `packages/safety_controller/transaction.py:230`, `:248`, `:332`; `apps/api/main.py:685`.

`execute()` kiểm tra mode trước khi lấy khóa/snapshot. `_execute_locked()` sau đó không kiểm tra lại trạng thái STOP/mode và bật `read_only_mode=False` trước vòng ghi. Nếu operator bấm STOP trong lúc lấy snapshot, giao dịch có thể mở lại cờ ghi và vẫn commit.

Đã tái hiện bằng client fixture không có socket: manager ban đầu ASSIST; callback lấy snapshot kích hoạt PANIC và đặt read-only; giao dịch vẫn trả SUCCESS và ghi `/ch/01/eq/1/g=0.45` sau STOP. Trạng thái cuối trở lại OBSERVE không hủy được lần ghi đã xảy ra.

Hướng xử lý: cơ chế hủy/generation cho mỗi giao dịch; kiểm tra dưới khóa sau snapshot và trước từng lần ghi; STOP phải chặn việc mở lại quyền ghi. Thiết kế rõ rollback khi STOP xảy ra sau một phần giao dịch và kiểm thử cả batch đang xếp hàng. Không giữ nguyên tuyên bố phản hồi <50ms nếu chưa đo các tình huống này.

### P1 — Giới hạn bước thay đổi dựa vào `from` không được xác minh

Vị trí: `transaction.py:173–195`, `:319`; `packages/eq_optimizer/recommender.py` phần tạo thay đổi preset.

SafetyPolicy so sánh `to - from` trong proposal. Executor đọc giá trị thực để rollback nhưng không đối chiếu `from` hoặc tính lại delta từ giá trị thực. SHA đúng chỉ xác nhận snapshot không đổi, không chứng minh `from` đúng. Các preset giọng nói còn dùng giá trị `from=0.5` cố định cho EQ.

Đã tái hiện: fader thực 0.75, proposal khai `from=0.10`, `to=0.15`. Delta khai báo 0.05 qua policy; delta thực 0.60 vượt giới hạn 0.10 nhưng giao dịch vẫn SUCCESS.

Hướng xử lý: lấy before từ snapshot/readback dưới khóa, từ chối stale before hoặc tính lại mọi giới hạn từ giá trị đó; kiểm tra miền giá trị hợp lệ và kiểu enum, không chỉ số hữu hạn. Bộ thử phải bắt EQ/fader/trim/bus send có `from` sai.

### P1 — Một số API phân tích có thể đo nhầm đầu vào

Vị trí: `apps/api/main.py:981–1011`, `:1029–1070`.

- Gain staging: nếu yêu cầu một kênh không tồn tại trong buffer, API lấy cột đầu thay vì trả “không có dữ liệu”. Fixture capture chỉ có 2 đầu vào nhưng yêu cầu kênh 32 vẫn nhận Peak -12 dBFS từ Input 1.
- Livestream: chọn bus 5/8 không làm nguồn audio chuyển tới bus đó; phép đo vẫn lấy cột USB đầu tiên. Trường `livestream_bus` chủ yếu phục vụ kiểm tra routing.
- Fixture capture 44.100 Hz vẫn được truyền vào đánh giá loudness với sample rate 48.000 Hz.
- Khi không có capture, các API này tạo tín hiệu tổng hợp; kết quả không cung cấp metadata nguồn/validity đồng nhất với trang giám sát tín hiệu.
- Giá trị integrated LUFS hiện được tính lại trên một buffer ngắn mỗi lần gọi, chưa phải lịch sử tích lũy của cả buổi như lời giải thích trên trang livestream.

Hướng xử lý: dùng chung bộ chọn nguồn có provenance, sample rate, clock, tap point và ánh xạ đã xác nhận; thiếu đầu vào phải trả UNKNOWN/không tạo đề xuất. Muốn đo bus livestream phải thực sự capture bus đã chọn. Loudness cả buổi cần bộ tích lũy theo phiên.

### P1 — Meter thiếu dữ liệu hiện thành full đỏ trong chế độ Đơn giản

Vị trí: `apps/web/js/views/home.js:288–298`.

`null + 60` trong JavaScript bằng 60, nên công thức cho ra 100%. `null > -6` cũng là true, khiến màu chuyển đỏ. Đã kiểm tra trực tiếp biểu thức: missingMeterPercent=100, missingMeterShownDanger=true.

Trang Live kiểm tra null tốt hơn nhưng vẫn đưa meter USB theo số thứ tự vào strip tên kênh X32; caption “chưa ánh xạ” chưa ngăn người dùng hiểu meter thuộc chính micro có tên trên strip.

Hướng xử lý: trạng thái UNKNOWN riêng với meter trống/xám và giải thích; không ghép USB Input vào strip X32 khi mapping chưa xác nhận. Kiểm thử trực tiếp frontend hiện tại, không chỉ frontend legacy.

### P2 — “Chưa xác minh” bị trình bày như “Talkback có thể lọt ra loa”

Vị trí: `apps/api/main.py:354–383`; `apps/web/js/views/home.js:84`.

Status với phần cứng thật luôn trả `safe=false`, scope `UNVERIFIED_HARDWARE`; hero Đơn giản coi mọi `safe=false` là cảnh báo rò talkback và nói “hệ thống đã chặn mọi thay đổi tự động”. Cần tách UNVERIFIED, VERIFIED_SAFE và VIOLATION, đồng thời kiểm tra rằng backend thực sự khóa ghi tương ứng với thông báo.

Việc đọc cấu hình talkback và kiểm tra tên kênh là tiến bộ, nhưng chưa tự chứng minh nguồn vật lý DL16 #11 đang vào channel đó. Snapshot cần xác minh nguồn/patch hoặc có workflow xác nhận mapping, và vô hiệu xác nhận khi patch thay đổi.

### P2 — Kiểm thử frontend mới chưa tương xứng với số trang

`tests/monitoring-ui.test.js` hiện chạy `apps/web/monitoring.js` của giao diện legacy. Nó không trực tiếp kiểm thử `js/views/signals.js`, `home.js`, `live.js` và các trang hiện tại. Một số lỗi trên vẫn tồn tại khi toàn bộ suite xanh.

Cần bổ sung kiểm thử cho thiếu dữ liệu, stale/disconnect, mapping chưa xác nhận, chuyển trang/cleanup, xác nhận ghi, STOP đang chạy batch và viewport 390px. Syntax check chỉ chứng minh JavaScript phân tích cú pháp được.

## Kiểm chứng đã thực hiện

- **240/240 bài Python đạt**, khoảng 29 giây trong bản sao tạm. `CHURCHMIX_X32_PORT=10943` tách app mock khỏi máy chủ đang chạy; các bộ fixture/mock còn lại được giữ theo thiết kế hiện có.
- **23/23 bài JavaScript đạt** bằng `npm test`.
- Mọi module JavaScript trong `apps/web/js` qua `node --check`.
- Tái hiện độc lập bốn hành vi: ghi sau STOP trong snapshot; delta fader vượt giới hạn; kênh audio không tồn tại lấy Input 1; meter null hiện full đỏ. Kiểm tra bằng mock thêm sample rate 44,1k bị truyền thành 48k ở broadcast.
- Có cảnh báo hiện có từ Starlette/httpx TestClient và escape sequence trong `report_generator.py`.
- Phiên công cụ không có browser kết nối; chưa đánh giá ảnh giao diện, lỗi console khi chạy trình duyệt hay bố cục thực tế trên điện thoại. Không dùng mixer thật để kiểm chứng OSC, latency STOP, clock hoặc bất biến routing.

## Thứ tự nên xử lý

1. Đóng lỗ hổng STOP và xác minh before/delta ngay trong giao dịch.
2. Đồng nhất source/mapping/validity trên mọi API đo; sửa meter null và ghép nhầm USB/X32.
3. Phân biệt trạng thái chưa xác minh và vi phạm; tích lũy loudness theo phiên.
4. Bổ sung kiểm thử cho các trang UI hiện tại và kiểm tra trong trình duyệt với mock.
5. Sau khi các mục trên đạt, kiểm chứng phần cứng theo workflow chỉ đọc trước, với operator xác nhận từng bước chuyển sang ghi.
