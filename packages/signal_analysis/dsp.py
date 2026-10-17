"""
Core Audio DSP Engine for X32 Sound Engineer.
- High precision float32 operations with NumPy & SciPy
- Standard acoustic metrics: RMS, Peak dBFS, Crest factor, Clipping detection
- Spectral analysis: Welch PSD with Hann window, 1/12-octave RTA bars for 60fps UI
- Synthetic test signal generators (Sine, Vocal Harmonic Tone, Pink Noise)
"""

from __future__ import annotations
import math
from functools import lru_cache
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import numpy as np
from scipy import signal


@dataclass
class AudioFrame:
    samples: np.ndarray # 1D float32 normalized -1.0 to 1.0
    sample_rate: int = 48000
    channel_id: int = 1
    timestamp: float = 0.0

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate


def calculate_rms_dbfs(samples: np.ndarray) -> float:
    """Calculate RMS level in dBFS."""
    if len(samples) == 0:
        return -120.0
    mean_sq = np.mean(np.square(samples))
    if mean_sq <= 1e-12:
        return -120.0
    rms = math.sqrt(mean_sq)
    return max(-120.0, 20.0 * math.log10(rms))


def calculate_peak_dbfs(samples: np.ndarray) -> float:
    """Calculate Peak level in dBFS."""
    if len(samples) == 0:
        return -120.0
    peak = np.max(np.abs(samples))
    if peak <= 1e-6:
        return -120.0
    return max(-120.0, 20.0 * math.log10(peak))


def calculate_crest_factor(samples: np.ndarray) -> float:
    """Calculate Crest Factor in dB: 20 * log10(Peak / RMS)."""
    peak_db = calculate_peak_dbfs(samples)
    rms_db = calculate_rms_dbfs(samples)
    if peak_db <= -100 or rms_db <= -100:
        return 0.0
    return max(0.0, peak_db - rms_db)


def detect_clipping(samples: np.ndarray, threshold: float = 0.999) -> Tuple[int, bool]:
    """Detect if audio frame contains clipped samples near 0 dBFS."""
    clip_count = int(np.sum(np.abs(samples) >= threshold))
    is_clipping = clip_count > 0
    return clip_count, is_clipping


def compute_welch_spectrum(
    samples: np.ndarray,
    sample_rate: int = 48000,
    nperseg: int = 2048,
    noverlap: int = 1024,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Power Spectral Density (PSD) using Welch's method with Hann window.
    Returns: (frequencies_hz, psd_dbfs)
    """
    if len(samples) < nperseg:
        # Pad with zeros if shorter than window
        padded = np.zeros(nperseg, dtype=np.float32)
        padded[:len(samples)] = samples
        samples = padded

    freqs, psd = signal.welch(
        samples,
        fs=sample_rate,
        window='hann',
        nperseg=nperseg,
        noverlap=noverlap,
        scaling='spectrum',
    )
    # Convert power to dBFS (reference 1.0 peak sine = 0 dBFS)
    psd_clean = np.maximum(psd, 1e-12)
    psd_dbfs = 10.0 * np.log10(psd_clean)
    return freqs, psd_dbfs


@lru_cache(maxsize=16)
def _rta_band_plan(freq_bytes: bytes, dtype: str, fraction: int, f_min: float, f_max: float):
    """Cache only band geometry and bin selections, never measured levels."""
    freqs = np.frombuffer(freq_bytes, dtype=np.dtype(dtype))
    sorted_grid = bool(np.all(freqs[:-1] <= freqs[1:]))
    ratio = 2.0 ** (1.0 / (2.0 * fraction))
    k_min = math.floor(fraction * math.log2(f_min / 1000.0))
    k_max = math.ceil(fraction * math.log2(f_max / 1000.0))
    plan = []
    for k in range(k_min, k_max + 1):
        center = 1000.0 * (2.0 ** (k / fraction))
        if not f_min <= center <= f_max:
            continue
        lower, upper = center / ratio, center * ratio
        if sorted_grid:
            start, stop = np.searchsorted(freqs, [lower, upper], side="left")
            selection = slice(int(start), int(stop))
        else:
            selection = np.flatnonzero((freqs >= lower) & (freqs < upper))
            selection.setflags(write=False)
        plan.append((round(center, 1), round(lower, 1), round(upper, 1), selection))
    return tuple(plan)


def compute_fractional_octave_rta(
    freqs: np.ndarray,
    psd_dbfs: np.ndarray,
    fraction: int = 12,
    f_min: float = 20.0,
    f_max: float = 20000.0,
) -> List[Dict[str, float]]:
    """
    Aggregate spectrum into standard 1/12th or 1/24th octave RTA bands.
    Center frequencies calculated via: f_c = 1000 * 2^(k / fraction).
    """
    bands: List[Dict[str, float]] = []
    plan = _rta_band_plan(freqs.tobytes(), freqs.dtype.str, fraction, f_min, f_max)
    for f_center, f_lower, f_upper, selection in plan:
        values = psd_dbfs[selection]
        # Preserve the existing peak-per-band display, including empty bands.
        band_level = float(np.max(values)) if values.size else -120.0

        bands.append({
            "center_freq": f_center,
            "lower_freq": f_lower,
            "upper_freq": f_upper,
            "level_dbfs": round(band_level, 2),
        })

    return bands


# --- Synthetic Audio Generators for Replay & Tests ---

def generate_sine_wave(
    freq_hz: float,
    duration_s: float,
    sample_rate: int = 48000,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Generate a clean sine tone (useful for simulating isolated feedback spike)."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False, dtype=np.float32)
    return amplitude * np.sin(2.0 * np.pi * freq_hz * t)


def generate_vocal_note(
    fundamental_hz: float,
    duration_s: float,
    sample_rate: int = 48000,
    harmonics: Optional[List[Tuple[float, float]]] = None,
) -> np.ndarray:
    """
    Generate a realistic vocal singing note containing natural harmonic overtones.
    Default harmonics: (2f: 0.5x, 3f: 0.3x, 4f: 0.15x, 5f: 0.08x) with subtle musical vibrato.
    """
    num_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, num_samples, endpoint=False, dtype=np.float32)

    # Subtle 5Hz vibrato (depth = 0.8% = ~14 cents)
    vib_freq = 5.0
    vib_depth = 0.008
    # Integral of 2*pi*(f0 + f0*depth*sin(2*pi*fv*t)) dt
    phase = 2.0 * np.pi * fundamental_hz * t - (fundamental_hz * vib_depth / vib_freq) * np.cos(2.0 * np.pi * vib_freq * t)

    signal_out = np.sin(phase)

    harm_specs = harmonics or [(2.0, 0.5), (3.0, 0.3), (4.0, 0.15), (5.0, 0.08)]
    for multiplier, rel_amp in harm_specs:
        signal_out += rel_amp * np.sin(multiplier * phase)

    max_val = np.max(np.abs(signal_out))
    if max_val > 0:
        signal_out = (signal_out / max_val) * 0.5
    return signal_out.astype(np.float32)


def generate_pink_noise(
    duration_s: float,
    sample_rate: int = 48000,
    amplitude: float = 0.3,
) -> np.ndarray:
    """Generate pink noise (equal energy per fraction octave) via Voss-McCartney algorithm."""
    num_samples = int(sample_rate * duration_s)
    # Simple 1/f filter approximation
    white = np.random.normal(0, 1, num_samples).astype(np.float32)
    # IIR filter for -3dB/octave slope
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.522189400]
    pink = signal.lfilter(b, a, white)
    max_val = np.max(np.abs(pink))
    if max_val > 0:
        pink = (pink / max_val) * amplitude
    return pink.astype(np.float32)
