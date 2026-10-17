"""
Sprint 23 Test Suite: Subjective Audio Quality Benchmark & Double-Blind A/B Listening Test Engine.
==================================================================================================
Tests:
1. 7-criteria weighted MOS calculation (Master Plan Section 3.4).
2. Acceptance recommendation: RECOMMENDED_FOR_COMMIT for excellent ratings (>= 4.0).
3. Veto rules: Critical flaw in intelligibility, timbre, or feedback margin (< 2.5) enforces REJECT_OR_REFINE.
4. Double-blind session creation, loudness compensation, and reveal mechanism.
5. SQLite database persistence and retrieval of listening test sessions.
6. REST API: /templates, /blind-session, /reveal, /evaluate, and /history.
"""
import unittest
from fastapi.testclient import TestClient

from packages.mix_assistant.listening_test import (
    ListeningTestCriteria,
    ListeningEvaluation,
    BlindABSession,
    ListeningTestEngine,
)
from packages.storage.database import ChurchMixDatabase
from apps.api.main import app


class TestSprint23ListeningTestBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_mos_calculation_excellent(self):
        """High scores across all 7 criteria produce MOS >= 4.0 and RECOMMENDED_FOR_COMMIT."""
        crit = ListeningTestCriteria(
            intelligibility=4.8,
            timbre_naturalness=4.5,
            warmth_body=4.2,
            harshness_control=4.5,
            band_balance=4.0,
            hall_coverage=4.0,
            feedback_margin=4.5,
        )

        mos, rec, strengths, weaknesses, advice = ListeningTestEngine.calculate_mos(crit)

        self.assertGreaterEqual(mos, 4.0)
        self.assertEqual(rec, "RECOMMENDED_FOR_COMMIT")
        self.assertGreater(len(strengths), 0)
        self.assertEqual(len(weaknesses), 0)
        self.assertIn("xuất sắc", advice)

    def test_mos_calculation_acceptable(self):
        """Moderate scores (3.2 - 3.8) produce ACCEPTABLE_WITH_MONITORING."""
        crit = ListeningTestCriteria(
            intelligibility=3.5,
            timbre_naturalness=3.5,
            warmth_body=3.5,
            harshness_control=3.5,
            band_balance=3.5,
            hall_coverage=3.5,
            feedback_margin=3.5,
        )

        mos, rec, strengths, weaknesses, advice = ListeningTestEngine.calculate_mos(crit)

        self.assertAlmostEqual(mos, 3.5, delta=0.1)
        self.assertEqual(rec, "ACCEPTABLE_WITH_MONITORING")
        self.assertIn("chấp nhận được", advice)

    def test_veto_rule_low_intelligibility(self):
        """If intelligibility is poor (< 2.5), recommendation must be REJECT_OR_REFINE even if average is high."""
        crit = ListeningTestCriteria(
            intelligibility=2.0, # Veto trigger!
            timbre_naturalness=4.5,
            warmth_body=4.5,
            harshness_control=4.5,
            band_balance=4.5,
            hall_coverage=4.5,
            feedback_margin=4.5,
        )

        mos, rec, strengths, weaknesses, advice = ListeningTestEngine.calculate_mos(crit)

        self.assertEqual(rec, "REJECT_OR_REFINE")
        self.assertTrue(any("Độ rõ lời" in w for w in weaknesses))
        self.assertIn("KHÔNG KHUYẾN NGHỊ ÁP DỤNG", advice)

    def test_veto_rule_low_feedback_margin(self):
        """If feedback margin is precarious (< 2.5), recommendation must be REJECT_OR_REFINE."""
        crit = ListeningTestCriteria(
            intelligibility=4.5,
            timbre_naturalness=4.5,
            warmth_body=4.5,
            harshness_control=4.5,
            band_balance=4.5,
            hall_coverage=4.5,
            feedback_margin=2.2, # Dangerous feedback margin
        )

        mos, rec, strengths, weaknesses, advice = ListeningTestEngine.calculate_mos(crit)

        self.assertEqual(rec, "REJECT_OR_REFINE")
        self.assertIn("KHÔNG KHUYẾN NGHỊ ÁP DỤNG", advice)

    def test_blind_ab_session_randomization_and_loudness_compensation(self):
        """Verify double-blind session creation, loudness matching, and reveal logic."""
        session = ListeningTestEngine.create_blind_ab_session(
            target_channel=1,
            channel_name="Pastor Mic",
            proposal_id="prop-test-01",
            dry_rms_dbfs=-20.0,
            processed_rms_dbfs=-17.5,
        )

        self.assertTrue(session.session_id.startswith("blind-01-"))
        self.assertEqual(session.loudness_compensation_db, -2.5)

        # Before reveal: identities must be HIDDEN
        data_hidden = session.to_dict(reveal_identity=False)
        self.assertEqual(data_hidden["option_a_identity"], "HIDDEN")
        self.assertEqual(data_hidden["option_b_identity"], "HIDDEN")
        self.assertFalse(data_hidden["revealed"])

        # Reveal
        revealed_session = ListeningTestEngine.reveal_blind_ab_session(session.session_id)
        data_revealed = revealed_session.to_dict(reveal_identity=True)
        self.assertTrue(data_revealed["revealed"])
        self.assertIn(data_revealed["option_a_identity"], ["TUNING_PROPOSAL", "DRY_ORIGINAL"])
        self.assertIn(data_revealed["option_b_identity"], ["TUNING_PROPOSAL", "DRY_ORIGINAL"])
        self.assertNotEqual(data_revealed["option_a_identity"], data_revealed["option_b_identity"])

    def test_database_persistence_and_retrieval(self):
        """Verify storing and loading listening evaluations in SQLite."""
        db = ChurchMixDatabase()
        crit = ListeningTestCriteria(
            intelligibility=4.5,
            timbre_naturalness=4.5,
            warmth_body=4.0,
            harshness_control=4.2,
            band_balance=4.0,
            hall_coverage=4.0,
            feedback_margin=4.5,
        )
        evaluation = ListeningTestEngine.evaluate_listening(
            target_channel=1,
            channel_name="Pastor Mic",
            operator="SoundTech_Lead",
            criteria=crit,
            proposal_id="prop-01-eq",
            loudness_compensation_db=-1.2,
            is_blind_test=True,
        )

        row_id = db.save_listening_test(evaluation.to_dict())
        self.assertGreater(row_id, 0)

        history = db.list_listening_tests(limit=5)
        self.assertGreater(len(history), 0)
        latest = history[0]

        self.assertEqual(latest["target_channel"], 1)
        self.assertEqual(latest["operator"], "SoundTech_Lead")
        self.assertEqual(latest["proposal_id"], "prop-01-eq")
        self.assertAlmostEqual(latest["overall_mos"], evaluation.overall_mos, delta=0.01)
        self.assertEqual(latest["recommendation"], "RECOMMENDED_FOR_COMMIT")
        self.assertTrue(latest["is_blind_test"])

    def test_listening_test_api_endpoints(self):
        """Verify REST API endpoints for benchmark templates, blind sessions, reveal, evaluate, and history."""
        # 1. GET templates
        res_tpl = self.client.get("/api/v1/listening-test/templates")
        self.assertEqual(res_tpl.status_code, 200)
        criteria = res_tpl.json()["criteria"]
        self.assertEqual(len(criteria), 7)
        total_weight = sum(c["weight"] for c in criteria)
        self.assertAlmostEqual(total_weight, 1.0, delta=0.01)

        # 2. POST blind-session
        res_blind = self.client.post(
            "/api/v1/listening-test/blind-session",
            json={"target_channel": 2, "channel_name": "Worship Lead", "proposal_id": "prop-w2"},
        )
        self.assertEqual(res_blind.status_code, 200)
        session_data = res_blind.json()
        session_id = session_data["session_id"]
        self.assertEqual(session_data["option_a_identity"], "HIDDEN")

        # 3. POST reveal
        res_reveal = self.client.post(f"/api/v1/listening-test/blind-session/{session_id}/reveal")
        self.assertEqual(res_reveal.status_code, 200)
        reveal_data = res_reveal.json()
        self.assertTrue(reveal_data["revealed"])
        self.assertNotEqual(reveal_data["option_a_identity"], "HIDDEN")

        # 4. POST evaluate
        res_eval = self.client.post(
            "/api/v1/listening-test/evaluate",
            json={
                "target_channel": 2,
                "channel_name": "Worship Lead",
                "operator": "AudioTech_QA",
                "proposal_id": "prop-w2",
                "intelligibility": 4.6,
                "timbre_naturalness": 4.6,
                "warmth_body": 4.0,
                "harshness_control": 4.2,
                "band_balance": 4.0,
                "hall_coverage": 4.0,
                "feedback_margin": 4.5,
                "loudness_compensation_db": -0.8,
                "is_blind_test": True,
            },
        )
        self.assertEqual(res_eval.status_code, 200)
        eval_data = res_eval.json()
        self.assertGreaterEqual(eval_data["overall_mos"], 4.0)
        self.assertEqual(eval_data["recommendation"], "RECOMMENDED_FOR_COMMIT")

        # 5. GET history
        res_hist = self.client.get("/api/v1/listening-test/history?limit=5")
        self.assertEqual(res_hist.status_code, 200)
        hist_data = res_hist.json()["evaluations"]
        self.assertGreater(len(hist_data), 0)


if __name__ == "__main__":
    unittest.main()
