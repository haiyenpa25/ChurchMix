"""
Sprint 20 Test Suite: Native Behringer X32 Scene (.scn) Importer & Pre-Flight Safety Validator.
==============================================================================================
Tests:
1. ASCII .scn text parsing into normalized X32 parameter dictionary.
2. Pre-flight safety audit:
   - Hard Invariant DL16 In 11 (Band Talkback) routing leak detection.
   - Excessive fader gain (> +5 dB) detection.
   - Missing vocal HPF (< 80 Hz) detection.
   - Aggressive narrow-band EQ boost detection.
3. Automated sanitization & invariant enforcement:
   - Forcing /ch/11/mix/lr = 0 (OFF).
   - Forcing /outputs/p16/11/src = 11.
   - Applying vocal HPF (95 Hz) and clamping high faders.
4. Complete import_and_vault pipeline with SQLite persistence & SHA-256 integrity.
5. REST API endpoints: POST /api/v1/vault/audit-scn and POST /api/v1/vault/import-scn.
"""
import unittest
import numpy as np
from fastapi.testclient import TestClient

from packages.storage.scn_importer import SceneImporter, SceneAuditReport
from packages.storage.scene_vault import SceneVaultManager
from packages.storage.database import ChurchMixDatabase
from apps.api.main import app


SAMPLE_UNSAFE_SCN = """#2.1# "Visiting_Band_Mix" "Guest Worship Band Scene" %000000000 1
/ch/01/config "Lead Vocal" 1 YE 0
/ch/01/preamp +0.0 OFF OFF 40.0
/ch/01/mix/fader 0.9200
/ch/01/mix/on ON
/ch/01/mix/lr ON
/ch/01/eq ON
/ch/01/eq/1 PEQ 80.0 +0.0 2.0
/ch/01/eq/2 PEQ 2500.0 +9.5 3.5

/ch/11/config "Band Talkback" 3 RD 10
/ch/11/mix/fader 0.7500
/ch/11/mix/on ON
/ch/11/mix/lr ON
/outputs/p16/11/src 10
"""

SAMPLE_SAFE_SCN = """#2.1# "Sunday_Sanctuary_Safe" "ChurchMix Approved Scene" %000000000 1
/ch/01/config "Pastor Mic" 1 YE 0
/ch/01/preamp +0.0 OFF ON 100.0
/ch/01/mix/fader 0.7500
/ch/01/mix/on ON
/ch/01/mix/lr ON

/ch/11/config "Talkback DL16" 3 RD 10
/ch/11/mix/fader 0.7500
/ch/11/mix/on ON
/ch/11/mix/lr OFF
/outputs/p16/11/src 11
"""


class TestSprint20ScnImporterAndSafetyValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_parse_scn_ascii_text(self):
        """Verify parsing of standard Behringer X32 .scn text file."""
        scene_name, params = SceneImporter.parse_scn_text(SAMPLE_UNSAFE_SCN)
        self.assertEqual(scene_name, "Visiting_Band_Mix")
        self.assertEqual(params["/ch/01/config/name"], "Lead Vocal")
        self.assertEqual(params["/ch/01/mix/fader"], 0.9200)
        self.assertEqual(params["/ch/01/mix/on"], 1)
        self.assertEqual(params["/ch/01/mix/lr"], 1)
        self.assertEqual(params["/ch/01/preamp/hpon"], 0)
        self.assertEqual(params["/ch/11/mix/lr"], 1) # Unsafe Talkback leak!
        self.assertEqual(params["/outputs/p16/11/src"], 10)

    def test_audit_safe_scene(self):
        """Verify safety audit on an approved church scene with proper isolation."""
        scene_name, params = SceneImporter.parse_scn_text(SAMPLE_SAFE_SCN)
        report = SceneImporter.audit_scene(params, scene_name=scene_name)

        self.assertTrue(report.invariant_passed)
        self.assertEqual(len(report.violations), 0)
        self.assertIn("AN TOÀN", report.summary_vi)

    def test_audit_unsafe_scene_talkback_violation_and_warnings(self):
        """
        Verify safety audit catches:
        1. DL16 In 11 Talkback leak to Main FOH.
        2. Excessive fader gain (> 0.85).
        3. Missing HPF on vocal channel 1.
        4. Dangerous narrow PEQ boost (+9.5 dB, Q=3.5).
        """
        scene_name, params = SceneImporter.parse_scn_text(SAMPLE_UNSAFE_SCN)
        report = SceneImporter.audit_scene(params, scene_name=scene_name)

        self.assertFalse(report.invariant_passed)
        self.assertFalse(report.is_safe)
        self.assertTrue(any("Band Talkback" in v for v in report.violations))
        self.assertTrue(any("FADER LỚN" in w for w in report.warnings))
        self.assertTrue(any("HPF" in w or "LỌC GIÓ" in w for w in report.warnings))
        self.assertTrue(any("HÚ ÂM" in w for w in report.warnings))

    def test_auto_sanitize_patches_invariants_and_clamps_faders(self):
        """Verify automated sanitization fixes all invariant hazards."""
        _, raw_params = SceneImporter.parse_scn_text(SAMPLE_UNSAFE_SCN)
        sanitized, patches = SceneImporter.sanitize_scene(raw_params)

        # 1. Talkback must be forced to OFF on Main FOH
        self.assertEqual(sanitized["/ch/11/mix/lr"], 0)
        # 2. P16 slot 11 must be re-routed to 11
        self.assertEqual(sanitized["/outputs/p16/11/src"], 11)
        # 3. Channel 1 fader must be clamped from 0.92 to 0.75
        self.assertEqual(sanitized["/ch/01/mix/fader"], 0.75)
        # 4. Channel 1 HPF must be turned ON
        self.assertEqual(sanitized["/ch/01/preamp/hpon"], 1)

        self.assertGreater(len(patches), 0)
        # Re-audit sanitized state
        post_report = SceneImporter.audit_scene(sanitized)
        self.assertTrue(post_report.invariant_passed, "Sanitized scene must pass invariant check 100%")

    def test_import_and_vault_pipeline(self):
        """Verify complete import -> audit -> auto-sanitize -> vault persistence."""
        db = ChurchMixDatabase()
        vault = SceneVaultManager(db)

        result = SceneImporter.import_and_vault(
            scn_content=SAMPLE_UNSAFE_SCN,
            vault_mgr=vault,
            author="TestEngineer",
            note="Test USB import with auto-sanitization",
            auto_sanitize=True,
        )

        self.assertTrue(result["sanitized"])
        self.assertGreater(len(result["patches_applied"]), 0)
        self.assertTrue(result["audit_report"]["invariant_passed"])
        self.assertIn("vault_backup", result)
        self.assertEqual(result["vault_backup"]["talkback_safe"], True)

        # Check that backup is retrieved from vault
        backup = vault.get_backup(result["vault_backup"]["id"])
        self.assertIsNotNone(backup)
        self.assertEqual(backup["state"]["/ch/11/mix/lr"], 0)

    def test_rest_api_audit_and_import_scn_endpoints(self):
        """Test POST /api/v1/vault/audit-scn and POST /api/v1/vault/import-scn."""
        # 1. POST /api/v1/vault/audit-scn (Pre-flight only)
        res_audit = self.client.post(
            "/api/v1/vault/audit-scn",
            json={"scn_content": SAMPLE_UNSAFE_SCN},
        )
        self.assertEqual(res_audit.status_code, 200)
        data_audit = res_audit.json()
        self.assertFalse(data_audit["invariant_passed"])
        self.assertGreater(len(data_audit["violations"]), 0)

        # 2. POST /api/v1/vault/import-scn (Import & Sanitize)
        res_import = self.client.post(
            "/api/v1/vault/import-scn",
            json={
                "scn_content": SAMPLE_UNSAFE_SCN,
                "author": "Guest_USB",
                "note": "Imported via API",
                "auto_sanitize": True,
            },
        )
        self.assertEqual(res_import.status_code, 200)
        data_import = res_import.json()
        self.assertTrue(data_import["sanitized"])
        self.assertTrue(data_import["audit_report"]["invariant_passed"])
        self.assertIn("vault_backup", data_import)

        # 3. Empty content should return 400 error
        res_err = self.client.post(
            "/api/v1/vault/audit-scn",
            json={"scn_content": "   "},
        )
        self.assertEqual(res_err.status_code, 400)


if __name__ == "__main__":
    unittest.main()
