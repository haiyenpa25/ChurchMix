"""
Sprint 10 Test Suite:
- SQLite Storage Layer (ChurchMixDatabase)
- Snapshot Persistence & SHA-256 Integrity Verification
- Immutable Audit Event Logging & Cryptographic Hashes
- Acoustic Transfer Function Measurement History
- Automated X32 Console Discovery over UDP OSC
- Live Service Assistant Tactical Status (Wizard 6)
"""

import unittest
import os
X32_TEST_PORT = int(os.environ.get("CHURCHMIX_X32_PORT", "10023"))
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.storage.database import ChurchMixDatabase
from packages.x32_osc_adapter.client import X32Client
from packages.mock_x32.server import MockX32Server
from packages.wizards.service import WizardService


class TestSprint10DatabaseAndDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup temporary isolated SQLite DB for testing
        cls.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db_path = os.path.join(cls.temp_dir.name, "test_churchmix.db")
        cls.db = ChurchMixDatabase(db_path=cls.db_path)

        # Setup mock X32 server for discovery test
        cls.server = MockX32Server(host="127.0.0.1", port=X32_TEST_PORT)
        cls.server.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        try:
            del cls.db
            cls.temp_dir.cleanup()
        except Exception:
            pass


    def test_database_snapshot_persistence(self):
        sample_state = {"/ch/01/mix/fader": 0.75, "/main/st/mix/fader": 0.75}
        sha = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
        
        row_id = self.db.save_snapshot(
            sha256=sha,
            state_dict=sample_state,
            mixer_id="X32_Compact",
            author="SoundTech_Lead",
            note="Pre-service baseline snapshot",
        )
        self.assertGreater(row_id, 0)

        latest = self.db.get_latest_snapshot()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["sha256"], sha)
        self.assertEqual(latest["author"], "SoundTech_Lead")
        self.assertEqual(latest["note"], "Pre-service baseline snapshot")

    def test_database_immutable_audit_events(self):
        ev_id = self.db.save_audit_event(
            actor="Engineer_Bao",
            action="APPLY_PROPOSAL",
            proposal_id="prop-sunday-001",
            status="COMMITTED",
            details={"band": 2, "freq": 2800, "gain": 1.2, "q": 1.8},
        )
        self.assertGreater(ev_id, 0)

        events = self.db.get_recent_audit_events(limit=10)
        self.assertTrue(len(events) >= 1)
        found = next((e for e in events if e["id"] == ev_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["actor"], "Engineer_Bao")
        self.assertEqual(found["action"], "APPLY_PROPOSAL")
        self.assertEqual(found["status"], "COMMITTED")
        self.assertEqual(len(found["immutable_hash"]), 12) # Shortened sha256 display

    def test_database_measurement_persistence(self):
        meas_id = self.db.save_measurement(
            name="Dual-Channel H1 Transfer Function",
            position="Center Hall - FOH",
            delay_ms=3.5,
            coherence_avg=0.978,
            rule_enforced="NO-BOOST-IN-NULLS",
            result_data={"curve_samples": 60, "peak_cut": -3.5},
        )
        self.assertGreater(meas_id, 0)

        history = self.db.get_measurements(limit=5)
        self.assertTrue(len(history) >= 1)
        m = history[0]
        self.assertEqual(m["name"], "Dual-Channel H1 Transfer Function")
        self.assertEqual(m["position"], "Center Hall - FOH")
        self.assertEqual(m["delay_ms"], 3.5)
        self.assertAlmostEqual(m["coherence_avg"], 0.978, places=3)
        self.assertEqual(m["rule_enforced"], "NO-BOOST-IN-NULLS")

    def test_hardware_discovery_scanner(self):
        # Discover mock console on localhost
        consoles = X32Client.discover_consoles(target_hosts=["127.0.0.1"], port=X32_TEST_PORT, timeout=0.8)
        self.assertGreaterEqual(len(consoles), 1)
        c = consoles[0]
        self.assertEqual(c["ip"], "127.0.0.1")
        self.assertEqual(c["port"], X32_TEST_PORT)
        self.assertIn("X32", c["model"])
        self.assertIn("V4.", c["firmware"])

    def test_live_assistant_wizard_service(self):
        client = X32Client(host="127.0.0.1", port=X32_TEST_PORT, read_only_mode=True)
        client.connect()
        service = WizardService(client=client)

        status = service.get_live_service_assistant_status(
            stop_auto_triggered=False,
            active_feedback_alerts=[],
        )
        self.assertTrue(status.mixer_online)
        self.assertTrue(status.read_only_mode)
        self.assertFalse(status.stop_auto_engaged)
        self.assertEqual(status.overall_health, "EXCELLENT")
        self.assertEqual(status.master_fader_pct, 75)
        self.assertEqual(len(status.channel_highlights), 4)

        # Invariant on Talkback (Ch 11) must be emphasized in recommendations
        ch11 = next(c for c in status.channel_highlights if c.channel_id == 11)
        self.assertEqual(ch11.role, "TALKBACK")
        self.assertIn("DL16 #11", ch11.recommendation_vi)
        self.assertIn("P16", ch11.recommendation_vi)

        client.close()


if __name__ == "__main__":
    unittest.main()
