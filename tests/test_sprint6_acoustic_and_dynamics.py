"""
Sprint 6 Test Suite:
- Acoustic Measurement: H1 Transfer Function, Coherence, Delay
- Spatial Multi-Position Averaging
- Hard Rule Enforcement: No-Boost-in-Nulls
- Open Sound Meter (OSM) & FRD File Parsers
- Voice Activity Detection (VAD) & Silence Hold (No Gain on Silence)
- Anti-Clipping Guard
"""

import unittest
import os
import sys
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.signal_analysis.dsp import AudioFrame, generate_pink_noise, generate_sine_wave
from packages.acoustic_measurement.transfer_function import (
    compute_transfer_function,
    estimate_delay_samples,
    spatial_average_transfer_functions,
    filter_no_boost_nulls,
)
from packages.acoustic_measurement.osm_importer import (
    parse_osm_csv,
    export_osm_csv,
    parse_frd_file,
    AcousticMeasurementData,
)
from packages.mix_assistant.leveler import (
    VoiceActivityDetector,
    AntiClippingGuard,
    SpeechLeveler,
)


class TestSprint6AcousticAndDynamics(unittest.TestCase):
    def test_transfer_function_and_delay_estimation(self):
        # Generate 1 sec pink noise reference
        ref = generate_pink_noise(duration_s=0.5, sample_rate=48000, amplitude=0.4)
        
        # Simulate acoustic delay of 144 samples (3.0 ms time-of-flight)
        delay_expected_samples = 144
        meas = np.zeros_like(ref)
        meas[delay_expected_samples:] = ref[:-delay_expected_samples] * 0.8 # -2dB room attenuation

        # Add small ambient room noise
        meas += np.random.normal(0, 0.005, len(meas)).astype(np.float32)

        delay_samples, delay_ms = estimate_delay_samples(ref, meas)
        self.assertAlmostEqual(delay_samples, delay_expected_samples, delta=5)
        self.assertAlmostEqual(delay_ms, 3.0, delta=0.2)

        # Compute Transfer Function H1
        tf_result = compute_transfer_function(ref, meas, sample_rate=48000, nperseg=1024, noverlap=512)
        self.assertEqual(len(tf_result.freqs), len(tf_result.magnitude_db))
        
        # Check coherence in high SNR band
        mid_freq_mask = (tf_result.freqs >= 300) & (tf_result.freqs <= 3000)
        avg_coherence = float(np.mean(tf_result.coherence[mid_freq_mask]))
        self.assertGreater(avg_coherence, 0.70, "Coherence should be high for correlated pink noise")

    def test_no_boost_in_nulls_rule(self):
        """CRITICAL CHURCH RULE: Never boost acoustic phase cancellation nulls."""
        freqs = np.linspace(100, 5000, 50)
        # Deep null of -18dB at 250Hz due to floor reflection
        raw_mag = np.zeros(50, dtype=np.float32)
        raw_mag[10] = -18.0 # Deep null
        coherence = np.ones(50, dtype=np.float32)
        coherence[10] = 0.20 # Low coherence in cancellation null

        # Naive target attempts to boost +12dB to fill the null
        target_gain = np.zeros(50, dtype=np.float32)
        target_gain[10] = 12.0 # Dangerous boost!

        safe_gain = filter_no_boost_nulls(target_gain, coherence, raw_mag)
        self.assertEqual(safe_gain[10], 0.0, "Boost in deep acoustic null must be strictly clamped to 0dB!")

    def test_osm_csv_and_frd_parsers(self):
        sample_osm_csv = """# Open Sound Meter export
Frequency (Hz),Magnitude (dB),Phase (deg),Coherence
100.0,-2.5,12.3,0.92
1000.0,1.2,-45.0,0.98
5000.0,-6.0,120.0,0.85
"""
        data = parse_osm_csv(sample_osm_csv, name="Hall_Center_Seat")
        self.assertEqual(len(data.freqs), 3)
        self.assertAlmostEqual(float(data.freqs[1]), 1000.0)
        self.assertAlmostEqual(float(data.coherence[1]), 0.98)

        # Test export
        exported = export_osm_csv(data)
        self.assertIn("1000.0", exported)
        self.assertIn("0.98", exported)

        # Test FRD format
        sample_frd = """100.0 -2.5 12.3
1000.0 1.2 -45.0
5000.0 -6.0 120.0"""
        frd_data = parse_frd_file(sample_frd, name="Speaker_Response")
        self.assertEqual(len(frd_data.freqs), 3)

    def test_silence_hold_prevents_upward_gain(self):
        """CRITICAL AUTOMIX RULE: Silence Hold must freeze fader when speaker is silent."""
        leveler = SpeechLeveler(target_rms_db=-20.0)

        # Very low ambient room noise (-65 dBFS)
        silent_samples = np.random.normal(0, 0.0005, 4800).astype(np.float32)
        frame = AudioFrame(samples=silent_samples, channel_id=1, timestamp=0.0)

        current_fader = 0.70
        action = leveler.process(frame, current_fader)

        self.assertEqual(action.action_type, "HOLD")
        self.assertEqual(action.fader_delta, 0.0, "Fader delta must be 0.0 on silence")
        self.assertEqual(action.target_fader, current_fader)
        self.assertIn("SILENCE HOLD", action.rationale)

    def test_anti_clipping_guard_triggers_downward_nudge(self):
        leveler = SpeechLeveler(target_rms_db=-20.0)

        # Loud distorted signal with digital clipping (sample = 1.0)
        clipped_samples = generate_sine_wave(freq_hz=1000.0, duration_s=0.1, amplitude=1.2)
        frame = AudioFrame(samples=clipped_samples, channel_id=1, timestamp=0.0)

        current_fader = 0.80
        action = leveler.process(frame, current_fader)

        self.assertEqual(action.action_type, "ANTI_CLIP")
        self.assertLess(action.fader_delta, 0.0, "Anti-clip must nudge fader downward")
        self.assertAlmostEqual(action.target_fader, 0.74, places=2)
        self.assertIn("ANTI-CLIP", action.rationale)


if __name__ == "__main__":
    unittest.main()
