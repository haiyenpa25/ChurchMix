"""
Conservative PEQ Recommendation Engine for Behringer X32.
- Respects church sound guidelines: preserve voice warmth, reduce mud, notch feedback surgically
- Translates between real acoustic units (Hz, dB, Q) and X32 normalized floats (0.0 to 1.0)
- Generates proposal diffs ready for Safety Gate & Transaction Executor
- Simulates cascaded magnitude response for A/B preview
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from packages.safety_controller.transaction import Proposal
from packages.feedback_detector.detector import FeedbackCandidate


# --- X32 Normalized Float Conversions ---

def freq_to_x32(freq_hz: float, f_min: float = 20.0, f_max: float = 20000.0) -> float:
    """Map frequency in Hz to X32 logarithmic float (0.0 to 1.0)."""
    clamped = max(f_min, min(f_max, freq_hz))
    val = math.log2(clamped / f_min) / math.log2(f_max / f_min)
    return round(max(0.0, min(1.0, val)), 4)


def x32_to_freq(val: float, f_min: float = 20.0, f_max: float = 20000.0) -> float:
    """Map X32 float (0.0 to 1.0) to frequency in Hz."""
    clamped = max(0.0, min(1.0, val))
    freq = f_min * (2.0 ** (clamped * math.log2(f_max / f_min)))
    return round(freq, 1)


def gain_to_x32(gain_db: float, min_db: float = -15.0, max_db: float = 15.0) -> float:
    """Map Gain in dB (-15dB to +15dB) to X32 float (0.0 to 1.0, 0.5 = 0dB)."""
    clamped = max(min_db, min(max_db, gain_db))
    val = (clamped - min_db) / (max_db - min_db)
    return round(max(0.0, min(1.0, val)), 4)


def x32_to_gain(val: float, min_db: float = -15.0, max_db: float = 15.0) -> float:
    """Map X32 float (0.0 to 1.0) to Gain in dB."""
    clamped = max(0.0, min(1.0, val))
    gain = min_db + clamped * (max_db - min_db)
    return round(gain, 2)


def q_to_x32(q: float, q_min: float = 0.3, q_max: float = 10.0) -> float:
    """Map Q factor to X32 float (0.0 to 1.0)."""
    clamped = max(q_min, min(q_max, q))
    val = math.log2(clamped / q_min) / math.log2(q_max / q_min)
    return round(max(0.0, min(1.0, val)), 4)


def x32_to_q(val: float, q_min: float = 0.3, q_max: float = 10.0) -> float:
    """Map X32 float (0.0 to 1.0) to Q factor."""
    clamped = max(0.0, min(1.0, val))
    q = q_min * (2.0 ** (clamped * math.log2(q_max / q_min)))
    return round(q, 2)


@dataclass
class PEQBandProposal:
    band_index: int # 1, 2, 3, or 4
    filter_type: str # "PEQ", "LCut", "LowShelf", "HighShelf"
    freq_hz: float
    gain_db: float
    q_factor: float
    rationale: str


@dataclass
class ChannelTuningProposal:
    channel_id: int
    role: str
    hpf_on: bool
    hpf_freq_hz: float
    bands: List[PEQBandProposal]
    expected_tradeoffs: List[str]
    simulated_curve: List[Dict[str, float]] # [{"freq": 100, "response_db": -0.5}, ...]


class PEQRecommender:
    def __init__(self):
        pass

    def recommend_role(
        self,
        channel_id: int,
        role: str,
        expected_sha256: str,
    ) -> Tuple[Proposal, ChannelTuningProposal]:
        """
        Generate conservative tuning for any supported church audio role:
        - PASTOR_SPEECH
        - LEAD_VOCAL_FEMALE
        - LEAD_VOCAL_MALE
        - CHOIR_OVERHEAD
        - ACOUSTIC_GUITAR
        - PIANO_KEYS
        - BASS_GUITAR
        """
        ch_str = f"/ch/{channel_id:02d}"

        if role == "LEAD_VOCAL_FEMALE":
            hpf = 110.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=320.0, gain_db=-1.5, q_factor=2.0, rationale="Khử đục dải low-mid giọng nữ trong không gian dội âm."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=3500.0, gain_db=1.2, q_factor=2.2, rationale="Tăng độ sáng và hiện diện của giọng hát trên nền ban nhạc."),
                PEQBandProposal(band_index=3, filter_type="PEQ", freq_hz=7200.0, gain_db=-1.6, q_factor=4.0, rationale="Giảm xì gắt âm sibilance ('s', 'x', 'tr')."),
            ]
            hypothesis = "Cân chỉnh giọng nữ đơn ca: làm sáng ca từ, giảm xì sibilance và khử đục low-mid"
            tradeoffs = [
                "Bảo toàn chất giọng nữ mượt mà, tránh chói tai khi hát nốt cao trên FOH.",
                "Làm sạch dải 320 Hz giúp giọng hát nổi bật mà không cần đẩy âm lượng quá lớn.",
            ]
        elif role == "LEAD_VOCAL_MALE":
            hpf = 75.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=220.0, gain_db=-1.6, q_factor=1.8, rationale="Giảm om phòng dải trầm nam, tránh ù đọng."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=2600.0, gain_db=1.2, q_factor=2.0, rationale="Tăng độ nét ca từ của giọng hát nam."),
            ]
            hypothesis = "Cân chỉnh giọng nam đơn ca: giữ độ ấm tự nhiên, tăng độ nét ca từ và khử om phòng"
            tradeoffs = [
                "Giữ trọn độ dày baritone ấm áp mà không làm nặng nề dàn loa FOH.",
                "Tăng độ hiện diện dải 2.6 kHz giúp ca từ rõ ràng ngay cả khi ban nhạc chơi cao trào.",
            ]
        elif role == "CHOIR_OVERHEAD":
            hpf = 130.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=400.0, gain_db=-2.0, q_factor=1.5, rationale="Cắt dội âm hội trường ca đoàn."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=3000.0, gain_db=-1.0, q_factor=2.0, rationale="Giảm chói tiếng cộng hưởng nhóm khi nhiều người cùng hát."),
            ]
            hypothesis = "Cân chỉnh micro ca đoàn: dọn dẹp dội âm phòng và kiểm soát chói dải 3 kHz"
            tradeoffs = [
                "Giúp tổng thể ca đoàn hòa quyện, thanh thoát mà không triệt tiêu hòa âm bè.",
            ]
        elif role == "ACOUSTIC_GUITAR":
            hpf = 80.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=200.0, gain_db=-2.0, q_factor=2.0, rationale="Khử tiếng ù thùng đàn và va chạm dây."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=800.0, gain_db=-1.8, q_factor=2.5, rationale="Giảm tiếng gắt/quack đặc trưng của pickup piezo."),
                PEQBandProposal(band_index=3, filter_type="PEQ", freq_hz=4500.0, gain_db=1.5, q_factor=2.0, rationale="Tăng độ long lanh (sparkle) của tiếng gảy acoustic."),
            ]
            hypothesis = "Cân chỉnh đàn Acoustic Guitar: khử tiếng gắt piezo, lọc ù thùng đàn và tăng độ nét dây"
            tradeoffs = [
                "Tiếng đàn acoustic trong trẻo, thanh thoát, hòa quyện với piano và giọng hát.",
            ]
        elif role == "PIANO_KEYS":
            hpf = 40.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=280.0, gain_db=-1.5, q_factor=1.5, rationale="Khử đục dải low-mid tránh tranh chấp dải tần với giọng Mục sư."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=3200.0, gain_db=1.0, q_factor=1.8, rationale="Tăng độ tách bạch của phím đàn trong bản phối thờ phượng."),
            ]
            hypothesis = "Cân chỉnh đàn Piano/Keys: dọn dẹp dải 280Hz và tạo khoảng không gian cho giọng hát"
            tradeoffs = [
                "Đàn piano rõ tiếng, thanh thoát, không chiếm chỗ dải vocal.",
            ]
        elif role == "BASS_GUITAR":
            hpf = 35.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=70.0, gain_db=1.5, q_factor=1.8, rationale="Tăng cường dải lực trầm ấm chắc khỏe của nốt bass."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=250.0, gain_db=-2.5, q_factor=2.0, rationale="Khoét dải đục 250Hz để nhường chỗ cho kick và vocal."),
                PEQBandProposal(band_index=3, filter_type="PEQ", freq_hz=1200.0, gain_db=1.5, q_factor=2.2, rationale="Tăng độ nảy ngón tay (finger attack) giúp nghe rõ đường chạy nốt."),
            ]
            hypothesis = "Cân chỉnh đàn Bass: tạo nền trầm chắc gọn, khoét mud 250Hz và nét ngón đàn"
            tradeoffs = [
                "Đảm bảo nốt trầm tròn trịa, chắc gọn, không làm rung rền hội trường.",
            ]
        else: # Default: PASTOR_SPEECH
            role = "PASTOR_SPEECH"
            hpf = 85.0
            bands = [
                PEQBandProposal(band_index=1, filter_type="PEQ", freq_hz=250.0, gain_db=-1.8, q_factor=1.5, rationale="Giảm đục và ù âm học nhà thờ ở dải 250 Hz giúp giọng nói rõ ràng hơn."),
                PEQBandProposal(band_index=2, filter_type="PEQ", freq_hz=2800.0, gain_db=1.2, q_factor=1.2, rationale="Tăng nhẹ hiện diện ở dải 2.8 kHz giúp hội chúng nghe rõ từng âm tiết bài giảng."),
            ]
            hypothesis = "Cải thiện độ rõ lời bài giảng Mục sư, khử ù 250Hz và lọc rung HPF 85Hz"
            tradeoffs = [
                "Giảm nhẹ độ trầm giả tạo do hiệu ứng tiệm cận (proximity effect) khi để mic sát miệng.",
                "Cải thiện độ rõ lời trong hội trường dội âm mà không làm mỏng chất giọng thật.",
            ]

        changes: List[Dict[str, Any]] = []

        # HPF
        changes.append({"parameter": f"{ch_str}/preamp/hpon", "from": 0, "to": 1})
        changes.append({"parameter": f"{ch_str}/preamp/hpf", "from": 0.0, "to": freq_to_x32(hpf, 20.0, 400.0)})

        # Bands
        for b in bands:
            prefix = f"{ch_str}/eq/{b.band_index}"
            changes.append({"parameter": f"{prefix}/f", "from": 0.5, "to": freq_to_x32(b.freq_hz)})
            changes.append({"parameter": f"{prefix}/g", "from": 0.5, "to": gain_to_x32(b.gain_db)})
            changes.append({"parameter": f"{prefix}/q", "from": 0.5, "to": q_to_x32(b.q_factor)})

        proposal = Proposal(
            proposal_id=f"{role.lower().replace('_', '-')}-ch{channel_id:02d}",
            target_channel=channel_id,
            hypothesis=hypothesis,
            confidence=0.90,
            changes=changes,
            expected_sha256=expected_sha256,
        )

        sim_curve = self.simulate_response(hpf_freq=hpf, bands=bands)

        tuning_detail = ChannelTuningProposal(
            channel_id=channel_id,
            role=role,
            hpf_on=True,
            hpf_freq_hz=hpf,
            bands=bands,
            expected_tradeoffs=tradeoffs,
            simulated_curve=sim_curve,
        )

        return proposal, tuning_detail

    def recommend_pastor_speech(
        self,
        channel_id: int,
        expected_sha256: str,
        current_eq_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Proposal, ChannelTuningProposal]:
        """
        Generate conservative tuning for Pastor/Speech mic (calls recommend_role).
        """
        return self.recommend_role(channel_id, "PASTOR_SPEECH", expected_sha256)

    def recommend_feedback_notch(
        self,
        candidate: FeedbackCandidate,
        expected_sha256: str,
        preferred_band: int = 3,
        current_parameters: Optional[Dict[str, Any]] = None,
    ) -> Proposal:
        """
        Generate surgical PEQ notch for an identified feedback frequency:
        - Q: High (Q = 7.0) to isolate resonance
        - Gain: -3.5 dB (conservative cut, avoids mutilating vocal tone)

        When the mixer's current parameters are given, the notch goes into a flat
        (unused) mid band — preferred_band first, then the other mid band — and the
        proposal's "from" values are the band's real current values. If both mid bands
        are in use, preferred_band is overwritten and the hypothesis says so.
        """
        ch = candidate.channel_id
        ch_str = f"/ch/{ch:02d}"
        band = preferred_band
        overwrites = False
        current = {"f": 0.5, "g": 0.5, "q": 0.5}
        if current_parameters is not None:
            def read(b, key):
                return current_parameters.get(f"{ch_str}/eq/{b}/{key}")
            candidates = [preferred_band] + [b for b in (3, 2) if b != preferred_band]
            flat = [b for b in candidates if read(b, "g") is not None and abs(float(read(b, "g")) - 0.5) < 0.01]
            band = flat[0] if flat else preferred_band
            overwrites = not flat
            current = {k: (float(read(band, k)) if read(band, k) is not None else 0.5) for k in ("f", "g", "q")}
        prefix = f"{ch_str}/eq/{band}"

        changes = [
            {"parameter": f"{prefix}/f", "from": current["f"], "to": freq_to_x32(candidate.freq_hz)},
            {"parameter": f"{prefix}/g", "from": current["g"], "to": gain_to_x32(-3.5)},
            {"parameter": f"{prefix}/q", "from": current["q"], "to": q_to_x32(7.0)},
        ]

        note = ""
        if current_parameters is not None:
            note = f" (band {band}, GHI ĐÈ band EQ đang dùng — kiểm tra lại âm sắc sau khi cắt)" if overwrites else f" (band {band}, đang trống)"
        return Proposal(
            proposal_id=f"feedback-notch-ch{ch:02d}-{int(candidate.freq_hz)}hz",
            target_channel=ch,
            hypothesis=f"Cắt notch hẹp tại {candidate.freq_hz} Hz để triệt tiêu cộng hưởng hú monitor/FOH{note}",
            confidence=candidate.confidence,
            changes=changes,
            expected_sha256=expected_sha256,
        )

    def simulate_response(
        self,
        hpf_freq: Optional[float],
        bands: List[PEQBandProposal],
        num_points: int = 80,
    ) -> List[Dict[str, float]]:
        """
        Simulate magnitude response in dB from 20 Hz to 20,000 Hz.
        Calculates biquad filter transfer functions.
        """
        freq_grid = np.geomspace(20.0, 20000.0, num_points)
        curve: List[Dict[str, float]] = []

        for f in freq_grid:
            total_db = 0.0

            # 1. HPF 12dB/oct (2nd order Butterworth)
            if hpf_freq and hpf_freq > 20.0:
                ratio = f / hpf_freq
                # Magnitude of 2nd order HPF: ratio^2 / sqrt((1 - ratio^2)^2 + 2*ratio^2)
                denom = math.sqrt((1.0 - ratio**2)**2 + 2.0 * (ratio**2))
                mag = (ratio**2) / max(1e-6, denom)
                total_db += 20.0 * math.log10(max(1e-3, mag))

            # 2. PEQ Bands (Parametric Bell EQ)
            for b in bands:
                if abs(b.gain_db) > 0.05:
                    w = 2.0 * math.pi * f
                    w0 = 2.0 * math.pi * b.freq_hz
                    # Standard bell filter approximation
                    bw = b.freq_hz / b.q_factor
                    delta_f = abs(f - b.freq_hz)
                    # Gaussian bell profile in log-frequency space
                    x = math.log2(f / b.freq_hz) * b.q_factor
                    band_effect = b.gain_db * math.exp(-0.5 * (x**2))
                    total_db += band_effect

            curve.append({
                "freq": round(float(f), 1),
                "response_db": round(max(-36.0, min(18.0, total_db)), 2),
            })

        return curve
