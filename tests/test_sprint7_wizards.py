"""
Sprint 7 Test Suite:
- Wizard 1: Comprehensive Markdown Inventory & Routing Protection Audit Report
- Wizard 2: Pre-service Line Check & Sunday Physical Checklist
- Wizard 7: End-of-service Review Report Generator
- Hardware Connection Switcher (Simulator vs Real Mixer LAN IP)
"""

import unittest
import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.main import app


class TestSprint7Wizards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_wizard1_inventory_report(self):
        res = self.client.get("/api/v1/wizards/inventory-report")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        report_md = data["report_markdown"]

        self.assertIn("# BÁO CÁO KIỂM KÊ THIẾT BỊ", report_md)
        self.assertIn("Mã băm toàn vẹn SHA-256", report_md)
        self.assertIn("DL16 số 11 (Talkback ban nhạc)", report_md)
        self.assertIn("P16 Slot 11", report_md)
        self.assertIn("Pastor Mic", report_md)

    def test_wizard2_pre_service_line_check(self):
        res = self.client.get("/api/v1/wizards/line-check")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["talkback_isolated"])
        self.assertEqual(len(data["items"]), 32)
        self.assertTrue(len(data["physical_checklist"]) >= 5)

        # Check physical checklist items
        tasks = [t["task"] for t in data["physical_checklist"]]
        self.assertTrue(any("pin micro" in t.lower() for t in tasks))
        self.assertTrue(any("p16" in t.lower() for t in tasks))

    def test_wizard7_end_of_service_report(self):
        res = self.client.get("/api/v1/wizards/end-of-service-report")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        report_md = data["report_markdown"]

        self.assertIn("# BÁO CÁO TỔNG KẾT BUỔI LỄ", report_md)
        self.assertIn("NHẬT KÝ CAN THIỆP THAM SỐ", report_md)
        self.assertIn("KHUYẾN NGHỊ CHO BUỔI TẬP", report_md)

    def test_hardware_switcher_to_simulator(self):
        res = self.client.post("/api/v1/hardware/connect", json={
            "mode": "SIMULATOR",
            "ip": "127.0.0.1",
            "port": int(os.environ.get("CHURCHMIX_X32_PORT", "10023")),
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "CONNECTED")
        self.assertEqual(data["mode"], "SIMULATOR")
        self.assertTrue(data["read_only_mode"])

    def test_wizard3_vocal_calibration(self):
        res = self.client.post("/api/v1/wizards/vocal-calibration", json={
            "channel_id": 1,
            "vocal_role": "PASTOR_SPEECH",
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["channel_id"], 1)
        self.assertEqual(data["vocal_role"], "PASTOR_SPEECH")
        self.assertEqual(data["hpf_freq_hz"], 85.0)
        self.assertTrue(len(data["bands"]) >= 2)
        self.assertIn("dynamics", data)
        self.assertIn("mic_placement_guide", data)
        self.assertTrue(len(data["simulated_curve"]) > 10)

    def test_wizard5_feedback_ringout(self):
        res = self.client.post("/api/v1/wizards/feedback-ringout", json={
            "channel_id": 3,
            "target_gain_increase_db": 3.5,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["channel_id"], 3)
        self.assertEqual(data["gain_margin_improvement_db"], 3.5)
        self.assertLess(data["notch_gain_db"], 0.0)
        self.assertGreaterEqual(data["notch_q"], 5.0)
        self.assertTrue(len(data["step_by_step_sop"]) >= 5)
        self.assertTrue(data["safety_lock_engaged"])

    def test_hardware_discovery(self):
        res = self.client.post("/api/v1/hardware/discover", json={"hosts": ["127.0.0.1"], "port": int(os.environ.get("CHURCHMIX_X32_PORT", "10023"))})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["count"], 1)
        self.assertEqual(data["consoles"][0]["ip"], "127.0.0.1")
        self.assertIn("X32", data["consoles"][0]["model"])

    def test_wizard6_live_assistant(self):
        res = self.client.get("/api/v1/wizards/live-assistant")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["mixer_online"])
        self.assertTrue(data["read_only_mode"])
        self.assertIn("channel_highlights", data)
        self.assertTrue(len(data["channel_highlights"]) >= 3)
        self.assertIn("tactical_guidance_vi", data)
        self.assertEqual(data["overall_health"], "EXCELLENT")


if __name__ == "__main__":
    unittest.main()


