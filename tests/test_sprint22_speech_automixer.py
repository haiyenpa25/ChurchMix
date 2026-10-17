"""
Sprint 22 Test Suite: Dugan Speech Automixer & NOM=1 Gain Sharing Controller.
=============================================================================
Tests:
1. Dugan gain-sharing math: single active speaker gets 0 dB (unity gain).
2. Two equal speakers get -3 dB each (NOM = 1 invariant maintained).
3. Priority weighting: +3 dB priority weight dominates equal level speech.
4. Silence Hold invariant: freeze gain allocations during speech pauses.
5. Hard Safety Invariant: Channel 11 (Band Talkback) strictly forbidden.
6. X32 native hardware automix proposal formulation & SafetyPolicy gate validation.
7. REST API: GET /api/v1/automixer/status and POST /api/v1/automixer/propose-setup.
"""
import unittest
from fastapi.testclient import TestClient

from packages.mix_assistant.automixer import (
    DuganSpeechAutomixer,
    AutomixerReport,
    ChannelAutomixState,
)
from packages.safety_controller.routing import InvariantViolationError
from packages.safety_controller.transaction import (
    SafetyPolicy,
    Proposal,
    ProposalRejectedError,
)
from apps.api.main import app


class TestSprint22SpeechAutomixer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_dugan_single_speaker_unity_gain(self):
        """When 1 speaker is active and others are quiet, speaker gets 0 dB (NOM=1)."""
        levels = {1: -18.0, 2: -60.0, 3: -60.0, 4: -60.0}
        weights = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}

        report = DuganSpeechAutomixer.compute_gain_sharing(levels, weights)

        self.assertTrue(report.talkback_safe)
        self.assertFalse(report.silence_hold_engaged)
        self.assertEqual(report.primary_speaker_id, 1)
        self.assertEqual(report.active_speakers_count, 1)

        # Ch 1 should receive essentially unity gain (>= -0.1 dB)
        ch1 = next(c for c in report.channels if c.channel_id == 1)
        self.assertGreaterEqual(ch1.gain_sharing_attenuation_db, -0.1)
        self.assertTrue(ch1.is_speaking)

        # Other channels should be heavily attenuated (-18 dB floor)
        for ch_id in [2, 3, 4]:
            c = next(c for c in report.channels if c.channel_id == ch_id)
            self.assertEqual(c.gain_sharing_attenuation_db, -18.0)
            self.assertFalse(c.is_speaking)

        # Total acoustic gain must not exceed 0.0 dB
        self.assertLessEqual(report.total_system_gain_db, 0.0)

    def test_dugan_two_equal_speakers_minus_3db(self):
        """When 2 speakers talk simultaneously at equal level, each gets ~ -3 dB."""
        levels = {1: -20.0, 2: -20.0, 3: -65.0, 4: -65.0}
        weights = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}

        report = DuganSpeechAutomixer.compute_gain_sharing(levels, weights)

        ch1 = next(c for c in report.channels if c.channel_id == 1)
        ch2 = next(c for c in report.channels if c.channel_id == 2)

        # Both should receive ~ -3.0 dB attenuation (half power each, sum = 1.0)
        self.assertAlmostEqual(ch1.gain_sharing_attenuation_db, -3.0, delta=0.2)
        self.assertAlmostEqual(ch2.gain_sharing_attenuation_db, -3.0, delta=0.2)
        self.assertEqual(report.active_speakers_count, 2)
        self.assertLessEqual(report.total_system_gain_db, 0.0)

    def test_dugan_priority_weighting(self):
        """Channel with higher priority weight receives higher gain allocation."""
        levels = {1: -20.0, 2: -20.0}
        # Ch 1 has +3.0 dB weight, Ch 2 has 0.0 dB weight
        weights = {1: 3.0, 2: 0.0}

        report = DuganSpeechAutomixer.compute_gain_sharing(levels, weights)

        ch1 = next(c for c in report.channels if c.channel_id == 1)
        ch2 = next(c for c in report.channels if c.channel_id == 2)

        # Ch 1 should have less attenuation than Ch 2
        self.assertGreater(ch1.gain_sharing_attenuation_db, ch2.gain_sharing_attenuation_db)
        # Ratio of powers is 10^(3/10) ≈ 2.0 -> Ch 1 gets ~ 2/3 (-1.8 dB), Ch 2 gets ~ 1/3 (-4.8 dB)
        self.assertAlmostEqual(ch1.gain_sharing_attenuation_db, -1.8, delta=0.3)
        self.assertAlmostEqual(ch2.gain_sharing_attenuation_db, -4.8, delta=0.3)
        self.assertEqual(report.primary_speaker_id, 1)

    def test_silence_hold_invariant(self):
        """When all channels are quiet (< -50 dBFS), Silence Hold activates and freezes gains."""
        levels = {1: -60.0, 2: -62.0, 3: -65.0, 4: -63.0}
        weights = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
        last_attenuations = {1: -2.0, 2: -5.0, 3: -12.0, 4: -8.0}

        report = DuganSpeechAutomixer.compute_gain_sharing(
            levels, weights, last_attenuations=last_attenuations
        )

        self.assertTrue(report.silence_hold_engaged)
        self.assertEqual(report.active_speakers_count, 0)
        self.assertIsNone(report.primary_speaker_id)
        self.assertIn("Silence Hold", report.advice_vi)

        # Verifies previous attenuations were frozen exactly without boosting
        for ch_id, expected_attn in last_attenuations.items():
            ch = next(c for c in report.channels if c.channel_id == ch_id)
            self.assertEqual(ch.gain_sharing_attenuation_db, expected_attn)

    def test_hard_safety_invariant_talkback_channel_11(self):
        """Channel 11 (Band Talkback) must NEVER enter Automixer under any circumstance."""
        levels = {1: -20.0, 11: -20.0}
        weights = {1: 0.0, 11: 0.0}

        # 1. compute_gain_sharing must raise InvariantViolationError
        with self.assertRaises(InvariantViolationError):
            DuganSpeechAutomixer.compute_gain_sharing(levels, weights)

        # 2. generate_x32_automix_proposals must raise InvariantViolationError
        with self.assertRaises(InvariantViolationError):
            DuganSpeechAutomixer.generate_x32_automix_proposals(
                channels=[1, 11],
                weights_db={1: 0.0, 11: 0.0},
                current_sha256="fake_sha",
            )

        # 3. SafetyPolicy must reject any automix mutation proposal targeting channel 11
        policy = SafetyPolicy()
        malicious_prop = Proposal(
            proposal_id="prop-hack-tb-11",
            target_channel=11,
            hypothesis="Unauthorized addition of Band Talkback to AutoMix",
            confidence=1.0,
            changes=[{"parameter": "/ch/11/automix/group", "from": 0, "to": 1}],
            expected_sha256="fake_sha",
        )
        with self.assertRaises(ProposalRejectedError) as cm:
            policy.validate_proposal(malicious_prop)
        self.assertIn("Channel 11 (Band Talkback)", str(cm.exception))

    def test_x32_hardware_proposals_generation_and_safety_gate(self):
        """Verify proposal structure and pass-through across SafetyGate whitelist for Ch 1-8."""
        channels = [1, 2, 3, 4]
        weights = {1: 3.0, 2: 0.0, 3: 0.0, 4: -3.0}
        sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        proposals = DuganSpeechAutomixer.generate_x32_automix_proposals(
            channels=channels,
            weights_db=weights,
            current_sha256=sha,
            group_id=1,
        )

        self.assertEqual(len(proposals), 4)

        # Check Ch 1 Proposal
        p1 = proposals[0]
        self.assertEqual(p1.target_channel, 1)
        self.assertEqual(len(p1.changes), 2)
        self.assertEqual(p1.changes[0]["parameter"], "/ch/01/automix/group")
        self.assertEqual(p1.changes[0]["to"], 1)
        self.assertEqual(p1.changes[1]["parameter"], "/ch/01/automix/weight")
        # 0.5 + 3.0 / 24.0 = 0.625
        self.assertEqual(p1.changes[1]["to"], 0.625)

        # Check SafetyPolicy validation: must approve for normal channels
        policy = SafetyPolicy()
        for p in proposals:
            # Should not raise ProposalRejectedError
            policy.validate_proposal(p)

    def test_automixer_api_endpoints(self):
        """Test GET /api/v1/automixer/status and POST /api/v1/automixer/propose-setup."""
        # 1. GET status
        res_get = self.client.get("/api/v1/automixer/status")
        self.assertEqual(res_get.status_code, 200)
        data = res_get.json()
        self.assertTrue(data["talkback_safe"])
        self.assertIn("channels", data)
        self.assertLessEqual(data["total_system_gain_db"], 0.0)
        self.assertGreater(data["noise_reduction_savings_db"], 0.0)

        # 2. POST propose-setup valid
        res_post = self.client.post(
            "/api/v1/automixer/propose-setup",
            json={
                "channels": [1, 2, 3, 4],
                "weights_db": {"1": 3.0, "2": 0.0, "3": 0.0, "4": -3.0},
                "group_id": 1,
            },
        )
        self.assertEqual(res_post.status_code, 200)
        res_data = res_post.json()
        self.assertEqual(res_data["status"], "PROPOSED")
        self.assertEqual(res_data["proposals_count"], 4)

        # 3. POST propose-setup containing forbidden channel 11 -> must return 400
        res_post_bad = self.client.post(
            "/api/v1/automixer/propose-setup",
            json={
                "channels": [1, 11],
                "weights_db": {"1": 0.0, "11": 0.0},
                "group_id": 1,
            },
        )
        self.assertEqual(res_post_bad.status_code, 400)
        self.assertIn("Kênh 11 (Band Talkback)", res_post_bad.json()["detail"])


if __name__ == "__main__":
    unittest.main()
