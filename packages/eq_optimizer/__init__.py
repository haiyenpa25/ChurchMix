"""
eq_optimizer package:
- Conservative PEQ recommendation engine for church audio
- Normalization mapping between physical acoustic units (Hz, dB, Q) and Behringer X32 values (0.0 - 1.0)
- Preserves vocal warmth while eliminating room mud and feedback
- Frequency response simulation for A/B preview
"""

from .recommender import (
    PEQBandProposal,
    ChannelTuningProposal,
    PEQRecommender,
    freq_to_x32,
    x32_to_freq,
    gain_to_x32,
    x32_to_gain,
    q_to_x32,
    x32_to_q,
)

__all__ = [
    "PEQBandProposal",
    "ChannelTuningProposal",
    "PEQRecommender",
    "freq_to_x32",
    "x32_to_freq",
    "gain_to_x32",
    "x32_to_gain",
    "q_to_x32",
    "x32_to_q",
]
