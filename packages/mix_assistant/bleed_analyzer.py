"""
ChurchMix Stage Bleed & Acoustic Cross-Talk Advisor.
===================================================
Analyzes microphone cross-talk, stage bleed (drums, guitar amplifiers, wedge monitors)
into vocal and speech microphones, and calibrates transparent Downward Expanders on X32.

Key Invariants & Capabilities:
1. Cross-Channel Correlation Analysis:
   - Measures cross-correlation and relative energy between vocal mics and stage instruments.
   - Detects comb-filtering and phase cancellation caused by stage bleed.
2. Transparent Downward Expander Calibration:
   - Unlike an aggressive Noise Gate that abruptly chops word endings and breath,
     church vocals require a gentle Downward Expander (Range 6 dB to 14 dB).
   - Optimizes Expander Threshold = Noise Floor + 3 dB safety buffer.
   - Recommends Key Sidechain Filter (HPF ~250 Hz) to ignore low stage rumbles.
3. Hard Safety Invariant Protection:
   - DL16 In 11 (Band Talkback) is strictly forbidden from triggering or entering
     the expander system on FOH channels.
"""
from __future__ import annotations
import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from packages.safety_controller.transaction import Proposal
from packages.safety_controller.routing import InvariantViolationError, get_talkback_channel


@dataclass
class ExpanderSettings:
    enabled: bool = True
    mode: int = 0 # 0 = Expander (gentle), 1 = Gate (hard cut), 2 = Duck
    threshold_dbfs: float = -52.0
    threshold_x32: float = 0.35 # Normalized 0.0 to 1.0 (-80 dB to 0 dB)
    range_db: float = 10.0 # 6 dB - 14 dB gentle attenuation
    range_x32: float = 0.167 # Normalized 0.0 to 1.0 (0 dB to 60 dB)
    attack_ms: float = 2.0
    hold_ms: float = 80.0
    release_ms: float = 350.0 # Smooth, musical release
    filter_on: bool = True
    filter_type: int = 1 # High-Pass
    filter_freq_hz: float = 250.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrossTalkReport:
    channel_id: int
    channel_name: str
    role: str
    bleed_source_channel_id: Optional[int]
    bleed_source_name: Optional[str]
    correlation_coeff: float # -1.0 to 1.0
    relative_bleed_level_db: float # Level of bleed relative to vocal direct signal
    comb_filtering_risk: str # LOW | MODERATE | HIGH | SEVERE
    phase_alignment_status: str # IN_PHASE | REVERSED_PHASE | DECORRELATED
    ambient_noise_floor_dbfs: float
    recommended_expander: ExpanderSettings
    advice_vi: str
    talkback_safe: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["recommended_expander"] = self.recommended_expander.to_dict()
        return d


class StageBleedAdvisor:
    """
    Advisor for analyzing stage microphone bleed and formulating X32 Downward Expander proposals.
    """

    @classmethod
    def db_to_gate_thr(cls, db: float) -> float:
        """Map dBFS (-80 to 0) to X32 normalized float 0.0 to 1.0."""
        clamped = max(-80.0, min(0.0, db))
        return round((clamped + 80.0) / 80.0, 3)

    @classmethod
    def gate_thr_to_db(cls, val: float) -> float:
        """Map X32 normalized float 0.0 to 1.0 to dBFS (-80 to 0)."""
        clamped = max(0.0, min(1.0, val))
        return round(-80.0 + (clamped * 80.0), 1)

    @classmethod
    def db_to_gate_range(cls, db: float) -> float:
        """Map attenuation range in dB (0 to 60) to X32 normalized float 0.0 to 1.0."""
        clamped = max(0.0, min(60.0, db))
        return round(clamped / 60.0, 3)

    @classmethod
    def gate_range_to_db(cls, val: float) -> float:
        """Map X32 normalized float 0.0 to 1.0 to attenuation range in dB (0 to 60)."""
        clamped = max(0.0, min(1.0, val))
        return round(clamped * 60.0, 1)

    @classmethod
    def analyze_cross_talk(
        cls,
        target_signal: np.ndarray,
        target_channel: int,
        target_name: str,
        target_role: str,
        stage_signals: Optional[Dict[int, Tuple[str, np.ndarray]]] = None,
    ) -> CrossTalkReport:
        """
        Analyze stage bleed into target channel from other stage microphone signals.
        """
        # Hard Invariant: Channel 11 must never be processed as an ordinary FOH channel
        if target_channel == get_talkback_channel():
            raise InvariantViolationError(
                "HARD SAFETY INVARIANT: Channel 11 (Band Talkback) is strictly isolated and cannot be analyzed for FOH bleed."
            )

        # 1. Compute target RMS and noise floor
        target_rms = float(np.sqrt(np.mean(target_signal ** 2))) if len(target_signal) > 0 else 1e-6
        target_rms_dbfs = 20.0 * math.log10(max(1e-6, target_rms))

        # Estimate noise floor (10th percentile energy)
        frame_size = 512
        num_frames = len(target_signal) // frame_size
        if num_frames > 2:
            frame_energies = [
                float(np.sqrt(np.mean(target_signal[i * frame_size : (i + 1) * frame_size] ** 2)))
                for i in range(num_frames)
            ]
            noise_floor_rms = float(np.percentile(frame_energies, 10))
        else:
            noise_floor_rms = target_rms * 0.1

        noise_floor_dbfs = round(20.0 * math.log10(max(1e-6, noise_floor_rms)), 1)
        # Clamp to realistic church stage range
        noise_floor_dbfs = max(-75.0, min(-45.0, noise_floor_dbfs))

        # 2. Check cross-correlation with stage signals (e.g. Drums / Amps / Choir)
        max_corr = 0.0
        primary_bleed_ch = None
        primary_bleed_name = None
        bleed_level_rel_db = -30.0

        if stage_signals:
            for s_ch, (s_name, s_sig) in stage_signals.items():
                if s_ch == target_channel or s_ch == get_talkback_channel():
                    continue # Skip self and talkback

                min_len = min(len(target_signal), len(s_sig))
                if min_len < 128:
                    continue

                sig_a = target_signal[:min_len]
                sig_b = s_sig[:min_len]

                norm_a = np.linalg.norm(sig_a)
                norm_b = np.linalg.norm(sig_b)
                if norm_a > 1e-6 and norm_b > 1e-6:
                    corr = float(np.dot(sig_a, sig_b) / (norm_a * norm_b))
                    corr_abs = abs(corr)
                    if corr_abs > abs(max_corr):
                        max_corr = corr
                        primary_bleed_ch = s_ch
                        primary_bleed_name = s_name

                        s_rms = float(np.sqrt(np.mean(sig_b ** 2)))
                        # Estimate bleed level relative to target
                        bleed_level_rel_db = round(20.0 * math.log10(max(1e-6, s_rms / max(1e-6, target_rms))), 1)

        # 3. Classify comb-filtering and phase risk
        abs_corr = abs(max_corr)
        if abs_corr >= 0.70 and bleed_level_rel_db > -12.0:
            comb_risk = "SEVERE"
        elif abs_corr >= 0.45 and bleed_level_rel_db > -18.0:
            comb_risk = "HIGH"
        elif abs_corr >= 0.25:
            comb_risk = "MODERATE"
        else:
            comb_risk = "LOW"

        if max_corr < -0.30:
            phase_status = "REVERSED_PHASE"
        elif max_corr > 0.30:
            phase_status = "IN_PHASE"
        else:
            phase_status = "DECORRELATED"

        # 4. Formulate optimal Downward Expander parameters
        # Threshold: set 3 dB above ambient noise floor
        exp_thr_db = min(-42.0, max(-65.0, noise_floor_dbfs + 3.0))
        # Range: gentle 8 dB to 12 dB attenuation to preserve natural acoustics
        exp_range_db = 12.0 if comb_risk in ("HIGH", "SEVERE") else 8.0

        exp_settings = ExpanderSettings(
            enabled=True,
            mode=0, # 0 = Expander
            threshold_dbfs=round(exp_thr_db, 1),
            threshold_x32=cls.db_to_gate_thr(exp_thr_db),
            range_db=round(exp_range_db, 1),
            range_x32=cls.db_to_gate_range(exp_range_db),
            attack_ms=2.0, # Fast opening
            hold_ms=80.0,
            release_ms=350.0, # Musical smooth release
            filter_on=True,
            filter_type=1, # HPF
            filter_freq_hz=250.0, # Cut sub/bass stage rumble
        )

        # 5. Formulate tactical Vietnamese advice
        if comb_risk in ("HIGH", "SEVERE"):
            advice_vi = (
                f"CẢNH BÁO RÒ RỈ SÂN KHẤU CAO: Phát hiện âm thanh từ {primary_bleed_name or 'Trống/Ban nhạc'} "
                f"(Kênh {primary_bleed_ch}) lọt vào {target_name} ({bleed_level_rel_db:+.1f} dB, tương quan {abs_corr:.2f}). "
                f"Nguy cơ méo pha và triệt tiêu giọng (Comb Filtering). Khuyến nghị kích hoạt Downward Expander (Nén nhẹ {exp_range_db} dB, Ngưỡng {exp_thr_db} dBFS)."
            )
        elif comb_risk == "MODERATE":
            advice_vi = (
                f"Rò rỉ âm thanh ở mức trung bình từ {primary_bleed_name or 'nhạc cụ lân cận'}. "
                f"Nên kích hoạt Downward Expander dịu nhẹ ({exp_range_db} dB) để làm sạch nền khi ca sĩ/diễn giả nghỉ nói."
            )
        else:
            advice_vi = (
                f"Độ sạch tín hiệu tốt (Nhiễu nền {noise_floor_dbfs} dBFS). "
                f"Không phát hiện hiện tượng cộng hưởng rò rỉ âm học nghiêm trọng từ sân khấu."
            )

        return CrossTalkReport(
            channel_id=target_channel,
            channel_name=target_name,
            role=target_role,
            bleed_source_channel_id=primary_bleed_ch,
            bleed_source_name=primary_bleed_name,
            correlation_coeff=round(max_corr, 3),
            relative_bleed_level_db=bleed_level_rel_db,
            comb_filtering_risk=comb_risk,
            phase_alignment_status=phase_status,
            ambient_noise_floor_dbfs=noise_floor_dbfs,
            recommended_expander=exp_settings,
            advice_vi=advice_vi,
            talkback_safe=True,
        )

    @classmethod
    def generate_expander_proposals(
        cls,
        channel_id: int,
        settings: ExpanderSettings,
        current_sha256: str,
    ) -> List[Proposal]:
        """
        Formulate safe X32 Proposals for Downward Expander (/ch/{ch}/gate/*).
        """
        if channel_id == get_talkback_channel():
            raise InvariantViolationError("HARD INVARIANT: Channel 11 (Band Talkback) must NEVER have expander proposals for FOH!")

        changes = [
            {
                "parameter": f"/ch/{channel_id:02d}/gate/on",
                "from": 0,
                "to": 1 if settings.enabled else 0,
                "detail": f"Bật Downward Expander Kênh {channel_id:02d}.",
            },
            {
                "parameter": f"/ch/{channel_id:02d}/gate/mode",
                "from": 1,
                "to": settings.mode, # 0 = Expander
                "detail": f"Chọn chế độ Expander (làm dịu âm đuôi tự nhiên, không ngắt cụt).",
            },
            {
                "parameter": f"/ch/{channel_id:02d}/gate/thr",
                "from": 0.0,
                "to": settings.threshold_x32,
                "detail": f"Đặt ngưỡng kích hoạt {settings.threshold_dbfs} dBFS (cao hơn ồn nền 3 dB).",
            },
            {
                "parameter": f"/ch/{channel_id:02d}/gate/range",
                "from": 0.0,
                "to": settings.range_x32,
                "detail": f"Đặt biên độ nén nền {settings.range_db} dB (bảo toàn không khí hội trường).",
            },
            {
                "parameter": f"/ch/{channel_id:02d}/gate/filter/on",
                "from": 0,
                "to": 1 if settings.filter_on else 0,
                "detail": "Kích hoạt Key Filter Sidechain để chặn tiếng ồn trầm sân khấu kích hoạt mic.",
            },
            {
                "parameter": f"/ch/{channel_id:02d}/gate/filter/f",
                "from": 0.20,
                "to": 0.35, # ~250 Hz
                "detail": f"Tần số cắt Key Filter Sidechain ở mức {settings.filter_freq_hz} Hz.",
            },
        ]

        prop = Proposal(
            proposal_id=f"prop-expander-{channel_id:02d}-{uuid.uuid4().hex[:6]}",
            target_channel=channel_id,
            hypothesis=f"Kích hoạt Downward Expander Kênh {channel_id:02d} để triệt tiêu tiếng rò rỉ sân khấu và chống comb-filtering.",
            confidence=0.92,
            changes=changes,
            expected_sha256=current_sha256,
            operator_approved=False,
        )

        return [prop]
