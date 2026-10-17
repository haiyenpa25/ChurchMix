"""X32 /meters streaming: blob parsing, mock streaming over UDP, source priority.

All network traffic goes to packages/mock_x32/server.py on loopback (AGENTS.md rule 1).
"""
import struct
import time
import unittest
from types import SimpleNamespace

import numpy as np

from packages.mock_x32.server import MockX32Server
from packages.monitoring.analyzer import SignalMonitor
from packages.monitoring.source import collect_signal
from packages.x32_osc_adapter.meters import (
    X32MeterReader, build_meter_request, linear_to_dbfs, parse_meter_blob, parse_meter_packet,
)
from packages.x32_osc_adapter.osc_codec import decode_osc

STREAM_PORT = 10045
RENEW_PORT = 10046


def blob(values, count=None):
    count = len(values) if count is None else count
    return struct.pack(f"<i{len(values)}f", count, *values)


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeReader:
    def __init__(self, levels, age=0.0, simulated=False):
        self.simulated = simulated
        self._snapshot = None if levels is None else {
            "received_at": time.monotonic() - age, "count": 96,
            "channels": [{"channel": ch, "level_dbfs": levels.get(ch, -90.0)} for ch in range(1, 33)]}

    def latest(self):
        return self._snapshot

    def is_fresh(self, max_age_s=0.5):
        return self._snapshot is not None and time.monotonic() - self._snapshot["received_at"] <= max_age_s


class BlobParsingTests(unittest.TestCase):
    def test_valid_blob(self):
        self.assertEqual(parse_meter_blob(blob([1.0, 0.5, 0.0])), [1.0, 0.5, 0.0])

    def test_truncated_blob_rejected(self):
        self.assertIsNone(parse_meter_blob(blob([1.0, 0.5, 0.0])[:-2]))
        self.assertIsNone(parse_meter_blob(b"\x01\x00"))

    def test_wrong_count_rejected(self):
        self.assertIsNone(parse_meter_blob(blob([1.0, 0.5], count=3)))
        self.assertIsNone(parse_meter_blob(blob([1.0], count=0)))
        self.assertIsNone(parse_meter_blob(blob([1.0], count=-1)))

    def test_packet_roundtrip_and_wrong_address(self):
        packet = MockX32Server.encode_meter_packet("/meters/1", [0.25] * 96)
        values = parse_meter_packet(packet)
        self.assertEqual(len(values), 96)
        self.assertAlmostEqual(values[0], 0.25)
        self.assertIsNone(parse_meter_packet(MockX32Server.encode_meter_packet("/meters/2", [0.25] * 4)))
        self.assertIsNone(parse_meter_packet(b"garbage"))

    def test_request_is_read_only_meters_subscription(self):
        msg = decode_osc(build_meter_request("/meters/1", 1))
        self.assertEqual(msg.address, "/meters")
        self.assertEqual(msg.args, ["/meters/1", 1])

    def test_dbfs_conversion(self):
        self.assertEqual(linear_to_dbfs(1.0), 0.0)
        self.assertAlmostEqual(linear_to_dbfs(0.5), -6.0, delta=0.05)
        self.assertEqual(linear_to_dbfs(0.0), -90.0)
        self.assertEqual(linear_to_dbfs(1e-9), -90.0)
        self.assertIsNone(linear_to_dbfs(float("nan")))
        self.assertIsNone(linear_to_dbfs(-0.1))

    def test_reader_ignores_malformed_packets(self):
        reader = X32MeterReader("127.0.0.1", 1)
        self.assertFalse(reader._ingest(b"/meters/1\x00\x00\x00,b\x00\x00\x00\x00\x00\x08", time.monotonic()))
        self.assertIsNone(reader.latest())
        self.assertTrue(reader._ingest(MockX32Server.encode_meter_packet("/meters/1", [1.0] * 8), time.monotonic()))
        snap = reader.latest()
        self.assertEqual(snap["count"], 8)
        self.assertEqual(snap["channels"][0]["level_dbfs"], 0.0)
        self.assertIsNone(snap["channels"][8]["level_dbfs"])  # not received != silence


class MockMeterStreamingTests(unittest.TestCase):
    def setUp(self):
        self.server = MockX32Server(port=STREAM_PORT)
        self.server.start()
        self.reader = X32MeterReader("127.0.0.1", STREAM_PORT, simulated=True)

    def tearDown(self):
        self.reader.stop()
        self.server.stop()

    def test_end_to_end_stream(self):
        self.reader.start()
        self.assertTrue(wait_for(lambda: self.reader.is_fresh()))
        snap = self.reader.latest()
        levels = {c["channel"]: c["level_dbfs"] for c in snap["channels"]}
        self.assertEqual(snap["count"], 96)
        self.assertEqual(len(levels), 32)
        self.assertGreater(levels[3], -40)            # band channel
        self.assertLess(levels[11], -50)              # talkback whisper
        self.assertEqual(levels[20], -90.0)           # spare input: silence, measured
        self.assertTrue(self.reader.status()["fresh"])

    def test_input_meters_are_pre_mute(self):
        before = self.server.meter_values(t=5.0)[2]
        self.server.state["/ch/03/mix/on"] = 0
        self.assertEqual(self.server.meter_values(t=5.0)[2], before)

    def test_meter_request_does_not_change_state(self):
        state = dict(self.server.state)
        self.reader.start()
        self.assertTrue(wait_for(lambda: self.reader.is_fresh()))
        self.assertEqual(self.server.state, state)

    def test_stale_after_server_stops(self):
        self.reader.start()
        self.assertTrue(wait_for(lambda: self.reader.is_fresh()))
        self.server.stop()
        self.assertTrue(wait_for(lambda: not self.reader.is_fresh(0.3), timeout=2.0))
        self.assertIsNotNone(self.reader.latest())


class MockSubscriptionRenewalTests(unittest.TestCase):
    def setUp(self):
        self.server = MockX32Server(port=RENEW_PORT)
        self.server.METER_STREAM_SECONDS = 0.4  # shorten the 10 s expiry for the test
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_subscription_expires_without_renewal_and_renewal_extends(self):
        import packages.x32_osc_adapter.meters as meters_mod
        reader = X32MeterReader("127.0.0.1", RENEW_PORT)
        original = (meters_mod.RENEW_INTERVAL_S, meters_mod.RETRY_INTERVAL_S)
        try:
            meters_mod.RENEW_INTERVAL_S = meters_mod.RETRY_INTERVAL_S = 60.0  # no renewals
            reader.start()
            self.assertTrue(wait_for(reader.is_fresh))
            self.assertTrue(wait_for(lambda: not reader.is_fresh(0.2), timeout=2.0))
        finally:
            reader.stop()
        try:
            meters_mod.RENEW_INTERVAL_S = meters_mod.RETRY_INTERVAL_S = 0.25  # renew before expiry
            reader = X32MeterReader("127.0.0.1", RENEW_PORT).start()
            self.assertTrue(wait_for(reader.is_fresh))
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                self.assertTrue(reader.is_fresh(0.3))
                time.sleep(0.05)
        finally:
            meters_mod.RENEW_INTERVAL_S, meters_mod.RETRY_INTERVAL_S = original
            reader.stop()


class SourcePriorityTests(unittest.TestCase):
    def setUp(self):
        self.soundcheck = SimpleNamespace(is_active=False)

    def test_fresh_meters_beat_demo(self):
        meters, samples, source = collect_signal(self.soundcheck, None, 0, {1: {"name": "Pastor"}},
                                                 meter_reader=FakeReader({1: -18.0}))
        self.assertEqual(source["id"], "x32-meters")
        self.assertEqual(source["tap_point"], "X32_INPUT_METER")
        self.assertTrue(source["mapping_verified"])
        self.assertFalse(source["simulated"])
        self.assertFalse(source["dsp_valid"])
        self.assertEqual(meters[0], {"channel": 1, "name": "Pastor", "meter_dbfs": -18.0, "rms_dbfs": None})
        self.assertEqual(len(meters), 32)
        self.assertEqual(samples.shape, (1024,))

    def test_mock_meters_are_simulated_and_keep_demo_rta(self):
        _, _, source = collect_signal(self.soundcheck, None, 0, {}, meter_reader=FakeReader({}, simulated=True))
        self.assertTrue(source["simulated"])
        self.assertEqual(source["label"], "Mixer giả lập • meter X32")
        self.assertTrue(source["dsp_valid"])

    def test_soundcheck_beats_meters(self):
        from packages.virtual_soundcheck.player import VirtualSoundcheckEngine
        soundcheck = VirtualSoundcheckEngine()
        soundcheck.start_session("SERMON_PREACHING")
        _, _, source = collect_signal(soundcheck, None, 0, {}, meter_reader=FakeReader({1: -10.0}))
        self.assertTrue(source["id"].startswith("soundcheck:"))

    def test_stale_meters_fall_back_with_reason(self):
        _, _, source = collect_signal(self.soundcheck, None, 0, {}, meter_reader=FakeReader({1: -10.0}, age=0.8))
        self.assertEqual(source["id"], "demo")
        self.assertIn("cũ", source["reasons"][0])
        _, _, source = collect_signal(self.soundcheck, None, 0, {}, meter_reader=FakeReader(None))
        self.assertEqual(source["id"], "demo")
        self.assertIn("Chưa nhận", source["reasons"][0])

    def test_simulated_usb_audio_not_mixed_with_real_meters(self):
        frame = dict(samples=np.ones((1024, 2), dtype=np.float32) * 0.1, captured_at=time.monotonic(),
                     is_simulated=True, clock_verified=True, clock_fault=None, overflow_count=0)
        worker = SimpleNamespace(is_running=True, sample_rate=44100, device_id=3, tap_point="PRE_EQ",
                                 get_latest_frame=lambda: frame)
        _, _, source = collect_signal(self.soundcheck, worker, 0, {}, meter_reader=FakeReader({}))
        self.assertIsNone(source["audio"])
        frame["is_simulated"] = False
        _, _, source = collect_signal(self.soundcheck, worker, 0, {}, meter_reader=FakeReader({}))
        self.assertEqual(source["audio"]["tap_point"], "PRE_EQ")
        self.assertTrue(source["dsp_valid"])
        self.assertEqual(source["sample_rate"], 44100)

    def test_signal_monitor_accepts_peak_only_meters(self):
        meters, _, source = collect_signal(self.soundcheck, None, 0, {}, meter_reader=FakeReader({1: -3.0}))
        row = SignalMonitor().ingest(meters, source)["channels"][0]
        self.assertTrue(row["measured"])
        self.assertEqual(row["status"], "CRITICAL")
        self.assertIsNone(row["rms_dbfs"])
        self.assertIsNone(row["crest_db"])


if __name__ == "__main__":
    unittest.main()
