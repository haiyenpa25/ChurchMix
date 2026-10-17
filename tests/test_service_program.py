"""
Service program (Chương trình lễ) test suite:
- Default program from existing segments; validation; persistence; current marker
- REST flow with TestClient on temp paths
- /program/current never writes to the mixer (mock only, AGENTS.md rule 1)
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from packages.storage.church_profile import DEFAULT_CHURCH_CHANNELS
from packages.storage.service_segments import ServiceSegmentStore
from packages.storage.service_program import ServiceProgramStore, ProgramError, MAX_ITEMS


def _stores(tmpdir):
    seg = ServiceSegmentStore(lambda: [dict(c) for c in DEFAULT_CHURCH_CHANNELS], path=os.path.join(tmpdir, "segments.json"))
    return seg, ServiceProgramStore(seg.list, path=os.path.join(tmpdir, "program.json"))


class TestProgramStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.segments, self.store = _stores(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_program_uses_existing_segments(self):
        prog = self.store.get()
        self.assertTrue(prog["is_default"])
        self.assertEqual([i["segment_id"] for i in prog["items"]],
                         ["ANNOUNCEMENT", "WORSHIP_TEAM", "PRAYER", "PASTOR_SERMON", "WORSHIP_TEAM", "ANNOUNCEMENT"])
        self.assertIsNone(prog["current_index"])
        self.assertEqual(prog["next_index"], 0)
        self.assertEqual(prog["next"]["segment_name"], "Thông báo / MC")
        self.assertFalse(os.path.exists(self.store.path), "reading must not create the file")

    def test_default_skips_deleted_segments(self):
        self.segments.delete("PRAYER")
        ids = [i["segment_id"] for i in self.store.get()["items"]]
        self.assertNotIn("PRAYER", ids)
        self.assertEqual(len(ids), 5)

    def test_validation(self):
        with self.assertRaises(ProgramError):
            self.store.replace([{"segment_id": "NOPE"}])
        with self.assertRaises(ProgramError):
            self.store.replace([{"segment_id": "PRAYER", "title": "x" * 81}])
        with self.assertRaises(ProgramError):
            self.store.replace([{"segment_id": "PRAYER"}] * (MAX_ITEMS + 1))
        with self.assertRaises(ProgramError):
            self.store.replace("not a list")
        self.assertFalse(os.path.exists(self.store.path))

    def test_replace_persists_and_fills_title(self):
        prog = self.store.replace([{"segment_id": "PASTOR_SERMON", "title": "  Giảng  ", "note": "Mục sư Hải"},
                                   {"segment_id": "PRAYER"}], author="Hai")
        self.assertFalse(prog["is_default"])
        self.assertEqual(prog["items"][0]["title"], "Giảng")
        self.assertEqual(prog["items"][1]["title"], "Cầu nguyện", "empty title falls back to the segment name")
        self.assertEqual(len({i["id"] for i in prog["items"]}), 2)
        reloaded = ServiceProgramStore(self.segments.list, path=self.store.path).get()
        self.assertEqual([i["segment_id"] for i in reloaded["items"]], ["PASTOR_SERMON", "PRAYER"])
        self.assertEqual(reloaded["updated_by"], "Hai")

    def test_current_next_and_marker_follows_item(self):
        prog = self.store.replace([{"segment_id": "ANNOUNCEMENT"}, {"segment_id": "PASTOR_SERMON"}, {"segment_id": "PRAYER"}])
        prog = self.store.set_current(1)
        self.assertEqual(prog["current"]["segment_id"], "PASTOR_SERMON")
        self.assertEqual(prog["next"]["segment_id"], "PRAYER")
        items = prog["items"]
        # Move the current item to the end: the marker follows it.
        prog = self.store.replace([items[0], items[2], items[1]])
        self.assertEqual(prog["current_index"], 2)
        self.assertIsNone(prog["next"])
        # Delete the current item: the marker is cleared.
        prog = self.store.replace([items[0], items[2]])
        self.assertIsNone(prog["current_index"])
        with self.assertRaises(ProgramError):
            self.store.set_current(5)
        with self.assertRaises(ProgramError):
            self.store.set_current(0, segment_id="PRAYER")
        self.assertIsNone(self.store.reset()["current_index"])

    def test_deleted_segment_is_flagged_not_fatal(self):
        self.store.replace([{"segment_id": "SOLO"}])
        self.segments.delete("SOLO")
        prog = self.store.get()
        self.assertTrue(prog["items"][0]["segment_missing"])

    def test_corrupt_file_falls_back_to_default(self):
        with open(self.store.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertTrue(self.store.get()["is_default"])


class TestProgramApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import apps.api.main as main_module
        cls.main = main_module
        cls.tmp = tempfile.TemporaryDirectory()
        cls.orig = (main_module.segment_store.path, main_module.program_store.path)
        main_module.segment_store.path = os.path.join(cls.tmp.name, "segments.json")
        main_module.program_store.path = os.path.join(cls.tmp.name, "program.json")
        cls._ctx = TestClient(main_module.app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)
        cls.main.segment_store.path, cls.main.program_store.path = cls.orig
        cls.tmp.cleanup()

    def setUp(self):
        if os.path.exists(self.main.program_store.path):
            os.remove(self.main.program_store.path)

    def test_get_put_current_reset(self):
        prog = self.client.get("/api/v1/program").json()
        self.assertTrue(prog["is_default"])
        res = self.client.put("/api/v1/program", json={"operator_id": "test", "items": [
            {"segment_id": "ANNOUNCEMENT", "title": "Chào mừng"}, {"segment_id": "PASTOR_SERMON", "note": "Bài giảng"}]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["items"][1]["title"], "Mục sư giảng")
        bad = self.client.put("/api/v1/program", json={"items": [{"segment_id": "NOPE"}]})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("không tồn tại", bad.json()["detail"])
        cur = self.client.post("/api/v1/program/current", json={"index": 0, "segment_id": "ANNOUNCEMENT", "operator_id": "test"})
        self.assertEqual(cur.status_code, 200, cur.text)
        self.assertEqual(cur.json()["next"]["segment_id"], "PASTOR_SERMON")
        self.assertEqual(self.client.post("/api/v1/program/current", json={"index": 9}).status_code, 400)
        self.assertIsNone(self.client.post("/api/v1/program/reset", json={}).json()["current_index"])
        self.assertTrue(self.client.post("/api/v1/program/restore-default", json={}).json()["is_default"])

    def test_current_never_writes_to_mixer(self):
        from packages.safety_controller.modes import OperatorMode
        self.main.safety_mode_mgr.set_mode(OperatorMode.ASSIST, operator="test")
        before = self.main.x32_client.take_full_snapshot(max_channels=32).sha256
        writes = []
        original = self.main.x32_client.send_write
        self.main.x32_client.send_write = lambda *a, **k: writes.append(a) or original(*a, **k)
        try:
            # PASTOR_SERMON would mute most channels if it were applied.
            res = self.client.post("/api/v1/program/current", json={"index": 3, "segment_id": "PASTOR_SERMON"})
            self.assertEqual(res.status_code, 200, res.text)
        finally:
            self.main.x32_client.send_write = original
        self.assertEqual(writes, [])
        self.assertEqual(self.main.x32_client.take_full_snapshot(max_channels=32).sha256, before)

    def test_suggestion_endpoint(self):
        data = self.client.get("/api/v1/segment-suggestion").json()
        self.assertIn("suggestion", data)
        self.assertIn("reason", data)


if __name__ == "__main__":
    unittest.main()
