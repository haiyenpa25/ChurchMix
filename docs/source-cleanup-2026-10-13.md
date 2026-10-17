# Rà soát và tối ưu source — 13/10/2026

## Đánh giá

ChurchMix có nền tảng phù hợp cho người kỹ thuật nhà thờ: giao diện đơn giản/kỹ thuật, tiết mục, dashboard Peak/RMS/headroom, lịch sử vượt ngưỡng, CSV và mock X32. Tuy nhiên repository trộn runtime âm thanh với một công cụ tạo dự án khác. Kiểm thử JavaScript cũ chủ yếu kiểm tra công cụ đó và giao diện đã thay thế, nên không chứng minh giao diện hiện tại đúng.

Ưu tiên của đợt này là giảm source không thuộc runtime, sửa lỗi đo/hiển thị có thể dẫn tới quyết định chỉnh sai và củng cố giao dịch an toàn. Đây chưa phải kiểm chứng vận hành với mixer thật hoặc benchmark hiệu năng DSP.

## Phần đã tách khỏi repository

Bản lưu: `C:\xampp\htdocs\ChurchMix-archive-20261013-132721`. Các mục giữ nguyên cấu trúc tương đối:

- `src/`, `public/`, `templates/`, `setup/`, `community-skills/`.
- `server.js`, `setup.bat`, `start.bat`, `pack.bat`, `pack.ps1`.
- `tests/generator.test.js`, `tests/toolchain.test.js`, `tests/monitoring-ui.test.js`.
- `apps/web/legacy.html`, `apps/web/monitoring.js`, `apps/web/monitoring.css`.

16 mục được chuyển, khoảng 12,2 MiB / 1.322 tệp kể cả metadata và license trong bản lưu. Có thêm bản `package.json` và `.gitignore` trước sửa để tham khảo. Muốn khôi phục, sao chép đúng mục từ bản lưu vào đường dẫn tương đối của repository; nếu sửa package.json, so sánh bản cũ trước khi thay. Git cũng giữ các tệp từng được theo dõi.

Không xóa dữ liệu vận hành, scene, audio, cơ sở dữ liệu hay cấu hình an toàn. Giữ các launcher ChurchMix, hướng dẫn tiếng Việt và module âm thanh đang dùng.

## Thay đổi source

- `npm start` chạy API Python thay vì công cụ tạo dự án; hỗ trợ `--port 8090`, kiểm tra Python 3.11+ và port hợp lệ. Không cần thêm dependency Node.
- Bỏ link giao diện cũ; thêm helper dùng chung cho mức meter và kiểm tra nguồn. Meter null/NaN không còn thành cột đỏ 100%; USB chưa ánh xạ không giả thành meter kênh X32.
- Sửa grid/card cho màn hình nhỏ: cột `minmax(0, 1fr)`, giới hạn kích thước tối thiểu và ngắt dòng tiêu đề.
- Gom chọn nguồn audio vào `apps/api/audio_sources.py`; bỏ fallback lấy đầu vào đầu tiên khi thiếu kênh; dùng sample rate thực; từ chối capture stale, mẫu không hữu hạn và USB thật chưa xác minh clock/ánh xạ/tap point.
- Gain staging/livestream trả metadata nguồn. Livestream ghi rõ buffer hiện tại, không gọi LUFS tích lũy là số đo cả buổi; xóa số liệu cũ nếu API lỗi. Bỏ 27 import không dùng trong API.
- STOP/mode change làm mất hiệu lực quyền của giao dịch đang chuẩn bị/chờ. Kiểm tra lại quyền ngay trước gửi packet; không giữ khóa STOP trong lúc đọc lại OSC.
- Giới hạn thay đổi tính từ giá trị mixer đọc được, không tin `from` trong đề xuất. Bảo vệ talkback dùng kênh X32 cấu hình. Hoàn tác cả packet đã gửi nhưng echo timeout; chỉ hoàn tác các tham số đã thử ghi.
- Khóa giao dịch theo client dùng weak reference, tránh giữ vô hạn các client đã bỏ.

## Kiểm chứng

- 256 bài Python trên bản sao tạm với mock UDP riêng; 2 bài Node cho logic meter/ánh xạ. 23 bài Node cũ đi cùng source đã tách.
- Kiểm tra cú pháp toàn bộ ES module; chạy launcher `npm start -- --port 8090` với mock riêng.
- Chrome headless kiểm tra giao diện hiện tại ở 390 px và desktop; bằng chứng ảnh ở `docs/review-assets/signals-mobile-optimized.png`.
- Không gửi OSC tới mixer thật. Không commit hay push.

## Phần còn cần phát triển

Đo bus livestream thật cần quy trình xác minh USB mapping/tap point; LUFS cả buổi cần bộ tích lũy liên tục. Các công cụ acoustics/speech còn cần rà soát độc lập nguồn mô phỏng và điều kiện đo. Dashboard hiện theo dõi đầu vào tín hiệu, chưa chứng minh trạng thái phần cứng từng thiết bị. API Python vẫn lớn; tách router nên làm theo từng chức năng với kiểm thử tương ứng. Chưa bổ sung LLM điều khiển tự động; mọi thay đổi mixer vẫn cần duyệt theo quy định AGENTS.md.
