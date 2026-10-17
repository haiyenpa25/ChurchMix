"""
Feedback Candidate Detector with Multi-Evidence Fusion and Harmonic Rejection.
Ensures church vocal sustained notes (singers holding high notes, organ, bells)
are NOT falsely classified as feedback.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import numpy as np
from scipy import signal

from packages.signal_analysis.dsp import AudioFrame, compute_welch_spectrum


@dataclass
class FeedbackCandidate:
    channel_id: int
    freq_hz: float
    confidence: float # 0.0 to 1.0
    severity: str     # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    level_dbfs: float
    persistence_frames: int
    is_musical_note: bool
    evidence: List[str]
    recommended_action: str
    timestamp: float = 0.0


class FeedbackDetector:
    def __init__(
        self,
        min_prominence_db: float = 14.0,
        min_persistence_frames: int = 3,
        confidence_threshold: float = 0.70,
        history_len: int = 10,
    ):
        self.min_prominence_db = min_prominence_db
        self.min_persistence_frames = min_persistence_frames
        self.confidence_threshold = confidence_threshold
        self.history_len = history_len

        # Sliding history: channel_id -> list of (timestamp, [(freq_hz, level_dbfs)])
        self.channel_history: Dict[int, List[Tuple[float, List[Tuple[float, float]]]]] = {}

    def process_frame(self, frame: AudioFrame) -> List[FeedbackCandidate]:
        """
        Analyze an AudioFrame and return high-confidence feedback candidates.
        Guaranteed: Will NOT trigger write commands to mixer.
        """
        ch = frame.channel_id
        if ch not in self.channel_history:
            self.channel_history[ch] = []

        # 1. Compute PSD
        freqs, psd = compute_welch_spectrum(frame.samples, frame.sample_rate)

        # Restrict search to typical feedback range (100 Hz to 12,000 Hz)
        mask = (freqs >= 100.0) & (freqs <= 12000.0)
        sub_freqs = freqs[mask]
        sub_psd = psd[mask]

        if len(sub_psd) == 0:
            return []

        # Find prominent narrow spectral peaks
        peaks_indices, properties = signal.find_peaks(
            sub_psd,
            prominence=self.min_prominence_db,
            distance=20, # At least ~20 bins between peaks
        )

        current_frame_peaks: List[Tuple[float, float]] = []
        for idx in peaks_indices:
            peak_f = float(sub_freqs[idx])
            peak_lvl = float(sub_psd[idx])
            current_frame_peaks.append((peak_f, peak_lvl))

        # Update sliding history
        self.channel_history[ch].append((frame.timestamp, current_frame_peaks))
        if len(self.channel_history[ch]) > self.history_len:
            self.channel_history[ch].pop(0)

        candidates: List[FeedbackCandidate] = []
        median_floor = float(np.median(sub_psd)) if current_frame_peaks else 0.0

        # 2. Evaluate each peak against multi-evidence criteria
        for peak_f, peak_lvl in current_frame_peaks:
            evidence: List[str] = []

            # CRITERION 1: Narrowband Tonality
            # Prominence above local noise floor
            prominence = peak_lvl - median_floor
            tonality_score = min(1.0, max(0.0, (prominence - self.min_prominence_db) / 20.0))
            evidence.append(f"Tonality: Prominence is {prominence:.1f} dB above median noise floor")

            # CRITERION 2: Temporal Persistence
            # Check how many consecutive past frames saw this frequency (within 10 Hz)
            persistence = 1
            past_levels = [peak_lvl]

            for past_t, past_peaks in reversed(self.channel_history[ch][:-1]):
                found_match = False
                for pf, pl in past_peaks:
                    if abs(pf - peak_f) <= 12.0:
                        persistence += 1
                        past_levels.append(pl)
                        found_match = True
                        break
                if not found_match:
                    break

            persistence_score = min(1.0, persistence / float(self.min_persistence_frames))
            evidence.append(f"Persistence: Active across {persistence} consecutive analysis frames")

            # CRITERION 3: Growth Rate / Energy profile
            if len(past_levels) >= 2:
                # Comparison with oldest tracked level
                delta_db = past_levels[0] - past_levels[-1] # current minus oldest
                growth_rate = delta_db / max(0.1, (persistence * frame.duration_s))
                if delta_db >= 0:
                    growth_score = min(1.0, 0.5 + 0.5 * (growth_rate / 10.0))
                    evidence.append(f"Growth: Level climbing/sustained at {delta_db:+.1f} dB")
                else:
                    growth_score = max(0.0, 0.5 + 0.5 * (delta_db / 10.0))
                    evidence.append(f"Growth: Level decaying naturally ({delta_db:.1f} dB)")
            else:
                growth_score = 0.5

            # CRITERION 4: Harmonic Rejection (THE CRITICAL SINGER CHECK)
            # A human singer holding a note has integer harmonic overtones: 2f, 3f, 4f
            # Acoustic feedback is typically a single isolated resonance frequency.
            is_musical_note, harmonic_evidence = self._check_harmonics(peak_f, peak_lvl, current_frame_peaks)
            if is_musical_note:
                evidence.append(f"Harmonic Check: REJECTED AS SINGER NOTE ({harmonic_evidence})")
            else:
                evidence.append("Harmonic Check: Isolated resonance without musical harmonic overtones")

            # FUSION SCORING
            if is_musical_note:
                confidence = 0.05 # Almost certainly a singing voice or musical instrument!
            else:
                # Weighted fusion: tonality (35%), persistence (35%), growth (30%)
                confidence = (
                    0.35 * tonality_score +
                    0.35 * persistence_score +
                    0.30 * growth_score
                )

            # Determine severity based on absolute level & confidence
            if peak_lvl >= -12.0:
                severity = "CRITICAL"
            elif peak_lvl >= -24.0:
                severity = "HIGH"
            elif peak_lvl >= -36.0:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            if confidence >= self.confidence_threshold and persistence >= self.min_persistence_frames:
                rec_action = (
                    f"Check singer distance to monitor. If ring persists, "
                    f"propose conservative notch at {round(peak_f, 1)} Hz with Q >= 6.0 and a cut no deeper than -4.5 dB (default -3.5 dB)."
                )
                candidates.append(FeedbackCandidate(
                    channel_id=ch,
                    freq_hz=round(peak_f, 1),
                    confidence=round(confidence, 2),
                    severity=severity,
                    level_dbfs=round(peak_lvl, 1),
                    persistence_frames=persistence,
                    is_musical_note=is_musical_note,
                    evidence=evidence,
                    recommended_action=rec_action,
                    timestamp=frame.timestamp,
                ))

        return candidates

    def _check_harmonics(
        self,
        fund_f: float,
        fund_lvl: float,
        all_peaks: List[Tuple[float, float]],
        tolerance_pct: float = 0.08,
    ) -> Tuple[bool, str]:
        """
        Check if the peak is part of a harmonic series (2f, 3f, 4f, 5f) or has a fundamental below it.
        Harmonic candidates must have plausible musical levels (within 30 dB of fundamental).
        """
        matched_multiples = []

        for pf, pl in all_peaks:
            if abs(pf - fund_f) < 8.0:
                continue

            # Overtones must have plausible musical energy, not deep noise floor
            if abs(fund_lvl - pl) > 30.0:
                continue

            # Check 2nd, 3rd, 4th, 5th harmonics above
            ratio = pf / fund_f
            closest_int = round(ratio)
            if 2 <= closest_int <= 5:
                if abs(ratio - closest_int) <= tolerance_pct:
                    matched_multiples.append(f"{closest_int}f ({pf:.1f}Hz)")

            # Check if this peak itself is the 2nd, 3rd, 4th, 5th harmonic of a lower fundamental
            sub_ratio = fund_f / pf
            sub_int = round(sub_ratio)
            if 2 <= sub_int <= 5:
                if abs(sub_ratio - sub_int) <= tolerance_pct:
                    matched_multiples.append(f"fundamental at {pf:.1f}Hz (1/{sub_int}f)")

        if len(matched_multiples) >= 1:
            return True, f"Found harmonics: {', '.join(matched_multiples)}"

        return False, "No harmonic overtones found"
