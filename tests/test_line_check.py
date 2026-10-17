"""Automatic line check: per-channel status from MeterHistory (read-only), trust rules, channel selection, API."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.autopilot.meter_history import MeterHistory
from packages.autopilot import line_check
from packages.storage.church_profile import DEFAULT_CHURCH_CHANNELS

X32 = {"id": "x32-meters", "valid": True, "simulated": False, "mapping_verified": True}
USB = {"id": "capture:1", "valid": True, "simulated": False, "mapping_verified": False}


def channels():
    return [dict(c) for c in DEFAULT_CHURCH_CHANNELS]


class Feeder:
    """MeterHistory on an injected clock, fed at 10 Hz with per-channel level functions."""

    def __init__(self, window_s=30.0):
        self.now = [1000.0]
        self.h = MeterHistory(window_s=window_s, clock=lambda: self.now[0])

    def feed(self, seconds, levels, source=X32, step=0.1):
        n = int(round(seconds / step))
        for i in range(n):
            t = i * step
            self.h.add([{"channel": ch, "meter_dbfs": fn(t) if callable(fn) else fn} for ch, fn in levels.items()], source)
            self.now[0] += step


def speech(t):
    # bursts around -20 with pauses at -80
    return -20.0 + 6.0 * math.sin(t * 7.0) if math.sin(t * 0.8) > -0.3 else -80.0


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.f = Feeder()

    def run_one(self, fn, seconds=30.0, source=X32, trusted=True):
        self.f.feed(seconds, {1: fn}, source=source)
        res = line_check.analyze(self.f.h, [c for c in channels() if c["channel"] == 1], {}, 30.0,
                                 trusted=trusted, talkback_channel=11)
        return res["items"][0]

    def test_ok(self):
        it = self.run_one(speech)
        self.assertEqual(it["status"], "OK")
        self.assertGreater(it["peak_dbfs"], -20.0)
        for key in ("median_dbfs", "spread_db", "count"):
            self.assertIn(key, it)

    def test_no_signal(self):
        it = self.run_one(-90.0)
        self.assertEqual(it["status"], "NO_SIGNAL")
        self.assertIn("pin", it["message_vi"])

    def test_constant_hum(self):
        it = self.run_one(lambda t: -40.0 + 0.3 * math.sin(t * 50))
        self.assertEqual(it["status"], "CONSTANT")
        self.assertLess(it["range_db"], line_check.CONSTANT_RANGE_DB)

    def test_constant_needs_level_above_floor(self):
        # a flat but very quiet floor (-68) is no signal-ish, not "constant hum"
        it = self.run_one(lambda t: -68.0 + 0.2 * math.sin(t))
        self.assertNotEqual(it["status"], "CONSTANT")

    def test_quiet_floor_with_short_speech_is_not_constant(self):
        it = self.run_one(lambda t: -20.0 if 10.0 < t < 12.0 else -62.0)
        self.assertEqual(it["status"], "OK")

    def test_clipping(self):
        it = self.run_one(lambda t: -0.5 if int(t * 10) % 20 == 0 else -15.0)
        self.assertEqual(it["status"], "CLIPPING")

    def test_low(self):
        it = self.run_one(lambda t: -52.0 + 4.0 * math.sin(t * 5))
        self.assertEqual(it["status"], "LOW")

    def test_untrusted_is_unknown(self):
        it = self.run_one(speech, trusted=False)
        self.assertEqual(it["status"], "UNKNOWN")

    def test_unmapped_usb_source_not_trusted(self):
        self.f.feed(30.0, {1: speech}, source=USB)
        self.assertFalse(self.f.h.trusted_for(False))

    def test_insufficient_window_is_unknown(self):
        it = self.run_one(speech, seconds=5.0)
        self.assertEqual(it["status"], "UNKNOWN")

    def test_too_few_samples_is_unknown(self):
        self.assertEqual(line_check.classify([-20.0] * 3)["status"], "UNKNOWN")


class TestChannelSelection(unittest.TestCase):
    def test_skips_spares_and_talkback(self):
        chans = channels()
        chans[19]["name"] = "Kèn Saxophone"  # channel 20 renamed -> checked
        picked = [c["channel"] for c in line_check.checked_channels(chans, 11)]
        self.assertNotIn(11, picked)
        self.assertNotIn(21, picked)
        self.assertIn(20, picked)
        self.assertIn(1, picked)

    def test_configured_talkback_channel_is_skipped(self):
        chans = channels()
        picked = [c["channel"] for c in line_check.checked_channels(chans, 5)]
        self.assertNotIn(5, picked)

    def test_muted_channel_flagged(self):
        f = Feeder()
        f.feed(30.0, {1: speech})
        res = line_check.analyze(f.h, channels()[:1], {"/ch/01/mix/on": 0}, 30.0, trusted=True, talkback_channel=11)
        self.assertTrue(res["items"][0]["muted"])
        self.assertTrue(res["items"][0]["hint_vi"])
        self.assertTrue(res["read_only"])


class FakeSnapshot:
    def __init__(self, params):
        self.parameters = params
        self.sha256 = "f" * 64


class FakeClient:
    """Read-only fake: any attempt to write fails the test."""

    def __init__(self, params):
        self.params = params

    def take_full_snapshot(self, max_channels=32):
        return FakeSnapshot(dict(self.params))

    def send_write(self, *a, **k):  # pragma: no cover - must never be called
        raise AssertionError("line check must never write to the mixer")


class TestLineCheckApi(unittest.TestCase):
    def setUp(self):
        from apps.api.soundcheck_auto_routes import build_router
        self.f = Feeder()
        self.proposals = {}
        app = FastAPI()
        app.include_router(build_router(get_client=lambda: FakeClient({"/ch/02/mix/on": 1}), meter_history=self.f.h,
                                        is_simulator=lambda: False, get_channels=channels, proposals=self.proposals))
        self.client = TestClient(app)

    def test_analyze_flow(self):
        self.f.feed(30.0, {1: speech, 2: -90.0, 3: -0.2, 11: speech})
        res = self.client.post("/api/v1/line-check/analyze", json={"seconds": 30})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        by = {it["channel"]: it for it in data["items"]}
        self.assertEqual(by[1]["status"], "OK")
        self.assertEqual(by[2]["status"], "NO_SIGNAL")
        self.assertEqual(by[3]["status"], "CLIPPING")
        self.assertNotIn(11, by)
        self.assertEqual(data["talkback_channel"], 11)
        self.assertEqual(self.proposals, {}, "line check never creates proposals")

    def test_untrusted_source_all_unknown(self):
        self.f.feed(30.0, {1: speech}, source=USB)
        data = self.client.post("/api/v1/line-check/analyze", json={"seconds": 30}).json()
        self.assertFalse(data["trusted"])
        self.assertTrue(all(it["status"] == "UNKNOWN" for it in data["items"]))

    def test_seconds_validated(self):
        self.assertEqual(self.client.post("/api/v1/line-check/analyze", json={"seconds": 120}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
