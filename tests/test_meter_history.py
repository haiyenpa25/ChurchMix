"""MeterHistory: rolling window, source isolation and trust rules."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.autopilot.meter_history import MeterHistory

X32 = {"id": "x32-meters", "valid": True, "simulated": False, "mapping_verified": True}
MOCK = {"id": "x32-meters", "valid": True, "simulated": True, "mapping_verified": True}
USB = {"id": "capture:1", "valid": True, "simulated": False, "mapping_verified": False}


class TestMeterHistory(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.h = MeterHistory(window_s=10.0, clock=lambda: self.now[0])

    def feed(self, seconds, level, source=X32, ch=1, step=0.1):
        end = self.now[0] + seconds
        while self.now[0] < end:
            self.h.add([{"channel": ch, "meter_dbfs": level}], source)
            self.now[0] += step

    def test_window_and_stats(self):
        self.feed(3.0, -20.0)
        self.feed(3.0, -30.0)
        st = self.h.stats(1, 6.0)
        self.assertGreater(st["count"], 50)
        self.assertEqual(st["peak_dbfs"], -20.0)
        self.assertEqual(st["min_dbfs"], -30.0)
        self.assertAlmostEqual(self.h.coverage_s(), 6.0, delta=0.2)

    def test_old_samples_expire(self):
        self.feed(5.0, -20.0)
        self.now[0] += 20.0
        self.feed(0.5, -40.0)
        self.assertEqual(self.h.stats(1, 30.0)["peak_dbfs"], -40.0)

    def test_source_change_clears_history(self):
        self.feed(3.0, -20.0, source=X32)
        self.feed(1.0, -50.0, source=USB)
        self.assertEqual(self.h.stats(1, 10.0)["peak_dbfs"], -50.0)

    def test_invalid_source_resets_coverage(self):
        self.feed(3.0, -20.0)
        self.h.add([], {"id": "x32-meters", "valid": False})
        self.assertEqual(self.h.coverage_s(), 0.0)
        self.assertFalse(self.h.trusted_for(False))

    def test_trust_rules(self):
        self.feed(0.2, -20.0, source=X32)
        self.assertTrue(self.h.trusted_for(False))
        self.feed(0.2, -20.0, source=USB)
        self.assertFalse(self.h.trusted_for(False), "unmapped USB must never be trusted")
        self.feed(0.2, -20.0, source={**MOCK, "id": "mock"})
        self.assertFalse(self.h.trusted_for(False), "simulated data only with the internal mock")
        self.assertTrue(self.h.trusted_for(True))

    def test_none_and_nan_are_not_measurements(self):
        self.h.add([{"channel": 2, "meter_dbfs": None}, {"channel": 3, "meter_dbfs": float("nan")}], X32)
        self.assertEqual(self.h.stats(2, 5.0)["count"], 0)
        self.assertEqual(self.h.stats(3, 5.0)["count"], 0)


if __name__ == "__main__":
    unittest.main()
