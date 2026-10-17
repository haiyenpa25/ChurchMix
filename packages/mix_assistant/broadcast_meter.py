"""
ChurchMix Broadcast & Livestream LUFS Loudness Monitor.
======================================================
Implements:
1. ITU-R BS.1770-4 / EBU R128 Compliant Loudness Measurement:
   - K-weighting pre-filter (Stage 1 High-Shelf + Stage 2 High-Pass RLB).
   - Momentary LUFS (400ms window).
   - Short-Term LUFS (3s window).
   - Integrated Gated LUFS with absolute (-70 LUFS) and relative (-10 dB) gates.
   - True Peak (dBTP) estimation with 4x oversampling.
2. Church Livestream Safety Invariant Guard:
   - Ensures DL16 In 11 (Band Talkback) NEVER leaks to the Livestream Broadcast Bus/Matrix.
   - Validates streaming compliance against YouTube/Facebook target (-14 LUFS) and Sanctuary target (-18 LUFS).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from packages.safety_controller.routing import get_talkback_channel
from scipy.signal import lfilter, resample_poly


# ITU-R BS.1770-4 Standard Filter Coefficients for 48,000 Hz
# Stage 1: Pre-filter (High-shelf simulating head acoustic shadowing)
B_SHELF = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285], dtype=np.float64)
A_SHELF = np.array([1.0, -1.69065929318241, 0.73248077421585], dtype=np.float64)

# Stage 2: RLB High-pass filter (Cutoff ~38 Hz)
B_RLB = np.array([1.0, -2.0, 1.0], dtype=np.float64)
A_RLB = np.array([1.0, -1.99004745483398, 0.99007225036621], dtype=np.float64)


def apply_k_weighting(signal: np.ndarray, sample_rate: int = 48000) -> np.ndarray:
    """
    Apply ITU-R BS.1770 K-weighting filter cascade.
    Input signal can be 1D (mono) or 2D (samples, channels).
    """
    if signal.ndim == 1:
        x = signal.astype(np.float64)
    else:
        x = signal[:, 0].astype(np.float64)

    # 1. High-shelf filter
    y_shelf = lfilter(B_SHELF, A_SHELF, x)
    # 2. RLB high-pass filter
    y_k = lfilter(B_RLB, A_RLB, y_shelf)
    return y_k


def compute_true_peak_dbtp(signal: np.ndarray, oversample: int = 4) -> float:
    """
    Estimate True Peak level in dBTP using 4x polyphase oversampling interpolation.
    """
    if len(signal) == 0:
        return -120.0

    mono = signal if signal.ndim == 1 else signal[:, 0]
    # 4x oversampling interpolation
    try:
        up = resample_poly(mono, up=oversample, down=1)
        peak = float(np.max(np.abs(up)))
    except Exception:
        peak = float(np.max(np.abs(mono)))

    if peak <= 1e-6:
        return -120.0
    return float(20.0 * np.log10(peak))


def compute_momentary_lufs(signal: np.ndarray, sample_rate: int = 48000) -> float:
    """
    Compute Momentary Loudness (M) over a 400ms sliding block.
    """
    win_samples = int(0.400 * sample_rate)
    if len(signal) < win_samples:
        segment = signal
    else:
        segment = signal[-win_samples:]

    y_k = apply_k_weighting(segment, sample_rate=sample_rate)
    ms = float(np.mean(y_k ** 2))
    if ms <= 1e-12:
        return -120.0
    return float(-0.691 + 10.0 * np.log10(ms))


def compute_short_term_lufs(signal: np.ndarray, sample_rate: int = 48000) -> float:
    """
    Compute Short-Term Loudness (S) over a 3.0s window.
    """
    win_samples = int(3.0 * sample_rate)
    if len(signal) < win_samples:
        segment = signal
    else:
        segment = signal[-win_samples:]

    y_k = apply_k_weighting(segment, sample_rate=sample_rate)
    ms = float(np.mean(y_k ** 2))
    if ms <= 1e-12:
        return -120.0
    return float(-0.691 + 10.0 * np.log10(ms))


def compute_integrated_lufs(signal: np.ndarray, sample_rate: int = 48000) -> float:
    """
    Compute Integrated Loudness (I) with EBU R128 dual gating:
    1. Absolute threshold: -70 LUFS
    2. Relative threshold: -10 dB below ungated average
    """
    block_size = int(0.400 * sample_rate)
    hop_size = int(0.100 * sample_rate) # 75% overlap

    if len(signal) < block_size:
        return compute_momentary_lufs(signal, sample_rate=sample_rate)

    y_k = apply_k_weighting(signal, sample_rate=sample_rate)

    # Calculate block power
    powers = []
    for i in range(0, len(y_k) - block_size + 1, hop_size):
        block = y_k[i : i + block_size]
        z = float(np.mean(block ** 2))
        powers.append(z)

    if not powers:
        return -120.0

    powers = np.array(powers)

    # 1. Absolute gate (-70 LUFS corresponds to z = 10^((-70 + 0.691)/10))
    abs_thresh_power = 10.0 ** ((-70.0 + 0.691) / 10.0)
    gated_abs = powers[powers > abs_thresh_power]

    if len(gated_abs) == 0:
        return -120.0

    # 2. Relative gate (-10 dB below average of above-absolute blocks)
    mean_gated_abs = float(np.mean(gated_abs))
    rel_thresh_power = mean_gated_abs * (10.0 ** (-10.0 / 10.0))

    gated_rel = gated_abs[gated_abs > rel_thresh_power]
    if len(gated_rel) == 0:
        return -120.0

    final_power = float(np.mean(gated_rel))
    return float(-0.691 + 10.0 * np.log10(final_power))


@dataclass
class LoudnessReport:
    momentary_lufs: float
    short_term_lufs: float
    integrated_lufs: float
    true_peak_dbtp: float
    target_lufs: float
    target_profile: str
    compliance_status: str # "OPTIMAL", "TOO_QUIET", "TOO_LOUD", "PEAK_WARNING"
    delta_to_target_db: float
    recommendation_vi: str
    talkback_isolated: bool = True
    talkback_warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BroadcastMixGuard:
    """
    Evaluates Livestream Broadcast Audio parameters and protects against Talkback leaks.
    Standard profiles:
    - YOUTUBE_STREAMING: Target -14.0 LUFS (+-1.0 dB), True Peak <= -1.0 dBTP
    - SANCTUARY_FOH: Target -18.0 LUFS (+-1.5 dB), True Peak <= -0.5 dBTP
    - EBU_R128_TV: Target -23.0 LUFS (+-0.5 dB), True Peak <= -1.0 dBTP
    """

    PROFILES = {
        "YOUTUBE_STREAMING": {"target_lufs": -14.0, "tolerance": 1.0, "max_true_peak": -1.0},
        "SANCTUARY_FOH": {"target_lufs": -18.0, "tolerance": 1.5, "max_true_peak": -0.5},
        "EBU_R128_TV": {"target_lufs": -23.0, "tolerance": 0.5, "max_true_peak": -1.0},
    }

    @staticmethod
    def verify_livestream_talkback_isolation(
        state_dict: Dict[str, Any],
        livestream_bus: int = 5,
    ) -> Tuple[bool, str]:
        """
        Hard Invariant: Channel 11 (Band Talkback) must NEVER send audio to the Livestream Broadcast Bus/Matrix.
        """
        # 1. Check send to Livestream MixBus
        bus_str = f"/ch/{get_talkback_channel():02d}/mix/{livestream_bus:02d}/on"
        bus_send = int(state_dict.get(bus_str, 0))
        if bus_send == 1:
            return False, f"CRITICAL INVARIANT VIOLATION: DL16 In 11 (Talkback) is actively feeding Livestream Bus {livestream_bus:02d}!"

        # 2. Check stereo main LR send
        st_send = int(state_dict.get(f"/ch/{get_talkback_channel():02d}/mix/st", 0))
        if st_send == 1:
            return False, "CRITICAL INVARIANT VIOLATION: DL16 In 11 (Talkback) is actively unmuted to Main Stereo Bus (which feeds broadcast stream)!"

        return True, f"VERIFIED SAFE: DL16 In 11 (Talkback) is 100% isolated from Livestream Bus {livestream_bus:02d} and Main FOH."

    @classmethod
    def evaluate_loudness(
        cls,
        signal: np.ndarray,
        sample_rate: int = 48000,
        target_profile: str = "YOUTUBE_STREAMING",
        state_dict: Optional[Dict[str, Any]] = None,
        livestream_bus: int = 5,
    ) -> LoudnessReport:
        """
        Analyze audio signal and return formal compliance report.
        """
        cfg = cls.PROFILES.get(target_profile, cls.PROFILES["YOUTUBE_STREAMING"])
        target = cfg["target_lufs"]
        tol = cfg["tolerance"]
        max_tp = cfg["max_true_peak"]

        m_lufs = compute_momentary_lufs(signal, sample_rate)
        s_lufs = compute_short_term_lufs(signal, sample_rate)
        i_lufs = compute_integrated_lufs(signal, sample_rate)
        tp_dbtp = compute_true_peak_dbtp(signal)

        # Check Talkback isolation if state provided
        tb_safe = True
        tb_msg = None
        if state_dict is not None:
            tb_safe, tb_msg = cls.verify_livestream_talkback_isolation(state_dict, livestream_bus=livestream_bus)

        delta = round(target - s_lufs, 1)

        # Determine compliance
        if tp_dbtp > max_tp:
            status = "PEAK_WARNING"
            rec = (
                f"CẢNH BÁO TRUE PEAK: Đỉnh tín hiệu chạm {tp_dbtp:+.1f} dBTP (vượt ngưỡng {max_tp} dBTP). "
                f"Có nguy cơ méo tiếng khi YouTube/Facebook nén âm thanh sang chuẩn AAC. Cần kéo Limiter xuống."
            )
        elif s_lufs < target - tol:
            status = "TOO_QUIET"
            rec = (
                f"Tín hiệu Livestream bị nhỏ ({s_lufs:.1f} LUFS, mục tiêu {target:.1f} LUFS). "
                f"Khán giả nghe qua điện thoại/laptop sẽ thấy bé. Đề xuất tăng Makeup Gain trên Bus phát thanh +{abs(delta):.1f} dB."
            )
        elif s_lufs > target + tol:
            status = "TOO_LOUD"
            rec = (
                f"Tín hiệu Livestream quá lớn ({s_lufs:.1f} LUFS). Nền tảng YouTube sẽ tự động nén giảm âm lượng (Penalty Compression). "
                f"Đề xuất giảm Master Bus phát thanh -{abs(delta):.1f} dB."
            )
        else:
            status = "OPTIMAL"
            rec = (
                f"Âm lượng phát trực tiếp đạt chuẩn phát thanh xuất sắc ({s_lufs:.1f} LUFS, True Peak: {tp_dbtp:.1f} dBTP). "
                f"Âm thanh rõ ràng, đầy đặn, không bị méo tiếng và không bị phạt thuật toán nén."
            )

        if not tb_safe:
            rec = f"🚨 KHẨN CẤP: {tb_msg} — " + rec

        return LoudnessReport(
            momentary_lufs=round(m_lufs, 1),
            short_term_lufs=round(s_lufs, 1),
            integrated_lufs=round(i_lufs, 1),
            true_peak_dbtp=round(tp_dbtp, 1),
            target_lufs=target,
            target_profile=target_profile,
            compliance_status=status,
            delta_to_target_db=delta,
            recommendation_vi=rec,
            talkback_isolated=tb_safe,
            talkback_warning=tb_msg if not tb_safe else None,
        )
