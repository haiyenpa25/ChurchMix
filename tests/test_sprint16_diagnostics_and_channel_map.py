"""
Sprint 16 Test Suite: System Diagnostics & 32-Channel Profile Map
=================================================================
Verifies:
1. REST API for church channel profile layout management (32 channels).
2. Immutable protection invariant on Channel 11 (Talkback Band -> P16 only).
3. Channel profile reset to default functionality.
4. Automated 10-point pre-service system health diagnostics endpoint.
5. CLI execution integrity of diagnose_system.py.
"""
from __future__ import annotations
import unittest
import os
import sys
import subprocess
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.main import app
from diagnose_system import run_all_diagnostics
from packages.storage.church_profile import ChurchProfileManager


class TestSprint16DiagnosticsAndChannelMap(unittest.TestCase):
    """Test Suite for Diagnostics Engine and 32-Channel Profile Customizer."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.mgr = ChurchProfileManager()

    def test_01_get_church_channels(self):
        """Test retrieving all 32 church channel definitions."""
        res = self.client.get("/api/v1/config/church-channels")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("channels", data)
        self.assertEqual(len(data["channels"]), 32)
        self.assertTrue(data.get("talkback_invariant_protected"))

        # Verify Channel 11 is strictly protected
        ch11 = next((c for c in data["channels"] if c["channel"] == 11), None)
        self.assertIsNotNone(ch11)
        self.assertTrue(ch11["is_protected"])
        self.assertEqual(ch11["role"], "TALKBACK_BAND")

    def test_02_update_channel_profile_permitted(self):
        """Updating benign channels (e.g., Ch 1 Pastor Mic, Ch 3 Lead Vocal) succeeds."""
        res = self.client.post(
            "/api/v1/config/church-channels/1",
            json={
                "name": "Mục Sư Quản Nhiệm (Senior Pastor)",
                "role": "PASTOR_SPEECH",
                "notes": "Micro bục giảng chính - Shure QLXD",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "UPDATED")
        self.assertEqual(data["channel"]["name"], "Mục Sư Quản Nhiệm (Senior Pastor)")

    def test_03_protect_channel_11_invariant(self):
        """Attempting to strip protection or change role of DL16 In 11 Talkback is denied."""
        # Attempt to disable protection or mutate role
        res = self.client.post(
            "/api/v1/config/church-channels/11",
            json={
                "name": "Hát Bè Ban Hát",
                "role": "LEAD_VOCAL_FEMALE", # Attempt to turn Talkback into FOH vocal
                "is_protected": False,
            },
        )
        # Even if updated, the manager locks is_protected and role
        self.assertEqual(res.status_code, 200)
        ch11 = res.json()["channel"]
        self.assertTrue(ch11["is_protected"])
        self.assertEqual(ch11["role"], "TALKBACK_BAND")

    def test_04_reset_church_channels(self):
        """Resetting church channels restores standard defaults."""
        res = self.client.post("/api/v1/config/church-channels/reset")
        self.assertEqual(res.status_code, 200)
        channels = res.json()["channels"]
        ch1 = next(c for c in channels if c["channel"] == 1)
        self.assertEqual(ch1["name"], "Pastor Mic")

    def test_05_system_diagnostics_function(self):
        """run_all_diagnostics executes 10 checks and passes 100%."""
        report = run_all_diagnostics(verbose=False)
        self.assertEqual(report["overall_status"], "PASS")
        self.assertEqual(report["total_count"], 10)
        self.assertEqual(report["passed_count"], 10)
        self.assertTrue(all(c["passed"] for c in report["checks"]))

    def test_06_system_diagnostics_api_endpoint(self):
        """GET /api/v1/system/diagnostics returns full health report."""
        res = self.client.get("/api/v1/system/diagnostics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["overall_status"], "PASS")
        self.assertEqual(data["total_count"], 10)
        self.assertGreaterEqual(data["passed_count"], 10)

    def test_07_diagnose_system_cli_exit_code(self):
        """Executing diagnose_system.py via CLI returns exit code 0."""
        python_exe = sys.executable
        res = subprocess.run(
            [python_exe, "diagnose_system.py"],
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(res.returncode, 0, f"CLI output: {res.stdout}\n{res.stderr}")
        self.assertIn("TOÀN BỘ 10/10 MỤC KIỂM TRA ĐẠT TIÊU CHUẨN 100%", res.stdout)


if __name__ == "__main__":
    unittest.main()
