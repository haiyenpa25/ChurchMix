import time
import unittest
from types import SimpleNamespace

import numpy as np

from apps.api.audio_sources import AudioSourceError, resolve_analysis_audio


class AudioSourceTests(unittest.TestCase):
    def setUp(self):
        self.soundcheck = SimpleNamespace(is_active=False)
        self.frame = dict(samples=np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
                          captured_at=time.monotonic(), is_simulated=True,
                          clock_verified=True, clock_fault=None, overflow_count=0)
        self.worker = SimpleNamespace(is_running=True, sample_rate=44100,
                                      get_latest_frame=lambda: self.frame)

    def test_exact_channel_and_capture_sample_rate(self):
        samples, source = resolve_analysis_audio(self.soundcheck, self.worker, 2)
        np.testing.assert_array_equal(samples, self.frame['samples'][:, 1])
        self.assertEqual(source['sample_rate'], 44100)
        self.assertTrue(source['simulated'])

    def test_missing_channel_never_falls_back(self):
        with self.assertRaises(AudioSourceError) as caught:
            resolve_analysis_audio(self.soundcheck, self.worker, 3)
        self.assertEqual(caught.exception.status_code, 503)

    def test_stale_capture_rejected(self):
        self.frame['captured_at'] -= 1
        with self.assertRaises(AudioSourceError):
            resolve_analysis_audio(self.soundcheck, self.worker, 1)

    def test_physical_usb_requires_mapping_and_tap(self):
        self.frame['is_simulated'] = False
        with self.assertRaises(AudioSourceError):
            resolve_analysis_audio(self.soundcheck, self.worker, 1)

    def test_clock_fault_rejected(self):
        self.frame.update(is_simulated=False, clock_fault='drift')
        with self.assertRaises(AudioSourceError):
            resolve_analysis_audio(self.soundcheck, self.worker)

    def test_nonfinite_samples_rejected(self):
        self.frame['samples'][0, 0] = np.nan
        with self.assertRaises(AudioSourceError):
            resolve_analysis_audio(self.soundcheck, self.worker, 1)

    def test_soundcheck_uses_own_clock(self):
        self.soundcheck = SimpleNamespace(is_active=True, sample_rate=32000,
                                         generate_audio_block=lambda block_size: self.frame['samples'])
        samples, source = resolve_analysis_audio(self.soundcheck, None, 2)
        self.assertEqual(source['sample_rate'], 32000)
        np.testing.assert_array_equal(samples, self.frame['samples'][:, 1])

    def test_demo_is_explicitly_simulated(self):
        samples, source = resolve_analysis_audio(self.soundcheck, None)
        self.assertTrue(source['simulated'])
        self.assertEqual(source['tap_point'], 'SIMULATED')
        self.assertTrue(np.all(np.isfinite(samples)))
