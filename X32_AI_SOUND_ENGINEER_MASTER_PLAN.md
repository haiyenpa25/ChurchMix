# X32 AI SOUND ENGINEER — MASTER IMPLEMENTATION PLAN

**Phiên bản:** 1.0 — 11/10/2026  
**Mục đích:** Tài liệu thiết kế, triển khai, đo kiểm và nghiệm thu hệ thống hỗ trợ kỹ thuật viên âm thanh nhà thờ, dùng Behringer X32 Compact, DL16 và hệ thống personal monitoring P16.  
**Nguyên tắc:** *Chất giọng trung thực → nghe rõ → nhất quán → tăng gain-before-feedback an toàn → bảo toàn âm sắc hệ thống loa*. Không có phần mềm nào bảo đảm “không bao giờ hú” trong mọi điều kiện. Kết quả phụ thuộc bố trí loa/micro, mô hình âm học phòng, vị trí ca sĩ, mức âm và vận hành.

> **TRẠNG THÁI THIẾT BỊ:** Tài liệu chỉ thiết kế và hướng dẫn. Chưa kết nối, đọc, đo hay thay đổi X32 thật; tên kênh, bus, routing, loại card USB, loa và micro cần được khám phá và xác thực bằng snapshot ở giai đoạn 1. Các trị số trong ví dụ là điểm khởi tạo thận trọng để thử nghiệm, **không phải preset bắt buộc**.

---

## 0. TÓM TẮT PHƯƠNG ÁN VÀ GIỚI HẠN

Phát triển ứng dụng web hoạt động theo ba lớp: **OSC Control** (đọc/ghi X32 qua LAN), **Audio/Acoustic Measurement** (thu multitrack X32 qua USB và đo hội trường bằng micro hiệu chuẩn), **Decision & Safety** (phân tích, ưu tiên hành động ít phá âm sắc, mô phỏng, bắt người vận hành duyệt và hoàn tác). AI ngôn ngữ chỉ **giải thích** thông số, hướng dẫn từng bước, tổ chức công việc; thuật toán DSP được kiểm thử mới tính kết quả và chỉ safety controller được ghi lên mixer.

**Chọn dùng:** Python/FastAPI + NumPy/SciPy + React/TypeScript + SQLite + driver thu âm native. Tích hợp/sử dụng có chọn lọc những dự án mã mở:

1. **pmaillot/X32-Behringer**: tài liệu OSC và utility X32, căn cứ để xây dựng adapter.
2. **wrodie/behringer-mixer (MIT)**: API Python cho thông tin/fader/mute/scene/gain; dùng làm thư viện hoặc tài liệu tham khảo, viết phần điều khiển EQ/meter còn thiếu.
3. **CristianMoresi/M32LiveConsoleTool (MIT)**: nghiên cứu bộ điều khiển auto-level, anti-clip, simulator, logging và tests; không bật logic auto-gain/auto-fader gốc trên buổi lễ khi chưa kiểm thử.
4. **psmokotnin/osm — Open Sound Meter (desktop GPL-3)**: phần mềm đo độc lập: transfer function, spectrum, pha, coherence, delay; ưu tiên import/export kết quả trước, cân nhắc kết nối API sau khi kiểm chứng bản/format.
5. **pierreaubert/autoeq (RoomEQ)**: thuật toán tối ưu đáp tuyến/phân bổ các nguồn, có các dạng xuất EQ; chỉ đưa vào pipeline nếu license phiên bản, khả năng export và ràng buộc PEQ X32 phù hợp.
6. **HEnquist/camilladsp (GPL-3.0-only OR MPL-2.0, ngoại lệ ASIO)**: **đề xuất dùng trong lab/offline** để audition và giả lập xử lý, không nối vào đường FOH live nếu chưa thiết kế fail-safe phần cứng.
7. **jaakkopasanen/AutoEq (MIT)**: nghiên cứu tối ưu PEQ đường mục tiêu; chủ yếu cho headphone — **không** dùng nguyên preset headphone để hiệu chuẩn nhà thờ.

**Mục tiêu MVP:** Đọc đủ trạng thái mixer và tạo backup, phân tích từng kênh từ USB, hiển thị phổ và dấu hiệu rủi ro feedback, đưa ra đề xuất HPF/EQ/dynamics dựa trên đo lường, lưu A/B, chỉ ghi lên đúng channel khi người vận hành đồng ý.

**Không hứa:** Auto mix đạt chất lượng kỹ sư chuyên nghiệp cho mọi ban hát, tự loại trừ hú bằng EQ mà không ảnh hưởng giọng, hay đo chuẩn xác SPL tuyệt đối bằng micro không hiệu chuẩn. Đặt chất lượng đo, khả năng nghe A/B và quyền quyết định của kỹ thuật viên lên đầu.

---

## 1. HIỆN TRẠNG VÀ SƠ ĐỒ KẾT NỐI

Thông tin đã có từ người vận hành:

- Mixer **Behringer X32 Compact**.
- X32 **AES50 A → DL16**.
- **DL16 ULTRANET → P16-D → ba P16-HQ**, các personal mixer đã có tiếng và hoạt động.
- Có yêu cầu micro giao tiếp ban nhạc tại cổng DL16 số 11, **chỉ về hệ thống monitor P16**, không đưa ra loa chính. Đây là **yêu cầu phải bảo toàn**, không mặc định đã xác minh routing hiện hành của input này.

```text
                                 LAN / OSC UDP
   [Laptop/mini PC X32 AI Sound Engineer] <----------------------> [X32 COMPACT]
                |                                                 |      |
                | (card USB, tối đa theo card/route đã xác minh)  |      +----> Main L/R → DSP/amp/loa FOH (kiểm tra thực tế)
                +<---------------------- USB AUDIO ----------------+      |
                |                                                 |      +---- AES50 A ---- [DL16]
                +-- USB measurement mic *                          |                         |
                     hoặc mic XLR qua interface độc lập            |                         +--- ULTRANET → P16-D → 3 × P16-HQ
                                                                  |
                        [Wi-Fi AP] ── web dashboard ──────────────+

* Measurement mic + nguồn phantom/driver đúng cách; nguồn sync/clock và signal reference phải xác thực.
```

### 1.1 Không được tự suy luận routing

X32 có tầng **physical sockets / preamps → input channel sources → channel processing → mix buses/main → output sources → physical output**. AES50, ULTRANET, USB recording có thể lấy tín hiệu từ các tap point khác nhau. Phần mềm phải đọc và mô hình hóa **cả đường tín hiệu**, không suy luận rằng DL16 input #11 bằng channel #11 hay P16 slot #11. `Input #11`, `Channel #11`, `Ultranet #11` là ba khái niệm khác nhau.

**Các bất biến bảo vệ:** không đổi `AES50 A/B`, `Routing/In`, `Routing/Out`, `P16/Ultranet`, bus sends, phantom, headphone, main mute, DCA assignment hay scene recall khi ở chế độ đề xuất EQ. Các thao tác này chỉ xuất hiện trong wizard routing với mật khẩu/quyền riêng, diff hiển thị đầy đủ và hậu kiểm audio. Đặc biệt micro talkback ban nhạc phải **không có đường đến FOH**; điều này cần kiểm tra trên tất cả bus/matrix/FX/return/cross-routing, không chỉ một nút `Main LR`.

### 1.2 Thiết kế LAN

- Đặt mixer và host trên mạng LAN riêng/segment quản lý, IP ổn định/DHCP reservation; không phơi UDP OSC ra Internet.
- X32 OSC chủ yếu dùng UDP port 10023; đăng ký nhận meter/trạng thái và heartbeat dựa trên giao thức thực tế/firmware. Không hard-code cổng nhận hay subscription từ dự án khác nếu chưa kiểm tra; dùng wireshark/log và mock tests.
- Nếu cần điều khiển từ xa: VPN WireGuard/Tailscale qua thiết bị gateway; remote chỉ `Observe` mặc định, không mở cổng OSC hay UI không xác thực lên WAN.
- App bị treo/mất mạng **không** làm dừng X32; vì âm thanh live vẫn do DSP trên mixer xử lý.

---

## 2. GITHUB MIỄN PHÍ: THẨM ĐỊNH VÀ CHIẾN LƯỢC TÍCH HỢP

| Repo / liên kết | Vai trò | Đã xác minh | Hình thức tích hợp khuyên dùng | Hạn chế/rủi ro |
|---|---|---|---|---|
| [pmaillot/X32-Behringer](https://github.com/pmaillot/X32-Behringer) | Mã C + tham khảo OSC X32/M32 | Repo public, utility và tài liệu OSC liên kết trang tác giả | Tham chiếu protocol; xây adapter Python với tests | Kiểm tra LICENSE cụ thể trước khi sao chép nguồn; không xem public = MIT |
| [wrodie/behringer-mixer](https://github.com/wrodie/behringer-mixer) | Python read/write fader, mute, scene, headamp... | MIT; không bao phủ mọi tham số | Dependency có khóa version hoặc tham khảo abstraction | Không thay thế toàn bộ adapter EQ/routing/meter; tests repo có thể thay đổi mixer thật |
| [CristianMoresi/M32LiveConsoleTool](https://github.com/CristianMoresi/M32LiveConsoleTool) | Auto-level + anti-clip + tempo delay, simulator | MIT, .NET 10, OSC/UDP | Fork sandbox để so sánh logic, port thuật toán có ghi nguồn hoặc chạy công cụ độc lập | Không chạy đồng thời hai controller ghi fader trên mixer live |
| [psmokotnin/osm](https://github.com/psmokotnin/osm) | Spectrum, transfer-function, phase/coherence/delay | Bản desktop GPL-3.0; release có Remote API chia sẻ measurement | Cài tool độc lập, nhập CSV/đồ thị/measurement; thử API khi kiểm tra schema | GPL khi phân phối code; Remote API không tự khẳng định tương thích mọi phiên bản |
| [pierreaubert/autoeq](https://github.com/pierreaubert/autoeq) | RoomEQ, PEQ optimization, multimeasurements | Có room CLI, export REW/biquad | CLI **ngoại tuyến**, parse kết quả + biến đổi sang 4-band/channel hoặc GEQ/PEQ output thích hợp | Phải kiểm tra license chính xác của commit; X32 không có số filter/tính năng tương đương pipeline bất kỳ |
| [HEnquist/camilladsp](https://github.com/HEnquist/camilladsp) | DSP IIR/FIR và giả lập audition | Dual GPL-3.0/MPL-2.0; build ASIO chỉ GPL-3 | Tool lab, preview, không ở đường FOH live | Độ trễ, cấu hình route, dropouts; nghĩa vụ license theo build |
| [jaakkopasanen/AutoEq](https://github.com/jaakkopasanen/AutoEq) | Optimization PEQ và target fitting | MIT | Reuse logic toán/libraries có kiểm thử | Thiết kế headphone; không coi target headphone là target loa hội trường |
| [tjoracoder/python-x32](https://github.com/tjoracoder/python-x32) | OSC X32 Python | Repo public | Đọc tham khảo | Ít cập nhật/commit; cần kiểm tra LICENSE trước khi chép code |

**Nguyên tắc pháp lý:** GitHub public ≠ giấy phép tái sử dụng. Trước khi copy bất cứ source nào phải ghi `repo URL`, SHA commit, LICENSE, notice, version, modified-files, nguồn phụ thuộc. MIT thường dễ tích hợp có điều kiện giữ notice. GPL có nghĩa vụ khi phân phối bản phái sinh/chương trình kết hợp; tách chạy thành chương trình ngoài **không tự động** loại bỏ mọi nghĩa vụ. Xin tư vấn chuyên môn nếu đóng gói/bán. Dùng chương trình nguồn mở độc lập và trao đổi file dữ liệu có thể là hướng đơn giản hơn.

### 2.1 Repo nào giải quyết đúng bài toán nào?

- **“Điều khiển mixer”**: pmaillot, wrodie.
- **“Tự cân mức”**: M32LiveConsoleTool — chỉ dùng sau khi thiết kế chính sách tránh âm lượng lên khi im lặng.
- **“Đo đáp tuyến/pha hệ loa”**: Open Sound Meter.
- **“Đề xuất EQ hệ loa”**: RoomEQ + thuật toán fit PEQ riêng theo số band/tính năng thật của X32.
- **“Phát hiện tiếng hú”**: phải tự phát triển thuật toán + kiểm thử thu âm; **không có repo trên nào được xác minh là giải pháp auto anti-feedback hoàn chỉnh cho X32.**
- **“AI tư vấn bằng tiếng Việt”**: dùng mô hình ngôn ngữ truy xuất tài liệu và dữ liệu đo, không cho model phát lệnh OSC trực tiếp.

### 2.2 Lược đồ thành phần dependency

```text
UI React ───────────────┐
                        ▼
                  FastAPI / WebSocket
             ┌──────────┼───────────┐
             ▼          ▼           ▼
       OSC Adapter  Audio Engine  Recommendation Engine
       (Python)     (native)      (SciPy + rules + AI explains)
             │          │           │
        X32 over LAN   X32 USB      ▼
             │        + measure   Safety Gate → Transaction Executor
             └──────────────────────┘        │
                                   Snapshot/verify/rollback
```

---

## 3. MỤC TIÊU CHẤT ÂM: CHỐNG HÚ NHƯNG KHÔNG PHÁ GIỌNG/LOA

### 3.1 Hiểu đúng cơ chế feedback

Feedback âm học là vòng kín `loa → không khí/phòng → micro → preamp → EQ/dynamics/mix → ampli/loa`; khi tích lũy gain và pha đủ thuận, vòng có thể dao động mạnh tại một hoặc nhiều tần số. Hú **không phải** chỉ là “một đỉnh FFT”. Một nốt hát giữ dài, tiếng đàn organ hay cymbal cũng có thể tạo đỉnh hẹp nhưng không phải feedback.

**Thứ tự xử lý ưu tiên — luôn áp dụng theo thứ tự:**

1. **Vật lý/bố trí:** hướng pickup của micro, ca sĩ đứng sau/ngoài vùng loa FOH, khoảng cách micro–miệng, hướng wedge monitor vào vùng suy giảm polar pattern, tránh hướng mic vào loa; thay mic/monitor placement trước khi cắt EQ.
2. **Gain structure:** giảm nguồn quá lớn/bus send/wedge; kiểm tra PFL, preamp không clipping, fader/dynamics; tính gain-before-feedback. Tránh lấy việc đẩy preamp làm cách bù fader nhỏ.
3. **Tách vùng:** FOH, monitor wedge, in-ear P16 có vòng feedback khác nhau. P16-HQ tự thân không phát âm ra phòng nếu dùng headphone/in-ear, nên không mặc định là nguyên nhân hú phòng.
4. **Tối ưu xử lý:** HPF phù hợp, PEQ cắt rất hẹp chỉ ở mode hiệu chuẩn/đã xác nhận tần số hú, compressor/gate hợp lý; không tăng treble bừa bãi để sửa mờ lời.
5. **Xác nhận bằng tai và đo:** so sánh A/B mức loudness tương đương, nhiều giọng, nhiều vị trí, câu hát thật và speech; tránh EQ gắt/mỏng/thiếu presence.

**Quy tắc vàng:** Không “flatten” giọng từng ca sĩ thành phổ chuẩn. Giọng người, phoneme và mic khác nhau; FFT chỉ là một nguồn bằng chứng.

### 3.2 Phân biệt EQ trên mixer và tuning loa

- **Channel EQ:** sửa nguồn cụ thể (plosive, proximity, boxy, sibilant, leakage) trong ngữ cảnh mix.
- **Bus/Matrix EQ / speaker DSP:** sửa hệ thống PA theo phép đo phòng có reference; tốt nhất xác định đúng processing tap và giới hạn bộ lọc của thiết bị. Không cộng chồng bù trừ vô hạn qua channel + bus + PA DSP.
- **Feedback notch:** bộ lọc hẹp tình huống để tăng biên an toàn; không coi là đường EQ thẩm mỹ.
- **Room modes / comb filtering:** nhiều null sâu là triệt tiêu do hình học, **không boost** để lấp null; phải thay vị trí/pha/delay hoặc dùng multi-position decisions.

### 3.3 Các profile không được điều chỉnh mù

| Nguồn | Quan sát & chẩn đoán | Khả năng đề xuất | Lưu ý chất giọng |
|---|---|---|---|
| Lead vocal | RMS/peak, spectrogram, sibilance, bleed, feedback candidates | HPF bảo thủ, low-mid cut nhẹ nếu thực sự đục, comp kiểm soát dynamic | Không cắt hàng loạt 200–400Hz làm mỏng giọng nam; kiểm tra articulation và độ ấm |
| Backing vocal/choir | Chênh level, tương quan giọng/nhạc, bleed | Group balance, HPF theo voice, DCA hoặc fader giới hạn | Không áp EQ giống nhau cho mọi mic |
| Micro giảng | intelligibility, proximity, plosive, noise, gain margin | Speech snapshot, comp nhẹ, HPF phù hợp, automix nhiều micro | Không lạm dụng gate khiến mất âm đầu/cuối từ |
| Keyboard/piano | phổ rộng, xung đột voice | EQ theo arrangement và stereo correlation | Tránh triệt quá nhiều harmonic; check mono compatibility |
| Bass/kick | low-end accumulation | HPF nguồn không cần bass, carve theo arrangement | Giữ nền, không “gọt” hết lực âm |
| Guitar/acoustic | harshness, boom, DI/mic bleed | EQ có kiểm chứng | Tôn trọng attack và body |
| Loa FOH | transfer function, coherence, delay, impulse, averaged positions | chấm điểm response, target slope, PEQ output-safe | Không ép response phẳng tuyệt đối; không boost sâu trong null |

### 3.4 Bộ tiêu chí listening test

Mọi preset nên được nghe tại mức tương đương và chấm 1–5 cho: **độ rõ lời**, **độ tự nhiên/chất giọng**, **độ ấm**, **âm gắt/xì**, **sự cân bằng ban nhạc**, **độ đồng đều hội trường**, **headroom/hú**. Không “pass” tự động chỉ vì đường FFT đẹp.

---

## 4. PHẦN CỨNG VÀ LUỒNG ĐO

### 4.1 Tối thiểu (Stage 1–2)

- Máy Windows 10/11 hoặc Linux, RAM từ khoảng 8 GB cho control + DSP đo vài kênh; khuyến nghị **16 GB** và SSD nếu phân tích nhiều luồng/phổ thời gian thực. Không cần GPU để làm FFT. Máy Dell Wyse 5070 **có thể** làm host UI/OSC nhẹ nhưng phải benchmark CPU/USB driver nếu thu nhiều channel.
- Ethernet từ host đến mixer, quyền quản trị firmware/config; nguồn điện ổn định.
- X32 card USB multichannel **nếu được trang bị và cấu hình**; kiểm tra card X-USB/X-LIVE/khác, driver, routing, sample rate, khả năng truy cập trên OS.
- Headphone để theo dõi PFL và nghe so sánh có an toàn.

### 4.2 Bộ đo loa (Stage 5)

- Micro đo **có file calibration** và tripod; ví dụ UMIK-1 (USB, phải xem khả năng reference/clock đồng bộ) hoặc ECM8000 + interface phantom 48V (nên có file calibrate theo từng đơn vị).
- Measurement interface/capture có cấu hình **reference loopback đồng bộ** khi dùng transfer function nếu khả thi. Nếu input đo từ USB mic và reference từ X32 trên hai clock độc lập, **drift clock** gây sai phép đo phase/delay khi tích lũy; dùng công cụ hỗ trợ drift correction, hoặc audio interface chung clock/analog reference loopback.
- Thiết bị đo SPL đã hiệu chuẩn nếu yêu cầu đơn vị dB SPL chính xác; dBFS trên X32 **không phải dB SPL ở ghế ngồi**.
- Tín hiệu sweep/pink noise ở mức thấp phù hợp, thực hiện khi không có người hoặc có thông báo rõ ràng; bảo vệ thính giác và loa.

### 4.3 Các đường đo được hỗ trợ

**Path A — OSC only:** đọc mức meter, mute, fader, EQ, dynamics; tạo configuration audit và safety report. **Không** thể lấy phổ FFT đầy đủ chỉ từ meter thông thường.

**Path B — OSC + X32 multitrack USB:** ghi/đọc tín hiệu từng channel/tap; phân tích phổ từng micro/nhạc cụ, tiếng hú trong audio sample; xác thực USB routing để biết là pre/post EQ/fader. Nếu nghe pre-EQ thì analyzer không được tự cho là đồ thị biểu thị post-EQ.

**Path C — Path B + calibrated measurement mic/reference:** đo âm học tại các vị trí người nghe, transfer function/phase/delay/coherence, thiết kế tuning loa. Thử nghiệm với microphone monitor và FOH riêng; đo full chain tại tap point đúng.

**Path D — import external measurements:** REW/OSM export, WAV/CSV/FRD, có schema version và calibration provenance; khả thi nếu không muốn điều khiển capture live trong app từ đầu.

---

## 5. KIẾN TRÚC HỆ THỐNG CHI TIẾT

### 5.1 Các service

1. `x32-discovery`: IP discovery thủ công/UDP probe theo tài liệu, firmware, device info; khả năng adapter.
2. `x32-osc-gateway`: one-writer policy, rate limiting, heartbeat, get/set/dump, reconnect, topic subscription, OSC validation.
3. `state-mirror`: cache trạng thái với timestamp, source, freshness, detect changes ngoài app.
4. `snapshot-service`: nguyên trạng trước thay đổi, checksum, diff, tag, export, restore có kiểm duyệt.
5. `audio-capture-agent`: native Windows WASAPI/ASIO hoặc Linux ALSA/JACK/PipeWire, buffer ring, per-channel route matrix, timestamp, level, clipping, drift.
6. `signal-analyzer`: STFT/FFT/RTA, smoothing, octave bands, RMS, peak, crest, noise floor, spectral stability.
7. `measurement-engine`: reference/measurement cross spectrum, impulse response, transfer H1, coherence, delay, averaging multi-location.
8. `feedback-guard`: phát hiện ứng viên, confidence/cause analysis, báo động; mặc định **không** notch tức thời.
9. `mix-assistant`: LUFS khi phù hợp với program segments, gain reduction profile, signal activity and silence hold, limited fader nudges.
10. `recommendation-engine`: conservative rules + optimizer + listening checklist.
11. `safety-gateway`: authorization, invariant checks, dry-run, transactional apply, rollback, audit.
12. `ai-copilot`: RAG tiếng Việt trên manual, hệ thống role/channel, giải thích nguyên nhân và hướng dẫn. AI không nhận secret/mật khẩu vào prompt.
13. `frontend`: channels, routing map, RTA, live meter, suggestion queue, A/B, calibration wizard, event log.

### 5.2 Luồng quyết định từ đo đến thay đổi

```text
Input audio + OSC state
    ↓ quality checks: drift? clipping? missing? wrong tap? reference?
    ↓ classify source and active segment (speech/music/silence)
    ↓ diagnostic hypotheses (feedback candidate? masking? placement?)
    ↓ conservative proposed parameter diff + predicted result
    ↓ Safety Gate (whitelist, bounds, snapshot, drift compare)
    ↓ User preview + explicit approve
    ↓ rate-limited writes to only allowed OSC paths
    ↓ readback compare + observe meter/audio changes
    ├─ unexpected? → rollback + STOP + report
    └─ pass? → commit + audit + A/B listen
```

### 5.3 One-writer và kiểm soát race condition

- Chỉ **một backend** sở hữu ghi OSC. Nếu Mixing Station/X32-Edit/nhân sự đổi fader: đọc trạng thái mới và ngừng apply nếu bản gốc đã thay đổi (`optimistic locking`).
- Không có `fire-and-forget` cho command nguy hiểm. Snapshot cấp đối tượng với nonce, transaction id, reason, operator id, timestamp, preconditions, write set, verification, rollback record.
- Ghi mỗi tham số một lần theo state delta; chặn oscillation/toggling bằng hysteresis, hold-off, cooldown.
- Web client không gửi OSC trực tiếp. Các thiết bị không xác thực chỉ được xem read-only ở LAN nội bộ khi operator cho phép.

### 5.4 Data model đề nghị

```text
Mixer(id, model, firmware, ip, sample_rate, card, last_seen)
Endpoint(id, mixer_id, physical_type, physical_index, preamp_id)
Channel(id, mixer_id, number, name, color, source_endpoint, role)
Bus(id, mixer_id, number, name, purpose)
SignalRoute(id, source, tap_point, destination, gain, enabled)
ParameterState(mixer_id, osc_path, dtype, value, observed_at, revision)
Snapshot(id, mixer_id, sha256, state_json, captured_at, author, note)
AudioSource(id, capture_device, index, sample_rate, channel_id, tap_point)
Measurement(id, source, mic_id, mic_cal_hash, clock_id, position, conditions,
            measurement_type, fft_settings, coherence, wav_ref, result_json)
Finding(id, kind, channel_id, freq_hz, confidence, evidence, severity)
Recommendation(id, scope, description, before_json, after_json, limits, status)
ApplyTransaction(id, operator, timestamp, snapshot_id, writes_json, readback_json,
                 rollback_state, result, failure_reason)
Profile(id, name, role, category, approved_by, snapshot_id, constraints_json)
AuditEvent(id, actor, action, object_ref, time, details, immutable_hash)
```

---

## 6. THUẬT TOÁN ĐO ÂM VÀ PHÂN TÍCH

### 6.1 Thu nhận tín hiệu

- Chọn sample rate của thiết bị (X32 thường 44.1/48k tùy hệ thống), không tự đổi clock mixer; mỗi channel có timestamp và tap-point.
- Buffer frame cỡ 1024–4096 samples để xem phổ nhanh, các khung dài hơn để phân giải vùng thấp; overlap 50–75%, window Hann, pipeline không block capture.
- Calibration gain cho kết quả dBFS. Tránh gọi dBFS peak là dB SPL; microphone frequency calibration và sensitivity riêng.
- Mất mẫu/xrun, clip, sample-rate mismatch, channel swap: hiện cảnh báo **invalid measurement** và cấm áp đề xuất.
- Lưu data 5–30 giây cho phát hiện tình huống theo chính sách riêng tư; tùy chọn không lưu giọng nói/thu âm bài giảng (chỉ lưu features).

### 6.2 FFT và RTA

Cho frame `x[n]`, FFT `X[k]=FFT(w[n]x[n])`; tạo power spectral density có chuẩn hóa năng lượng window; chọn cửa sổ/smoothing nhất quán khi so sánh. Hiển thị dải log 20 Hz–20 kHz (giới hạn Nyquist), smoothing 1/24 / 1/12 / 1/6 octave, max hold và time average. Dùng Welch khi muốn estimate phổ ổn định hơn. Tránh suy ra chất lượng âm từ một frame.

Metrics: `peak dBFS`, `RMS dBFS`, `crest factor`, clipping count, channel correlation, noise floor estimate, spectral centroid, octave-band energy, LUFS chỉ khi có đoạn program/algorithm phù hợp.

### 6.3 Transfer function và đo hệ loa

- Có reference signal `x(t)` và mic measurement `y(t)` trên clock xử lý đồng bộ.
- Ước lượng transfer function `H1(f)=S_yx(f)/S_xx(f)`; coherence `γ²(f)=|S_xy(f)|²/[S_xx(f)S_yy(f)]` để đánh giá độ tin cậy theo frequency.
- Estimate time-of-flight/latency qua impulse/cross-correlation; time alignment cần làm **trước** khi diễn giải phase; tránh alignment tùy tiện làm sai đánh giá loa/sub.
- Lấy ít nhất nhiều điểm đo ở khu vực người nghe thật: trung tâm/trước/sau/trái/phải; gắn điều kiện, khoảng cách, độ cao, noise. Không chỉnh theo một ghế duy nhất.
- Apply giới hạn: ưu tiên cut broad peaks, không boost deep nulls, tránh notch sắc trên master nếu chưa xác định nguyên nhân; số filter phù hợp thiết bị thực. Đánh giá trước/sau bằng các vị trí không dùng để fit (holdout measurements).

### 6.4 Feedback Candidate Detector — thiết kế không nhầm nốt hát

**Kết hợp bằng chứng** thay vì một peak detector:

1. `tonality`: peak narrowband có tỷ lệ năng lượng so với lân cận và local noise floor đủ lớn.
2. `persistence`: tồn tại xuyên nhiều frame, tần số drift nhỏ, độ lớn có xu hướng tăng hoặc giữ bất thường.
3. `independence`: không tương quan hợp lý với pitch/harmonic track của singer/instrument; kiểm tra nhiều channels và monitor bus nếu capture có dữ liệu.
4. `context`: detector chỉ cảnh báo nếu mixer source đang mở và có acoustic path; phân biệt ring-out mic khi test với buổi hát đang diễn ra.
5. `coherence/phase`: nếu có reference phù hợp, đánh giá thêm loop resonance nhưng không coi coherence cao là chứng cứ đủ.
6. `cross-signal`: một tone xuất hiện ở nhiều mic và FOH output với quá trình phát triển không bình thường có thể tăng độ tin cậy.

**State machine:** `NORMAL → SUSPECT → CONFIRMED_WITH_OPERATOR / AUTO_LIMITED_SAFE_ACTION → COOLDOWN`. Emergency alarm cho operator, không tự động EQ chỉ dựa vào FFT. Cho kỹ thuật viên nghe tần số ứng viên ở âm lượng an toàn và so sánh A/B; không phát tone thử gây hú trong giờ lễ.

**Pseudo-code:**

```python
for frame in audio_frames:
    if not frame.valid or frame.clipped or frame.channel_map_uncertain:
        invalidate_findings(frame.channel)
        continue
    spectrum = welch_psd(frame)
    peaks = find_narrow_peaks(spectrum, relative_threshold_db=CONFIGURED)
    for peak in peaks:
        score = combine(
            narrowband_score(peak),
            persistence_score(peak),
            anomalous_growth_score(peak),
            source_activity_score(frame.channel),
            not_voice_or_instrument_harmonic_score(peak),
            cross_channel_evidence(peak),
        )
        if score > REVIEW_THRESHOLD:
            issue_warning(channel=frame.channel, frequency=peak.hz, confidence=score)
# Không phát write_osc() trực tiếp trong detector.
```

Các threshold cần tune bằng dữ liệu thực tại nhà thờ; không khẳng định giá trị mặc định phổ quát. Vòng lặp không tự notch nếu không có quyền operator và chứng cứ đáng tin.

### 6.5 EQ recommendation engine — bảo toàn chất giọng

1. Xác định source profile từ operator; không đoán cứng giọng nam/nữ chỉ theo phổ.
2. Đo signal sạch ở rehearsal, các âm tiết và mức hát/nói khác nhau.
3. Xác định vấn đề từ spectrum **cùng phép nghe**: plosive/rumble, mud, honk/nasal, harsh, sibilance, feedback candidates.
4. Ưu tiên **position/mic technique**, HPF đủ dùng rồi cân EQ rộng nhẹ; tránh notch nhiều dải chỉ để FFT mịn.
5. Tạo `proposed_eq`: `freq`, `Q`, `gain_db`, `filter_type`, `expected_tradeoff`, `evidence`, `confidence`; chạy magnitude response simulation cho tổng cascaded EQ.
6. Constrain theo capability: chỉ đề xuất số band X32 hỗ trợ tại channel/bus đó và loại filter/frequency/Q hợp lệ; không phát tham số giả định.
7. Chạy A/B đoạn thu đã xin phép và nghe live; normalize loudness; operator chấp nhận.

**Tài liệu khởi tạo để đào tạo kỹ thuật viên, KHÔNG phải thông số tự động áp:** HPF cho nhiều micro giọng nói thường bắt đầu khảo sát vùng ~70–120 Hz tùy người/mic/độ trầm; giọng trầm có thể cần thấp hơn, micro bục có thể cần khác. Kiểm tra 150–400 Hz khi đục, 2–5 kHz khi cần intelligibility nhưng dễ gắt/hú, 5–10 kHz khi xì/brightness; không auto-boost theo bảng này. Mỗi quyết định theo nguồn/mic/vị trí/hệ loa.

### 6.6 Dynamics / Automixing

- Ưu tiên comp vừa phải trên voice/speech; attack/release/knee/ratio/threshold không tự tính chỉ từ `peak`. Đo distribution mức, speech activity, gain-reduction histogram, sibilance/bleed.
- Khi ca sĩ ngừng hát, không tự tăng fader để bắt noise. Có `activity detector`, `silence hold`, `max upward step`, `max overall boost`, `slower upward than downward`, `manual touch suspend`, `feedback-risk freeze`.
- DCA/group acts không ảnh hưởng cả FOH + IEM ngoài ý muốn: audit pre/post sends, DCA membership. Với monitor P16, chỉ điều khiển FOH path nếu đã xác nhận P16 tap independent.
- Auto mix nhiều micro giảng nên dùng nguyên tắc gain sharing nếu cần, phân biệt automixer speech với volume rider cho nhạc.
- Anti-clipping không tự hạ preamp gain trong buổi live khi preamp dùng chung nhiều route (ảnh hưởng monitor/recording); đề xuất thay đổi nguồn/cấp vào, cảnh báo, chỉ giảm FOH fader hạn chế nếu người quản trị chọn và không còn phương án khác.

---

## 7. CÁC WIZARD HƯỚNG DẪN KỸ THUẬT VIÊN “TẬN RĂNG”

### Wizard 1 — `Connect & Inventory` (read-only)

1. Kết nối Ethernet, nhập IP, ping/probe status.
2. Đọc tên/firmware/card capability, sample rate/clock, scene/show identifiers.
3. Duyệt tất cả channel, preamp, source, send, groups, bus, matrix, output, AES50, P16.
4. Hiển thị sơ đồ source→destination từ snapshot với nhãn **Đã xác minh/Chưa xác minh**; yêu cầu người dùng đánh dấu vị trí mic và loa.
5. Export báo cáo Markdown + JSON snapshot + bản diff.
6. Freeze protected routes (`AES50`, `P16-D/HQ`, talkback monitor only, FOH outputs).

**Pass khi:** tạo full snapshot với hashes và đối chiếu trên X32-Edit/console; không có OSC write.

### Wizard 2 — `Pre-service Line Check`

1. Đọc signal/mute/phantom/headamp (read only), check missing signal, clip, wrong channel label.
2. Operator solo/PFL **bằng thao tác có chủ đích**, app chỉ gợi ý; hiển thị meter/video hướng dẫn.
3. Thu sample ngắn từng mic với sự đồng ý, phân biệt source voice/instrument.
4. Đánh dấu mic feedback-prone, vị trí wedge/PA, monitors; kiểm tra talkback P16 không có đường FOH.
5. Sinh checklist mỗi Chủ Nhật: cable/mic, source, preamp, bus, talkback, recording, main, monitor, backup scene.

### Wizard 3 — `Vocal/Speech Calibration`

1. Chọn micro và người dùng, yêu cầu hát/nói đoạn tự nhiên 20–40 giây, tránh background noise.
2. Kiểm tra clipping, mic distance và monitor placement; báo lỗi nếu không hợp lệ.
3. Đưa ra đề xuất **từng bước**: kỹ thuật micro → HPF → EQ nhẹ → dynamics → FOH balance.
4. Mỗi đề xuất: trước/sau, lý do, mặt trái có thể, ảnh hưởng dự kiến đối với P16/FOH; chờ duyệt.
5. Kiểm tra giọng trầm/cao, nói nhỏ/hát lớn, sibilance, plosive; lưu profile tương ứng microphone và vị trí, không “preset chung mọi giọng”.

### Wizard 4 — `Room/PA Calibration` (ngoài giờ)

1. Xác nhận hall trống/an toàn, khu vực đo; chọn mic file hiệu chuẩn đúng serial.
2. Xác nhận measurement/reference paths và clock, delay timing, speaker zones.
3. Giảm mức ban đầu, phát test ở mức đã được người vận hành chấp thuận; không phát thẳng mức cao.
4. Đo từng vùng, tách mains/sub nếu phần cứng cho phép; xác minh polarity/timing.
5. Thu ít nhất 5–9 vị trí đại diện tùy kích thước hall; ghi lại vị trí, mic height, dB SPL nếu đo được.
6. Đánh giá phase, coherence; đo thiếu tin cậy thì không fit.
7. Sinh target *nhẹ, có độ dốc hợp lý*, cut peaks, tránh boost nulls; preview giới hạn 4/6 band thực của scope đã xác minh.
8. Người vận hành duyệt; chỉ thử từng nhóm thay đổi, A/B mức âm tương đương ở nhiều vị trí.
9. Ghi before/after measurements, listening score, revert button.

### Wizard 5 — `Feedback Ring-Out` (không trong buổi lễ)

1. Xác nhận không có người gần loa và volume được kiểm soát; chọn micro/monitor path riêng.
2. Đặt mic đúng tư thế thật, đặt wedge/FOH hợp lý, mở từng đường path theo thứ tự.
3. Tăng gain **thủ công và từ từ** dưới giám sát người có chuyên môn, dừng ngay khi bắt đầu ring; không dùng app để tự tăng mức phát nhằm ép hú.
4. Detector đánh dấu tần số ứng viên, ghi nhận tap point, source, polarity/position, snapshot.
5. Kiểm tra bằng thay đổi vị trí/micro/gain; notch chỉ khi xác nhận và thật sự cần, số notch tối thiểu.
6. Quay lại nghe giọng hát/nói thật tại mức giống nhau. Nếu mất body/presence, ưu tiên quay lại xử lý nguyên nhân vật lý.
7. Ghi gain margin đạt được thực nghiệm, kèm mức/điều kiện; không khẳng định miễn nhiễm feedback về sau.

### Wizard 6 — `Live Service Assistant`

- Dashboard một màn hình: critical clipping, loss of network/audio, channel activity, *feedback suspect* đã đánh mức tin cậy, mức main, trạng thái monitor path.
- Hiển thị tin nhắn ngắn bằng tiếng Việt: **“Lead vocal 2: nghi tần số dao động; kiểm tra ca sĩ đứng trước loa trái; không khuyến nghị auto-notch khi đang hát”**.
- Mọi điều chỉnh live cần quyền phù hợp; emergency = nhắc kỹ thuật viên xử lý mutes/mức bằng console, không gửi lệnh mạo hiểm từ AI.
- One-click **STOP AUTO** ngừng mọi controller; vẫn nghe tiếng từ mixer nguyên trạng.

### Wizard 7 — `End-of-service Review`

Báo cáo: số lần clipping, thời điểm feedback suspects, ảnh hưởng EQ, live changes, undo, chất lượng meter/capture, checklist công việc lần sau; xuất MD/PDF ở pha sau.

---

## 8. SAFETY ENGINE VÀ GIỚI HẠN GHI LỆNH

### 8.1 Chế độ quyền

| Mode | OSC read | OSC write | Dùng khi |
|---|---:|---:|---|
| OBSERVE | Có | Không | Mặc định, trong giờ lễ |
| ASSIST | Có | Mỗi thay đổi đã duyệt | Rehearsal, tuning |
| LIMITED_AUTO | Có | Chỉ whitelist và giới hạn | Sau test trên từng loại kênh |
| ADMIN_MAINTENANCE | Có | Routing có phê duyệt riêng | Ngoài giờ / operator cấp cao |

`LIMITED_AUTO` mặc định **OFF** sau khi app start/reconnect/scene change/firmware change; operator phải bật lại. Chỉ chạy khi meter fresh, sync/record stable, channel map verified, snapshot available, no recent external edits, monitoring path confirmed safe.

### 8.2 Whitelist ban đầu

- Read mọi tham số đã hỗ trợ, nhưng writes ban đầu chỉ **Channel EQ/HPF** trên channel được chọn, sau đó mở comp/fader theo mức trưởng thành.
- Deny tất cả: global settings, sample rate, AES50 routing, P16 outputs, phantom, preamp gain, main amp, scene recall, monitor routing, FX routing. Admin operation tách biệt tuyệt đối.
- Fader live tự động (sau M5) chỉ dùng mức `±` giới hạn do quản trị gán cho **từng kênh**; default no upward writes.

### 8.3 Transaction pseudocode

```python
async def apply_proposal(proposal, operator):
    require_auth(operator, role="engineer")
    require_mode("ASSIST")
    require_explicit_approval(proposal.id, operator)
    require_all_paths_whitelisted(proposal.diff)
    assert_snapshot_revision_equal(proposal.expected_revision)
    assert_measurements_fresh(proposal.source_measurement_ids)
    assert_constraints_hold(proposal.diff)
    old = await readback_exact_paths(proposal.diff.keys())
    persist_transaction_before_write(old, proposal)
    try:
        for command in order_safely(proposal.diff):
            await send_rate_limited(command)
            await verify_readback(command)
        assert_routes_unchanged()
        persist_commit()
    except Exception:
        await rollback_exact_paths(old)
        disable_automatic_writes()
        escalate_alarm()
        raise
```

**Lưu ý:** rollback OSC là best effort, mạng có thể mất. Bắt buộc có bản snapshot mixer offline và khả năng operator khôi phục trên console. Khi đọc không khớp, **đóng băng** write thay vì tiếp tục gửi lệnh.

### 8.4 Sự kiện làm ngưng auto

- OSC disconnect / heartbeat lost / stale meter.
- Audio buffer overrun, clock drift, wrong input mapping, clipping quá mức.
- Scene recall, chỉnh tay trên console, source reassignment, channel link đổi.
- Không có xác nhận path monitor độc lập.
- Feedback probability tăng nhanh hoặc operator nhấn STOP.
- Host CPU overload / latency vượt giới hạn đo.

---

## 9. API, CONTRACT VÀ CẤU TRÚC REPOSITORY

### 9.1 Endpoints

```http
GET  /api/v1/mixers
POST /api/v1/mixers/{id}/discover                  # read only
GET  /api/v1/mixers/{id}/status
GET  /api/v1/mixers/{id}/routing/graph
GET  /api/v1/mixers/{id}/channels
POST /api/v1/snapshots                            # read only
GET  /api/v1/snapshots/{id}/diff?to=...
POST /api/v1/measurements/session                 # init capture/import
GET  /api/v1/measurements/{id}/quality
GET  /api/v1/measurements/{id}/spectrum
POST /api/v1/analysis/feedback                   # offline or read only
POST /api/v1/recommendations/eq                  # proposal only
POST /api/v1/recommendations/dynamics            # proposal only
POST /api/v1/proposals/{id}/preview
POST /api/v1/proposals/{id}/approve              # explicit authority
POST /api/v1/proposals/{id}/apply                # gateway validates
POST /api/v1/transactions/{id}/rollback
POST /api/v1/automation/stop
GET  /api/v1/audit/events
WS   /ws/v1/live                                   # only server-sanitized telemetry
```

`POST /apply` không cho client gửi raw OSC path tự do; chỉ chấp nhận `proposal ID` server-side đã ký/bound snapshot revision. Role-based access và CSRF/Origin protection nếu dùng cookie.

### 9.2 Example proposal

```json
{
  "proposal_id": "eq-20261011-001",
  "scope": "channel",
  "channel_id": "verified-id-from-discovery",
  "source_measurement_id": "measurement-123",
  "expected_revision": 42,
  "hypothesis": "low-mid buildup may reduce clarity",
  "confidence": 0.67,
  "changes": [{"semantic_parameter": "eq.band2.gain_db", "from": 0.0, "to": -1.5}],
  "requires_operator_approval": true,
  "preview_only": true,
  "safety_constraints": {"allow_routing_changes": false, "allow_p16_changes": false},
  "rollback_snapshot_id": "snapshot-456"
}
```

`semantic_parameter` cần adapter X32 ánh xạ sang OSC path thực tế theo firmware, không viết `/ch/...` bừa khi chưa xác nhận.

### 9.3 Monorepo đề nghị

```text
x32-ai-sound-engineer/
  README.md
  docs/
    architecture.md
    osc-protocol-matrix.md
    measurement-sop.md
    feedback-safety.md
    licensing-SBOM.md
    operator-manual-vi.md
    test-plan.md
  apps/
    web/                         # React + TS + visualizations
    api/                         # FastAPI, auth, database, command gate
    capture-agent/               # native audio driver access
  packages/
    x32-osc-adapter/             # protocol + transport + mock
    signal-analysis/             # FFT/PSD/RMS/spectrum
    acoustic-measurement/        # impulse/transfer/coherence
    feedback-detector/           # warning only
    eq-optimizer/                # constrained X32 PEQ mapping
    safety-controller/          # policies + transactions
    ai-copilot/                  # RAG only, no direct OSC write
  configs/
    protected-paths.yaml
    safety-defaults.yaml
    roles-example.yaml
  datasets/
    synthetic/
    anonymized-golden/          # only consented, no private recordings
  integrations/
    osm-import/
    roomeq-cli/
    camilladsp-lab/
    m32-live-console-reference/
  tests/
    unit/
    integration/
    fuzz/
    hardware-in-loop/           # intentionally gated
  deploy/
    docker-compose.yml
    systemd/
    windows-service/
```

---

## 10. UI/UX: GIAO DIỆN TẬP TRUNG VÀO VIỆC CẦN LÀM

### A. Dashboard live

Thanh trên: `Connected / Read-only / Session / Firmware / Audio USB / Safety Lock`. Trung tâm: 32 channel strips với meter, name, role, clip, mute, active; rõ bus MAIN/monitor/P16; không hiện giả trạng thái OK khi thiếu dữ liệu. Cột phải: `3 ưu tiên xử lý`, nguyên nhân/certainty/chứng cứ, nút `Hướng dẫn` và `Preview`. Góc đỏ: `STOP AUTO` luôn hiện.

### B. Mixer Explorer

Mỗi channel: nguồn vật lý, gain (readonly), EQ, comp, gate, sends, mixbus paths, USB capture tap, P16 slots (theo routing đã đọc). Có graph input→output và indicator `không đi FOH` cho DL16 input 11 **chỉ khi có đủ kiểm chứng**. Nút `Export full audit`.

### C. Acoustic Lab

Live spectrum / octave bands / coherence / phase / delay, multi-position measurement manager. A/B frequency curve cùng lúc tại mức nghe tương đương. Chú giải tần số theo bài toán cụ thể, không diễn giải phổ là âm thanh “hay” một cách máy móc.

### D. Guided Calibration

Wizard kiểu checklist: step; bằng chứng còn thiếu; hình bố trí mic/wedge do operator nhập; đánh dấu đo hợp lệ; action đề xuất; mức confidence; A/B; hoàn tác. Không ép kỹ thuật viên đọc bảng thông số khó hiểu.

### E. Knowledge Assistant

Ví dụ câu hỏi:
- “Vì sao lead vocal bị hú khi đứng gần loa trái?” → app so sánh history, mic position, bus/path, confidence, giải thích khả năng có căn cứ.
- “Có cắt 250 Hz không?” → trước hết hỏi/tự kiểm tra loại giọng, profile, đo và A/B; không trả lời mặc định.
- “P16 của ban nhạc có bị ảnh hưởng khi giảm fader FOH không?” → tra tín hiệu tap point từ graph đã xác minh, không tự phỏng đoán.
- “Hãy hướng dẫn chỉnh rõ lời Mục sư” → theo checklist từng bước, lấy mẫu, đề xuất HPF/dynamics bảo thủ.

---

## 11. ROADMAP 8 GIAI ĐOẠN, GATE NGHIỆM THU

### M0 — Requirement & safety baseline

- Chốt X32 firmware, card USB, audio driver, số mic/speaker, input/output map, network, stage plan, operator access.
- Chốt tính năng `read-only first`, protected routing, consent audio policy.
- **Gate:** có audit checklist và kế hoạch rollback; chưa code kết nối live write.

### M1 — OSC adapter và digital twin

- Clone/mở repo tham khảo; tạo mock X32, serialization OSC, readback, heartbeat; query thực trên mixer **read only**.
- Map full config, scene, channels, buses, P16, AES50, FX/returns; export snapshot/diff.
- **Gate:** 0 write trên live; mapping đối chiếu console bằng mẫu từng khối; fallback unknown path = opaque/read-only.

### M2 — Capture & Spectrum

- Capture agent native, route detector pre/post tap, waveforms, RMS/peak/FFT/RTA.
- File WAV test cố định, synthetic sine/sweep/noise, deterministic spectrum tests, channel sync tests.
- **Gate:** sai lệch phổ/tần số trong tolerance xác định, không swap channel, xrun được báo đúng.

### M3 — Operator Guidance + Safe EQ

- Labels voice/band/speech; analysis + suggestion; dry-run/snapshot/apply/readback/rollback.
- Thử nghiệm EQ trên channel phụ/simulator, không tác động FOH/main.
- **Gate:** mọi proposal có bằng chứng, có path whitelist và diff; các thay đổi được readback và rollback chính xác trong simulator; clip/latency invalidation.

### M4 — Feedback Risk Assistant

- Detector dữ liệu multi-frame, phân biệt note/harmonics vs feedback; operator feedback review UI.
- Bộ dataset positive/negative tự tổng hợp và rehearsal recordings có xin phép.
- **Gate:** thống kê precision/recall bằng tập test độc lập; false positives từ sustained notes được đánh giá riêng; không tự notch.

### M5 — Speech/Vocal/Live Mix Pilot

- Điều chỉnh theo segmentation activity, silence-hold, rate-limit, manual touch suspend, freeze on feedback risk.
- A/B rehearsals với ca sĩ/diễn giả; speech intelligibility/loudness metrics là evidence phụ, listening panel là chính.
- **Gate:** không có upward drift khi silence; không đổi tap monitor/P16, không mất chữ đầu/cuối, kỹ thuật viên có quyền STOP.

### M6 — Room Calibration

- Open Sound Meter independent capture + import, traceable measurements, reference quality checks; test RoomEQ optimizer offline.
- Measure multiple positions + holdout, consistency phase, A/B, headroom and no-boost-null.
- **Gate:** không tạo peak boost nguy hiểm; operator nhận thấy giữ chất âm/độ rõ, không làm vùng khác tệ nghiêm trọng.

### M7 — Limited Auto (opt-in)

- Chỉ một loại hành động an toàn được test: ví dụ fader downward-only giới hạn trên một channel lab.
- Chaos testing network drop, app crash, scene change, manual fader touch, P16 route change, firmware change.
- **Gate:** fail closed, mixer vẫn chạy độc lập, stop/undo/restore đạt test acceptance; owner ký duyệt trước live.

### M8 — Multi-site & AI advisor

- Versioned hall profile; report so sánh nhà thờ/điểm nhóm khác nhau, baseline check.
- RAG từ OSC/protocol docs/manuals và SOP nhà thờ; fine-grained access controls.
- **Gate:** AI không thể gửi raw OSC, không bịa trạng thái khi dữ liệu thiếu, có citation/measurement provenance.

**Thứ tự ưu tiên thực dụng:** M1 + M2 + M3 + M4 + M6 là giá trị nhất. M7 chỉ triển khai khi đã có người vận hành được đào tạo và đủ dữ liệu kiểm định.

---

## 12. KIỂM THỬ, QA VÀ TIÊU CHÍ CHẤP NHẬN

| Bộ test | Tình huống | Expected result |
|---|---|---|
| Protocol | OSC malformed/duplicate/delay/reorder | parser không crash; stale state không ghi |
| Mapping | DL16 physical #11 != X32 ch11 | không tự suy luận routing; yêu cầu xác minh |
| Protected route | proposal sửa P16/Ultranet | reject tuyệt đối ở mode normal |
| Audio | sine 100Hz/1k/10k, multi-tone, sweep | FFT peak đúng tolerance được ghi trong test |
| Harmonics | ca sĩ ngân nốt lâu | không đánh nhãn `confirmed feedback` nếu thiếu bằng chứng |
| Acoustic feedback lab | feedback được mô phỏng an toàn trên bản ghi | detector phát cảnh báo, không tự tăng gain |
| Room | deep null trong curve | optimizer không boost null |
| Gain | source silent >30s | fader không tăng vô hạn hoặc nâng noise |
| Dynamics | speech đầu âm tiết/đuôi câu | không gate/chặt mất từ trong listening test |
| Authorization | user Viewer nhấn Apply | 403, no OSC write |
| Drift | manual touch trong lúc đề xuất | abort revision conflict |
| Recovery | app/network crash giữa transaction | no further writes, alert; snapshot available |
| Clock | USB/ref drift hoặc sample drop | invalid measurement, block correction |
| Service | app/host tắt | X32 âm thanh vẫn hoạt động nguyên trạng |

**KPIs nội bộ ban đầu (không bảo đảm trước thử nghiệm):** 100% writes có audit/snapshot; 100% protected OSC paths bị chặn; 0 write OSC trong observe; tất cả proposal có readback; không “confirmed feedback” nếu không có evidence; latency UI hiển thị đủ cho operator nhận biết; dữ liệu đo mất/clock sai phải dừng khuyến nghị ngay. Chỉ đặt KPI precision/recall và gain-before-feedback sau khi có baseline đo thực tế.

### 12.1 Quy trình thử trước giờ lễ

1. Backup scene thật và chụp trạng thái ngoài app.
2. Dùng input/channel không ra FOH, monitor mute, amplifier test ở mức phù hợp.
3. Mỗi phép thử thay đúng một tham số, readback so sánh console.
4. Nghe main/monitor/P16 trước/sau trên loa/tai nghe mức an toàn.
5. Rollback và đối chiếu routing + AUX + talkback + scenes.
6. Đánh dấu operator sign-off; **không** để AI tự chạy khi không có người quan sát.

---

## 13. TRIỂN KHAI VÀ VẬN HÀNH

### 13.1 Khuyến nghị môi trường

**Windows laptop có USB X32**: chạy capture-agent native (driver phù hợp), Python API/React cùng host; Docker chỉ chạy backend/UI khi USB mapping và latency được kiểm chứng. Đây là đường triển khai thử nhanh dễ dùng.

**Linux mini PC**: ALSA/JACK/PipeWire capture có quản lý audio device độc lập, backend FastAPI service, PostgreSQL tùy nhu cầu, UI LAN/VPN. Dell Wyse 5070 phù hợp OSC/UI nhưng cần benchmark cho USB multi-channel, phiên bản CPU và driver thật.

**Production safety**: UPS cho mixer/router/host khi khả thi; API chỉ LAN/VPN; HTTPS, auth, backup hàng ngày; thiết bị demo/simulator trước live hardware. Không để cập nhật Docker tự động trong giờ lễ.

### 13.2 Bảo mật

- Chỉ kết nối mixer qua subnet hạn chế; không port-forward X32 OSC ra Internet.
- Phân quyền `Viewer`, `Sound Tech`, `Engineer`, `Admin`; audit thay đổi với operator identity.
- Tách token/API credential khỏi prompt AI; bảo vệ recordings của giọng hát/bài giảng (xin phép, thời hạn lưu, delete policy).
- Tải mã GitHub có pin commit và scan dependencies; không thực thi installer nguồn lạ trên PC nối mixer live.

---

## 14. DANH SÁCH CÔNG VIỆC CỤ THỂ CHO ANTIGRAVITY / AI CODING AGENT

### 14.1 Project rules (`AGENTS.md` hoặc cấu hình tương đương)

```markdown
# X32 AI Sound Engineer — Mandatory Agent Rules
- NEVER send write OSC to a real mixer in development or tests by default.
- Every hardware integration starts in READ_ONLY_MODE=true.
- All OSC writes pass through server-side safety-controller whitelist.
- Never touch AES50, P16/Ultranet, routing, scene recall, preamp, phantom, main bus without a separate admin maintenance workflow.
- Do not assume physical DL16 input number equals X32 channel or Ultranet slot.
- A proposal is never a command. AI may explain and request approval but cannot directly generate executable OSC writes.
- Validate source tap points and measurement clock before DSP inference.
- Never claim zero feedback risk. Prefer positioning, microphone technique and gain structure to destructive EQ.
- No auto boost while channel is silent; freeze on uncertain meter, route or state.
- Every mutation must have before snapshot, explicit approval, readback, audit, and best-effort rollback.
- Preserve source repo licenses, notices, commit SHA and attribution. Do not copy public code without verified license.
- Unit/integration/simulation tests are required before real-hardware testing.
```

### 14.2 Các prompt phát triển theo sprint

**SPRINT 1 — OSC Digital Twin**

> Xây dựng adapter X32 Python kiểu type-safe. Bắt đầu từ protocol và tools pmaillot/X32-Behringer, kiểm chứng với thư viện wrodie/behringer-mixer. Tạo UDP transport mock, codecs cho int/float/string/blob, subscription manager, heartbeat, state mirror, firmware capabilities; read-only mixer inventory và full snapshot. Viết unit/fuzz tests. Tuyệt đối không write X32 thật. Xuất docs/schema và example dump anonymized.

**SPRINT 2 — Routing Graph & Protected DL16/P16**

> Từ snapshot mixer phát hiện mapping physical→channel→bus/main→AES50/Ultranet/USB. Sinh graph UI rõ nguồn/đích/tap point. Tạo invariant bảo vệ DL16 input #11 chỉ monitor, không FOH **sau khi operator gán đường thực tế**, và cấm thay đổi ULTRANET/P16/AES50 ở mode observe/assist. Tạo tests channel re-patching và routing nonidentity.

**SPRINT 3 — Native Audio DSP Analyzer**

> Xây capture-agent native + file replay với WAV deterministic 44.1/48k, channel map, peak/RMS, FFT/Welch, 1/12-octave RTA, clipping/xrun diagnostics, WebSocket stream. Gắn trạng thái tap pre/post và clock valid. Thêm test sine/multi-tone/white/pink noise, fake drift và no-device failures.

**SPRINT 4 — Constrained Vocal EQ Recommender**

> Tạo module phân tích HPF/PEQ phi phá hủy cho vocal/speech theo đo FFT và metadata mic. Trả evidence + confidence + A/B simulated frequency response + proposed diff. Không ghi OSC trong analyzer. Chỉ apply qua safety-controller sau explicit approval, revision precondition, whitelisted channel paths, readback và rollback simulator.

**SPRINT 5 — Feedback Risk Detector**

> Thiết kế detector đa bằng chứng: narrowband growth, persistence, pitch/harmonic checks, cross-channel context. Xây bộ synthetic dataset voice sustain, organ/sine, real feedback simulation (file offline only). Xuất probability cùng caveat, không tự notch. Thêm alert UI và evaluation confusion matrix trên holdout.

**SPRINT 6 — Acoustic Measurement Wizard**

> Import OSM WAV/CSV/measurement, metadata calibration/reference position/clock; tính H1/coherence/delay với tests; từ multiple positions tạo PEQ proposal hạn chế boosts, no deep-null inversion. Triển khai A/B và export report measurement. Không thay đổi speaker DSP/main cho đến khi engineer duyệt.

**SPRINT 7 — Limited Automixer Lab**

> Đọc nghiên cứu M32LiveConsoleTool; tạo fader rider trên simulator có voice activity/silence-hold/hysteresis/slew limits/manual touch freeze. Default no upward write. Thử mismatch meter, disconnect, stale state, feedback alarm, scene change. Không triển khai production cho đến khi nghiệm thu.

### 14.3 Tiêu chí “Definition of Done” mỗi sprint

Mỗi sprint bắt buộc có: `design.md`, API/schema, coverage test quan trọng, screenshot UI/demo, event logs có timestamp, hướng dẫn chạy Windows/Linux, license-SBOM và `KNOWN_LIMITATIONS.md`; nêu rõ chức năng nào đã test trên simulator và chức năng nào **chưa** test trên X32 thật.

---

## 15. KẾ HOẠCH KHẢO SÁT HIỆN TRƯỜNG: PHẢI THU THẬP GÌ?

Giao diện inventory/wizard sẽ yêu cầu nhưng **không bắt người dùng cung cấp hết trước khi bắt đầu coding**:

- X32 Compact firmware, IP LAN, sample rate/clock source, card USB đang có.
- X32 Show/Scene snapshot; input/output routing screenshot/export nếu OSC chưa đọc đủ.
- Danh sách micro (dynamic/condenser, model, vị trí), số ca sĩ, người giảng, DI/instruments.
- Main L/R đi qua thiết bị nào trước khi tới loa? model loa/sub, ampli/DSP, vị trí loa, số zones.
- Wedge floor monitor nào có mặt, kết nối bus nào? P16-HQ chỉ dùng headphone/IEM hay còn nối active speaker?
- Bản đồ hội trường/ghế/chỗ ban nhạc, vị trí mic hát/mic giảng, khoảng cách loa.
- Mic đo và calibration file nếu đã có; audio interface/reference clock nếu đo phase/delay.
- Policy: ai có quyền apply, khi nào được thử noise/sweep, giờ tập/giờ lễ, âm lượng tối đa an toàn.
- Xác nhận chính xác route DL16 **input 11** và các slot ULTRANET được cấp cho P16.

---

## 16. CHI PHÍ VÀ ƯU TIÊN MUA SẮM

Không ghi giá tiền cố định vì giá theo thị trường Việt Nam thay đổi; kiểm tra báo giá thật khi mua.

| Nhóm | Mức độ | Khuyến nghị |
|---|---|---|
| Host hiện có | Có thể tái sử dụng | Windows laptop/PC có USB X32; Wyse 5070 cho OSC/web nếu benchmark qua |
| Router/switch LAN | Cần | Ethernet ổn định riêng hoặc segment quản lý, không cần cloud |
| X32 USB card | Cần cho phân tích đa kênh | Xác minh card đang lắp trước khi mua |
| Measurement mic + chân | Nên có | Dùng mic có calibration individual file; với mic XLR cần phantom/interface phù hợp |
| Audio reference/loopback | Quan trọng cho phase/delay | Cùng clock để đo transfer chuẩn xác |
| Sound level meter | Tùy mức QA | Máy đo SPL hiệu chuẩn cho giới hạn SPL theo quy định/tiêu chuẩn áp dụng |
| AI GPU/model server | Không cần MVP | Chỉ bổ sung khi làm RAG/cố vấn offline; DSP hoạt động độc lập AI |

**Tối ưu ngân sách:** ưu tiên micro đo kiểm + capture/reference ổn định hơn mua GPU. Không mua DSP xử lý live ngoài mixer nếu mục tiêu hiện tại là tư vấn/chỉnh EQ X32 có kiểm soát.

---

## 17. RỦI RO CẦN BÁO TRƯỚC

| Rủi ro | Giải pháp |
|---|---|
| Tự động cắt EQ gây mỏng giọng | A/B loudness matched, notch tối thiểu, review giọng thật |
| FFT nhầm nốt nhạc thành hú | đa-frame + harmonic classifier + cross-signal + human approval |
| Auto gain đẩy ồn/hú | no boost silence, activity gate, downward-only pilot |
| Điều khiển X32 làm sai monitor | routing invariant và P16/AES50 deny-list |
| OSC stale/hụt packet | heartbeat, timeout, readback, STOP AUTO |
| USB capture không khớp X32 channel | explicit channel mapping và injected test tone ở mức an toàn/lab |
| Measurement phase sai clock | reference chung clock hoặc công cụ drift handling đã xác minh |
| Hiệu chuẩn 1 điểm phá nhiều ghế | multi-position average + holdout validation |
| Đòi “không hú tuyệt đối” | đánh giá margin/điều kiện, bố trí vật lý, training operator |
| GPL/MIT bị dùng sai | SBOM, pinned licenses, independent tools khi thích hợp |
| AI bịa config | trạng thái chỉ từ OSC verified, provenance + confidence, không raw write |

---

## 18. TÀI LIỆU GỐC VÀ GHI CHÚ XÁC MINH

Tổng hợp từ README và trang repo được truy cập ngày **11/10/2026**; kiểm tra lại commit, LICENSE và releases khi bắt đầu tích hợp. Danh sách sau đủ để Antigravity truy cập trực tiếp:

1. X32 OSC utilities + tài liệu Patrick-Gilles Maillot: https://github.com/pmaillot/X32-Behringer và https://sites.google.com/site/patrickmaillot/x32
2. Python adapter Behringer/X32, MIT: https://github.com/wrodie/behringer-mixer
3. M32/X32 auto-level + simulator, MIT: https://github.com/CristianMoresi/M32LiveConsoleTool
4. Open Sound Meter desktop (GPL-3): https://github.com/psmokotnin/osm và https://github.com/psmokotnin/osm/releases
5. RoomEQ/AutoEQ Rust CLI: https://github.com/pierreaubert/autoeq
6. CamillaDSP DSP engine: https://github.com/HEnquist/camilladsp
7. Headphone AutoEq optimizer (MIT): https://github.com/jaakkopasanen/AutoEq
8. Alternative Python X32 repo (license must be verified): https://github.com/tjoracoder/python-x32

**Đã trực tiếp xác minh qua trang GitHub:** M32LiveConsoleTool hỗ trợ auto leveling/anti clipping/simulator với MIT; wrodie/behringer-mixer MIT chủ yếu fader/mute/scene và một số headamp controls; OSM có bản desktop GPL-3 và Remote API chia sẻ dữ liệu; CamillaDSP có dual license với caveat ASIO; RoomEQ có CLI xuất cấu hình REW/coefficients. **Chưa xác minh:** giao thức Remote API của OSM bản triển khai cụ thể, định dạng OSC/routing theo firmware mixer của nhà thờ, khả năng áp dụng filter RoomEQ đủ fidelity trong X32, license của một số repo khi copy code, các thông số âm học thực tế của phòng.

---

## 19. QUYẾT ĐỊNH KIẾN TRÚC CHỐT

**Nên bắt đầu ngay bằng read-only X32 + full routing audit + USB RTA.** Chỉ khi xác minh đường tín hiệu và lưu an toàn toàn bộ trạng thái mới mở tính năng đề xuất/áp EQ từng kênh. Chống hú dựa trên **micro placement + gain structure + multi-evidence detector + tối thiểu notch khi thật sự cần**, không dùng auto notch vô tội vạ. Đo loa bằng **measurement mic + reference + nhiều điểm**, tối ưu bảo toàn âm sắc chứ không ép phẳng FFT. Tách AI giải thích ra khỏi DSP và controller. Giữ nguyên X32→DL16→P16-D→P16-HQ; routing micro DL16 input 11 chỉ monitor phải là một invariant có kiểm chứng.

**Kết quả mong đợi:** Một trợ lý kỹ thuật nhà thờ hướng dẫn người chỉnh âm thanh từ kiểm tra dây/micro → đo tần số → phát hiện rủi ro hú → đề xuất chỉnh EQ/comp/fader → nghe kiểm tra → lưu profile → báo cáo, theo cách an toàn và khả thi để phát triển từng giai đoạn.
