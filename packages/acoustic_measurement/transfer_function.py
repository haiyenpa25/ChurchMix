"""
Dual-Channel Transfer Function H1(f), Coherence, Delay & Acoustic Spatial Averaging.
Adheres strictly to church hall PA tuning rules:
- Transfer Function: H1(f) = Syx(f) / Sxx(f)
- Coherence: gamma^2(f) gating to discard room reflection nulls and noise
- Delay alignment via Cross-Correlation Impulse Response
- Multi-position spatial averaging
- HARD ACOUSTIC RULE: NO-BOOST-IN-NULLS (Never boost acoustic cancellation dips)
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import numpy as np
from scipy import signal


@dataclass
class TransferFunctionResult:
    freqs: np.ndarray          # 1D array of frequencies (Hz)
    magnitude_db: np.ndarray   # Magnitude response in dB
    phase_deg: np.ndarray      # Phase in degrees (-180 to +180)
    coherence: np.ndarray      # Coherence values (0.0 to 1.0)
    delay_ms: float            # Estimated latency / time of flight
    valid_mask: np.ndarray     # Boolean mask where coherence >= min_coherence


def estimate_delay_samples(
    ref_signal: np.ndarray,
    meas_signal: np.ndarray,
    max_delay_samples: int = 4800, # Up to 100ms at 48kHz
) -> Tuple[int, float]:
    """
    Estimate time delay between reference signal and mic measurement
    using cross-correlation. Returns (delay_samples, delay_ms).
    """
    # Cross-correlate reference and measurement
    corr = signal.correlate(meas_signal, ref_signal, mode='full')
    lags = signal.correlation_lags(len(meas_signal), len(ref_signal), mode='full')

    # Restrict to realistic delay window [0, max_delay_samples]
    valid_indices = np.where((lags >= 0) & (lags <= max_delay_samples))[0]
    if len(valid_indices) == 0:
        return 0, 0.0

    peak_idx = valid_indices[np.argmax(np.abs(corr[valid_indices]))]
    delay_samples = int(lags[peak_idx])
    delay_ms = (delay_samples / 48000.0) * 1000.0
    return delay_samples, round(delay_ms, 2)


def compute_transfer_function(
    ref_signal: np.ndarray,
    meas_signal: np.ndarray,
    sample_rate: int = 48000,
    nperseg: int = 2048,
    noverlap: int = 1024,
    min_coherence: float = 0.50,
    auto_delay_align: bool = True,
) -> TransferFunctionResult:
    """
    Compute H1 transfer function: H1(f) = Syx(f) / Sxx(f)
    and coherence: gamma^2(f) = |Sxy|^2 / (Sxx * Syy).
    """
    delay_samples = 0
    delay_ms = 0.0

    if auto_delay_align:
        delay_samples, delay_ms = estimate_delay_samples(ref_signal, meas_signal)
        if delay_samples > 0 and len(meas_signal) > delay_samples:
            # Shift measurement to align time-of-flight with reference
            meas_signal = meas_signal[delay_samples:]
            ref_signal = ref_signal[:len(meas_signal)]

    min_len = min(len(ref_signal), len(meas_signal))
    if min_len < nperseg:
        # Pad signals
        ref_padded = np.zeros(nperseg, dtype=np.float32)
        meas_padded = np.zeros(nperseg, dtype=np.float32)
        ref_padded[:len(ref_signal)] = ref_signal
        meas_padded[:len(meas_signal)] = meas_signal
        ref_signal = ref_padded
        meas_signal = meas_padded

    # 1. Auto-spectral density Sxx (Reference) and Syy (Measurement)
    freqs, sxx = signal.welch(ref_signal, fs=sample_rate, window='hann', nperseg=nperseg, noverlap=noverlap)
    _, syy = signal.welch(meas_signal, fs=sample_rate, window='hann', nperseg=nperseg, noverlap=noverlap)

    # 2. Cross-spectral density Syx
    _, syx = signal.csd(meas_signal, ref_signal, fs=sample_rate, window='hann', nperseg=nperseg, noverlap=noverlap)

    # Safeguard against zero division
    sxx_clean = np.maximum(sxx, 1e-12)
    syy_clean = np.maximum(syy, 1e-12)

    # 3. Transfer Function H1(f)
    h1 = syx / sxx_clean
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(h1), 1e-6))
    phase_deg = np.angle(h1, deg=True)

    # 4. Coherence gamma^2(f)
    coherence = (np.abs(syx) ** 2) / (sxx_clean * syy_clean)
    coherence = np.clip(coherence, 0.0, 1.0)

    # Valid mask where measurement has high signal-to-noise and low room reflection interference
    valid_mask = coherence >= min_coherence

    return TransferFunctionResult(
        freqs=freqs,
        magnitude_db=magnitude_db,
        phase_deg=phase_deg,
        coherence=coherence,
        delay_ms=delay_ms,
        valid_mask=valid_mask,
    )


def spatial_average_transfer_functions(
    results: List[TransferFunctionResult],
) -> TransferFunctionResult:
    """
    Perform complex spatial averaging across multiple mic locations in the church hall
    (e.g., Center, Left Wing, Right Wing, Balcony).
    """
    if not results:
        raise ValueError("Cannot average empty results list")
    if len(results) == 1:
        return results[0]

    freqs = results[0].freqs
    mag_sum = np.zeros_like(freqs)
    coh_sum = np.zeros_like(freqs)
    phase_sum = np.zeros_like(freqs)
    avg_delay = float(np.mean([r.delay_ms for r in results]))

    for r in results:
        mag_sum += r.magnitude_db
        coh_sum += r.coherence
        phase_sum += r.phase_deg

    n = float(len(results))
    avg_mag = mag_sum / n
    avg_coh = coh_sum / n
    avg_phase = phase_sum / n
    valid_mask = avg_coh >= 0.45

    return TransferFunctionResult(
        freqs=freqs,
        magnitude_db=avg_mag,
        phase_deg=avg_phase,
        coherence=avg_coh,
        delay_ms=round(avg_delay, 2),
        valid_mask=valid_mask,
    )


def filter_no_boost_nulls(
    target_gain_db: np.ndarray,
    coherence: np.ndarray,
    raw_mag_db: np.ndarray,
    null_threshold_db: float = -8.0,
    min_coherence_for_boost: float = 0.65,
) -> np.ndarray:
    """
    HARD RULE ENFORCEMENT: 'No-Boost-in-Nulls'.
    If a frequency has a sharp dip (raw_mag <= null_threshold_db) or poor coherence,
    positive EQ gain boost is strictly forbidden (clamped to <= 0.0 dB).
    """
    filtered = np.copy(target_gain_db)

    # Detect acoustic cancellations:
    # 1. Low coherence (< 0.65)
    # 2. Deep acoustic notch relative to median
    median_level = np.median(raw_mag_db)
    is_deep_null = (raw_mag_db - median_level) < null_threshold_db
    is_poor_coherence = coherence < min_coherence_for_boost

    null_mask = is_deep_null | is_poor_coherence

    # For any frequency in null_mask, NEVER allow boost (gain > 0)
    filtered[null_mask & (filtered > 0.0)] = 0.0

    return filtered
