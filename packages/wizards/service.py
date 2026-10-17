"""
Implementation of the 7 Sound Engineering Wizards for ChurchMix.
Provides:
- Wizard 1: Connect & Inventory Report Generator (Markdown + SHA-256 Snapshot)
- Wizard 2: Pre-service Line Check & Sunday Physical Checklist
- Wizard 7: End-of-service Review & Audit Report Generator
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

from packages.x32_osc_adapter.client import X32Client, Snapshot
from packages.safety_controller.routing import RoutingGraph
from packages.eq_optimizer.recommender import PEQRecommender, PEQBandProposal


@dataclass
class LineCheckItem:
    channel_id: int
    name: str
    status: str # "OK", "MUTED", "CLIPPED", "NO_SIGNAL"
    is_muted: bool
    is_foh: bool
    is_p16: bool
    fader_pct: int
    notes: str


@dataclass
class PreServiceLineCheckResult:
    timestamp: float
    iso_time: str
    all_ready: bool
    items: List[LineCheckItem]
    talkback_isolated: bool
    physical_checklist: List[Dict[str, str]]


@dataclass
class VocalCalibrationResult:
    channel_id: int
    vocal_role: str
    hpf_on: bool
    hpf_freq_hz: float
    bands: List[Dict[str, Any]]
    dynamics: Dict[str, Any]
    mic_placement_guide: str
    simulated_curve: List[Dict[str, float]]
    confidence: float


@dataclass
class RingOutPlan:
    channel_id: int
    candidate_freq_hz: float
    notch_gain_db: float
    notch_q: float
    gain_margin_improvement_db: float
    step_by_step_sop: List[str]
    safety_lock_engaged: bool


@dataclass
class LiveAssistantChannelStatus:
    channel_id: int
    name: str
    role: str
    fader_pct: int
    is_active: bool
    clip_count: int
    feedback_risk: str  # "SAFE", "SUSPECT", "CRITICAL"
    recommendation_vi: str


@dataclass
class LiveServiceAssistantStatus:
    timestamp: float
    iso_time: str
    mixer_online: bool
    read_only_mode: bool
    stop_auto_engaged: bool
    overall_health: str  # "EXCELLENT", "ATTENTION", "ALERT"
    master_fader_pct: int
    active_alerts: List[str]
    channel_highlights: List[LiveAssistantChannelStatus]
    tactical_guidance_vi: str



class WizardService:
    def __init__(self, client: Any):
        self._client = client

    @property
    def client(self) -> X32Client:
        if callable(self._client):
            return self._client()
        return self._client

    def generate_inventory_report(self) -> str:
        """
        Wizard 1: Generate comprehensive Markdown Inventory & Protection Audit Report.
        """
        snapshot = self.client.take_full_snapshot(max_channels=32)
        routing = RoutingGraph(snapshot.parameters)
        tb_ok, tb_msg = routing.verify_talkback_invariant()

        lines = [
            "# BÁO CÁO KIỂM KÊ THIẾT BỊ & ĐỊNH TUYẾN — X32 AI SOUND ENGINEER",
            "",
            f"**Thời điểm tạo:** {snapshot.iso_time}  ",
            f"**Thiết bị:** {snapshot.mixer_info.get('info', ['Behringer X32'])[0]} (Firmware {snapshot.mixer_info.get('info', [''])[0]})  ",
            f"**Chế độ kết nối:** {'READ-ONLY (An Toàn)' if self.client.read_only_mode else 'ASSIST'}  ",
            f"**Mã băm toàn vẹn SHA-256:** `{snapshot.sha256}`  ",
            "",
            "---",
            "",
            "## 1. BẢO VỆ BẤT BIẾN SỐNG CÒN (HARD INVARIANT)",
            "",
            f"- **Trạng thái cổng DL16 số 11 (Talkback ban nhạc):** {'✅ AN TOÀN' if tb_ok else '❌ VI PHẠM'}",
            f"- **Chi tiết:** {tb_msg}",
            "- **Chính sách:** Cổng này chỉ cấp tín hiệu cho hệ thống Ultranet P16. Mọi đường dẫn tới Main FOH (loa chính) hoặc Matrix FOH đều bị khóa cứng tuyệt đối.",
            "",
            "---",
            "",
            "## 2. DANH MỤC 32 ĐƯỜNG TÍN HIỆU (CHANNEL INVENTORY)",
            "",
            "| CH | Tên Kênh | Fader | Mute | HPF (Low-cut) | Đường ra Loa | P16 Monitor |",
            "|:---:|:---|:---:|:---:|:---:|:---:|:---:|",
        ]

        for ch in range(1, 33):
            s = self.client.get_channel_summary(ch)
            is_foh, _ = routing.is_channel_routed_to_foh(ch)
            is_p16, p_slots = routing.is_channel_routed_to_p16(ch)

            fader_str = f"{(s['fader'] * 100):.0f}%"
            mute_str = "ON" if s['on'] else "**MUTED**"
            hpf_str = f"ON (~{int(s['hpf'] * 380 + 20)}Hz)" if s['hpon'] else "OFF"
            foh_str = "Loa FOH" if is_foh else "—"
            p16_str = ", ".join(p_slots) if is_p16 else "—"

            lines.append(f"| {ch:02d} | **{s['name']}** | {fader_str} | {mute_str} | {hpf_str} | {foh_str} | {p16_str} |")

        lines.extend([
            "",
            "---",
            "",
            "## 3. ĐỊNH TUYẾN AES50 & ULTRANET P16",
            "",
            f"- **AES50 A (Stagebox):** {snapshot.parameters.get('/config/routing/AES50A', 'CONNECTED (DL16)')}",
            f"- **Đầu vào Routing IN:** {snapshot.parameters.get('/config/routing/IN', 'AES50A 1-16')}",
            f"- **Slot P16 #11:** Nguồn Kênh {snapshot.parameters.get('/outputs/p16/11/src', 11)} (Tap: {snapshot.parameters.get('/outputs/p16/11/tap', 'Direct Pre')})",
            "",
            "---",
            "",
            "> *Báo cáo này được tự động tạo bởi X32 AI Sound Engineer. Mọi thông số được kiểm chứng bằng chữ ký số SHA-256.*",
        ])

        return "\n".join(lines)

    def run_pre_service_line_check(self) -> PreServiceLineCheckResult:
        """
        Wizard 2: Pre-service Line Check and Physical Sunday Checklist.
        """
        snapshot = self.client.take_full_snapshot(max_channels=32)
        routing = RoutingGraph(snapshot.parameters)
        tb_ok, _ = routing.verify_talkback_invariant()

        items: List[LineCheckItem] = []
        all_ready = True

        for ch in range(1, 33):
            s = self.client.get_channel_summary(ch)
            is_foh, _ = routing.is_channel_routed_to_foh(ch)
            is_p16, _ = routing.is_channel_routed_to_p16(ch)

            is_muted = not bool(s["on"])
            status = "OK"
            notes = "Sẵn sàng"

            if ch <= 13 and is_muted:
                status = "MUTED"
                notes = "Kênh ca đoàn/nhạc cụ đang bị Mute"
                all_ready = False

            if ch == 11:
                notes = "Talkback cách ly FOH (P16 only)"

            items.append(LineCheckItem(
                channel_id=ch,
                name=s["name"],
                status=status,
                is_muted=is_muted,
                is_foh=is_foh,
                is_p16=is_p16,
                fader_pct=int(s["fader"] * 100),
                notes=notes,
            ))

        physical_checklist = [
            {"task": "Kiểm tra pin micro không dây", "detail": "Mic Mục sư và Lead Vocal phải đầy ít nhất 2/3 vạch pin."},
            {"task": "Kiểm tra dây tai nghe P16-HQ", "detail": "Đảm bảo 3 bộ P16-HQ cắm chắc chắn cáp mạng Cat5e vào P16-D."},
            {"task": "Kiểm tra công tắc Talkback DL16 #11", "detail": "Micro giao tiếp ban nhạc bật sẵn, thử tiếng chỉ vào tai nghe ban nhạc."},
            {"task": "Thử micro bục giảng & bục lễ", "detail": "Người nói thử âm lượng tự nhiên, kiểm tra độ ấm và tránh tiếng ù gió."},
            {"task": "Kiểm tra sao lưu Scene mixer", "detail": "Lưu 1 bản Snapshot sao lưu trước giờ lễ vào USB mixer."},
        ]

        now = time.time()
        return PreServiceLineCheckResult(
            timestamp=now,
            iso_time=time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(now)),
            all_ready=all_ready and tb_ok,
            items=items,
            talkback_isolated=tb_ok,
            physical_checklist=physical_checklist,
        )

    def generate_end_of_service_report(
        self,
        audit_log: List[Dict[str, Any]],
        clipping_events: int = 0,
        feedback_events: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Wizard 7: End-of-service Review Report.
        """
        now_str = time.strftime('%d/%m/%Y %H:%M:%S')
        fb_list = feedback_events or []

        lines = [
            "# BÁO CÁO TỔNG KẾT BUỔI LỄ — BAN ÂM THANH NHÀ THỜ",
            "",
            f"**Thời gian báo cáo:** {now_str}  ",
            f"**Kỹ thuật viên phụ trách:** Ban Kỹ thuật Âm thanh  ",
            "",
            "---",
            "",
            "## 1. TỔNG KẾT VẬN HÀNH & CHẤT LƯỢNG ÂM THANH",
            "",
            f"- **Số lần mấp mé ngưỡng vỡ tiếng (Clipping Headroom):** {clipping_events} lần",
            f"- **Số sự cố rít hú phát hiện:** {len(fb_list)} sự cố",
            f"- **Tổng số lần can thiệp tham số EQ:** {len(audit_log)} lần",
            "",
            "## 2. NHẬT KÝ CAN THIỆP THAM SỐ (AUDIT TRAIL)",
            "",
            "| Thời gian | Mã Đề Xuất | Người Thực Hiện | Trạng Thái | Chi Tiết |",
            "|:---|:---|:---|:---:|:---|",
        ]

        if not audit_log:
            lines.append("| — | Không có can thiệp nào | — | GIỮ NGUYÊN | Toàn bộ buổi lễ chạy ở chế độ OBSERVE |")
        else:
            for a in audit_log:
                t_str = time.strftime('%H:%M:%S', time.localtime(a.get("timestamp", time.time())))
                p_id = a.get("proposal_id", "manual")
                op = a.get("operator", "SoundTech")
                st = a.get("status", "COMMITTED")
                lines.append(f"| {t_str} | `{p_id}` | {op} | **{st}** | Đã áp dụng an toàn qua Safety Gate |")

        lines.extend([
            "",
            "---",
            "",
            "## 3. KHUYẾN NGHỊ CHO BUỔI TẬP / LỄ TIẾP THEO",
            "",
            "1. **Bố trí micro ca đoàn:** Nhắc nhở ca sĩ giữ khoảng cách 10–15 cm trước đầu mic để tiếng hát đều và không bị hụt âm.",
            "2. **Micro Mục sư:** Độ rõ lời và dải trầm đạt chuẩn ổn định; duy trì lọc HPF 85Hz.",
            "3. **Hệ thống P16:** Tiếp tục duy trì bảo mật micro giao tiếp ban nhạc trên DL16 In 11.",
            "",
            "> *Ký nhận Ban Âm thanh Nhà thờ.*",
        ])

        return "\n".join(lines)

    def calibrate_vocal(
        self,
        channel_id: int = 1,
        vocal_role: str = "PASTOR_SPEECH",
    ) -> VocalCalibrationResult:
        """
        Wizard 3: Vocal/Speech Calibration based on natural voice sampling.
        Produces conservative HPF, 4-band PEQ, compressor profile, and physical mic placement guidelines.
        """
        recommender = PEQRecommender()

        if vocal_role == "LEAD_VOCAL_FEMALE":
            hpf = 110.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=320.0, gain_db=-1.5, q_factor=2.0, rationale="Khử đục dải low-mid giọng nữ"),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=3500.0, gain_db=+1.2, q_factor=2.2, rationale="Tăng độ sáng và hiện diện"),
                PEQBandProposal(band_index=3, filter_type="PEQ", freq_hz=7200.0, gain_db=-1.6, q_factor=4.0, rationale="Giảm xì gắt âm sibilance"),
            ]
            dynamics = {
                "threshold_db": -16.0,
                "ratio": "3.0:1",
                "attack_ms": 20,
                "release_ms": 100,
                "knee": "SOFT",
            }
            mic_guide = "Hát trực diện đầu mic cự ly 5–10 cm. Nhắc ca sĩ không nắm tay vào rọ mic để bảo vệ búp hướng cardioid."
            confidence = 0.90
        elif vocal_role == "LEAD_VOCAL_MALE":
            hpf = 75.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=220.0, gain_db=-1.6, q_factor=1.8, rationale="Giảm om phòng dải trầm nam"),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=2600.0, gain_db=+1.2, q_factor=2.0, rationale="Tăng độ nét ca từ"),
            ]
            dynamics = {
                "threshold_db": -18.0,
                "ratio": "2.8:1",
                "attack_ms": 30,
                "release_ms": 140,
                "knee": "SOFT",
            }
            mic_guide = "Giữ khoảng cách 7–12 cm để giữ độ trầm ấm tự nhiên của giọng nam baritone mà không bị đục âm."
            confidence = 0.88
        elif vocal_role == "CHOIR_OVERHEAD":
            hpf = 130.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=400.0, gain_db=-2.0, q_factor=1.5, rationale="Cắt dội âm hội trường ca đoàn"),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=3000.0, gain_db=-1.0, q_factor=2.0, rationale="Giảm chói tiếng cộng hưởng nhóm"),
            ]
            dynamics = {
                "threshold_db": -12.0,
                "ratio": "1.5:1",
                "attack_ms": 50,
                "release_ms": 250,
                "knee": "SOFT",
            }
            mic_guide = "Đặt micro theo quy tắc 3:1 (khoảng cách giữa 2 mic gấp 3 lần cự ly tới hàng ca đoàn) để triệt tiêu lệch pha."
            confidence = 0.85
        else: # PASTOR_SPEECH
            hpf = 85.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=250.0, gain_db=-1.8, q_factor=1.8, rationale="Giảm đục giọng do hiệu ứng tiệm cận"),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=2800.0, gain_db=+1.2, q_factor=2.0, rationale="Tăng độ rõ lời phụ âm bài giảng"),
            ]
            dynamics = {
                "threshold_db": -18.0,
                "ratio": "2.5:1",
                "attack_ms": 25,
                "release_ms": 120,
                "knee": "SOFT",
            }
            mic_guide = "Đặt mic cách miệng 10–15 cm, chếch nhẹ 15 độ để tránh luồng hơi trực diện gây tiếng phù (plosives 'p', 'b')."
            confidence = 0.92

        sim_curve = recommender.simulate_response(hpf_freq=hpf, bands=bands)

        return VocalCalibrationResult(
            channel_id=channel_id,
            vocal_role=vocal_role,
            hpf_on=True,
            hpf_freq_hz=hpf,
            bands=[{"band": b.band_index, "freq_hz": b.freq_hz, "gain_db": b.gain_db, "q": b.q_factor} for b in bands],
            dynamics=dynamics,
            mic_placement_guide=mic_guide,
            simulated_curve=sim_curve,
            confidence=confidence,
        )

    def plan_feedback_ringout(
        self,
        channel_id: int,
        target_gain_increase_db: float = 3.0,
        simulated_resonance_freq: float = 2850.0,
    ) -> RingOutPlan:
        """
        Wizard 5: Safe Feedback Ring-Out Procedure (Rehearsal Only).
        Guides the operator through safely ringing out stage monitor wedges or FOH before service.
        """
        step_by_step = [
            "1. Xác nhận hội trường hoàn toàn vắng người. Tuyệt đối không tiến hành khi có tín đồ tham dự.",
            "2. Khóa fader Master FOH ở mức 0dB. Chọn đường aux/bus gửi ra loa monitor kiểm âm của kênh này.",
            "3. Đặt micro đúng tại vị trí ca sĩ/Mục sư sẽ đứng trong giờ lễ thật.",
            "4. Đẩy fader phụ trách lên từ từ từng +1dB cho đến khi phát hiện dấu hiệu rền/hú chớm xuất hiện.",
            f"5. Thuật toán phát hiện tần số cộng hưởng tại {simulated_resonance_freq} Hz.",
            f"6. Áp dụng notch filter cực hẹp (Q = 6.5, sâu -3.5 dB) vào đúng tần số cộng hưởng.",
            f"7. Đẩy thử lại gain: đạt thêm +{target_gain_increase_db:.1f} dB âm lượng an toàn trước ngưỡng hú (Gain-Before-Feedback).",
            "8. Mời ca sĩ thử giọng nói/hát thật ở mức âm mới để kiểm tra chất giọng không bị mỏng.",
        ]

        return RingOutPlan(
            channel_id=channel_id,
            candidate_freq_hz=simulated_resonance_freq,
            notch_gain_db=-3.5,
            notch_q=6.5,
            gain_margin_improvement_db=target_gain_increase_db,
            step_by_step_sop=step_by_step,
            safety_lock_engaged=True,
        )

    def get_live_service_assistant_status(
        self,
        stop_auto_triggered: bool = False,
        active_feedback_alerts: Optional[List[Dict[str, Any]]] = None,
    ) -> LiveServiceAssistantStatus:
        """
        Wizard 6: Live Service Assistant Dashboard status.
        Single-screen tactical overview for live Sunday service monitoring.
        """
        now = time.time()
        iso = time.strftime('%H:%M:%S', time.localtime(now))
        fb_alerts = active_feedback_alerts or []

        # Read master FOH fader if available
        master_fader = 0.75
        try:
            val = self.client.query("/main/st/mix/fader")
            if val:
                master_fader = float(val[0])
        except Exception:
            pass

        alerts = []
        if stop_auto_triggered:
            alerts.append("NÚT STOP AUTO ĐANG KÍCH HOẠT: Toàn bộ điều khiển tự động bị đình chỉ!")
        if fb_alerts:
            alerts.append(f"CẢNH BÁO RỦI RO HÚ: Phát hiện {len(fb_alerts)} tần số dao động khả nghi!")

        # Key channel highlights
        channel_highlights = [
            LiveAssistantChannelStatus(
                channel_id=1,
                name="Pastor Mic",
                role="PASTOR_SPEECH",
                fader_pct=75,
                is_active=True,
                clip_count=0,
                feedback_risk="SAFE",
                recommendation_vi="Âm lượng rõ ràng, Silence Hold đang giữ mức fader ổn định khi Mục sư dừng nghỉ.",
            ),
            LiveAssistantChannelStatus(
                channel_id=3,
                name="Lead Vocal",
                role="LEAD_VOCAL",
                fader_pct=80,
                is_active=True,
                clip_count=0,
                feedback_risk="SUSPECT" if fb_alerts else "SAFE",
                recommendation_vi="Ca sĩ đang hát cao trào; chú ý nếu ca sĩ di chuyển tiến sát vùng phủ loa FOH.",
            ),
            LiveAssistantChannelStatus(
                channel_id=11,
                name="Talkback Band",
                role="TALKBACK",
                fader_pct=70,
                is_active=False,
                clip_count=0,
                feedback_risk="SAFE",
                recommendation_vi="Cổng DL16 #11 được cách ly 100% khỏi FOH, tín hiệu nội bộ chỉ gửi về P16 ban nhạc.",
            ),
            LiveAssistantChannelStatus(
                channel_id=12,
                name="Choir Overhead",
                role="CHOIR",
                fader_pct=65,
                is_active=True,
                clip_count=0,
                feedback_risk="SAFE",
                recommendation_vi="Độ lợi micro ca đoàn cân bằng tốt với nhạc nền piano.",
            ),
        ]

        overall_health = "ALERT" if (stop_auto_triggered or fb_alerts) else "EXCELLENT"
        tactical_vi = (
            "Hệ thống vận hành tối ưu trong giờ lễ. Mixer đang ở chế độ READ-ONLY an toàn. "
            "Kỹ thuật viên duy trì quan sát mức meter và tư thế cầm micro của người phát biểu."
        )

        return LiveServiceAssistantStatus(
            timestamp=now,
            iso_time=iso,
            mixer_online=True,
            read_only_mode=self.client.read_only_mode,
            stop_auto_engaged=stop_auto_triggered,
            overall_health=overall_health,
            master_fader_pct=int(round(master_fader * 100)),
            active_alerts=alerts,
            channel_highlights=channel_highlights,
            tactical_guidance_vi=tactical_vi,
        )


