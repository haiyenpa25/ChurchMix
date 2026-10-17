"""
Sprint 21 Test Suite: Preamp Gain Staging & Digital Trim Headroom Calibrator.
=============================================================================
Tests:
1. Bidirectional Digital Trim conversion (dB <-> X32 normalized float).
2. Headroom analysis across church roles (Pastor -18 dBFS, Vocals -14 dBFS, Band -12 dBFS).
3. Clipping hazard detection & urgent attenuation advice.
4. Silence Hold invariant: never auto-boost on quiet / silent channels.
5. SafetyPolicy integration: Whitelist for /ch/xx/preamp/trim and slew-rate protection.
6. REST API: GET /api/v1/gain-staging/{channel_id} and POST /api/v1/gain-staging/{channel_id}/propose-trim.
"""
import unittest
import numpy as np
from fastapi.testclient import TestClient

from packages.mix_assistant.gain_staging import (
    trim_to_x32,
    x32_to_trim,
    GainStagingAdvisor,
    GainStagingReport,
)
from packages.safety_controller.transaction import (
    SafetyPolicy,
    Proposal,
    ProposalRejectedError,
)
from packages.safety_controller.modes import OperatorMode
from apps.api.main import app, safety_mode_mgr


class TestSprint21GainStagingAndHeadroom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()
        safety_mode_mgr.set_mode(OperatorMode.ASSIST, operator="TestEngineer")

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_trim_conversions_bidirectional(self):
        """Verify mathematical mapping between Trim in dB and X32 float."""
        # 0.0 dB -> 0.50
        self.assertEqual(trim_to_x32(0.0), 0.5)
        self.assertEqual(x32_to_trim(0.5), 0.0)

        # +18.0 dB -> 1.00
        self.assertEqual(trim_to_x32(18.0), 1.0)
        self.assertEqual(x32_to_trim(1.0), 18.0)

        # -18.0 dB -> 0.00
        self.assertEqual(trim_to_x32(-18.0), 0.0)
        self.assertEqual(x32_to_trim(0.0), -18.0)

        # Arbitrary test: +6.0 dB
        f_val = trim_to_x32(6.0)
        reconstructed_db = x32_to_trim(f_val)
        self.assertAlmostEqual(reconstructed_db, 6.0, delta=0.1)

    def test_analyze_headroom_optimal_pastor(self):
        """Verify optimal headroom detection around -18.0 dBFS target."""
        sr = 48000
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)
        # 10^( -18 / 20 ) ≈ 0.1259
        sig_optimal = 0.1259 * np.sin(2 * np.pi * 200 * t).astype(np.float32)

        report = GainStagingAdvisor.analyze_headroom(
            signal=sig_optimal,
            channel_id=1,
            channel_name="Pastor Mic",
            role="PASTOR",
            current_trim_float=0.5,
        )

        self.assertEqual(report.health_status, "OPTIMAL")
        self.assertAlmostEqual(report.peak_dbfs, -18.0, delta=0.5)
        self.assertAlmostEqual(report.headroom_db, 18.0, delta=0.5)
        self.assertEqual(report.recommended_trim_delta_db, 0.0)

    def test_analyze_headroom_clipping_hazard(self):
        """Verify clipping alert when peak exceeds -1.0 dBFS."""
        sr = 48000
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)
        sig_clipped = 0.98 * np.sin(2 * np.pi * 440 * t).astype(np.float32) # -0.18 dBFS

        report = GainStagingAdvisor.analyze_headroom(
            signal=sig_clipped,
            channel_id=3,
            channel_name="Vocal Solo",
            role="FEMALE_LEAD",
            current_trim_float=0.5,
        )

        self.assertEqual(report.health_status, "CLIPPING_DETECTED")
        self.assertLess(report.recommended_trim_delta_db, 0)
        self.assertIn("CẢNH BÁO VỠ TIẾNG", report.advice_vi)

    def test_silence_hold_invariant_on_quiet_channel(self):
        """Verify Silence Hold: Never recommend auto-boosting digital silence."""
        silence = np.zeros(2048, dtype=np.float32)
        report = GainStagingAdvisor.analyze_headroom(
            signal=silence,
            channel_id=1,
            channel_name="Pastor Mic",
            role="PASTOR",
            current_trim_float=0.5,
        )

        self.assertEqual(report.health_status, "LOW_GAIN")
        self.assertEqual(report.recommended_trim_delta_db, 0.0, "Must NOT boost silent channel")
        self.assertIn("Silence Hold", report.advice_vi)

    def test_safety_policy_whitelist_and_step_limit_for_trim(self):
        """Verify /ch/xx/preamp/trim is whitelisted and guarded against excessive jump."""
        policy = SafetyPolicy()

        # 1. Safe Trim Proposal (0.50 -> 0.58, delta = 0.08 <= 0.20)
        safe_prop = Proposal(
            proposal_id="prop-trim-safe",
            target_channel=2,
            hypothesis="Adjust trim within safe limits",
            confidence=0.85,
            changes=[{"parameter": "/ch/02/preamp/trim", "from": 0.50, "to": 0.58}],
            expected_sha256="abc",
        )
        # Should not raise exception
        policy.validate_proposal(safe_prop)

        # 2. Dangerous Excessive Trim Jump (0.50 -> 0.80, delta = 0.30 > 0.20)
        jump_prop = Proposal(
            proposal_id="prop-trim-jump",
            target_channel=2,
            hypothesis="Dangerous jump",
            confidence=0.85,
            changes=[{"parameter": "/ch/02/preamp/trim", "from": 0.50, "to": 0.80}],
            expected_sha256="abc",
        )
        with self.assertRaises(ProposalRejectedError) as ctx:
            policy.validate_proposal(jump_prop)
        self.assertIn("Trim delta", str(ctx.exception))

    def test_rest_api_gain_staging_endpoints(self):
        """Test GET /api/v1/gain-staging/{channel_id} and POST propose-trim."""
        # 1. GET /api/v1/gain-staging/1
        res_get = self.client.get("/api/v1/gain-staging/1")
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()

        self.assertEqual(data_get["channel_id"], 1)
        self.assertIn("peak_dbfs", data_get)
        self.assertIn("headroom_db", data_get)
        self.assertIn("health_status", data_get)
        self.assertIn("advice_vi", data_get)

        # 2. POST /api/v1/gain-staging/1/propose-trim
        res_prop = self.client.post("/api/v1/gain-staging/1/propose-trim")
        self.assertEqual(res_prop.status_code, 200)
        data_prop = res_prop.json()

        self.assertIn("proposal_id", data_prop)
        prop_id = data_prop["proposal_id"]
        self.assertEqual(data_prop["target_channel"], 1)
        self.assertEqual(len(data_prop["changes"]), 1)
        self.assertEqual(data_prop["changes"][0]["parameter"], "/ch/01/preamp/trim")

        # 3. Apply the generated proposal via SafetyGate
        res_apply = self.client.post(
            "/api/v1/proposals/apply",
            json={"proposal_id": prop_id, "operator_id": "Headroom_Engineer"},
        )
        self.assertEqual(res_apply.status_code, 200)
        data_apply = res_apply.json()
        self.assertEqual(data_apply["status"], "SUCCESS")
        self.assertEqual(data_apply["proposal_id"], prop_id)

        # 4. Bad channel ID error check
        res_bad = self.client.get("/api/v1/gain-staging/99")
        self.assertEqual(res_bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
