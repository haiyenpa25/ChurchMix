"""
Feedback notch proposals must not silently overwrite an EQ band that is in use,
and must record the band's real current values as "from" (audit + rollback trail).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.eq_optimizer.recommender import PEQRecommender, gain_to_x32
from packages.feedback_detector.detector import FeedbackCandidate


def _candidate():
    return FeedbackCandidate(channel_id=3, freq_hz=3150.0, confidence=0.9, severity="HIGH", level_dbfs=-12.0,
                             persistence_frames=4, is_musical_note=False, evidence=[], recommended_action="notch")


def _params(band2_g=0.5, band3_g=0.5):
    p = {}
    for b in range(1, 5):
        p[f"/ch/03/eq/{b}/f"] = 0.25 * b
        p[f"/ch/03/eq/{b}/g"] = 0.5
        p[f"/ch/03/eq/{b}/q"] = 0.4
    p["/ch/03/eq/2/g"] = band2_g
    p["/ch/03/eq/3/g"] = band3_g
    return p


class TestNotchBandSelection(unittest.TestCase):
    def setUp(self):
        self.rec = PEQRecommender()

    def test_uses_flat_band_3_with_real_from_values(self):
        p = self.rec.recommend_feedback_notch(_candidate(), "sha", current_parameters=_params())
        self.assertEqual(p.changes[0]["parameter"], "/ch/03/eq/3/f")
        self.assertAlmostEqual(p.changes[0]["from"], 0.75)
        self.assertAlmostEqual(p.changes[2]["from"], 0.4)
        self.assertIn("đang trống", p.hypothesis)

    def test_falls_back_to_band_2_when_band_3_is_in_use(self):
        p = self.rec.recommend_feedback_notch(_candidate(), "sha", current_parameters=_params(band3_g=0.38))
        self.assertTrue(all(c["parameter"].startswith("/ch/03/eq/2/") for c in p.changes))
        self.assertAlmostEqual(p.changes[1]["from"], 0.5)

    def test_warns_when_both_mid_bands_are_in_use(self):
        p = self.rec.recommend_feedback_notch(_candidate(), "sha", current_parameters=_params(band2_g=0.6, band3_g=0.38))
        self.assertEqual(p.changes[1]["parameter"], "/ch/03/eq/3/g")
        self.assertAlmostEqual(p.changes[1]["from"], 0.38)
        self.assertIn("GHI ĐÈ", p.hypothesis)

    def test_notch_cut_is_the_conservative_default(self):
        p = self.rec.recommend_feedback_notch(_candidate(), "sha", current_parameters=_params())
        self.assertAlmostEqual(p.changes[1]["to"], gain_to_x32(-3.5))
        self.assertLess(p.changes[1]["to"], 0.5, "a notch must cut, never boost")


if __name__ == "__main__":
    unittest.main()
