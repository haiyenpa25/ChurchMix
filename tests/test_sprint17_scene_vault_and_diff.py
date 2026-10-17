"""
Sprint 17 Test Suite: Scene Vault Archive, Invariant Checks & Snapshot Diff
===========================================================================
Verifies:
1. Snapshot archival with SHA-256 integrity calculation and metadata.
2. DL16 In 11 Talkback safety invariant audit upon backup creation.
3. Native Behringer X32 (.scn) USB file generation from archived snapshots.
4. Granular side-by-side delta diffing (faders, mutes, HPF, PEQ bands).
5. REST API endpoints for Scene Vault (List, Create, Compare, Download .scn, Delete).
"""
from __future__ import annotations
import unittest
import os
import sys
import tempfile
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.main import app
from packages.storage.database import ChurchMixDatabase
from packages.storage.scene_vault import SceneVaultManager


def make_clean_test_state() -> dict:
    """Construct a clean, valid 32-channel mock state dictionary."""
    state = {}
    for ch in range(1, 33):
        prefix = f"/ch/{ch:02d}"
        state[f"{prefix}/config/name"] = f"Channel {ch}"
        state[f"{prefix}/mix/fader"] = 0.75
        state[f"{prefix}/mix/on"] = 1
        state[f"{prefix}/preamp/hpon"] = 1
        state[f"{prefix}/eq/on"] = 1
        for b in range(1, 5):
            state[f"{prefix}/eq/{b}/f"] = 0.5
            state[f"{prefix}/eq/{b}/g"] = 0.5
            state[f"{prefix}/eq/{b}/q"] = 0.5
    # Configure routing: DL16 In 11 -> Ultranet P16 Slot 11 ONLY
    state["/outputs/p16/11/src"] = 11  # DL16 #11 -> P16 #11
    state["/ch/11/mix/st"] = 0         # Ch 11 stereo main LR OFF
    state["/ch/11/mix/mono"] = 0       # Ch 11 mono bus OFF
    return state


class TestSprint17SceneVaultAndDiff(unittest.TestCase):
    """Test Suite for Scene Vault and Snapshot Diffing."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Create temporary database for test isolation
        cls.temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.temp_db_path = cls.temp_db_file.name
        cls.temp_db_file.close()

        cls.db = ChurchMixDatabase(cls.temp_db_path)
        cls.vault = SceneVaultManager(db=cls.db)

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls.temp_db_path):
                os.remove(cls.temp_db_path)
        except Exception:
            pass

    def test_01_create_and_retrieve_backup(self):
        """Test creating a versioned snapshot with SHA-256 and retrieving it."""
        state = make_clean_test_state()
        state["/ch/01/config/name"] = "Pastor Pulpit"

        backup = self.vault.create_backup(
            name="Sunday Morning Soundcheck",
            author="SoundTech_Hai",
            note="Pre-worship baseline soundcheck",
            state_dict=state,
        )

        self.assertIsNotNone(backup.get("id"))
        self.assertEqual(backup["name"], "Sunday Morning Soundcheck")
        self.assertEqual(len(backup["sha256"]), 64)
        self.assertTrue(backup["talkback_safe"])

        # Retrieve and verify parameters
        fetched = self.vault.get_backup(backup["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["author"], "SoundTech_Hai")
        self.assertEqual(fetched["state"]["/ch/01/config/name"], "Pastor Pulpit")

    def test_02_talkback_invariant_detection_in_vault(self):
        """Snapshots that route Ch 11 to Main LR fail the Talkback safety check."""
        state = make_clean_test_state()
        # Deliberately violate invariant: assign Ch 11 to Stereo Main
        state["/ch/11/mix/st"] = 1

        backup = self.vault.create_backup(
            name="Compromised Scene",
            author="Attacker",
            note="Accidentally unmuted band talkback to FOH",
            state_dict=state,
        )

        self.assertFalse(backup["talkback_safe"])
        self.assertIn("VIOLATION", backup["talkback_message"].upper())

    def test_03_export_native_scn_file(self):
        """Exporting a snapshot produces valid Behringer X32 .scn file syntax."""
        state = make_clean_test_state()
        backup = self.vault.create_backup(
            name="Easter Service",
            author="Operator",
            note="Special holiday service setup",
            state_dict=state,
        )

        scn_data = self.vault.export_backup_scn(backup["id"])
        self.assertIn("filename", scn_data)
        self.assertTrue(scn_data["filename"].endswith(".scn"))
        self.assertIn('#2.1# "Easter Service"', scn_data["content"])
        self.assertIn("/ch/01/mix/fader", scn_data["content"])

    def test_04_snapshot_diffing(self):
        """Diffing two snapshots identifies fader, mute, and EQ modifications."""
        state_a = make_clean_test_state()
        state_a["/ch/01/mix/fader"] = 0.70
        state_a["/ch/02/mix/on"] = 1
        state_a["/ch/03/eq/2/g"] = 0.50

        state_b = make_clean_test_state()
        state_b["/ch/01/mix/fader"] = 0.80  # +10%
        state_b["/ch/02/mix/on"] = 0        # Muted
        state_b["/ch/03/eq/2/g"] = 0.65     # +4.5dB boost

        diff = self.vault.diff_states(state_a, state_b, label_a="Before", label_b="After")
        self.assertEqual(diff["total_channels_changed"], 3)

        ch1_diff = next((c for c in diff["channel_diffs"] if c["channel"] == 1), None)
        ch2_diff = next((c for c in diff["channel_diffs"] if c["channel"] == 2), None)
        ch3_diff = next((c for c in diff["channel_diffs"] if c["channel"] == 3), None)

        self.assertIsNotNone(ch1_diff)
        self.assertTrue(any("Fader" in change for change in ch1_diff["changes"]))

        self.assertIsNotNone(ch2_diff)
        self.assertTrue(any("MUTE" in change for change in ch2_diff["changes"]))

        self.assertIsNotNone(ch3_diff)
        self.assertTrue(any("PEQ Band 2" in change for change in ch3_diff["changes"]))

    def test_05_rest_api_vault_flow(self):
        """Test full REST API workflow for vault snapshot creation, listing, compare, download, and delete."""
        state = make_clean_test_state()
        res_post = self.client.post(
            "/api/v1/vault/snapshots",
            json={
                "name": "Integration Test Scene",
                "author": "CI_Runner",
                "note": "Snapshot generated during automated integration test",
                "state_dict": state,
            },
        )
        self.assertEqual(res_post.status_code, 200)
        snap_data = res_post.json()
        self.assertEqual(snap_data["status"], "BACKUP_SAVED")
        backup_id = snap_data["backup"]["id"]

        # 2. List snapshots
        res_list = self.client.get("/api/v1/vault/snapshots")
        self.assertEqual(res_list.status_code, 200)
        snapshots = res_list.json().get("snapshots", [])
        self.assertTrue(any(s["id"] == backup_id for s in snapshots))

        # 3. Create a second snapshot to compare
        state2 = make_clean_test_state()
        state2["/ch/01/mix/fader"] = 0.90
        res_post2 = self.client.post(
            "/api/v1/vault/snapshots",
            json={
                "name": "Integration Test Scene v2",
                "author": "CI_Runner",
                "note": "Second revision",
                "state_dict": state2,
            },
        )
        self.assertEqual(res_post2.status_code, 200)
        backup_id_2 = res_post2.json()["backup"]["id"]

        # 4. Compare both snapshots via API
        res_comp = self.client.post(
            "/api/v1/vault/snapshots/compare",
            json={
                "snapshot_id_a": backup_id,
                "snapshot_id_b": backup_id_2,
            },
        )
        self.assertEqual(res_comp.status_code, 200)
        comp_data = res_comp.json()
        self.assertIn("summary_vi", comp_data)
        self.assertTrue(comp_data["talkback_status_a"]["safe"])

        # 5. Download .scn file
        res_scn = self.client.get(f"/api/v1/vault/snapshots/{backup_id}/download-scn")
        self.assertEqual(res_scn.status_code, 200)
        scn_payload = res_scn.json()
        self.assertIn("#2.1#", scn_payload["content"])

        # 6. Delete snapshot
        res_del = self.client.delete(f"/api/v1/vault/snapshots/{backup_id}")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["status"], "DELETED")


if __name__ == "__main__":
    unittest.main()
