"""
Segment suggestion (Tự nhận diện tiết mục) test suite — synthetic MeterHistory data,
injected clock, no mixer at all:
- channel activity is relative (pre-mute bleed on a muted mic is not "active")
- scoring picks the segment whose ON/OFF set matches
- stability window, margin over the current segment, untrusted / short data
- the detector never writes anything (it has no client to write with)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.autopilot.meter_history import MeterHistory
from packages.autopilot.segment_detector import SegmentDetector, classify_channels, score_segment, STABLE_S
from packages.storage.church_profile import DEFAULT_CHURCH_CHANNELS
from packages.storage.service_segments import build_default_segments

SOURCE = {"id": "x32-meters", "label": "X32", "valid": True, "simulated": False, "mapping_verified": True}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def sermon_levels(t):
    """Pastor speaking; band/choir mics only show quiet room bleed (pre-mute meters)."""
    levels = {ch: -60.0 for ch in range(1, 17)}
    levels[1] = -18.0 if int(t * 10) % 5 else -50.0   # speech with short pauses
    levels[3] = -40.0   # lead vocal mic picks up the PA: bleed, ~22 dB below the pastor
    levels[5] = -36.0   # choir overhead picks up the whole room
    levels[11] = -30.0  # talkback chatter is never considered
    return levels


def worship_levels(t):
    levels = {ch: -14.0 for ch in range(3, 11)}
    levels.update({ch: -10.0 for ch in range(12, 17)})
    levels[1] = -30.0   # muted pastor mic: bleed from the band
    levels[2] = -32.0
    levels[11] = -30.0
    return levels


class TestSegmentDetector(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.wall = lambda: 5_000_000.0 + self.clock.t
        self.history = MeterHistory(clock=self.clock)
        self.segments = build_default_segments(DEFAULT_CHURCH_CHANNELS)
        self.trusted = True
        self.active = "WORSHIP_TEAM"
        self.det = SegmentDetector(
            self.history, lambda: self.segments, lambda: [dict(c) for c in DEFAULT_CHURCH_CHANNELS],
            trusted_provider=lambda: self.trusted, active_provider=lambda: self.active,
            clock=self.clock, wall_clock=self.wall, run_inline=True)

    def feed(self, seconds, levels_fn, source=SOURCE):
        """10 Hz meters; ticks the detector like the telemetry loop."""
        for _ in range(int(seconds * 10)):
            lv = levels_fn(self.clock.t)
            self.history.add([{"channel": ch, "meter_dbfs": v} for ch, v in lv.items()], source)
            self.det.tick()
            self.clock.t += 0.1

    def test_bleed_on_muted_mic_is_not_active(self):
        self.feed(9, sermon_levels)
        roles = {c["channel"]: c["role"] for c in DEFAULT_CHURCH_CHANNELS}
        obs = classify_channels(self.history, list(range(1, 17)), roles)
        self.assertTrue(obs[1]["active"])
        self.assertFalse(obs[3]["active"], "vocal mic bleed is far below the pastor")
        self.assertFalse(obs[5]["active"], "choir overhead room pickup is far below the pastor")
        sermon = next(s for s in self.segments if s["id"] == "PASTOR_SERMON")
        worship = next(s for s in self.segments if s["id"] == "WORSHIP_TEAM")
        self.assertGreater(score_segment(sermon, obs), 0.9)
        self.assertLess(score_segment(worship, obs), 0.3)

    def test_suggests_sermon_after_stability_window(self):
        self.feed(8.5, sermon_levels)
        self.assertIsNone(self.det.suggestion, "not stable long enough yet")
        self.feed(STABLE_S + 1.5, sermon_levels)
        s = self.det.suggestion
        self.assertIsNotNone(s)
        self.assertEqual(s["segment_id"], "PASTOR_SERMON")
        self.assertEqual(s["name"], "Mục sư giảng")
        self.assertGreaterEqual(s["confidence"], 0.75)
        self.assertIn("Pastor Mic", s["reason_vi"])
        self.assertLessEqual(s["since"], self.wall() - STABLE_S)

    def test_no_suggestion_when_already_on_best_segment(self):
        self.active = "PASTOR_SERMON"
        self.feed(16, sermon_levels)
        self.assertIsNone(self.det.suggestion)
        self.assertIn("đúng tiết mục", self.det.status()["reason"])

    def test_worship_detected_from_sermon(self):
        self.active = "PASTOR_SERMON"
        self.feed(16, worship_levels)
        self.assertEqual(self.det.suggestion["segment_id"], "WORSHIP_TEAM")

    def test_change_of_scene_restarts_stability(self):
        self.active = "PRAYER"
        self.feed(16, sermon_levels)
        self.assertEqual(self.det.suggestion["segment_id"], "PASTOR_SERMON")
        self.feed(2, worship_levels)
        self.assertNotEqual((self.det.suggestion or {}).get("segment_id"), "WORSHIP_TEAM",
                            "a new winner must hold for the stability window first")
        self.feed(14, worship_levels)
        self.assertEqual(self.det.suggestion["segment_id"], "WORSHIP_TEAM")

    def test_untrusted_data_gives_nothing(self):
        self.trusted = False
        self.feed(16, sermon_levels)
        self.assertIsNone(self.det.suggestion)
        self.assertIn("chưa đáng tin", self.det.status()["reason"])

    def test_short_history_gives_nothing(self):
        self.feed(6, sermon_levels)
        self.assertIsNone(self.det.suggestion)
        self.assertIn("Chưa đủ dữ liệu", self.det.status()["reason"])

    def test_invalid_source_clears_history(self):
        self.feed(16, sermon_levels)
        self.assertIsNotNone(self.det.suggestion)
        self.feed(1.5, sermon_levels, source={"id": "x", "valid": False})
        self.assertIsNone(self.det.suggestion)

    def test_silence_gives_nothing(self):
        self.feed(16, lambda t: {ch: -70.0 for ch in range(1, 17)})
        self.assertIsNone(self.det.suggestion)

    def test_unknown_mixer_state_gives_nothing(self):
        def boom():
            raise OSError("mixer timeout")
        self.det._active_provider = boom
        self.feed(16, sermon_levels)
        self.assertIsNone(self.det.suggestion)

    def test_invalidate_clears_suggestion(self):
        self.feed(16, sermon_levels)
        self.assertIsNotNone(self.det.suggestion)
        self.active = "PASTOR_SERMON"
        self.det.invalidate_active()
        self.assertIsNone(self.det.suggestion)
        self.feed(2, sermon_levels)
        self.assertIsNone(self.det.suggestion)

    def test_talkback_is_ignored(self):
        segs = [{"id": "TB", "name": "x", "channels": {"11": 1}}]
        self.segments = segs
        self.feed(16, sermon_levels)
        self.assertIsNone(self.det.suggestion)


if __name__ == "__main__":
    unittest.main()
