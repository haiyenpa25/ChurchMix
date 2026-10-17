"""
Sprint 11 Test Suite:
End-to-End Sunday Service Lifecycle & Hard Invariant Integration Tests
====================================================================
Tests the full lifecycle of a Sunday worship service:
1. Phase 1: Boot, Snapshot & DL16 In 11 Talkback Isolation Invariant
2. Phase 2: Pre-service Line Check & Physical Checklist (Wizard 2)
3. Phase 3: Vocal Calibration, Harmonic Rejection & Safe Feedback Notch (W3 & W5)
4. Phase 4: Live Service Tactical Monitoring, Silence Hold Invariant & USB Scene Export (W6 & W7)
"""

import unittest
import os
X32_TEST_PORT = int(os.environ.get("CHURCHMIX_X32_PORT", "10023"))
import sys
import tempfile
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.mock_x32.server import MockX32Server
from packages.x32_osc_adapter.client import X32Client
from packages.x32_osc_adapter.scene_exporter import SceneExporter
from packages.safety_controller.routing import RoutingGraph, InvariantViolationError
from packages.signal_analysis.dsp import AudioFrame, generate_sine_wave, generate_vocal_note
from packages.feedback_detector.detector import FeedbackDetector
from packages.mix_assistant.leveler import SpeechLeveler
from packages.storage.database import ChurchMixDatabase
from packages.wizards.service import WizardService


class TestSprint11E2EService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MockX32Server(host="127.0.0.1", port=X32_TEST_PORT)
        cls.server.start()
        time.sleep(0.1)

        cls.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db_path = os.path.join(cls.temp_dir.name, "e2e_churchmix.db")
        cls.db = ChurchMixDatabase(db_path=cls.db_path)

        cls.client = X32Client(host="127.0.0.1", port=X32_TEST_PORT, read_only_mode=True)
        cls.client.connect()
        cls.wizard = WizardService(client=cls.client)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.client.close()
            cls.server.stop()
            del cls.db
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def test_e2e_phase1_boot_and_safety_invariant(self):
        """Phase 1: Boot in READ_ONLY_MODE, Snapshot SHA-256 and Talkback DL16 #11 isolation."""
        self.assertTrue(self.client.read_only_mode)

        snapshot = self.client.take_full_snapshot()
        self.assertIsNotNone(snapshot.sha256)
        self.assertEqual(len(snapshot.sha256), 64)

        # Invariant Verification
        routing = RoutingGraph(snapshot.parameters)
        talkback_safe, msg = routing.verify_talkback_invariant()
        self.assertTrue(talkback_safe, f"Talkback invariant failed: {msg}")
        self.assertIn("strictly isolated from FOH", msg)
        self.assertIn("P16 Slot 11", msg)

        # Ensure no write can occur without approval
        with self.assertRaises(PermissionError):
            self.client.send_write("/ch/01/mix/fader", [0.8])

    def test_e2e_phase2_pre_service_line_check(self):
        """Phase 2: Wizard 2 line check for 32 channels and physical readiness."""
        check = self.wizard.run_pre_service_line_check()
        self.assertTrue(check.talkback_isolated)
        self.assertEqual(len(check.items), 32)
        self.assertTrue(len(check.physical_checklist) >= 5)

        # Channel 11 must be marked as P16 Only
        ch11 = next(item for item in check.items if item.channel_id == 11)
        self.assertFalse(ch11.is_foh)
        self.assertTrue(ch11.is_p16)

    def test_e2e_phase3_vocal_and_harmonic_rejection(self):
        """Phase 3: Harmonic Rejection prevents false alarms on singing, feedback resonance is caught."""
        detector = FeedbackDetector(min_prominence_db=12.0, min_persistence_frames=3, confidence_threshold=0.70)

        # 1. Singer sustained note A4 (440 Hz + harmonics)
        for i in range(5):
            vocal_audio = generate_vocal_note(fundamental_hz=440.0, duration_s=0.1)
            frame = AudioFrame(samples=vocal_audio, channel_id=1, timestamp=i * 0.1)
            candidates = detector.process_frame(frame)

        high_conf_vocal = [c for c in candidates if c.confidence >= 0.70]
        self.assertEqual(len(high_conf_vocal), 0, "Singing voice was falsely flagged as feedback!")

        # 2. Pure feedback squeal at 3150 Hz
        feedback_candidates = []
        for i in range(4):
            amp = 0.3 + (i * 0.15)
            raw = generate_sine_wave(freq_hz=3150.0, duration_s=0.1, amplitude=amp)
            noise = np.random.normal(0, 0.005, len(raw)).astype(np.float32)
            frame = AudioFrame(samples=raw + noise, channel_id=3, timestamp=i * 0.1)
            feedback_candidates = detector.process_frame(frame)

        self.assertGreater(len(feedback_candidates), 0)
        cand = feedback_candidates[0]
        self.assertTrue(3130.0 <= cand.freq_hz <= 3170.0)
        self.assertGreaterEqual(cand.confidence, 0.70)
        self.assertIn("notch", cand.recommended_action.lower())

    def test_e2e_phase4_live_silence_hold_and_scene_export(self):
        """Phase 4: Silence Hold prevents fader creep during pause, USB scene generated with invariant."""
        leveler = SpeechLeveler(target_rms_db=-20.0)

        # Active speech
        speech = generate_sine_wave(freq_hz=220.0, duration_s=0.1, amplitude=0.1)
        action_speech = leveler.process(AudioFrame(samples=speech, channel_id=1, timestamp=0.0), current_fader=0.75)
        self.assertEqual(action_speech.channel_id, 1)

        # Silence pause
        silence = np.random.normal(0, 0.0005, len(speech)).astype(np.float32)
        for _ in range(4):
            action_silence = leveler.process(AudioFrame(samples=silence, channel_id=1, timestamp=0.1), current_fader=0.75)

        self.assertEqual(action_silence.action_type, "HOLD")
        self.assertIn("SILENCE HOLD", action_silence.rationale)
        self.assertEqual(action_silence.target_fader, 0.75)

        # Export scene and check hard invariant on line 11
        snapshot = self.client.take_full_snapshot()
        scene_content = SceneExporter.export_scn(snapshot, scene_name="E2E_Test_Scene")
        self.assertIn('/ch/11/mix/lr OFF', scene_content)
        self.assertIn('/outputs/p16/11/src 11', scene_content)


if __name__ == "__main__":
    unittest.main()
