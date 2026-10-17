"""
Sprint 1 Test Suite:
- OSC Binary Codec Unit Tests
- Mock X32 Compact Server Tests
- Read-Only Mode & Safety Gate Enforcement
- Critical DL16 #11 Talkback Invariant Verification
- Full Snapshot Generation & SHA-256 Integrity Verification
- Snapshot Diff Engine
"""

import unittest
import time
import os
import sys

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.x32_osc_adapter.osc_codec import OSCMessage, encode_osc, decode_osc
from packages.x32_osc_adapter.client import X32Client, Snapshot, ReadOnlyViolationError
from packages.mock_x32.server import MockX32Server


class TestOSCCodec(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        msg = OSCMessage("/ch/01/mix/fader", [0.75])
        encoded = encode_osc(msg)
        self.assertEqual(len(encoded) % 4, 0, "Packet length must be multiple of 4")
        decoded = decode_osc(encoded)
        self.assertEqual(decoded.address, "/ch/01/mix/fader")
        self.assertAlmostEqual(decoded.args[0], 0.75, places=5)

    def test_multi_arg_types(self):
        msg = OSCMessage("/test/multi", [42, 3.14159, "ChurchMix", True, b"\x01\x02\x03"])
        encoded = encode_osc(msg)
        self.assertEqual(len(encoded) % 4, 0)
        decoded = decode_osc(encoded)
        self.assertEqual(decoded.address, "/test/multi")
        self.assertEqual(decoded.args[0], 42)
        self.assertAlmostEqual(decoded.args[1], 3.14159, places=4)
        self.assertEqual(decoded.args[2], "ChurchMix")
        self.assertEqual(decoded.args[3], 1) # bool encoded as int 1
        self.assertEqual(decoded.args[4], b"\x01\x02\x03")


class TestSprint1X32Adapter(unittest.TestCase):
    SERVER_PORT = 10025

    @classmethod
    def setUpClass(cls):
        # Start Mock X32 on isolated test port
        cls.server = MockX32Server(host="127.0.0.1", port=cls.SERVER_PORT)
        cls.server.start()
        time.sleep(0.1) # Wait for socket to bind

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.client = X32Client(host="127.0.0.1", port=self.SERVER_PORT, read_only_mode=True, timeout=1.0)
        self.client.connect()

    def tearDown(self):
        self.client.close()

    def test_info_and_status(self):
        info = self.client.query("/info")
        self.assertIn("X32 Compact", info)
        self.assertIn("V4.09", info)

        status = self.client.query("/status")
        self.assertEqual(status[0], "active")
        self.assertEqual(status[2], "ChurchMix-X32")

    def test_channel_summary_pastor(self):
        summary = self.client.get_channel_summary(1)
        self.assertEqual(summary["name"], "Pastor Mic")
        self.assertEqual(summary["on"], 1)
        self.assertEqual(summary["mix_st"], 1, "Pastor mic must be routed to Main FOH")
        self.assertEqual(len(summary["eq_bands"]), 4)

    def test_dl16_11_talkback_invariant(self):
        """CRITICAL CHURCH INVARIANT: DL16 In 11 (Talkback) MUST NOT route to Main FOH."""
        tb_summary = self.client.get_channel_summary(11)
        self.assertEqual(tb_summary["name"], "Talkback Band")
        self.assertEqual(tb_summary["mix_st"], 0, "HARD INVARIANT VIOLATION: Talkback must NOT send to Main FOH (mix_st must be 0)!")

        # Verify Ultranet P16 Slot 11 receives Talkback signal
        p16_src = self.client.query("/outputs/p16/11/src")[0]
        self.assertEqual(p16_src, 11, "P16 slot 11 must receive Channel 11 (Talkback)")

    def test_safety_gate_blocks_write_in_read_only_mode(self):
        """Verify that attempting to write in READ_ONLY_MODE is strictly rejected."""
        self.assertTrue(self.client.read_only_mode)

        with self.assertRaises(ReadOnlyViolationError) as ctx:
            self.client.send_write("/ch/01/mix/fader", [0.0])

        self.assertIn("SAFETY GATE BLOCKED WRITE", str(ctx.exception))

        # Verify server state was NOT changed
        current_fader = self.client.query("/ch/01/mix/fader")[0]
        self.assertEqual(current_fader, 0.75, "Server fader must remain unchanged at 0.75")

    def test_take_snapshot_and_sha256(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)
        self.assertEqual(snapshot.channel_count, 32)
        self.assertEqual(len(snapshot.sha256), 64, "SHA-256 digest must be 64 characters")
        self.assertIn("/main/st/mix/fader", snapshot.parameters)
        self.assertIn("/ch/11/mix/st", snapshot.parameters)
        self.assertEqual(snapshot.parameters["/ch/11/mix/st"], 0)

        # Self-diff must report no changes
        diff = X32Client.diff_snapshots(snapshot, snapshot)
        self.assertFalse(diff["has_changes"])

    def test_snapshot_diff_detection(self):
        # Create write-enabled client temporarily for test simulation
        writer_client = X32Client(host="127.0.0.1", port=self.SERVER_PORT, read_only_mode=False, timeout=1.0)
        writer_client.connect()
        try:
            snap1 = self.client.take_full_snapshot(max_channels=8)

            # Change an allowed test parameter
            writer_client.send_write("/ch/01/config/name", ["Pastor Headset"])

            snap2 = self.client.take_full_snapshot(max_channels=8)
            diff = X32Client.diff_snapshots(snap1, snap2)

            self.assertTrue(diff["has_changes"])
            self.assertIn("/ch/01/config/name", diff["changed"])
            self.assertEqual(diff["changed"]["/ch/01/config/name"]["before"], "Pastor Mic")
            self.assertEqual(diff["changed"]["/ch/01/config/name"]["after"], "Pastor Headset")

            # Restore original state
            writer_client.send_write("/ch/01/config/name", ["Pastor Mic"])
        finally:
            writer_client.close()


if __name__ == "__main__":
    unittest.main()
