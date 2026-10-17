"""
Sprint 19 Test Suite: Broadcast & Livestream Loudness (ITU-R BS.1770-4 / EBU R128)
and Church Livestream Safety Invariant Guard.
===================================================================================
Tests:
1. ITU-R BS.1770 K-weighting pre-filter frequency response.
2. Momentary (400ms), Short-Term (3s), and Integrated (Gated) LUFS calculations.
3. True Peak (dBTP) estimation with 4x polyphase oversampling.
4. BroadcastMixGuard compliance against streaming targets (YouTube -14, Sanctuary -18, EBU -23).
5. Hard Safety Invariant: DL16 In 11 (Band Talkback) isolation from Livestream Bus.
6. REST API endpoints: GET /api/v1/broadcast/loudness and POST /api/v1/broadcast/analyze.
"""
import unittest
import numpy as np
from fastapi.testclient import TestClient

from packages.mix_assistant.broadcast_meter import (
    apply_k_weighting,
    compute_true_peak_dbtp,
    compute_momentary_lufs,
    compute_short_term_lufs,
    compute_integrated_lufs,
    BroadcastMixGuard,
    LoudnessReport,
)
from apps.api.main import app


class TestSprint19BroadcastMeterAndGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_k_weighting_filter_properties(self):
        """Verify K-weighting high-shelf and RLB high-pass filter behavior."""
        sr = 48000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        
        # 1 kHz reference tone
        tone_1k = np.sin(2 * np.pi * 1000 * t).astype(np.float64)
        k_1k = apply_k_weighting(tone_1k, sample_rate=sr)
        rms_orig = np.sqrt(np.mean(tone_1k ** 2))
        rms_k1k = np.sqrt(np.mean(k_1k ** 2))
        # At 1 kHz, K-weighting gain is close to unity (within 1.5 dB)
        self.assertAlmostEqual(rms_k1k, rms_orig, delta=0.2)

        # 20 Hz sub-bass tone should be significantly attenuated by RLB stage
        tone_20hz = np.sin(2 * np.pi * 20 * t).astype(np.float64)
        k_20hz = apply_k_weighting(tone_20hz, sample_rate=sr)
        rms_k20hz = np.sqrt(np.mean(k_20hz ** 2))
        self.assertLess(rms_k20hz, rms_orig * 0.4, "RLB filter must attenuate sub-bass below 40 Hz")

    def test_lufs_calculations_standard_signals(self):
        """Test Momentary, Short-Term, and Integrated LUFS on controlled audio."""
        sr = 48000
        # 3 seconds of 1 kHz sine at 0 dBFS peak (amplitude = 1.0)
        t = np.linspace(0, 3.0, int(3.0 * sr), endpoint=False)
        tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)

        m_lufs = compute_momentary_lufs(tone, sample_rate=sr)
        s_lufs = compute_short_term_lufs(tone, sample_rate=sr)
        i_lufs = compute_integrated_lufs(tone, sample_rate=sr)

        # Theoretical LUFS for full-scale 1kHz sine is approximately -3.0 LUFS
        self.assertAlmostEqual(m_lufs, -3.0, delta=0.5)
        self.assertAlmostEqual(s_lufs, -3.0, delta=0.5)
        self.assertAlmostEqual(i_lufs, -3.0, delta=0.5)

        # Digital silence must produce floor of -120 LUFS
        silence = np.zeros(sr, dtype=np.float32)
        self.assertEqual(compute_momentary_lufs(silence), -120.0)
        self.assertEqual(compute_short_term_lufs(silence), -120.0)
        self.assertEqual(compute_integrated_lufs(silence), -120.0)

    def test_true_peak_polyphase_oversampling(self):
        """Test 4x polyphase True Peak (dBTP) estimation."""
        # Amplitude 0.5 is -6.02 dBFS
        sr = 48000
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)
        sig = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)

        tp = compute_true_peak_dbtp(sig, oversample=4)
        self.assertAlmostEqual(tp, -6.02, delta=0.2)

        # Silence True Peak
        self.assertEqual(compute_true_peak_dbtp(np.array([], dtype=np.float32)), -120.0)

    def test_integrated_gated_loudness(self):
        """Verify integrated loudness dual gating (-70 LUFS abs and -10 dB rel)."""
        sr = 48000
        t1 = np.linspace(0, 2.0, int(2.0 * sr), endpoint=False)
        # Active loud signal: 2 seconds tone
        sig1 = 0.5 * np.sin(2 * np.pi * 1000 * t1).astype(np.float32)
        # 3 seconds silence
        sig2 = np.zeros(int(3.0 * sr), dtype=np.float32)
        combined = np.concatenate([sig1, sig2])

        # Integrated loudness should gate out the 3 seconds silence
        i_active = compute_integrated_lufs(sig1, sample_rate=sr)
        i_combined = compute_integrated_lufs(combined, sample_rate=sr)

        # Due to gating, the silence should not drag loudness down by more than 1 dB
        self.assertAlmostEqual(i_combined, i_active, delta=1.0)

    def test_talkback_isolation_invariant_verification(self):
        """
        Hard Invariant: DL16 In 11 (Band Talkback) must NEVER route to Livestream Bus or Main LR.
        """
        # Case 1: Clean safe state
        safe_state = {
            "/ch/11/mix/05/on": 0,
            "/ch/11/mix/st": 0,
        }
        is_safe, msg = BroadcastMixGuard.verify_livestream_talkback_isolation(safe_state, livestream_bus=5)
        self.assertTrue(is_safe)
        self.assertIn("VERIFIED SAFE", msg)

        # Case 2: Violation on Livestream MixBus 5
        leaking_bus_state = {
            "/ch/11/mix/05/on": 1,
            "/ch/11/mix/st": 0,
        }
        is_safe, msg = BroadcastMixGuard.verify_livestream_talkback_isolation(leaking_bus_state, livestream_bus=5)
        self.assertFalse(is_safe)
        self.assertIn("CRITICAL INVARIANT VIOLATION", msg)
        self.assertIn("Bus 05", msg)

        # Case 3: Violation on Stereo Main LR
        leaking_st_state = {
            "/ch/11/mix/05/on": 0,
            "/ch/11/mix/st": 1,
        }
        is_safe, msg = BroadcastMixGuard.verify_livestream_talkback_isolation(leaking_st_state, livestream_bus=5)
        self.assertFalse(is_safe)
        self.assertIn("CRITICAL INVARIANT VIOLATION", msg)
        self.assertIn("Main Stereo Bus", msg)

    def test_broadcast_compliance_evaluation(self):
        """Verify compliance status: OPTIMAL, TOO_QUIET, TOO_LOUD, PEAK_WARNING."""
        sr = 48000
        t = np.linspace(0, 2.0, int(2.0 * sr), endpoint=False)

        # Target -14 LUFS for YouTube streaming
        # Amplitude ~0.28 gives ~ -14 LUFS
        sig_optimal = 0.28 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        report_opt = BroadcastMixGuard.evaluate_loudness(
            signal=sig_optimal,
            sample_rate=sr,
            target_profile="YOUTUBE_STREAMING",
            state_dict={"/ch/11/mix/05/on": 0, "/ch/11/mix/st": 0},
            livestream_bus=5,
        )
        self.assertEqual(report_opt.compliance_status, "OPTIMAL")
        self.assertTrue(report_opt.talkback_isolated)

        # Very quiet signal (-30 LUFS)
        sig_quiet = 0.03 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        report_quiet = BroadcastMixGuard.evaluate_loudness(
            signal=sig_quiet,
            sample_rate=sr,
            target_profile="YOUTUBE_STREAMING",
        )
        self.assertEqual(report_quiet.compliance_status, "TOO_QUIET")
        self.assertIn("tăng Makeup Gain", report_quiet.recommendation_vi)

        # Too loud signal (-5 LUFS)
        sig_loud = 0.8 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        report_loud = BroadcastMixGuard.evaluate_loudness(
            signal=sig_loud,
            sample_rate=sr,
            target_profile="YOUTUBE_STREAMING",
        )
        # Note: at 0.8 amplitude, peak is -1.9 dBFS, but if true peak exceeds -1.0 dBTP it could be PEAK_WARNING or TOO_LOUD
        self.assertIn(report_loud.compliance_status, ["TOO_LOUD", "PEAK_WARNING"])

        # Signal with clipping peak > -1.0 dBTP
        sig_clipped = 1.05 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        report_clipped = BroadcastMixGuard.evaluate_loudness(
            signal=sig_clipped,
            sample_rate=sr,
            target_profile="YOUTUBE_STREAMING",
        )
        self.assertEqual(report_clipped.compliance_status, "PEAK_WARNING")
        self.assertIn("TRUE PEAK", report_clipped.recommendation_vi)

    def test_rest_api_broadcast_endpoints(self):
        """Test GET /api/v1/broadcast/loudness and POST /api/v1/broadcast/analyze."""
        # 1. GET /api/v1/broadcast/loudness
        res_get = self.client.get("/api/v1/broadcast/loudness?target_profile=YOUTUBE_STREAMING&livestream_bus=5")
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()

        self.assertIn("momentary_lufs", data_get)
        self.assertIn("short_term_lufs", data_get)
        self.assertIn("integrated_lufs", data_get)
        self.assertIn("true_peak_dbtp", data_get)
        self.assertIn("target_lufs", data_get)
        self.assertIn("compliance_status", data_get)
        self.assertIn("recommendation_vi", data_get)
        self.assertIn("talkback_isolated", data_get)
        self.assertTrue(data_get["talkback_isolated"])
        self.assertEqual(data_get["target_profile"], "YOUTUBE_STREAMING")

        # 2. POST /api/v1/broadcast/analyze
        res_post = self.client.post(
            "/api/v1/broadcast/analyze",
            json={"target_profile": "EBU_R128_TV", "livestream_bus": 6},
        )
        self.assertEqual(res_post.status_code, 200)
        data_post = res_post.json()
        self.assertEqual(data_post["target_profile"], "EBU_R128_TV")
        self.assertEqual(data_post["target_lufs"], -23.0)


if __name__ == "__main__":
    unittest.main()
