"""
Sprint 8 Test Suite: Native Audio Capture Agent & Multi-Channel USB Streaming
Tests device discovery, audio streaming worker, level calculation, and REST endpoints.
"""
import unittest
import time
import numpy as np
from fastapi.testclient import TestClient

from apps.capture_agent.device_manager import AudioDeviceManager, AudioDeviceInfo
from apps.capture_agent.stream_worker import AudioStreamWorker
from apps.api.main import app


class TestAudioCaptureAgent(unittest.TestCase):

    def setUp(self):
        self.mgr = AudioDeviceManager()

    def test_device_manager_enumeration(self):
        devices = self.mgr.list_input_devices()
        self.assertIsInstance(devices, list)
        self.assertGreaterEqual(len(devices), 1)

        # Simulator device must always be present
        sim_dev = next((d for d in devices if d["device_id"] == -1), None)
        self.assertIsNotNone(sim_dev)
        self.assertEqual(sim_dev["max_inputs"], 32)
        self.assertEqual(sim_dev["default_samplerate"], 48000.0)
        self.assertTrue(sim_dev["is_x32_compatible"])

    def test_audio_device_info_structure(self):
        info = AudioDeviceInfo(
            device_id=5,
            name="Behringer X-USB ASIO",
            hostapi="ASIO",
            max_inputs=32,
            max_outputs=32,
            default_sr=48000.0,
        )
        d = info.to_dict()
        self.assertEqual(d["device_id"], 5)
        self.assertEqual(d["name"], "Behringer X-USB ASIO")
        self.assertTrue(d["is_x32_compatible"])

    def test_stream_worker_simulation(self):
        blocks_received = []

        def callback(block: np.ndarray):
            blocks_received.append(block.shape)

        worker = AudioStreamWorker(
            device_id=-1,
            channels=2,
            sample_rate=48000,
            block_size=512,
            on_block_callback=callback,
        )
        self.assertFalse(worker.is_running)

        worker.start()
        self.assertTrue(worker.is_running)

        # Wait for a few blocks to process
        time.sleep(0.15)
        status = worker.get_status()

        self.assertTrue(status["is_running"])
        self.assertGreater(status["blocks_processed"], 0)
        self.assertEqual(len(status["peak_dbfs"]), 2)
        self.assertEqual(len(status["rms_dbfs"]), 2)
        # Levels should be bounded in dBFS
        self.assertLessEqual(status["peak_dbfs"][0], 0.0)
        self.assertGreater(status["peak_dbfs"][0], -90.0)

        worker.stop()
        self.assertFalse(worker.is_running)
        self.assertGreater(len(blocks_received), 0)
        self.assertEqual(blocks_received[0], (512, 2))


class TestAudioCaptureAPI(unittest.TestCase):
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

    def test_get_audio_devices_endpoint(self):
        res = self.client.get("/api/v1/audio/devices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("devices", data)
        self.assertIn("is_capturing", data)
        self.assertGreaterEqual(len(data["devices"]), 1)

    def test_start_and_stop_audio_capture_endpoints(self):
        # 1. Start simulated capture
        start_res = self.client.post("/api/v1/audio/capture/start", json={
            "device_id": -1,
            "channels": 2,
            "sample_rate": 48000,
        })
        self.assertEqual(start_res.status_code, 200)
        self.assertEqual(start_res.json()["status"], "STARTED")

        # 2. Check status while running
        time.sleep(0.1)
        status_res = self.client.get("/api/v1/audio/capture/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertTrue(status_data["is_running"])
        self.assertEqual(status_data["channels"], 2)

        # 3. Stop capture
        stop_res = self.client.post("/api/v1/audio/capture/stop")
        self.assertEqual(stop_res.status_code, 200)
        self.assertEqual(stop_res.json()["status"], "STOPPED")

        # 4. Check status is stopped
        final_status = self.client.get("/api/v1/audio/capture/status").json()
        self.assertFalse(final_status["is_running"])


if __name__ == "__main__":
    unittest.main()
