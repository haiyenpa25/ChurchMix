"""
ChurchMix Preamp Gain Staging & Digital Trim Headroom Calibrator.
================================================================
Assists church sound engineers in achieving optimal digital headroom
and signal-to-noise ratio (SNR) on the Behringer X32 / Midas M32:
1. Church Audio Target Headroom:
   - Speech / Pastor / Prayer: Peak -18.0 dBFS (Nominal Dialogue Headroom: 18 dB).
   - Worship Vocals / Solos: Peak -14.0 dBFS.
   - Band Instruments / Drums: Peak -12.0 dBFS.
2. Digital Trim vs Preamp Analog Gain:
   - Uses Channel Digital Trim (/ch/{ch:02d}/preamp/trim) for non-destructive digital adjustments
     that protect physical Ultranet P16 personal monitor sends.
3. Pre-mutation Proposal Generation adhering to Rule 7 ("A proposal is never a command")
   and Rule 11 (5-step safety transaction).
"""
from __future__ import annotations
import math
import uuid
import numpy as np
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple

from packages.safety_controller.transaction import Proposal


def trim_to_x32(db: float) -> float:
    """Map Trim in dB (-18.0 to +18.0 dB) to X32 normalized float (0.0 to 1.0, 0.5 = 0.0 dB)."""
    clamped = max(-18.0, min(18.0, db))
    val = 0.5 + (clamped / 36.0)
    return round(max(0.0, min(1.0, val)), 4)


def x32_to_trim(val: float) -> float:
    """Map X32 normalized float (0.0 to 1.0) to Trim in dB (-18.0 to +18.0 dB)."""
    clamped = max(0.0, min(1.0, val))
    db = (clamped - 0.5) * 36.0
    return round(db, 2)


@dataclass
class GainStagingReport:
    channel_id: int
    channel_name: str
    role: str
    peak_dbfs: float
    rms_dbfs: float
    crest_factor_db: float
    headroom_db: float
    target_peak_dbfs: float
    recommended_trim_delta_db: float
    current_trim_db: float
    proposed_trim_db: float
    proposed_trim_float: float
    health_status: str # "OPTIMAL", "LOW_GAIN", "HIGH_GAIN", "CLIPPING_DETECTED"
    advice_vi: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GainStagingAdvisor:
    """Calculates headroom, SNR, and optimal Digital Trim for church channels."""

    ROLE_TARGETS = {
        "PASTOR": -18.0,
        "SERMON": -18.0,
        "PRAYER": -18.0,
        "FEMALE_LEAD": -14.0,
        "MALE_LEAD": -14.0,
        "CHOIR": -14.0,
        "ACOUSTIC_GUITAR": -14.0,
        "PIANO": -14.0,
        "BASS": -12.0,
        "DRUMS": -12.0,
    }

    @classmethod
    def analyze_headroom(
        cls,
        signal: np.ndarray,
        channel_id: int = 1,
        channel_name: str = "Pastor Mic",
        role: str = "PASTOR",
        current_trim_float: float = 0.5, # 0.0 dB
    ) -> GainStagingReport:
        """
        Analyze audio block to evaluate headroom against target role levels.
        """
        if len(signal) == 0:
            peak_dbfs = -120.0
            rms_dbfs = -120.0
        else:
            abs_max = float(np.max(np.abs(signal)))
            rms = float(np.sqrt(np.mean(signal ** 2)))
            peak_dbfs = 20.0 * math.log10(abs_max) if abs_max > 1e-6 else -120.0
            rms_dbfs = 20.0 * math.log10(rms) if rms > 1e-6 else -120.0

        crest_factor = round(peak_dbfs - rms_dbfs, 1) if peak_dbfs > -100.0 else 0.0
        headroom = round(-peak_dbfs, 1) if peak_dbfs <= 0.0 else 0.0

        role_key = role.upper()
        target = cls.ROLE_TARGETS.get(role_key, -16.0)

        current_trim_db = x32_to_trim(current_trim_float)

        # Calculate needed delta to hit target peak
        if peak_dbfs <= -90.0:
            # Near silence: do not boost (Silence Hold principle)
            delta_db = 0.0
            status = "LOW_GAIN"
            advice = (
                f"Kênh {channel_id:02d} ({channel_name}) hiện không có tín hiệu (im lặng hoặc mic chưa bật). "
                f"Giữ nguyên Gain để không kéo tiếng ồn nền (Silence Hold)."
            )
        elif peak_dbfs >= -1.0:
            delta_db = -6.0
            status = "CLIPPING_DETECTED"
            advice = (
                f"🚨 CẢNH BÁO VỠ TIẾNG (CLIPPING): Tín hiệu chạm đỉnh {peak_dbfs:.1f} dBFS (sát ngưỡng vỡ 0 dBFS). "
                f"Cần giảm ngay Preamp Gain hoặc Trim tối thiểu -6.0 dB để bảo vệ âm thanh loa FOH và bản ghi."
            )
        elif peak_dbfs > target + 3.0:
            delta_db = round(target - peak_dbfs, 1)
            delta_db = max(-6.0, delta_db) # Clamp step
            status = "HIGH_GAIN"
            advice = (
                f"Tín hiệu hơi lớn so với chuẩn {role_key} (Đỉnh {peak_dbfs:.1f} dBFS > mục tiêu {target:.1f} dBFS). "
                f"Headroom còn {headroom:.1f} dB (hơi mỏng). Đề xuất giảm Trim {delta_db:+.1f} dB để tránh vỡ tiếng khi cao trào."
            )
        elif peak_dbfs < target - 5.0:
            delta_db = round(target - peak_dbfs, 1)
            delta_db = min(6.0, delta_db) # Clamp step to max +6 dB
            status = "LOW_GAIN"
            advice = (
                f"Tín hiệu vào hơi nhỏ (Đỉnh {peak_dbfs:.1f} dBFS < mục tiêu {target:.1f} dBFS). "
                f"Tỷ số tín hiệu/nhiễu (SNR) chưa tối ưu. Đề xuất tăng Trim {delta_db:+.1f} dB để fader không phải đẩy quá cao."
            )
        else:
            delta_db = 0.0
            status = "OPTIMAL"
            advice = (
                f"Gain Staging hoàn hảo! Đỉnh tín hiệu {peak_dbfs:.1f} dBFS đạt chuẩn {role_key} (Mục tiêu: {target:.1f} dBFS). "
                f"Dự trữ headroom sạch {headroom:.1f} dB, dynamic range tự nhiên, không có nguy cơ méo tiếng."
            )

        proposed_trim_db = round(current_trim_db + delta_db, 2)
        proposed_trim_float = trim_to_x32(proposed_trim_db)

        return GainStagingReport(
            channel_id=channel_id,
            channel_name=channel_name,
            role=role,
            peak_dbfs=round(peak_dbfs, 1),
            rms_dbfs=round(rms_dbfs, 1),
            crest_factor_db=crest_factor,
            headroom_db=headroom,
            target_peak_dbfs=target,
            recommended_trim_delta_db=delta_db,
            current_trim_db=current_trim_db,
            proposed_trim_db=proposed_trim_db,
            proposed_trim_float=proposed_trim_float,
            health_status=status,
            advice_vi=advice,
        )

    @classmethod
    def generate_trim_proposal(
        cls,
        report: GainStagingReport,
        current_sha256: str,
        current_trim_float: float,
    ) -> Proposal:
        """
        Formulate a safe Proposal for Digital Trim adjustment ready for operator authorization.
        """
        ch = report.channel_id
        param_path = f"/ch/{ch:02d}/preamp/trim"

        changes = [
            {
                "parameter": param_path,
                "from": current_trim_float,
                "to": report.proposed_trim_float,
                "detail": f"Điều chỉnh Digital Trim Kênh {ch:02d} từ {report.current_trim_db:+.1f} dB sang {report.proposed_trim_db:+.1f} dB (Độ lệch {report.recommended_trim_delta_db:+.1f} dB).",
            }
        ]

        return Proposal(
            proposal_id=f"prop-gain-{ch:02d}-{uuid.uuid4().hex[:6]}",
            target_channel=ch,
            hypothesis=f"Tối ưu Gain Staging Kênh {ch:02d} ({report.channel_name}) về mức đỉnh danh định {report.target_peak_dbfs} dBFS.",
            confidence=0.90 if report.health_status != "OPTIMAL" else 0.50,
            changes=changes,
            expected_sha256=current_sha256,
            operator_approved=False,
        )
