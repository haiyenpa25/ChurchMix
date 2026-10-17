"""Numerical equivalence and read-count checks using isolated fixtures only."""
import math
import unittest
from unittest.mock import Mock, patch

import numpy as np

from packages.signal_analysis.dsp import compute_fractional_octave_rta
from packages.x32_osc_adapter.client import Snapshot, X32Client


def reference_rta(freqs, levels, fraction=12, f_min=20.0, f_max=20000.0):
    ratio = 2.0 ** (1.0 / (2.0 * fraction))
    result = []
    for k in range(math.floor(fraction * math.log2(f_min / 1000.0)),
                   math.ceil(fraction * math.log2(f_max / 1000.0)) + 1):
        center = 1000.0 * 2.0 ** (k / fraction)
        if not f_min <= center <= f_max:
            continue
        lower, upper = center / ratio, center * ratio
        mask = (freqs >= lower) & (freqs < upper)
        result.append({"center_freq": round(center, 1), "lower_freq": round(lower, 1),
                       "upper_freq": round(upper, 1),
                       "level_dbfs": round(float(np.max(levels[mask])) if mask.any() else -120.0, 2)})
    return result


class TestRTAEquivalence(unittest.TestCase):
    def test_grids_resolutions_and_changed_levels(self):
        rng = np.random.default_rng(42)
        for size in (0, 513, 1025, 2049):
            for fraction in (3, 12, 24):
                freqs = np.linspace(0, 24000, size)
                for _ in range(2):
                    levels = rng.uniform(-120, 0, size).astype(np.float32)
                    self.assertEqual(compute_fractional_octave_rta(freqs, levels, fraction),
                                     reference_rta(freqs, levels, fraction))

    def test_unsorted_and_boundary_bins(self):
        ratio = 2.0 ** (1.0 / 24)
        freqs = np.array([1000 * ratio, 1000 / ratio, 0, 1000, 24000])
        levels = np.array([-1, -40, -120, -20, -80], dtype=np.float32)
        self.assertEqual(compute_fractional_octave_rta(freqs, levels), reference_rta(freqs, levels))


class TestChannelSnapshotReads(unittest.TestCase):
    def make_client(self):
        client = X32Client()
        client.query = Mock(side_effect=lambda path: [float(len(path))])
        return client

    def test_summary_matches_live_reads_without_more_osc(self):
        client = self.make_client()
        live = client.get_channel_summary(7)
        params = {call.args[0]: float(len(call.args[0])) for call in client.query.call_args_list}
        snapshot = Snapshot(0, "", {}, "fixture", 32, params)
        client.query.reset_mock()
        self.assertEqual(client.get_channel_summary(7, snapshot=snapshot), live)
        client.query.assert_not_called()
        self.assertTrue(client.read_only_mode)

    def test_incomplete_snapshot_never_falls_back_to_network(self):
        client = self.make_client()
        with self.assertRaises(KeyError):
            client.get_channel_summary(7, snapshot=Snapshot(0, "", {}, "fixture", 32, {}))
        client.query.assert_not_called()

    def test_channels_endpoint_reads_profile_once_and_uses_snapshot(self):
        from apps.api import main
        client = self.make_client()
        params = {}
        for ch in range(1, 33):
            client.get_channel_summary(ch)
        for call in client.query.call_args_list:
            params[call.args[0]] = float(len(call.args[0]))
        snapshot = Snapshot(0, "", {}, "fixture", 32, params)
        client.take_full_snapshot = Mock(return_value=snapshot)
        client.query.reset_mock()
        profile = Mock()
        profile.get_channels.return_value = [{"channel": 7, "role": "PIANO_KEYS"}]
        routing = Mock()
        routing.is_channel_routed_to_foh.return_value = (False, "fixture")
        routing.is_channel_routed_to_p16.return_value = (False, [])
        with patch.object(main, "x32_client", client), patch.object(main, "church_profile_mgr", profile), \
                patch.object(main, "RoutingGraph", return_value=routing):
            channels = main.get_channels()["channels"]
        self.assertEqual(len(channels), 32)
        self.assertEqual(channels[6]["church_role"], "PIANO_KEYS")
        client.query.assert_not_called()
        client.take_full_snapshot.assert_called_once_with(max_channels=32)
        profile.get_channels.assert_called_once_with()
        profile.get_channel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
