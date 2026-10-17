"""
Sprint 2 Test Suite:
- Routing Graph Analysis & Signal Path Tracing
- Hard Invariant Verification (DL16 In 11 -> P16 only)
- Safety Gate Whitelist & Denylist Enforcement
- Operator Approval Verification
- Optimistic Locking (State Drift Abort)
- Transactional Execution with Readback & Rollback
"""

import unittest
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.x32_osc_adapter.client import X32Client
from packages.mock_x32.server import MockX32Server
from packages.safety_controller.routing import RoutingGraph, InvariantViolationError
from packages.safety_controller.transaction import (
    SafetyPolicy,
    Proposal,
    TransactionExecutor,
    ProposalRejectedError,
    TransactionFailedError,
)


class TestSprint2Safety(unittest.TestCase):
    SERVER_PORT = 10026

    @classmethod
    def setUpClass(cls):
        cls.server = MockX32Server(host="127.0.0.1", port=cls.SERVER_PORT)
        cls.server.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.client = X32Client(host="127.0.0.1", port=self.SERVER_PORT, read_only_mode=True, timeout=1.0)
        self.client.connect()
        self.executor = TransactionExecutor(client=self.client)

    def tearDown(self):
        self.client.close()

    def test_routing_graph_pastor_and_talkback(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)
        graph = RoutingGraph(snapshot.parameters)

        # Pastor mic routes to FOH
        is_foh, paths = graph.is_channel_routed_to_foh(1)
        self.assertTrue(is_foh)
        self.assertIn("Main Stereo Bus", paths[0])

        # Talkback Band strictly isolated from FOH
        is_foh_tb, tb_paths = graph.is_channel_routed_to_foh(11)
        self.assertFalse(is_foh_tb, f"Talkback must NOT route to FOH: {tb_paths}")

        # Talkback routes to P16
        is_p16_tb, p16_slots = graph.is_channel_routed_to_p16(11)
        self.assertTrue(is_p16_tb)
        self.assertIn("P16 Slot 11", p16_slots[0])

        # Invariant check passes
        ok, msg = graph.verify_talkback_invariant()
        self.assertTrue(ok)
        self.assertIn("VERIFIED SAFE", msg)

    def test_talkback_leakage_detection(self):
        """Simulate accidental routing of Talkback to Main FOH."""
        snapshot = self.client.take_full_snapshot(max_channels=32)
        corrupted_params = dict(snapshot.parameters)
        corrupted_params["/ch/11/mix/st"] = 1 # Leaked to Main!

        corrupted_graph = RoutingGraph(corrupted_params)
        ok, msg = corrupted_graph.verify_talkback_invariant()
        self.assertFalse(ok)
        self.assertIn("CRITICAL INVARIANT VIOLATION", msg)

    def test_denylist_policy_blocks_routing_and_p16(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)

        # Try to modify P16 output
        p16_proposal = Proposal(
            proposal_id="prop-p16-bad",
            target_channel=11,
            hypothesis="Accidental P16 edit",
            confidence=0.5,
            changes=[{"parameter": "/outputs/p16/11/src", "from": 11, "to": 1}],
            expected_sha256=snapshot.sha256,
        )
        p16_proposal.approve("operator_test")

        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(p16_proposal, "operator_test")
        self.assertIn("strictly protected system configuration", str(ctx.exception))

    def test_unapproved_proposal_is_rejected(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)
        proposal = Proposal(
            proposal_id="prop-unapproved",
            target_channel=1,
            hypothesis="Tune low-mid",
            confidence=0.8,
            changes=[{"parameter": "/ch/01/eq/2/g", "from": 0.5, "to": 0.45}],
            expected_sha256=snapshot.sha256,
            operator_approved=False, # NOT approved!
        )

        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(proposal, "operator_test")
        self.assertIn("has not been approved", str(ctx.exception))

    def test_optimistic_lock_revision_mismatch(self):
        proposal = Proposal(
            proposal_id="prop-stale",
            target_channel=1,
            hypothesis="Stale proposal",
            confidence=0.9,
            changes=[{"parameter": "/ch/01/eq/2/g", "from": 0.5, "to": 0.45}],
            expected_sha256="stale_hash_00000000000000000000000000000000000000000000000000000000",
        )
        proposal.approve("sound_tech")

        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(proposal, "sound_tech")
        self.assertIn("Mixer state has changed externally", str(ctx.exception))

    def test_successful_safe_transaction_with_readback(self):
        snapshot = self.client.take_full_snapshot(max_channels=32)

        # Propose conservative Pastor EQ tuning: cut 2nd band gain from 0.5 to 0.45
        proposal = Proposal(
            proposal_id="prop-pastor-eq-001",
            target_channel=1,
            hypothesis="Gentle low-mid mud reduction",
            confidence=0.85,
            changes=[
                {"parameter": "/ch/01/eq/2/g", "from": 0.50, "to": 0.45},
                {"parameter": "/ch/01/preamp/hpon", "from": 1, "to": 1},
            ],
            expected_sha256=snapshot.sha256,
        )
        proposal.approve("operator_hai")

        result = self.executor.execute(proposal, "operator_hai")
        self.assertEqual(result["status"], "SUCCESS")

        # Verify mixer updated and readback confirmed
        new_gain = self.client.query("/ch/01/eq/2/g")[0]
        self.assertAlmostEqual(new_gain, 0.45, places=2)

        # Verify client returned to read_only_mode = True
        self.assertTrue(self.client.read_only_mode)

        # Verify audit log entry
        self.assertEqual(len(self.executor.audit_log), 1)
        self.assertEqual(self.executor.audit_log[0]["status"], "COMMITTED")
        self.assertEqual(self.executor.audit_log[0]["operator"], "operator_hai")

        # Restore original value
        restore_snap = self.client.take_full_snapshot(max_channels=32)
        restore_prop = Proposal(
            proposal_id="prop-restore",
            target_channel=1,
            hypothesis="Restore test",
            confidence=1.0,
            changes=[{"parameter": "/ch/01/eq/2/g", "from": 0.45, "to": 0.50}],
            expected_sha256=restore_snap.sha256,
        )
        restore_prop.approve("operator_hai")
        self.executor.execute(restore_prop, "operator_hai")


if __name__ == "__main__":
    unittest.main()
