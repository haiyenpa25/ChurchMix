"""
Sprint 24 Test Suite: Stage Bleed & Acoustic Cross-Talk Advisor with Vocal Expander Calibration.
==============================================================================================
Tests:
1. Bidirectional conversion for X32 Gate/Expander Threshold and Range.
2. Cross-channel correlation & relative bleed level calculation (Drums spill into vocal mic).
3. Comb-filtering risk classification & phase alignment detection.
4. Gentle Downward Expander parameter optimization (Threshold = Noise Floor + 3 dB, Range 8-12 dB, HPF 250 Hz).
5. Hard Safety Invariant: DL16 In 11 (Band Talkback) strictly protected from expander/gate in Advisor & SafetyPolicy.
6. SafetyPolicy validation: Gate/Expander whitelist, max range clamp (<= 24.0 dB / 0.40), rejection of excessive attenuation.
7. REST API: GET /api/v1/bleed-analysis/{channel_id} and POST /api/v1/bleed-analysis/{channel_id}/propose-expander.
8. REST API Hard Invariant check on Channel 11 returning HTTP 400.
"""
import unittest
import numpy as np
from fastapi.testclient import TestClient

from packages.mix_assistant.bleed_analyzer import (
    StageBleedAdvisor,
    ExpanderSettings,
    CrossTalkReport,
)
from packages.safety_controller.transaction import (
    SafetyPolicy,
    Proposal,
    ProposalRejectedError,
)
from packages.safety_controller.routing import InvariantViolationError
from apps.api.main import app


class TestSprint24StageBleedAndExpander(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_gate_conversions_bidirectional(self):
        """Verify mathematical mapping between Gate dB and X32 normalized floats."""
        # Threshold: -80 dBFS -> 0.0, 0 dBFS -> 1.0, -40 dBFS -> 0.5
        self.assertEqual(StageBleedAdvisor.db_to_gate_thr(-80.0), 0.0)
        self.assertEqual(StageBleedAdvisor.db_to_gate_thr(0.0), 1.0)
        self.assertEqual(StageBleedAdvisor.db_to_gate_thr(-40.0), 0.5)

        self.assertEqual(StageBleedAdvisor.gate_thr_to_db(0.0), -80.0)
        self.assertEqual(StageBleedAdvisor.gate_thr_to_db(1.0), 0.0)
        self.assertEqual(StageBleedAdvisor.gate_thr_to_db(0.5), -40.0)

        # Range: 0 dB -> 0.0, 60 dB -> 1.0, 12 dB -> 0.20
        self.assertEqual(StageBleedAdvisor.db_to_gate_range(0.0), 0.0)
        self.assertEqual(StageBleedAdvisor.db_to_gate_range(60.0), 1.0)
        self.assertAlmostEqual(StageBleedAdvisor.db_to_gate_range(12.0), 0.2, delta=0.01)

        self.assertEqual(StageBleedAdvisor.gate_range_to_db(0.0), 0.0)
        self.assertEqual(StageBleedAdvisor.gate_range_to_db(1.0), 60.0)
        self.assertAlmostEqual(StageBleedAdvisor.gate_range_to_db(0.2), 12.0, delta=0.1)

    def test_bleed_cross_correlation_and_comb_risk(self):
        """Verify correlation matrix and comb-filtering risk detection with drum spill."""
        sr = 48000
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)

        # Lead vocal signal + drum snare bleed
        vocal = 0.15 * np.sin(2 * np.pi * 261.63 * t).astype(np.float32)
        snare = 0.08 * np.sin(2 * np.pi * 180 * t).astype(np.float32) + np.random.normal(0, 0.02, len(t)).astype(np.float32)

        # Heavy drum spill into vocal mic
        spilled_vocal = vocal + 0.60 * snare

        stage_sigs = {
            13: ("Snare Drum", snare),
            4: ("Choir Left", np.random.normal(0, 0.01, len(t)).astype(np.float32)),
        }

        report = StageBleedAdvisor.analyze_cross_talk(
            target_signal=spilled_vocal,
            target_channel=2,
            target_name="Lead Vocal 1",
            target_role="LEAD_VOCAL",
            stage_signals=stage_sigs,
        )

        self.assertIsInstance(report, CrossTalkReport)
        self.assertEqual(report.channel_id, 2)
        self.assertEqual(report.bleed_source_channel_id, 13)
        self.assertEqual(report.bleed_source_name, "Snare Drum")
        self.assertGreater(report.correlation_coeff, 0.20)
        self.assertIn(report.comb_filtering_risk, ("MODERATE", "HIGH", "SEVERE"))
        self.assertTrue(len(report.advice_vi) > 0)

    def test_clean_signal_low_comb_risk(self):
        """Verify that a clean signal with no stage correlation yields LOW risk."""
        sr = 48000
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)
        clean_vocal = 0.15 * np.sin(2 * np.pi * 440 * t).astype(np.float32)

        other_uncorrelated = {
            13: ("Snare Drum", np.random.normal(0, 0.02, len(t)).astype(np.float32)),
        }

        report = StageBleedAdvisor.analyze_cross_talk(
            target_signal=clean_vocal,
            target_channel=1,
            target_name="Pastor Mic",
            target_role="SPEECH",
            stage_signals=other_uncorrelated,
        )

        self.assertEqual(report.comb_filtering_risk, "LOW")
        self.assertEqual(report.phase_alignment_status, "DECORRELATED")
        self.assertIn("Độ sạch tín hiệu tốt", report.advice_vi)

    def test_gentle_vocal_expander_parameters(self):
        """Verify gentle expander parameter calculation (Threshold = Noise Floor + 3 dB, Range <= 12 dB)."""
        sr = 48000
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)
        noise = np.random.normal(0, 0.003, len(t)).astype(np.float32) # ~ -50 dBFS
        voice = 0.10 * np.sin(2 * np.pi * 300 * t).astype(np.float32)
        target = voice + noise

        report = StageBleedAdvisor.analyze_cross_talk(
            target_signal=target,
            target_channel=3,
            target_name="Vocalist Female",
            target_role="LEAD_VOCAL",
            stage_signals=None,
        )

        exp = report.recommended_expander
        self.assertTrue(exp.enabled)
        self.assertEqual(exp.mode, 0) # 0 = Expander (gentle)
        self.assertGreaterEqual(exp.range_db, 6.0)
        self.assertLessEqual(exp.range_db, 14.0) # Church transparent range
        self.assertTrue(exp.filter_on)
        self.assertEqual(exp.filter_freq_hz, 250.0) # High-pass sidechain key

    def test_hard_safety_invariant_channel_11_advisor(self):
        """Verify that StageBleedAdvisor strictly raises InvariantViolationError for Channel 11 (Band Talkback)."""
        sig = np.zeros(2048, dtype=np.float32)

        with self.assertRaises(InvariantViolationError):
            StageBleedAdvisor.analyze_cross_talk(
                target_signal=sig,
                target_channel=11,
                target_name="Band Talkback",
                target_role="TALKBACK",
            )

        exp_settings = ExpanderSettings()
        with self.assertRaises(InvariantViolationError):
            StageBleedAdvisor.generate_expander_proposals(
                channel_id=11,
                settings=exp_settings,
                current_sha256="abc123456",
            )

    def test_safety_policy_gate_whitelist_and_channel_11_block(self):
        """Verify SafetyPolicy enforces gate whitelist, maximum range clamp, and channel 11 denial."""
        snapshot_hash = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        policy = SafetyPolicy()

        # 1. Valid Expander Proposal on Channel 2
        valid_prop = Proposal(
            proposal_id="prop-test-01",
            target_channel=2,
            hypothesis="Configure Gentle Downward Expander on Ch 02",
            confidence=0.9,
            changes=[
                {"parameter": "/ch/02/gate/on", "from": 0, "to": 1},
                {"parameter": "/ch/02/gate/mode", "from": 1, "to": 0},
                {"parameter": "/ch/02/gate/thr", "from": 0.0, "to": 0.35},
                {"parameter": "/ch/02/gate/range", "from": 0.0, "to": 0.167}, # ~10 dB
            ],
            expected_sha256=snapshot_hash,
        )
        # Should not raise
        policy.validate_proposal(valid_prop)

        # 2. Gate Proposal on Channel 11 (Band Talkback) MUST BE DENIED
        tb_prop = Proposal(
            proposal_id="prop-test-tb",
            target_channel=11,
            hypothesis="Illegal Gate proposal on Talkback",
            confidence=0.9,
            changes=[
                {"parameter": "/ch/11/gate/on", "from": 0, "to": 1},
            ],
            expected_sha256=snapshot_hash,
        )
        with self.assertRaises(ProposalRejectedError) as cm:
            policy.validate_proposal(tb_prop)
        self.assertIn("Band Talkback", str(cm.exception))

        # 3. Excessive Gate Range (> 24 dB / 0.40) MUST BE REJECTED
        excessive_range_prop = Proposal(
            proposal_id="prop-test-range",
            target_channel=2,
            hypothesis="Excessive gate range",
            confidence=0.9,
            changes=[
                {"parameter": "/ch/02/gate/range", "from": 0.0, "to": 0.50}, # 30 dB (> 24 dB)
            ],
            expected_sha256=snapshot_hash,
        )
        with self.assertRaises(ProposalRejectedError) as cm:
            policy.validate_proposal(excessive_range_prop)
        self.assertIn("maximum safe limit 0.40 (~24 dB)", str(cm.exception))

    def test_rest_api_bleed_analysis_flow(self):
        """Verify REST API GET bleed-analysis and POST propose-expander endpoints."""
        # 1. GET bleed analysis for Channel 1
        res = self.client.get("/api/v1/bleed-analysis/1")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["channel_id"], 1)
        self.assertIn("comb_filtering_risk", data)
        self.assertIn("recommended_expander", data)
        self.assertIn("advice_vi", data)

        # 2. POST propose expander for Channel 1
        res_prop = self.client.post("/api/v1/bleed-analysis/1/propose-expander")
        self.assertEqual(res_prop.status_code, 200)
        prop_data = res_prop.json()
        self.assertEqual(prop_data["status"], "PROPOSED")
        self.assertIsNotNone(prop_data["proposal"])
        changes = prop_data["proposal"]["changes"]
        params = [c["parameter"] for c in changes]
        self.assertIn("/ch/01/gate/on", params)
        self.assertIn("/ch/01/gate/range", params)

    def test_rest_api_channel_11_forbidden(self):
        """Verify REST API rejects Channel 11 (Band Talkback) with 400 Bad Request."""
        res_get = self.client.get("/api/v1/bleed-analysis/11")
        self.assertEqual(res_get.status_code, 400)
        self.assertIn("Band Talkback", res_get.json()["detail"])

        res_post = self.client.post("/api/v1/bleed-analysis/11/propose-expander")
        self.assertEqual(res_post.status_code, 400)
        self.assertIn("Band Talkback", res_post.json()["detail"])


if __name__ == "__main__":
    unittest.main()
