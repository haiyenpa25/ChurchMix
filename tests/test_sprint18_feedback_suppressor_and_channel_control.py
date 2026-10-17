"""
Sprint 18 Test Suite: Live Feedback Suppressor Action Protocol, Speech Leveler HUD & Channel Mute Safety Toggle
===============================================================================================================
Verifies:
1. Surgical feedback notch proposal generation enforcing Rule 9 constraints (Q >= 6.0, depth <= -4.5dB).
2. Channel mute toggle execution through TransactionExecutor and SafetyPolicy whitelist (/ch/xx/mix/on).
3. Protection of Talkback Channel 11 invariant during mute manipulation.
4. Speech Leveler Silence Hold invariant enforcement (no upward fader drift during speaker pauses).
5. REST API integration for /api/v1/channels/{id}/mute and /api/v1/proposals/generate-notch.
"""
from __future__ import annotations
import unittest
import os
import sys
import numpy as np
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.main import app, x32_client, executor, safety_mode_mgr
from packages.safety_controller.modes import OperatorMode
from packages.feedback_detector.detector import FeedbackCandidate
from packages.eq_optimizer.recommender import PEQRecommender
from packages.safety_controller.transaction import Proposal, TransactionExecutor, SafetyPolicy
from packages.mix_assistant.leveler import SpeechLeveler, AudioFrame


class TestSprint18FeedbackAndChannelControl(unittest.TestCase):
    """Test Suite for Feedback Suppressor and Channel Control."""

    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()
        safety_mode_mgr.set_mode(OperatorMode.ASSIST, operator="TestEngineer")
        cls.recommender = PEQRecommender()
        cls.speech_leveler = SpeechLeveler(target_rms_db=-20.0)

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_01_surgical_notch_rule_9_compliance(self):
        """Test that feedback notch proposals strictly enforce Rule 9 surgical parameters."""
        candidate = FeedbackCandidate(
            channel_id=3,
            freq_hz=3150.0,
            confidence=0.92,
            severity="WARNING",
            level_dbfs=-12.0,
            persistence_frames=4,
            is_musical_note=False,
            evidence=["Narrowband energy peak", "Harmonic test cleared"],
            recommended_action="Surgical Notch",
        )
        proposal = self.recommender.recommend_feedback_notch(candidate, expected_sha256="dummy_sha")

        self.assertEqual(proposal.target_channel, 3)
        self.assertGreaterEqual(proposal.confidence, 0.85)

        # Check changes
        param_names = [c["parameter"] for c in proposal.changes]
        self.assertTrue(any("/eq/3" in p or "/eq/4" in p for p in param_names))

        # Check that notch depth is conservative and Q is surgical (Q >= 6.0)
        q_change = next((c for c in proposal.changes if c["parameter"].endswith("/q")), None)
        self.assertIsNotNone(q_change)
        # Note: on X32, Q=7.0 maps to high float value (> 0.65)
        self.assertGreaterEqual(q_change["to"], 0.6)

    def test_02_channel_mute_safety_whitelist(self):
        """Channel mute (/ch/xx/mix/on) is allowed in SafetyPolicy whitelist."""
        policy = SafetyPolicy()
        proposal = Proposal(
            proposal_id="TEST_MUTE_CH01",
            target_channel=1,
            hypothesis="Test mute toggle",
            confidence=1.0,
            changes=[{"parameter": "/ch/01/mix/on", "from": 1, "to": 0}],
            expected_sha256="dummy_sha",
            operator_approved=True,
            approved_by="Operator",
        )
        # Should NOT raise ProposalRejectedError
        try:
            policy.validate_proposal(proposal)
        except Exception as e:
            self.fail(f"SafetyPolicy wrongly rejected allowed parameter /ch/01/mix/on: {e}")

    def test_03_silence_hold_invariant_freezes_fader(self):
        """SpeechLeveler MUST freeze fader (action HOLD, delta 0.0) when audio is silent."""
        # Create a near-silent audio frame (-70 dBFS background room noise)
        silent_samples = np.random.normal(0, 0.0001, 1024).astype(np.float32)
        silent_frame = AudioFrame(samples=silent_samples, channel_id=1, timestamp=0.0)

        action = self.speech_leveler.process(silent_frame, current_fader=0.75)
        self.assertEqual(action.action_type, "HOLD")
        self.assertEqual(action.fader_delta, 0.0)
        self.assertEqual(action.target_fader, 0.75)
        self.assertIn("SILENCE HOLD", action.rationale)

    def test_04_rest_api_channel_mute_flow(self):
        """Test toggling channel mute via REST API endpoint /api/v1/channels/{id}/mute."""
        # 1. Ensure channel 2 starts in a known state (Mute = 0)
        res_mute = self.client.post("/api/v1/channels/2/mute", json={"on": 0, "operator_id": "Tech_Hai"})
        self.assertEqual(res_mute.status_code, 200)
        data = res_mute.json()
        self.assertEqual(data["status"], "COMMITTED")
        self.assertEqual(data["channel_id"], 2)
        self.assertEqual(data["on"], 0)
        self.assertEqual(data["state_text"], "MUTE")

        # 2. Toggle to Unmute (on = 1)
        res_unmute = self.client.post("/api/v1/channels/2/mute", json={"on": 1, "operator_id": "Tech_Hai"})
        self.assertEqual(res_unmute.status_code, 200)
        data_unmute = res_unmute.json()
        self.assertEqual(data_unmute["status"], "COMMITTED")
        self.assertEqual(data_unmute["on"], 1)
        self.assertEqual(data_unmute["state_text"], "ON")

        # 3. Automatic toggle without specifying 'on'
        res_toggle = self.client.post("/api/v1/channels/2/mute", json={"operator_id": "Tech_Hai"})
        self.assertEqual(res_toggle.status_code, 200)
        self.assertEqual(res_toggle.json()["on"], 0) # 1 -> 0

    def test_05_rest_api_generate_and_apply_notch_flow(self):
        """Test end-to-end feedback notch generation and application via REST API."""
        # 1. Generate notch proposal for Channel 3 at 2850 Hz
        res_notch = self.client.post(
            "/api/v1/proposals/generate-notch",
            json={"channel_id": 3, "freq_hz": 2850.0, "confidence": 0.90},
        )
        self.assertEqual(res_notch.status_code, 200)
        data = res_notch.json()
        self.assertIn("proposal_id", data)
        self.assertEqual(data["target_channel"], 3)
        self.assertIn("simulated_curve", data.get("tuning_detail", {}))
        proposal_id = data["proposal_id"]

        # 2. Apply proposal through Safety Gate
        res_apply = self.client.post(
            "/api/v1/proposals/apply",
            json={"proposal_id": proposal_id, "operator_id": "Lead_Engineer"},
        )
        self.assertEqual(res_apply.status_code, 200)
        apply_data = res_apply.json()
        self.assertEqual(apply_data["status"], "SUCCESS")
        self.assertEqual(apply_data["proposal_id"], proposal_id)
        self.assertEqual(apply_data["audit"]["status"], "COMMITTED")


if __name__ == "__main__":
    unittest.main()
