# ChurchMix — X32 AI Sound Engineer Project Context

## 1. Thông Tin Tổng Quan
- **Dự Án:** ChurchMix — Trợ lý Kỹ sư Âm thanh AI cho Nhà thờ
- **Bàn Trộn Mục Tiêu:** Behringer X32 Compact + Hộp mở rộng DL16 stagebox qua AES50 A + Hệ thống kiểm âm cá nhân Ultranet P16-D / 3x P16-HQ
- **Ngôn Ngữ & Công Nghệ:**
  - Backend: Python 3.12, FastAPI, Uvicorn, WebSockets, SQLite, SoundDevice, NumPy, SciPy
  - Frontend: Vanilla JavaScript ES modules (`apps/web/js`), HTML5 Canvas, một file CSS tự chứa (`apps/web/assets/app.css`), không CDN — chạy được offline
  - Hướng dẫn cho agent (Codex/Gemini/Claude): xem `AGENTS.md`
- **Cổng Dịch Vụ:**
  - Web UI & API: `http://127.0.0.1:8080`
  - WebSocket Live Telemetry: `ws://127.0.0.1:8080/ws/live`
  - Mock X32 Simulator UDP OSC: `127.0.0.1:10023`

## 2. Bất Biến An Toàn Sống Còn (Safety Invariants)
1. **Talkback DL16 #11 Cách Ly Tuyệt Đối:**
   - Cổng vào vật lý DL16 số 11 (Band Talkback) **CHỈ ĐƯỢC PHÉP** gửi về Ultranet P16 personal monitors.
   - Tuyệt đối cấm kết nối vào Main FOH hoặc Matrix FOH trong mọi tình huống.
2. **Read-Only First:** Mọi kết nối mới với bàn trộn luôn bắt đầu ở chế độ `READ_ONLY_MODE = True`.
3. **Silence Hold Invariant:** Fader tự động khóa đóng băng khi diễn giả nghỉ nói; tuyệt đối không tự động trôi fader lên làm khuếch đại tiếng ồn nền phòng.
4. **No-Boost-in-Nulls Invariant:** Tuyệt đối cấm tăng gain dương vào các hố lõm triệt tiêu pha âm học ($Coherence < 0.65$ và $Magnitude < -6\text{ dB}$).
5. **Nút Khẩn Cấp STOP AUTO:** Luôn ghim cố định trên màn hình, phản hồi dưới 50ms để lập tức hủy bỏ mọi điều khiển tự động và khóa chặt OSC write.

## 3. Các Lệnh Điều Hành Chính
- **Khởi động hệ thống:**
  ```powershell
  .\start_church_engineer.bat
  # hoặc
  & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080
  ```
- **Chạy toàn bộ bài kiểm thử tự động (Python + `npm test`):**
  ```powershell
  & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest discover -s tests -p "test_*.py"
  ```
- **Xuất Scene File chuẩn USB:**
  Truy cập `http://127.0.0.1:8080` bấm "Xuất Scene USB (.scn)" hoặc gọi `GET /api/v1/scenes/export?name=ChurchMix_Sunday`.
