"""
Sprint 3 Test Suite:
- Audio DSP Metrics (RMS, Peak dBFS, Crest Factor, Clipping)
- Welch PSD & 1/12-Octave RTA Spectrum
- Acoustic Feedback Detection on Isolated Resonance
- False-Positive Prevention on Sustained Singer Note (Harmonic Rejection)
"""

import unittest
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.signal_analysis.dsp import (
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
from packages.feedback_detector.detector import FeedbackDetector, FeedbackCandidate


class TestSprint3DSP(unittest.TestCase):
    def test_dsp_metrics_sine(self):
        # 0.5 amplitude sine -> peak is -6.02 dBFS, RMS is -9.03 dBFS
        samples = generate_sine_wave(freq_hz=1000.0, duration_s=0.5, amplitude=0.5)

        peak_db = calculate_peak_dbfs(samples)
        self.assertAlmostEqual(peak_db, -6.02, places=1)

        rms_db = calculate_rms_dbfs(samples)
        self.assertAlmostEqual(rms_db, -9.03, places=1)

        crest_db = calculate_crest_factor(samples)
        self.assertAlmostEqual(crest_db, 3.01, places=1)

        clip_count, is_clip = detect_clipping(samples)
        self.assertEqual(clip_count, 0)
        self.assertFalse(is_clip)

    def test_clipping_detection(self):
        samples = np.array([0.5, -0.8, 1.0, 0.9995, -1.0], dtype=np.float32)
        count, is_clip = detect_clipping(samples, threshold=0.999)
        self.assertTrue(is_clip)
        self.assertEqual(count, 3)

    def test_welch_and_12th_octave_rta(self):
        # 1000 Hz sine wave
        samples = generate_sine_wave(freq_hz=1000.0, duration_s=0.5, amplitude=0.5)
        freqs, psd = compute_welch_spectrum(samples, sample_rate=48000)

        # Peak frequency in Welch spectrum
        max_idx = np.argmax(psd)
        peak_freq = freqs[max_idx]
        self.assertTrue(980.0 <= peak_freq <= 1020.0, f"Expected ~1000Hz, got {peak_freq}Hz")

        # 1/12th octave RTA
        rta_bands = compute_fractional_octave_rta(freqs, psd, fraction=12)
        self.assertGreater(len(rta_bands), 20)

        # The 1000 Hz band should have the highest level
        max_band = max(rta_bands, key=lambda b: b["level_dbfs"])
        self.assertTrue(950.0 <= max_band["center_freq"] <= 1050.0)

    def test_feedback_detection_on_isolated_resonance(self):
        """Simulate real feedback: pure isolated sine squeal at 2500 Hz growing over frames."""
        detector = FeedbackDetector(min_prominence_db=12.0, min_persistence_frames=3, confidence_threshold=0.70)
        candidates = []

        # Stream 4 consecutive frames of growing 2500 Hz resonance
        for i in range(4):
            amp = 0.2 + (i * 0.1) # Growing amplitude
            raw_audio = generate_sine_wave(freq_hz=2500.0, duration_s=0.1, amplitude=amp)
            # Add small background noise
            noise = np.random.normal(0, 0.005, len(raw_audio)).astype(np.float32)
            frame = AudioFrame(samples=raw_audio + noise, channel_id=3, timestamp=i * 0.1)
            candidates = detector.process_frame(frame)

        # On frame 4, persistence is >= 3 and confidence should trigger candidate
        self.assertGreater(len(candidates), 0, "Detector should identify 2500Hz feedback")
        cand = candidates[0]
        self.assertEqual(cand.channel_id, 3)
        self.assertTrue(2480.0 <= cand.freq_hz <= 2520.0)
        self.assertGreaterEqual(cand.confidence, 0.70)
        self.assertFalse(cand.is_musical_note, "Isolated spike must not be flagged as musical note")
        self.assertIn("Tonality", cand.evidence[0])

    def test_false_alarm_prevention_on_sustained_singer_note(self):
        """
        CRITICAL TEST: Lead singer holds high note A4 (440 Hz) for 5 frames.
        Natural voice contains rich harmonics: 880 Hz, 1320 Hz, 1760 Hz.
        Detector must NOT raise feedback alarm!
        """
        detector = FeedbackDetector(min_prominence_db=12.0, min_persistence_frames=3, confidence_threshold=0.70)
        candidates = []

        # Stream 5 frames of singer holding note
        for i in range(5):
            vocal_audio = generate_vocal_note(fundamental_hz=440.0, duration_s=0.1)
            frame = AudioFrame(samples=vocal_audio, channel_id=1, timestamp=i * 0.1)
            candidates = detector.process_frame(frame)

        # Detector should reject this as a vocal singing note and NOT emit high-confidence feedback alarms
        high_conf_feedback = [c for c in candidates if c.confidence >= 0.70]
        self.assertEqual(
            len(high_conf_feedback),
            0,
            f"Singing voice was falsely flagged as feedback: {high_conf_feedback}"
        )


if __name__ == "__main__":
    unittest.main()
