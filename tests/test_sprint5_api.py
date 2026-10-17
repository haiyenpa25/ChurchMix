"""
Sprint 5 Test Suite:
- FastAPI REST API Endpoints
- System Status & DL16 In 11 Invariant Check
- 32 Channel Summary Retrieval & Isolation Verification
- Proposal Generation & Approval Flow
- STOP AUTO Emergency Panic Button & Lockout
- AI Copilot Vietnamese Guidance
"""

import unittest
import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.main import app


class TestSprint5API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_status_endpoint(self):
        res = self.client.get("/api/v1/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ONLINE")
        self.assertTrue(data["read_only_mode"])
        self.assertTrue(data["dl16_talkback_invariant"]["safe"])
        self.assertIn("VERIFIED SAFE", data["dl16_talkback_invariant"]["message"])

    def test_channels_endpoint_and_invariants(self):
        res = self.client.get("/api/v1/channels")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        channels = data["channels"]
        self.assertEqual(len(channels), 32)

        # Pastor (Ch 1) routes to FOH
        pastor = channels[0]
        self.assertEqual(pastor["channel"], 1)
        self.assertEqual(pastor["name"], "Pastor Mic")
        self.assertTrue(pastor["is_foh"])

        # DL16 #11 Talkback Band (Ch 11) is isolated from FOH and mapped to P16
        tb = channels[10]
        self.assertEqual(tb["channel"], 11)
        self.assertEqual(tb["name"], "Talkback Band")
        self.assertFalse(tb["is_foh"], "Channel 11 must NOT route to FOH!")
        self.assertTrue(tb["is_p16"], "Channel 11 must route to P16!")

    def test_routing_endpoint(self):
        res = self.client.get("/api/v1/routing")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["dl16_input_11_status"]["is_isolated_from_foh"])
        self.assertEqual(data["dl16_input_11_status"]["channel_assigned"], 11)

    def test_proposal_generation_and_stop_auto_panic(self):
        # 1. Generate Proposal for Pastor Mic
        res_prop = self.client.post("/api/v1/proposals/generate-pastor", json={"channel_id": 1, "role": "PASTOR_SPEECH"})
        self.assertEqual(res_prop.status_code, 200)
        prop_data = res_prop.json()
        proposal_id = prop_data["proposal_id"]
        self.assertTrue(len(prop_data["tuning_detail"]["simulated_curve"]) > 10)

        # 2. Trigger EMERGENCY STOP AUTO
        res_stop = self.client.post("/api/v1/emergency/stop-auto")
        self.assertEqual(res_stop.status_code, 200)
        self.assertEqual(res_stop.json()["status"], "STOPPED")

        # 3. Attempting to apply proposal while STOP AUTO is active MUST be rejected with HTTP 403!
        res_apply_blocked = self.client.post("/api/v1/proposals/apply", json={
            "proposal_id": proposal_id,
            "operator_id": "SoundTech_Test",
        })
        self.assertEqual(res_apply_blocked.status_code, 403)
        self.assertIn("STOP AUTO panic button is currently ENGAGED", res_apply_blocked.json()["detail"])

        # 4. Resume standby
        res_resume = self.client.post("/api/v1/emergency/resume-auto")
        self.assertEqual(res_resume.status_code, 200)

    def test_copilot_vietnamese_qa(self):
        # Ask about anti-feedback
        res_fb = self.client.post("/api/v1/copilot/ask", json={"question": "Làm sao để chống hú cho micro?"})
        self.assertEqual(res_fb.status_code, 200)
        self.assertIn("Bố trí vật lý", res_fb.json()["answer"])
        self.assertIn("HPF", res_fb.json()["answer"])

        # Ask about pastor sermon clarity
        res_pastor = self.client.post("/api/v1/copilot/ask", json={"question": "Chỉnh micro Mục sư rõ lời"})
        self.assertEqual(res_pastor.status_code, 200)
        self.assertIn("85 Hz", res_pastor.json()["answer"])
        self.assertIn("250 Hz", res_pastor.json()["answer"])

    def test_acoustic_measurement_endpoints(self):
        # 1. Transfer function measurement
        res_tf = self.client.post("/api/v1/acoustics/measure")
        self.assertEqual(res_tf.status_code, 200)
        data = res_tf.json()
        self.assertIn("delay_ms", data)
        self.assertIn("NO-BOOST-IN-NULLS", data["rule_enforced"])
        self.assertTrue(len(data["curve"]) > 20)

        # 2. OSM CSV Import
        sample_csv = "Frequency,Magnitude,Phase,Coherence\n100,-2,0,0.95\n1000,1,10,0.99"
        res_osm = self.client.post("/api/v1/acoustics/import-osm", json={"csv_content": sample_csv})
        self.assertEqual(res_osm.status_code, 200)
        self.assertEqual(res_osm.json()["row_count"], 2)

    def test_mix_assistant_speech_status(self):
        res = self.client.get("/api/v1/mix-assistant/speech-status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["channel_id"], 1)
        self.assertIn("silence_hold", data["safety_invariants"])
        self.assertIn("anti_clipping", data["safety_invariants"])

    def test_audit_and_measurement_history(self):
        res_audit = self.client.get("/api/v1/audit/events")
        self.assertEqual(res_audit.status_code, 200)
        data_audit = res_audit.json()
        self.assertIn("events", data_audit)
        self.assertTrue(len(data_audit["events"]) > 0)

        res_meas = self.client.get("/api/v1/acoustics/history")
        self.assertEqual(res_meas.status_code, 200)
        data_meas = res_meas.json()
        self.assertIn("measurements", data_meas)

    def test_sunday_simulation_endpoint(self):
        res = self.client.post("/api/v1/simulation/run")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(len(data["timeline"]), 5)
        self.assertTrue(any("Boot" in t["phase"] for t in data["timeline"]))
        self.assertTrue(any("Line Check" in t["phase"] for t in data["timeline"]))
        self.assertTrue(any("Live Service" in t["phase"] for t in data["timeline"]))

    def test_generate_role_and_notch_endpoints(self):
        # 1. Test generate-role for ACOUSTIC_GUITAR on Ch 6
        res_role = self.client.post("/api/v1/proposals/generate-role", json={
            "channel_id": 6,
            "role": "ACOUSTIC_GUITAR",
        })
        self.assertEqual(res_role.status_code, 200)
        data_role = res_role.json()
        self.assertEqual(data_role["target_channel"], 6)
        self.assertEqual(data_role["tuning_detail"]["role"], "ACOUSTIC_GUITAR")
        self.assertEqual(data_role["tuning_detail"]["hpf_freq_hz"], 80.0)
        self.assertTrue(len(data_role["tuning_detail"]["simulated_curve"]) > 10)

        # 2. Test generate-notch for feedback frequency on Ch 3
        res_notch = self.client.post("/api/v1/proposals/generate-notch", json={
            "channel_id": 3,
            "freq_hz": 3150.0,
            "confidence": 0.92,
        })
        self.assertEqual(res_notch.status_code, 200)
        data_notch = res_notch.json()
        self.assertEqual(data_notch["target_channel"], 3)
        self.assertIn("3150", data_notch["hypothesis"])
        self.assertEqual(data_notch["tuning_detail"]["role"], "FEEDBACK_NOTCH")
        self.assertTrue(len(data_notch["tuning_detail"]["simulated_curve"]) > 10)


if __name__ == "__main__":
    unittest.main()

