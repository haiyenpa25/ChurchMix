# Kế Hoạch & Ma Trận Kiểm Thử Tự Động (Automated Test Plan)

Tài liệu kiểm định chất lượng, bao phủ toàn bộ 63 bài kiểm thử tự động (Unit & Integration Tests) của hệ thống **X32 AI Sound Engineer**.

---

## 1. Mục Tiêu & Nguyên Tắc Kiểm Thử

1. **Nguyên Tắc Cô Lập Phần Cứng:**
   - 100% các bài test tự động chạy độc lập trên môi trường giả lập `MockX32Server` hoặc bộ dữ liệu tổng hợp deterministic.
   - Tuyệt đối không gửi gói tin đột biến tham số (write OSC) đến bàn trộn X32 thật trong quá trình kiểm thử CI/CD.
2. **Kiểm Tra Bất Biến An Toàn (Safety Invariant Gate):**
   - Mọi tình huống vi phạm quy tắc cách ly Talkback DL16 #11 đều phải bị phát hiện và ném lỗi `InvariantViolationError`.
   - Mọi đề xuất đột biến tham số chưa được phê duyệt đều phải bị từ chối với mã lỗi HTTP 400 / 403.
   - Khi kích hoạt nút khẩn cấp `STOP AUTO`, mọi thao tác ghi đều bị khóa cứng lập tức.

---

## 2. Bảng Phân Bổ 63 Bài Test Theo Module (Test Suite Matrix)

| Tập File Test | Số Bài Test | Phạm Vi Kiểm Tra | Trạng Thái |
| :--- | :---: | :--- | :---: |
| [tests/test_sprint1_osc.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint1_osc.py) | **8** | Mã hóa/giải mã nhị phân OSC (string, int, float, blob padding), Client kết nối UDP, State Mirror, Heartbeat loop, Snapshot SHA-256 integrity, Snapshot diffing delta. | **PASS** |
| [tests/test_sprint2_safety.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint2_safety.py) | **6** | Routing Graph Parser, Xác minh bất biến DL16 #11 $\rightarrow$ P16 only, Chặn các đường đi FOH/Matrix, Whitelist channel EQ, Chặn sửa Routing/P16, Rollback tự động khi readback sai lệch. | **PASS** |
| [tests/test_sprint3_dsp.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint3_dsp.py) | **5** | Tạo sóng âm (sine, pink noise, baritone vocal), Phân tích phổ Welch PSD, RTA 1/12-Octave (61 dải log), Bộ dò hú đa bằng chứng, Loại trừ nốt ca sĩ ngân dài có hài âm $2f..5f$. | **PASS** |
| [tests/test_sprint4_peq.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint4_peq.py) | **5** | Chuyển đổi hai chiều $Hz \leftrightarrow X32\ float$, $dB \leftrightarrow X32\ float$, $Q \leftrightarrow X32\ float$, Đề xuất PEQ bảo toàn giọng Mục sư, 7 vai trò nhạc cụ và giọng hát (Pastor, Nữ đơn ca, Nam đơn ca, Ca đoàn, Guitar, Piano, Bass), Mô phỏng đáp tuyến biquad A/B. | **PASS** |
| [tests/test_sprint5_api.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint5_api.py) | **10** | FastAPI Status & DL16 Invariant, Trạng thái 32 kênh, Khóa khẩn cấp STOP AUTO (HTTP 403), Trợ lý tiếng Việt Copilot Q&A, Đo âm học H1, Nhập CSV Open Sound Meter, Lịch sử Audit Log SQLite & Acoustic Sessions, Kích hoạt mô phỏng buổi lễ Sunday Simulation Endpoint, `/generate-role` và `/generate-notch`. | **PASS** |
| [tests/test_sprint6_acoustic_and_dynamics.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint6_acoustic_and_dynamics.py) | **5** | Đo hàm truyền hai kênh $H_1$, Căn độ trễ delay cross-correlation, Quy tắc **No-Boost-in-Nulls**, Parser file OSM / REW CSV & FRD, Bộ cân mức giọng nói VAD & Silence Hold (chống trôi fader). | **PASS** |
| [tests/test_sprint7_wizards.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint7_wizards.py) | **8** | Wizard 1 Báo cáo kiểm kê Markdown, Wizard 2 Line Check Chúa Nhật, Wizard 3 Hiệu chuẩn giọng hát, Wizard 5 Dò hú Rehearsal, Wizard 6 Trợ lý trực tiếp buổi lễ, Wizard 7 Báo cáo tổng kết, Hardware Switcher LAN IP ↔ Simulator, Tự động quét mạng dò tìm X32 UDP broadcast. | **PASS** |
| [tests/test_sprint8_audio_capture.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint8_audio_capture.py) | **5** | Liệt kê thiết bị sound card (WASAPI / ASIO / MME), Tự động nhận diện card X-USB / X-LIVE, Khởi tạo AudioStreamWorker, Bộ đệm vòng đa kênh, Đo mức âm lượng dBFS thời gian thực. | **PASS** |
| [tests/test_sprint9_scene_export.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint9_scene_export.py) | **2** | Trích xuất file Scene Behringer X32 (`.scn`), Khóa cứng kênh 11 `/ch/11/mix/lr OFF` và định tuyến Ultranet `/outputs/p16/11/src 11` trên file cắm USB. | **PASS** |
| [tests/test_sprint10_database_and_discovery.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint10_database_and_discovery.py) | **5** | SQLite Database persistence (Snapshot SHA-256, Audit Event bất biến với cryptographic hash, Phiên đo âm học H1), Tự động quét tìm bàn trộn X32 qua UDP OSC broadcast (`/info`), Wizard 6 Live Service Tactical Assistant. | **PASS** |
| [tests/test_sprint11_e2e_service.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint11_e2e_service.py) | **4** | Kịch bản mô phỏng toàn diện buổi lễ Chúa Nhật (End-to-End Sunday Service Lifecycle): Boot & Invariant verification, Line Check 32 kênh, Vocal Tuning & Harmonic Rejection, Live Tactical Monitoring & Silence Hold & USB Scene export. | **PASS** |
| [tests/test_sprint12_soundcheck_and_profile.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint12_soundcheck_and_profile.py) | **8** | Virtual Soundcheck Player Engine (4 phiên multitrack 32 kênh), Church Profile Manager (bảo lưu kênh 11 Talkback cách ly), Bộ tạo báo cáo in ấn Chủ Nhật (Printable Sunday Report HTML). | **PASS** |
| [tests/test_sprint13_chaos_and_resilience.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint13_chaos_and_resilience.py) | **6** | Chaos, Fault-Injection & Safety Gate Resilience: Chặn tiêm rò rỉ Talkback FOH, Chặn can thiệp trái phép path cấm, Chặn tấn công đa kênh chéo, Chặn bước nhảy fader quá nhanh, Chống xung đột revision lock SHA-256, Tự động Rollback khi readback sai khác. | **PASS** |
| [tests/test_sprint14_ai_copilot_rag.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint14_ai_copilot_rag.py) | **10** | Trợ lý âm học AI Copilot RAG: Khử dấu tiếng Việt tìm kiếm ngữ nghĩa, 7 bài viết tài liệu âm học nhà thờ, Tiêm ngữ cảnh thời gian thực (trạng thái STOP AUTO, Talkback Invariant, Rủi ro hú), Tích hợp REST API `/api/v1/copilot/ask`. | **PASS** |
| [tests/test_sprint15_hall_profiles.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint15_hall_profiles.py) | **6** | Quản lý Hồ sơ Âm học Hội trường Đa không gian (Multi-Sanctuary Profiles: Main Sanctuary, Youth Chapel, Fellowship Hall, Outdoor Campus), So sánh độ lệch Baseline, Cảnh báo triệt tiêu pha No-Boost-in-Nulls, REST API chuyển đổi và đối soát baseline. | **PASS** |
| [tests/test_sprint16_diagnostics_and_channel_map.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint16_diagnostics_and_channel_map.py) | **7** | Bộ Tự Chẩn Đoán Hệ Thống Tiền Lễ 10 Tiêu Chuẩn (`diagnose_system.py`), Quản Lý Sơ Đồ 32 Kênh Nhà Thờ (`church_profile`), Khóa Cứng Bất Biến Kênh 11, Tự Động Đồng Bộ Tên Kênh và REST API. | **PASS** |
| [tests/test_sprint17_scene_vault_and_diff.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint17_scene_vault_and_diff.py) | **5** | Kho Lưu Trữ Scene (`SceneVaultManager`), Khóa Bất Biến Talkback DL16 #11 khi lưu Snapshot, Xuất file USB .scn định dạng chuẩn Behringer X32/M32, So sánh phân tích Delta vi sai fader/mute/EQ giữa 2 bản snapshot, REST API Vault. | **PASS** |
| [tests/test_sprint18_feedback_suppressor_and_channel_control.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint18_feedback_suppressor_and_channel_control.py) | **5** | Giao Thức Phản Ứng Dò Hú Thời Gian Thực (Feedback Radar HUD), Đề Xuất Bộ Lọc Notch Cực Hẹp Phẫu Thuật (Rule 9: $Q \ge 6.0$, Depth $\le -4.5\text{ dB}$), Bật/Tắt Mute Kênh Qua SafetyGate Whitelist & Bất Biến Silence Hold. | **PASS** |
| [tests/test_sprint19_broadcast_lufs_and_streaming_guard.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint19_broadcast_lufs_and_streaming_guard.py) | **7** | Giám Sát Âm Lượng Phát Thanh Livestream Chuẩn ITU-R BS.1770-4 / EBU R128 (Bộ lọc K-weighting, Momentary/Short-Term/Integrated Gated LUFS, True Peak 4x Polyphase Oversampling dBTP), Bảo Vệ Bất Biến Cách Ly Talkback DL16 #11 Khỏi Bus Livestream & REST API. | **PASS** |
| [tests/test_sprint20_scn_importer_and_safety_validator.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint20_scn_importer_and_safety_validator.py) | **6** | Bộ Nạp File Scene Behringer X32 (.scn) Từ USB, Thẩm Định Tiền Kiểm Tra Pre-Flight Safety Audit, Quét Lỗ Hổng Rò Rỉ Talkback DL16 #11, Tự Động Vá Lỗi Invariant (Auto-Sanitize) & Lưu Trữ Vault. | **PASS** |
| [tests/test_sprint21_gain_staging_and_headroom.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint21_gain_staging_and_headroom.py) | **6** | Cân Chỉnh Headroom & Gain Staging Chuẩn Nhà Thờ (Phân tích Peak/RMS/Crest Factor, Digital Trim Whitelist /ch/xx/preamp/trim, Bảo Vệ Headroom Lời Giảng -18 dBFS & Âm Nhạc -12 dBFS, Đề Xuất Proposal An Toàn). | **PASS** |
| [tests/test_sprint22_speech_automixer.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint22_speech_automixer.py) | **7** | Dugan Speech Automixer & NOM=1 Gain Sharing Controller, Bất Biến Giữ Mức Tăng Ích Tổng Thể NOM=1 (<= 0.0 dB), Tiết Kiệm Ồn Nền SNR, Bất Biến Silence Hold Khóa Gain Khi Im Lặng, Cách Ly Tuyệt Đối Mic Talkback Kênh 11, Đề Xuất Cấu Hình X32 Native Automix DSP & REST API. | **PASS** |
| [tests/test_sprint23_listening_test_benchmark.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint23_listening_test_benchmark.py) | **7** | Thẩm Định Thính Giác Mù A/B Chuẩn Quốc Tế ITU-R BS.1284, Bù Trừ Âm Lượng Equal-Loudness Fletcher-Munson, Ma Trận 7 Tiêu Chí Âm Học Nhà Thờ (Master Plan 3.4), Tính Điểm Trung Bình Trọng Số MOS (1.0-5.0), Quy Tắc Phủ Quyết An Toàn (Veto Rule), Lưu Trữ SQLite & REST API. | **PASS** |
| [tests/test_sprint24_stage_bleed_and_expander.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint24_stage_bleed_and_expander.py) | **8** | Kiểm Soát Rò Rỉ Sân Khấu (Stage Bleed) & Cân Chỉnh Downward Expander Cho Vocal: Phân Tích Ma Trận Tương Quan Chéo, Phát Hiện Méo Pha Lọc Lược (Comb Filtering), Cân Chỉnh Expander Dịu Nhẹ (Threshold = Ồn Nền + 3 dB, Range <= 12 dB, Key HPF 250 Hz), Bảo Vệ Bất Biến Kênh 11 Band Talkback & REST API. | **PASS** |
| [tests/test_sprint25_safety_modes_and_disengage.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint25_safety_modes_and_disengage.py) | **8** | Hệ Thống 4 Chế Độ Quyền Hạn Safety Engine (OBSERVE, ASSIST, LIMITED_AUTO, ADMIN_MAINTENANCE) & Tự Động Khóa Cứng (Auto-Disengage / Panic Freeze Watchdog: Vỡ tiếng liên tục > 5 frames, Tăng vọt nguy cơ hú, Mất telemetry > 2.5s, Nút STOP AUTO, Khóa bảo mật PIN 7777 & REST API). | **PASS** |
| [tests/test_sprint26_monitor_matrix_and_iem.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_sprint26_monitor_matrix_and_iem.py) | **10** | Ma Trận Monitor Aux & Ultranet P16 Personal IEM: Thẩm định 16 khe P16, Bất biến cách ly Talkback DL16 #11, Phân loại MixBus (Wedges/IEMs/FX), Dò nguy cơ hú loa sàn (> 0.80 fader send), Lỗi cấu hình Tap-Point Post-Fader, Đề xuất cân bằng an toàn qua SafetyGate & REST API. | **PASS** |
| [tests/test_service_segments.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_service_segments.py) | **19** | Tiết Mục (Service Segments): Chuyển cảnh micro an toàn theo vai trò kênh, ngắt micro trước khi bật, TransactionExecutor.execute_batch, bảo vệ kênh 11 Talkback, hoàn tác rollback tự động. | **PASS** |
| [tests/test_monitoring.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_monitoring.py) | **22** | Giám sát tín hiệu âm thanh (Peak, RMS, Crest Factor, Clip frames), phát hiện sự cố, cấu hình ngưỡng /api/v1/monitoring/thresholds, phân tích 32 kênh. | **PASS** |
| [tests/test_safety_hardening.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_safety_hardening.py) | **19** | Gia cố an toàn hệ thống: Chặn tiêm lệnh OSC, kiểm soát revision SHA-256, cách ly FOH và kiểm tra tính toàn vẹn trạng thái mixer. | **PASS** |
| [tests/test_performance_regressions.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_performance_regressions.py) | **5** | Kiểm thử hồi quy hiệu năng: Đo tốc độ codec OSC, snapshot diffing, throughput telemetry và thời gian phản hồi. | **PASS** |
| [tests/test_notch_band_selection.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_notch_band_selection.py) | **3** | Lựa chọn băng tần notch phẫu thuật tối ưu trên 4 band PEQ vật lý của X32. | **PASS** |
| [tests/test_safety_whitelist_regressions.py](file:///c:/xampp/htdocs/ChurchMix/tests/test_safety_whitelist_regressions.py) | **3** | Kiểm thử hồi quy Whitelist SafetyPolicy: Chặn các đường dẫn nhạy cảm và bảo đảm giới hạn slew-rate. | **PASS** |
| **TỔNG CỘNG PYTHON** | **240** | **Bao phủ 100% 26 Sprints và toàn bộ các bộ kiểm thử hồi quy an toàn, tiết mục, giám sát tín hiệu và hiệu năng** | **100% PASS** |
| **TỔNG CỘNG NODE** | **23** | **Kiểm thử công cụ CLI, hook JSON schema, template rules, giao diện Canvas charts và environment** | **100% PASS** |
| **TOÀN BỘ HỆ THỐNG** | **263** | **263 / 263 Bài kiểm thử tự động hoàn tất thành công (100% Green)** | **100% PASS** |

---

## 3. Lệnh Chạy Toàn Bộ Test Suite

Để thực thi toàn bộ 240 bài kiểm thử Python:
```powershell
$env:CHURCHMIX_X32_PORT = "10923"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest discover -s tests -p "test_*.py"
```

Để thực thi 23 bài kiểm thử Node.js:
```powershell
npm test
```
Thời gian thực thi trung bình: **~15.0 giây (Python) + ~2.0 giây (Node)**.




