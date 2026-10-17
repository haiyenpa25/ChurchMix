"""
Sprint 4 Test Suite:
- Normalization Unit Conversions (Hz, dB, Q <-> X32 0.0 - 1.0 floats)
- Pastor / Speech Tuning Recommender
- Feedback Candidate Notch Filter Generator
- End-to-End Execution with TransactionExecutor & Mock X32
- Frequency Response Simulation (A/B Preview Curve)
"""

import unittest
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.x32_osc_adapter.client import X32Client
from packages.mock_x32.server import MockX32Server
from packages.safety_controller.transaction import TransactionExecutor, SafetyPolicy
from packages.feedback_detector.detector import FeedbackCandidate
from packages.eq_optimizer.recommender import (
    freq_to_x32,
    x32_to_freq,
    gain_to_x32,
    x32_to_gain,
    q_to_x32,
    x32_to_q,
    PEQRecommender,
    PEQBandProposal,
)


class TestSprint4PEQ(unittest.TestCase):
    SERVER_PORT = 10027

    @classmethod
    def setUpClass(cls):
        cls.server = MockX32Server(host="127.0.0.1", port=cls.SERVER_PORT)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.client = X32Client(host="127.0.0.1", port=self.SERVER_PORT, read_only_mode=True, timeout=1.0)
        self.client.connect()
        self.executor = TransactionExecutor(client=self.client)
        self.recommender = PEQRecommender()

    def tearDown(self):
        self.client.close()

    def test_float_conversions_roundtrip(self):
        # Frequency conversions
        for test_f in [30.0, 100.0, 440.0, 1000.0, 5000.0, 16000.0]:
            x_val = freq_to_x32(test_f)
            self.assertTrue(0.0 <= x_val <= 1.0)
            f_back = x32_to_freq(x_val)
            self.assertAlmostEqual(test_f, f_back, delta=test_f * 0.05)

        # Gain conversions (-15 to +15 dB, 0.5 = 0 dB)
        self.assertAlmostEqual(gain_to_x32(0.0), 0.5, places=2)
        self.assertAlmostEqual(x32_to_gain(0.5), 0.0, places=2)
        for test_g in [-12.0, -3.5, 0.0, 2.5, 10.0]:
            x_val = gain_to_x32(test_g)
            self.assertTrue(0.0 <= x_val <= 1.0)
            g_back = x32_to_gain(x_val)
            self.assertAlmostEqual(test_g, g_back, delta=0.2)

        # Q factor conversions
        for test_q in [0.5, 1.4, 4.0, 7.0]:
            x_val = q_to_x32(test_q)
            self.assertTrue(0.0 <= x_val <= 1.0)
            q_back = x32_to_q(x_val)
            self.assertAlmostEqual(test_q, q_back, delta=0.3)

    def test_pastor_speech_recommendation_and_execution(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)
        proposal, tuning_detail = self.recommender.recommend_pastor_speech(
            channel_id=1,
            expected_sha256=snapshot.sha256,
        )

        self.assertEqual(proposal.target_channel, 1)
        self.assertGreaterEqual(proposal.confidence, 0.80)
        self.assertEqual(tuning_detail.role, "PASTOR_SPEECH")
        self.assertEqual(tuning_detail.hpf_freq_hz, 85.0)

        # Approve and execute via Safety Gate
        proposal.approve("sound_tech_hai")
        result = self.executor.execute(proposal, "sound_tech_hai")
        self.assertEqual(result["status"], "SUCCESS")

        # Verify Mock X32 updated
        new_hpon = self.client.query("/ch/01/preamp/hpon")[0]
        self.assertEqual(new_hpon, 1)

    def test_feedback_notch_recommendation_and_execution(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)
        candidate = FeedbackCandidate(
            channel_id=3,
            freq_hz=2480.0,
            confidence=0.85,
            severity="HIGH",
            level_dbfs=-15.0,
            persistence_frames=4,
            is_musical_note=False,
            evidence=["Narrowband prominence +42dB"],
            recommended_action="Apply notch",
        )

        notch_proposal = self.recommender.recommend_feedback_notch(
            candidate=candidate,
            expected_sha256=snapshot.sha256,
            preferred_band=3,
        )

        self.assertEqual(notch_proposal.target_channel, 3)
        notch_proposal.approve("operator_hai")

        result = self.executor.execute(notch_proposal, "operator_hai")
        self.assertEqual(result["status"], "SUCCESS")

        # Verify Band 3 Gain was cut on Channel 3
        b3_gain = self.client.query("/ch/03/eq/3/g")[0]
        actual_db = x32_to_gain(b3_gain)
        self.assertAlmostEqual(actual_db, -3.5, delta=0.5)

    def test_frequency_response_simulation(self):
        bands = [
            PEQBandProposal(1, "PEQ", freq_hz=250.0, gain_db=-2.0, q_factor=1.5, rationale="Mud cut"),
            PEQBandProposal(2, "PEQ", freq_hz=2800.0, gain_db=+1.5, q_factor=1.2, rationale="Presence"),
        ]
        curve = self.recommender.simulate_response(hpf_freq=85.0, bands=bands, num_points=60)
        self.assertEqual(len(curve), 60)

        # Verify HPF roll-off below 50 Hz
        low_pt = next(pt for pt in curve if pt["freq"] <= 40.0)
        self.assertLess(low_pt["response_db"], -10.0, "HPF must roll off sub-frequencies")

        # Verify ~250 Hz dip
        mid_pt = min(curve, key=lambda pt: abs(pt["freq"] - 250.0))
        self.assertLess(mid_pt["response_db"], -0.5, "Should have dip around 250 Hz")

        # Verify ~2800 Hz boost
        pres_pt = min(curve, key=lambda pt: abs(pt["freq"] - 2800.0))
        self.assertGreater(pres_pt["response_db"], 0.5, "Should have boost around 2.8 kHz")

    def test_recommend_role_various_church_instruments(self):
        roles_to_test = [
            ("LEAD_VOCAL_FEMALE", 110.0, 3),
            ("LEAD_VOCAL_MALE", 75.0, 2),
            ("CHOIR_OVERHEAD", 130.0, 2),
            ("ACOUSTIC_GUITAR", 80.0, 3),
            ("PIANO_KEYS", 40.0, 2),
            ("BASS_GUITAR", 35.0, 3),
        ]
        snapshot = self.client.take_full_snapshot(max_channels=32)

        for role, expected_hpf, expected_bands_count in roles_to_test:
            prop, detail = self.recommender.recommend_role(
                channel_id=5,
                role=role,
                expected_sha256=snapshot.sha256,
            )
            self.assertEqual(prop.target_channel, 5)
            self.assertEqual(detail.role, role)
            self.assertEqual(detail.hpf_freq_hz, expected_hpf)
            self.assertEqual(len(detail.bands), expected_bands_count)
            self.assertTrue(len(detail.expected_tradeoffs) >= 1)
            self.assertTrue(len(detail.simulated_curve) > 0)


if __name__ == "__main__":
    unittest.main()
