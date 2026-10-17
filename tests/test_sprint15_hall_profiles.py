"""
Sprint 15 Test Suite:
Multi-Sanctuary Hall Acoustic Profiles & Baseline Comparison Engine
===================================================================
Tests:
1. Multi-Hall Profile Management (4 Church Presets: Main, Youth, Fellowship, Outdoor)
2. Hall Profile Versioning & Active Selection Persistence
3. Acoustic Baseline Deviation Analysis (RMS error, delay drift, critical deviations)
4. Enforcement of No-Boost-in-Nulls during acoustic comparison
5. REST API Endpoints (/api/v1/halls/*)
"""

import unittest
import os
import sys
import tempfile
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.storage.hall_profiles import HallProfileManager, HallProfile
from apps.api.main import app


class TestSprint15HallProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

        cls.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.config_path = os.path.join(cls.temp_dir.name, "test_halls.json")
        cls.mgr = HallProfileManager(config_path=cls.config_path)

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_default_hall_profiles_initialized(self):
        """Verify the 4 default church hall acoustic profiles exist."""
        halls = self.mgr.get_all_halls()
        self.assertEqual(len(halls), 4)
        hall_ids = [h.id for h in halls]
        self.assertIn("MAIN_SANCTUARY", hall_ids)
        self.assertIn("YOUTH_CHAPEL", hall_ids)
        self.assertIn("FELLOWSHIP_HALL", hall_ids)
        self.assertIn("OUTDOOR_CAMPUS", hall_ids)

        active = self.mgr.get_active_hall()
        self.assertEqual(active.id, "MAIN_SANCTUARY")

    def test_02_switch_active_hall(self):
        """Switch active hall and verify persistence."""
        switched = self.mgr.set_active_hall("YOUTH_CHAPEL")
        self.assertEqual(switched.id, "YOUTH_CHAPEL")

        active = self.mgr.get_active_hall()
        self.assertEqual(active.id, "YOUTH_CHAPEL")

        # Switch back
        self.mgr.set_active_hall("MAIN_SANCTUARY")
        self.assertEqual(self.mgr.get_active_hall().id, "MAIN_SANCTUARY")

    def test_03_hall_profile_versioning(self):
        """Creating and updating a hall increments its version number."""
        new_hall = HallProfile(
            id="BAPTISM_CHAPEL",
            name="Phòng Nhóm Báp-têm",
            capacity_seats=60,
            target_rt60_seconds=0.7,
            nominal_delay_ms=1.2,
            ambient_noise_dbfs=-64.0,
            speaker_system="2x Loa Monitor Treo Tường",
            target_curve_slope_db_per_oct=-1.0,
            safe_gain_limit_db=3.5,
            notes="Phòng lễ nhỏ yên tĩnh",
        )
        saved = self.mgr.save_hall(new_hall)
        self.assertEqual(saved.version, 1)

        # Update notes
        saved.notes = "Phòng lễ nhỏ đã lắp thảm tiêu âm"
        updated = self.mgr.save_hall(saved)
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.notes, "Phòng lễ nhỏ đã lắp thảm tiêu âm")

    def test_04_baseline_comparison_healthy_curve(self):
        """Comparing a matching transfer function produces HEALTHY status."""
        main_hall = self.mgr.get_hall("MAIN_SANCTUARY")
        # Synthesize matching measurement curve
        meas_curve = []
        for pt in main_hall.baseline_curve:
            meas_curve.append({
                "freq": pt["freq"],
                "magnitude_db": pt["target_db"] + 0.3, # Minimal 0.3dB deviation
                "coherence": pt["coherence"],
            })

        diff = self.mgr.compare_measurement_against_baseline(
            hall_id="MAIN_SANCTUARY",
            measurement_curve=meas_curve,
            delay_ms=3.5,
        )
        self.assertEqual(diff["status"], "HEALTHY")
        self.assertLess(diff["rms_deviation_db"], 1.5)
        self.assertAlmostEqual(diff["delay_drift_ms"], 0.0, places=2)
        self.assertIn("Trạng thái tối ưu", diff["recommendations_vi"][0])

    def test_05_baseline_comparison_deviation_and_null_warning(self):
        """Critical deviations and deep nulls trigger specific tactical recommendations."""
        main_hall = self.mgr.get_hall("MAIN_SANCTUARY")
        meas_curve = []
        for pt in main_hall.baseline_curve:
            val = pt["target_db"]
            if pt["freq"] == 250.0:
                val += 4.5 # Heavy resonance
            elif pt["freq"] == 4000.0:
                val -= 5.5 # Deep acoustic null dip
            meas_curve.append({
                "freq": pt["freq"],
                "magnitude_db": val,
                "coherence": pt["coherence"],
            })

        diff = self.mgr.compare_measurement_against_baseline(
            hall_id="MAIN_SANCTUARY",
            measurement_curve=meas_curve,
            delay_ms=5.0, # 1.5ms drift compared to nominal 3.5ms
        )
        self.assertEqual(diff["status"], "DEVIATED")
        self.assertGreater(diff["rms_deviation_db"], 2.0)
        self.assertAlmostEqual(diff["delay_drift_ms"], 1.5, places=2)

        recs = " ".join(diff["recommendations_vi"])
        self.assertIn("Độ trễ loa lệch", recs)
        self.assertIn("cộng hưởng phòng", recs)
        self.assertIn("NO-BOOST-IN-NULLS", recs)

    def test_06_fastapi_hall_endpoints(self):
        """Test REST API routes for sanctuary hall management."""
        # 1. List halls
        res = self.client.get("/api/v1/halls")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["count"], 4)
        self.assertIn("active_hall_id", data)

        # 2. Get specific hall
        res = self.client.get("/api/v1/halls/MAIN_SANCTUARY")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Hội Trường Lớn (Main Sanctuary)")

        # 3. Activate hall
        res = self.client.post("/api/v1/halls/YOUTH_CHAPEL/activate")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ACTIVATED")
        self.assertEqual(res.json()["active_hall"]["id"], "YOUTH_CHAPEL")

        # 4. Compare endpoint
        res = self.client.post(
            "/api/v1/halls/YOUTH_CHAPEL/compare",
            json={
                "delay_ms": 1.8,
                "curve": [
                    {"freq": 100.0, "magnitude_db": 2.0, "coherence": 0.95},
                    {"freq": 1000.0, "magnitude_db": 0.0, "coherence": 0.97},
                ]
            }
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("rms_deviation_db", res.json())
        self.assertIn("status", res.json())

        # 5. Get active hall directly
        res = self.client.get("/api/v1/halls/active")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["id"], "YOUTH_CHAPEL")

        # 6. Compare active hall baseline directly
        res = self.client.get("/api/v1/halls/active/compare")
        self.assertEqual(res.status_code, 200)
        self.assertIn("status", res.json())
        self.assertIn("recommendations_vi", res.json())


if __name__ == "__main__":
    unittest.main()
