"""
Service Segments (Tiết mục) test suite:
- Defaults are built from channel roles; talkback is never part of a segment
- Validation, capture, diff and active-segment matching
- TransactionExecutor.execute_batch: one transaction, ordered writes, full rollback
- REST flow: preview -> apply (mutes then unmutes), OBSERVE refusal, stale preview (409)
- Feedback drill preset produces detector alerts on channel 3
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from packages.storage.church_profile import DEFAULT_CHURCH_CHANNELS
from packages.storage.service_segments import ServiceSegmentStore, SegmentError, build_default_segments
from packages.x32_osc_adapter.client import X32Client
from packages.mock_x32.server import MockX32Server
from packages.safety_controller.transaction import (
    Proposal, TransactionExecutor, ProposalRejectedError, TransactionFailedError,
)


def _store(tmpdir):
    return ServiceSegmentStore(lambda: [dict(c) for c in DEFAULT_CHURCH_CHANNELS], path=os.path.join(tmpdir, "segments.json"))


class TestSegmentStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = _store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_from_roles_exclude_talkback_and_spares(self):
        segs = {s["id"]: s for s in build_default_segments(DEFAULT_CHURCH_CHANNELS)}
        self.assertIn("PASTOR_SERMON", segs)
        sermon = segs["PASTOR_SERMON"]["channels"]
        self.assertEqual(sermon["1"], 1)
        self.assertEqual(sermon["2"], 0)
        self.assertEqual(sermon["3"], 0)
        for seg in segs.values():
            self.assertNotIn("11", seg["channels"], f"{seg['id']} must not touch talkback")
            self.assertNotIn("20", seg["channels"], "spare GENERAL_INPUT channels are left untouched")
        worship = segs["WORSHIP_TEAM"]["channels"]
        self.assertEqual(worship["1"], 0)
        self.assertEqual(worship["3"], 1)
        self.assertEqual(worship["12"], 1)

    def test_create_rejects_talkback_and_bad_values(self):
        with self.assertRaises(SegmentError):
            self.store.create("Sai", {"11": 1})
        with self.assertRaises(SegmentError):
            self.store.create("Sai", {"3": 2})
        with self.assertRaises(SegmentError):
            self.store.create("Sai", {"40": 1})
        with self.assertRaises(SegmentError):
            self.store.create("   ", {"3": 1})

    def test_create_update_delete_persist(self):
        seg = self.store.create("Lễ Thiếu Nhi", {"3": 1, "5": 1, "1": 0}, icon="users", author="Hai")
        self.assertEqual(seg["id"], "LE_THIEU_NHI")
        again = self.store.create("Lễ Thiếu Nhi", {"3": 1})
        self.assertEqual(again["id"], "LE_THIEU_NHI_2")
        updated = self.store.update(seg["id"], {"channels": {"3": 0}})
        self.assertEqual(updated["channels"], {"3": 0})
        reloaded = _store(self.tmp.name)
        self.assertEqual(reloaded.get(seg["id"])["channels"], {"3": 0})
        reloaded.delete(seg["id"])
        with self.assertRaises(SegmentError):
            reloaded.get(seg["id"])

    def test_diff_and_active(self):
        params = {f"/ch/{c:02d}/mix/on": 1 for c in range(1, 33)}
        diff = self.store.diff("PASTOR_SERMON", params)
        muted = {i["channel"] for i in diff["to_mute"]}
        self.assertIn(3, muted)
        self.assertNotIn(1, muted)
        self.assertNotIn(11, muted)
        self.assertEqual(diff["to_unmute"], [])
        for item in diff["to_mute"]:
            params[f"/ch/{item['channel']:02d}/mix/on"] = 0
        self.assertEqual(self.store.active_id(params), "PASTOR_SERMON")

    def test_capture_records_current_state_without_talkback(self):
        params = {f"/ch/{c:02d}/mix/on": (1 if c in (1, 7) else 0) for c in range(1, 33)}
        seg = self.store.capture("PRAYER", params, author="Hai")
        self.assertEqual(seg["channels"]["1"], 1)
        self.assertEqual(seg["channels"]["7"], 1)
        self.assertEqual(seg["channels"]["2"], 0)
        self.assertNotIn("11", seg["channels"])

    def test_hand_edited_file_with_talkback_is_ignored_in_diff(self):
        segs = self.store.list()
        segs[0]["channels"]["11"] = 0
        self.store._write(segs)
        params = {f"/ch/{c:02d}/mix/on": 1 for c in range(1, 33)}
        diff = self.store.diff(segs[0]["id"], params)
        self.assertNotIn(11, {i["channel"] for i in diff["to_mute"] + diff["to_unmute"]})


class TestExecuteBatch(unittest.TestCase):
    SERVER_PORT = 10043

    @classmethod
    def setUpClass(cls):
        cls.server = MockX32Server(host="127.0.0.1", port=cls.SERVER_PORT)
        cls.server.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        with self.server.lock:
            self.server.state.clear()
            self.server._init_default_church_state()
        self.client = X32Client(host="127.0.0.1", port=self.SERVER_PORT, read_only_mode=True, timeout=1.0)
        self.client.connect()
        self.executor = TransactionExecutor(client=self.client)

    def tearDown(self):
        self.client.close()

    def _mute(self, ch, sha, to=0):
        p = Proposal(f"P{ch}", ch, "test", 1.0, [{"parameter": f"/ch/{ch:02d}/mix/on", "from": 1, "to": to}], sha)
        p.approve("op")
        return p

    def test_batch_applies_all_in_one_transaction(self):
        sha = self.client.take_full_snapshot(32).sha256
        result = self.executor.execute_batch([self._mute(3, sha), self._mute(6, sha)], "op", batch_id="B1")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(self.server.state["/ch/03/mix/on"], 0)
        self.assertEqual(self.server.state["/ch/06/mix/on"], 0)
        self.assertEqual(len(self.executor.audit_log), 1)
        self.assertTrue(self.client.read_only_mode)

    def test_batch_rolls_back_every_write_on_failure(self):
        sha = self.client.take_full_snapshot(32).sha256
        original_query = self.client.query
        original_write = self.client.send_write
        state = {"ch6_written": False, "corrupted": False}

        def write(address, args, timeout=None):
            if address == "/ch/06/mix/on":
                state["ch6_written"] = True
            return original_write(address, args, timeout)

        def corrupt(address, timeout=None):
            # Only the readback right after the 2nd write disagrees.
            if address == "/ch/06/mix/on" and state["ch6_written"] and not state["corrupted"]:
                state["corrupted"] = True
                return [1]
            return original_query(address, timeout)

        self.client.query = corrupt
        self.client.send_write = write
        with self.assertRaises(TransactionFailedError):
            self.executor.execute_batch([self._mute(3, sha), self._mute(6, sha)], "op", batch_id="B2")
        self.client.query = original_query
        self.client.send_write = original_write
        self.assertEqual(self.server.state["/ch/03/mix/on"], 1, "first write must be rolled back too")
        self.assertEqual(self.server.state["/ch/06/mix/on"], 1)
        self.assertEqual(self.executor.audit_log[-1]["status"], "ROLLED_BACK")

    def test_batch_rejects_mixed_snapshots_and_duplicates(self):
        sha = self.client.take_full_snapshot(32).sha256
        with self.assertRaises(ProposalRejectedError):
            self.executor.execute_batch([self._mute(3, sha), self._mute(6, "other")], "op", batch_id="B3")
        with self.assertRaises(ProposalRejectedError):
            self.executor.execute_batch([self._mute(3, sha), self._mute(3, sha)], "op", batch_id="B4")
        with self.assertRaises(ProposalRejectedError):
            self.executor.execute_batch([], "op", batch_id="B5")

    def test_batch_validates_each_proposal_against_policy(self):
        sha = self.client.take_full_snapshot(32).sha256
        bad = Proposal("BAD", 3, "test", 1.0, [{"parameter": "/main/st/mix/fader", "from": 0.7, "to": 0.8}], sha)
        bad.approve("op")
        with self.assertRaises(ProposalRejectedError):
            self.executor.execute_batch([self._mute(6, sha), bad], "op", batch_id="B6")
        self.assertEqual(self.server.state["/ch/06/mix/on"], 1, "nothing may be written when validation fails")


class TestSegmentApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import apps.api.main as main_module
        cls.main = main_module
        cls.tmp = tempfile.TemporaryDirectory()
        cls.original_path = main_module.segment_store.path
        main_module.segment_store.path = os.path.join(cls.tmp.name, "segments.json")
        cls._ctx = TestClient(main_module.app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)
        cls.main.segment_store.path = cls.original_path
        cls.tmp.cleanup()

    def setUp(self):
        from packages.safety_controller.modes import OperatorMode
        self.main.stop_auto_triggered = False
        self.main.safety_mode_mgr.set_mode(OperatorMode.ASSIST, operator="test")
        for ch in range(1, 17):
            if ch != 11:
                self.client.post(f"/api/v1/channels/{ch}/mute", json={"on": 1, "operator_id": "test"})

    def _on(self, ch):
        chans = self.client.get("/api/v1/channels").json()["channels"]
        return next(c["on"] for c in chans if c["channel"] == ch)

    def test_list_has_defaults(self):
        data = self.client.get("/api/v1/segments").json()
        ids = [s["id"] for s in data["segments"]]
        self.assertIn("PASTOR_SERMON", ids)
        self.assertIn("WORSHIP_TEAM", ids)
        self.assertEqual(data["talkback_channel"], 11)

    def test_preview_then_apply_switches_mics_and_keeps_talkback(self):
        tb_before = self._on(11)
        preview = self.client.get("/api/v1/segments/PASTOR_SERMON/preview").json()
        self.assertTrue(preview["to_mute"])
        res = self.client.post("/api/v1/segments/PASTOR_SERMON/apply",
                               json={"operator_id": "test", "expected_sha256": preview["expected_sha256"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["status"], "SUCCESS")
        self.assertEqual(self._on(1), 1)
        self.assertEqual(self._on(3), 0)
        self.assertEqual(self._on(12), 0)
        self.assertEqual(self._on(11), tb_before, "talkback must never be touched")
        self.assertEqual(self.client.get("/api/v1/segments").json()["active_id"], "PASTOR_SERMON")
        again = self.client.post("/api/v1/segments/PASTOR_SERMON/apply", json={"operator_id": "test"}).json()
        self.assertEqual(again["status"], "NO_CHANGE")

    def test_apply_refused_in_observe_mode(self):
        from packages.safety_controller.modes import OperatorMode
        self.main.safety_mode_mgr.set_mode(OperatorMode.OBSERVE, operator="test")
        res = self.client.post("/api/v1/segments/PASTOR_SERMON/apply", json={"operator_id": "test"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._on(3), 1, "nothing changes in OBSERVE")

    def test_stale_preview_is_rejected(self):
        res = self.client.post("/api/v1/segments/PASTOR_SERMON/apply",
                               json={"operator_id": "test", "expected_sha256": "0" * 64})
        self.assertEqual(res.status_code, 409)

    def test_capture_and_crud(self):
        created = self.client.post("/api/v1/segments", json={"name": "Lễ Báp-têm", "channels": {"1": 1, "3": 0}}).json()
        self.assertEqual(self.client.post("/api/v1/segments", json={"name": "X", "channels": {"11": 1}}).status_code, 400)
        captured = self.client.post(f"/api/v1/segments/{created['id']}/capture", json={"operator_id": "test"}).json()
        self.assertEqual(captured["channels"], {"1": 1, "3": 1})
        self.assertEqual(self.client.delete(f"/api/v1/segments/{created['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/segments/{created['id']}/preview").status_code, 404)


class TestFeedbackDrill(unittest.TestCase):
    def test_drill_triggers_detector_on_channel_3(self):
        from packages.virtual_soundcheck.player import VirtualSoundcheckEngine
        from packages.feedback_detector.detector import FeedbackDetector
        from packages.signal_analysis.dsp import AudioFrame
        eng = VirtualSoundcheckEngine()
        eng.start_session("FEEDBACK_DRILL")
        det = FeedbackDetector(min_prominence_db=12.0, min_persistence_frames=3, confidence_threshold=0.70)
        found = []
        for i in range(int(12 * 48000 / 1024)):
            block = eng.generate_audio_block(1024)
            found += det.process_frame(AudioFrame(samples=block[:, 2], sample_rate=48000, channel_id=3, timestamp=i * 0.02))
        self.assertTrue(found, "drill must produce a feedback alert")
        self.assertAlmostEqual(found[0].freq_hz, 3150, delta=60)


if __name__ == "__main__":
    unittest.main()
