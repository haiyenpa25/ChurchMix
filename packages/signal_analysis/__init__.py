"""
signal_analysis package:
- Real-time Audio DSP
- RMS, Peak dBFS, Crest Factor, Clipping Detection
- Welch PSD and 1/12-Octave RTA Spectrum
- Synthetic Audio Generators for Offline Testing
"""

from .dsp import (
    AudioFrame,
    calculate_rms_dbfs,
    calculate_peak_dbfs,
    calculate_crest_factor,
    detect_clipping,
    compute_welch_spectrum,
    compute_fractional_octave_rta,
    generate_sine_wave,
    generate_vocal_note,
    generate_pink_noise,
)

__all__ = [
    "AudioFrame",
    "calculate_rms_dbfs",
    "calculate_peak_dbfs",
    "calculate_crest_factor",
    "detect_clipping",
    "compute_welch_spectrum",
    "compute_fractional_octave_rta",
    "generate_sine_wave",
    "generate_vocal_note",
    "generate_pink_noise",
]
