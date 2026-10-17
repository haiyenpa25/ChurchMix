"""Reject malformed proposals before any OSC I/O (isolated fixtures)."""
import unittest
from unittest.mock import Mock

from packages.safety_controller.transaction import (
    Proposal, ProposalRejectedError, SafetyPolicy, TransactionExecutor,
)


class TestExactSafetyWhitelist(unittest.TestCase):
    def proposal(self, path, before=0.5, after=0.45, channel=1):
        return Proposal("fixture", channel, "fixture", 1.0,
                        [{"parameter": path, "from": before, "to": after}],
                        "fixture-sha", True, "fixture-operator")

    def assert_rejected_without_io(self, proposal):
        client = Mock()
        executor = TransactionExecutor(client, SafetyPolicy())
        with self.assertRaises(ProposalRejectedError):
            executor.execute(proposal, "fixture-operator")
        self.assertEqual(client.mock_calls, [])

    def test_unknown_nested_paths_and_malformed_bus_ids(self):
        for path in ("/ch/01/eq/5/g", "/ch/01/eq/1/unknown", "/ch/01/eq/on/extra",
                     "/ch/01/automix/unknown", "/ch/01/gate/unknown",
                     "/ch/01/gate/filter/unknown", "/ch/01/mix/1/level",
                     "/ch/01/mix/+1/level", "/ch/01/mix/17/level"):
            with self.subTest(path=path):
                self.assert_rejected_without_io(self.proposal(path))

    def test_non_finite_and_non_numeric_values(self):
        for value in (float("nan"), float("inf"), float("-inf"), "0.45", None):
            with self.subTest(value=value):
                self.assert_rejected_without_io(self.proposal("/ch/01/eq/1/g", after=value))
                self.assert_rejected_without_io(self.proposal("/ch/01/eq/1/g", before=value))

    def test_invalid_channel_ids(self):
        for channel in (0, 33, -1, True, 1.0):
            with self.subTest(channel=channel):
                self.assert_rejected_without_io(self.proposal("/ch/01/eq/1/g", channel=channel))

    def test_supported_tuning_paths_remain_allowed(self):
        paths = ["/ch/01/eq/on", "/ch/01/automix/group", "/ch/01/automix/weight",
                 "/ch/01/gate/on", "/ch/01/gate/mode", "/ch/01/gate/thr",
                 "/ch/01/gate/range", "/ch/01/gate/filter/on", "/ch/01/gate/filter/f",
                 "/ch/01/mix/01/on", "/ch/01/mix/16/level"]
        paths += [f"/ch/01/eq/{band}/{parameter}" for band in range(1, 5) for parameter in ("f", "g", "q")]
        for path in paths:
            with self.subTest(path=path):
                SafetyPolicy().validate_proposal(self.proposal(path, before=0.3, after=0.35))


if __name__ == "__main__":
    unittest.main()
