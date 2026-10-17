"""
Sprint 9 Test Suite: Native Behringer X32 Scene (.scn) File Generation & USB Export
Tests ASCII scene syntax, 32-channel parameter mapping, and hard invariant enforcement.
"""
import unittest
from fastapi.testclient import TestClient

from packages.x32_osc_adapter.scene_exporter import SceneExporter
from packages.mock_x32.server import MockX32Server
from packages.x32_osc_adapter.client import X32Client
from apps.api.main import app


class TestSceneExport(unittest.TestCase):

    def setUp(self):
        self.server = MockX32Server(host="127.0.0.1", port=10024)
        self.server.start()
        self.client = X32Client(host="127.0.0.1", port=10024, read_only_mode=True)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.server.stop()

    def test_scene_exporter_format_and_invariants(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)
        scn_text = SceneExporter.export_scn(snapshot, scene_name="Sunday_Chuan")

        # 1. Header verification
        self.assertTrue(scn_text.startswith('#2.1# "Sunday_Chuan"'))

        # 2. 32 channels present
        for ch in range(1, 33):
            self.assertIn(f"/ch/{ch:02d}/config", scn_text)
            self.assertIn(f"/ch/{ch:02d}/mix/fader", scn_text)
            self.assertIn(f"/ch/{ch:02d}/eq/1 PEQ", scn_text)

        # 3. Hard invariant: DL16 #11 Talkback must NEVER be routed to Main FOH
        self.assertIn("/ch/11/mix/lr OFF", scn_text)
        self.assertIn("/outputs/p16/11/src 11", scn_text)
        self.assertIn('/outputs/p16/11/tap "Direct Pre"', scn_text)


class TestSceneExportAPI(unittest.TestCase):
    _ctx = None
    client = None

    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        if cls._ctx:
            cls._ctx.__exit__(None, None, None)

    def test_get_scene_export_endpoint(self):
        res = self.client.get("/api/v1/scenes/export?name=Sunday_Test_Scene")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], "Sunday_Test_Scene.scn")
        self.assertIn('#2.1# "Sunday_Test_Scene"', data["content"])
        self.assertIn("/ch/11/mix/lr OFF", data["content"])


if __name__ == "__main__":
    unittest.main()
