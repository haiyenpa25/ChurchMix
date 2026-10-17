"""
Sprint 12 Test Suite:
- Virtual Soundcheck Multitrack Engine (4 Worship & Sermon Presets)
- Multi-track 32-channel Block Generation & Invariant Isolation
- Church Channel Profile Customization & Channel 11 Protection Enforcer
- Printable Sunday Service Executive HTML Report Generator
- REST API Endpoints Integration for Soundcheck, Profiles, and Reports
"""

import unittest
import os
import sys
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.virtual_soundcheck.player import VirtualSoundcheckEngine, SESSION_PRESETS
from packages.storage.church_profile import ChurchProfileManager
from packages.storage.report_generator import generate_printable_sunday_report_html
from apps.api.main import app


class TestSprint12VirtualSoundcheckAndReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    # --- 1. Virtual Soundcheck Engine Tests ---

    def test_virtual_soundcheck_lifecycle(self):
        engine = VirtualSoundcheckEngine(sample_rate=48000)
        self.assertFalse(engine.is_active)

        # Before start, block should be complete silence
        silence = engine.generate_audio_block(block_size=1024)
        self.assertEqual(silence.shape, (1024, 32))
        self.assertEqual(np.max(np.abs(silence)), 0.0)

        # Start Sunday Worship Ballad
        session = engine.start_session("SUNDAY_WORSHIP_BALLAD")
        self.assertTrue(engine.is_active)
        self.assertEqual(session.id, "SUNDAY_WORSHIP_BALLAD")
        self.assertIn(3, session.active_channels) # Female Lead
        self.assertIn(6, session.active_channels) # Acoustic Guitar

        # Stream audio block
        block = engine.generate_audio_block(block_size=1024)
        self.assertEqual(block.shape, (1024, 32))

        # Channel 3 (Female vocal) should have active energy
        ch3_peak = np.max(np.abs(block[:, 2]))
        self.assertGreater(ch3_peak, 0.1)

        # Channel 11 (Talkback Band) should be isolated with minimal whisper level
        ch11_peak = np.max(np.abs(block[:, 10]))
        self.assertLess(ch11_peak, 0.02, "Channel 11 talkback must remain strictly isolated")

        # Inactive drum channel (Ch 12) in ballad session should be 0
        ch12_peak = np.max(np.abs(block[:, 11]))
        self.assertEqual(ch12_peak, 0.0)

        # Stop engine
        engine.stop()
        self.assertFalse(engine.is_active)
        post_stop = engine.generate_audio_block(block_size=1024)
        self.assertEqual(np.max(np.abs(post_stop)), 0.0)

    def test_soundcheck_session_presets(self):
        engine = VirtualSoundcheckEngine(sample_rate=48000)
        presets = ["SUNDAY_WORSHIP_BALLAD", "SUNDAY_UPTEMPO_PRAISE", "SERMON_PREACHING", "CONGREGATIONAL_PRAYER"]
        for p in presets:
            s = engine.start_session(p)
            self.assertEqual(s.id, p)
            status = engine.get_status()
            self.assertTrue(status["is_active"])
            self.assertEqual(status["session_id"], p)
            self.assertGreater(len(status["available_presets"]), 0)

    # --- 2. Church Channel Profile Manager Tests ---

    def test_church_profile_manager_and_invariant_protection(self):
        mgr = ChurchProfileManager()
        channels = mgr.get_channels()
        self.assertEqual(len(channels), 32)

        # Verify Channel 11 is protected by default
        ch11 = next(c for c in channels if c["channel"] == 11)
        self.assertTrue(ch11["is_protected"])
        self.assertEqual(ch11["role"], "TALKBACK_BAND")

        # Attempt to compromise Channel 11 role or remove protection
        updated_11 = mgr.update_channel(11, {
            "name": "Hacker Mic",
            "role": "LEAD_VOCAL_FEMALE",
            "is_protected": False,
        })
        self.assertTrue(updated_11["is_protected"], "Channel 11 protection must NOT be removed!")
        self.assertEqual(updated_11["role"], "TALKBACK_BAND", "Channel 11 role must remain TALKBACK_BAND!")

        # Update legitimate channel (Ch 1)
        updated_1 = mgr.update_channel(1, {
            "name": "Pastor Main Pulpit",
            "notes": "Micro bục giảng phòng nhóm chính",
        })
        self.assertEqual(updated_1["name"], "Pastor Main Pulpit")

        # Reset back to default
        reset_channels = mgr.reset_to_default()
        ch1 = next(c for c in reset_channels if c["channel"] == 1)
        self.assertEqual(ch1["name"], "Pastor Mic")

    # --- 3. Printable Sunday Service Report Generator Tests ---

    def test_report_generator_html_structure(self):
        html = generate_printable_sunday_report_html(
            church_name="Hội Thánh Tin Lành Hà Nội",
            engineer_name="Nguyễn Văn A",
            mixer_model="Behringer X32 Compact",
            snapshot_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            stats={
                "duration_minutes": 105,
                "peak_dbfs": -2.1,
                "loudness_lufs": -18.0,
                "feedback_incidents_prevented": 3,
                "clipping_events": 0,
                "silence_hold_activations": 18,
            },
        )
        self.assertIn("BÁO CÁO KỸ THUẬT ÂM THANH BUỔI LỄ CHÚA NHẬT", html)
        self.assertIn("Hội Thánh Tin Lành Hà Nội", html)
        self.assertIn("Nguyễn Văn A", html)
        self.assertIn("Behringer X32 Compact", html)
        self.assertIn("e3b0c44298fc1c14", html)
        self.assertIn("Bất biến DL16 #11", html)
        self.assertIn("Silence Hold Invariant", html)
        self.assertIn("105 Phút", html)
        self.assertIn("KỸ THUẬT VIÊN ÂM THANH TRỰC LỄ", html)
        self.assertIn("TRƯỞNG BAN KỸ THUẬT / PHỤ TRÁCH THÁNH LỄ", html)

    # --- 4. FastAPI REST Endpoints Tests ---

    def test_api_soundcheck_endpoints(self):
        # Initial status
        res = self.client.get("/api/v1/soundcheck/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("is_active", data)
        self.assertIn("available_presets", data)

        # List presets
        res = self.client.get("/api/v1/soundcheck/sessions")
        self.assertEqual(res.status_code, 200)
        sessions = res.json()["sessions"]
        self.assertEqual(len(sessions), 5)
        self.assertIn("FEEDBACK_DRILL", [s["id"] for s in sessions])

        # Start Uptempo session
        res = self.client.post("/api/v1/soundcheck/start", json={"session_id": "SUNDAY_UPTEMPO_PRAISE"})
        self.assertEqual(res.status_code, 200)
        start_data = res.json()
        self.assertEqual(start_data["status"], "STARTED")
        self.assertEqual(start_data["session_id"], "SUNDAY_UPTEMPO_PRAISE")
        self.assertTrue(start_data["is_active"])

        # Check status reflects active session
        res = self.client.get("/api/v1/soundcheck/status")
        self.assertTrue(res.json()["is_active"])
        self.assertEqual(res.json()["session_id"], "SUNDAY_UPTEMPO_PRAISE")

        # Stop soundcheck
        res = self.client.post("/api/v1/soundcheck/stop")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["is_active"])

    def test_api_church_channels_endpoints(self):
        # Fetch channels
        res = self.client.get("/api/v1/config/church-channels")
        self.assertEqual(res.status_code, 200)
        channels = res.json()["channels"]
        self.assertEqual(len(channels), 32)
        self.assertTrue(res.json()["talkback_invariant_protected"])

        # Update Channel 3
        res = self.client.post(
            "/api/v1/config/church-channels/3",
            json={"name": "Chị Lan (Lead Nữ)", "color": "pink"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["channel"]["name"], "Chị Lan (Lead Nữ)")

        # Attempt to compromise Channel 11
        res = self.client.post(
            "/api/v1/config/church-channels/11",
            json={"name": "Compromised Ch 11", "role": "FOH_VOCAL"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["channel"]["role"], "TALKBACK_BAND")
        self.assertTrue(res.json()["channel"]["is_protected"])

        # Reset channels
        res = self.client.post("/api/v1/config/church-channels/reset")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "RESET")

    def test_api_sunday_report_endpoint(self):
        res = self.client.get(
            "/api/v1/reports/sunday-service?church_name=Hội%20Thánh%20Grace&engineer_name=Lê%20Văn%20B"
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers.get("content-type", ""))
        html = res.text
        self.assertIn("BÁO CÁO KỸ THUẬT ÂM THANH BUỔI LỄ CHÚA NHẬT", html)
        self.assertIn("Hội Thánh Grace", html)
        self.assertIn("Lê Văn B", html)
        self.assertIn("Bất biến DL16 #11", html)


if __name__ == "__main__":
    unittest.main()
