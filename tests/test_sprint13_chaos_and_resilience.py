"""
Sprint 13 Test Suite:
Chaos, Fault Injection & Safety Resilience
==========================================
Tests the system's fault tolerance, fail-safe invariants, and automatic recovery:
1. Adversarial Talkback Invariant Violation Injection (/ch/11/mix/st -> 1)
2. Protected Route Deny-List Infiltration (/config/routing, /outputs/p16, /main/st)
3. Cross-Channel Mutation Attack Rejection
4. Slew-Rate Jump Limit Violations
5. Stale Proposal & External Mixer Revision Drift (SHA-256 Lock)
6. Readback Mismatch & Automatic Rollback to Pre-Mutation Snapshot
7. Network Drop / UDP Timeout Resilience & Safe Recovery
8. Emergency Panic Lockdown (STOP AUTO) Invariant
"""

import unittest
import os
import sys
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.mock_x32.server import MockX32Server
from packages.x32_osc_adapter.client import (
    X32Client,
    Snapshot,
    ReadOnlyViolationError,
    X32ConnectionError,
)
from packages.safety_controller.routing import RoutingGraph, InvariantViolationError
from packages.safety_controller.transaction import (
    TransactionExecutor,
    SafetyPolicy,
    Proposal,
    ProposalRejectedError,
    TransactionFailedError,
)
from apps.api.main import app
from fastapi.testclient import TestClient


class TestSprint13ChaosAndResilience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Dedicated port for isolated chaos testing
        cls.server = MockX32Server(host="127.0.0.1", port=10033)
        cls.server.start()
        time.sleep(0.1)

        cls.client = X32Client(host="127.0.0.1", port=10033, read_only_mode=True, timeout=0.8)
        cls.client.connect()
        cls.policy = SafetyPolicy(max_fader_delta=0.1, max_eq_gain_delta=0.2)
        cls.executor = TransactionExecutor(client=cls.client, policy=cls.policy)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.client.close()
            cls.server.stop()
        except Exception:
            pass

    def test_01_read_only_mode_blocks_direct_writes(self):
        """Hard Rule: Direct send_write MUST fail when read_only_mode is True."""
        self.assertTrue(self.client.read_only_mode)
        with self.assertRaises(ReadOnlyViolationError):
            self.client.send_write("/ch/01/mix/fader", [0.80])

    def test_02_adversarial_talkback_leak_injection_fails(self):
        """Hard Invariant #1: DL16 In 11 (Ch 11) must NEVER route to Main FOH."""
        snap = self.client.take_full_snapshot(max_channels=32)

        # Craft malicious proposal trying to turn on Main FOH for Channel 11
        bad_prop = Proposal(
            proposal_id="exploit-tb-leak",
            target_channel=11,
            hypothesis="Malicious routing bypass attempt",
            confidence=0.99,
            changes=[{"parameter": "/ch/11/mix/st", "from": 0, "to": 1}],
            expected_sha256=snap.sha256,
        )
        bad_prop.approve(operator_id="attacker")

        # Must be rejected by policy (not in allowed EQ/HPF/Fader whitelist)
        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(bad_prop, operator_id="attacker")
        self.assertIn("SAFETY DENIAL", str(ctx.exception))

        # Check mixer state was untouched: /ch/11/mix/st remains 0
        val = self.client.query("/ch/11/mix/st")[0]
        self.assertEqual(val, 0)
        self.assertTrue(self.client.read_only_mode)

    def test_03_protected_route_deny_list_infiltration(self):
        """Protected paths (/config/routing, /outputs/p16, /main/st) are strictly denied."""
        snap = self.client.take_full_snapshot(max_channels=32)

        denied_targets = [
            ("/config/routing/IN", "AES50B 1-16"),
            ("/outputs/p16/11", 5),
            ("/main/st/mix/fader", 0.0),
        ]

        for path, bad_val in denied_targets:
            prop = Proposal(
                proposal_id=f"exploit-{path.replace('/', '_')}",
                target_channel=1,
                hypothesis="Protected path injection attack",
                confidence=0.9,
                changes=[{"parameter": path, "from": None, "to": bad_val}],
                expected_sha256=snap.sha256,
            )
            prop.approve(operator_id="attacker")

            with self.assertRaises(ProposalRejectedError) as ctx:
                self.executor.execute(prop, operator_id="attacker")
            self.assertIn("SAFETY DENIAL", str(ctx.exception))

        self.assertTrue(self.client.read_only_mode)

    def test_04_cross_channel_mutation_attack_rejected(self):
        """Proposal targeting Channel 2 cannot modify Channel 5."""
        snap = self.client.take_full_snapshot(max_channels=32)
        prop = Proposal(
            proposal_id="exploit-cross-ch",
            target_channel=2,
            hypothesis="Cross channel mutation attack",
            confidence=0.8,
            changes=[{"parameter": "/ch/05/eq/1/g", "from": 0.5, "to": 0.3}],
            expected_sha256=snap.sha256,
        )
        prop.approve(operator_id="attacker")

        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(prop, operator_id="attacker")
        self.assertIn("Proposal targets Channel 2, but attempts to mutate '/ch/05/eq/1/g'", str(ctx.exception))

    def test_05_slew_rate_jump_limit_violation(self):
        """Fader change greater than max_fader_delta (0.10) must be rejected."""
        snap = self.client.take_full_snapshot(max_channels=32)
        prop = Proposal(
            proposal_id="exploit-fader-jump",
            target_channel=1,
            hypothesis="Violent fader volume jump",
            confidence=0.9,
            changes=[{"parameter": "/ch/01/mix/fader", "from": 0.75, "to": 0.95}], # Delta = 0.20 > 0.10
            expected_sha256=snap.sha256,
        )
        prop.approve(operator_id="attacker")

        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(prop, operator_id="attacker")
        self.assertIn("exceeds maximum safe limit", str(ctx.exception))

    def test_06_stale_proposal_revision_drift_detection(self):
        """If mixer state changes externally (knob turned on console), proposal is rejected."""
        # 1. Take snapshot
        old_snap = self.client.take_full_snapshot(max_channels=32)

        # 2. Simulate someone turning a knob on the physical console
        with self.server.lock:
            self.server.state["/ch/02/eq/2/g"] = 0.65

        # 3. Try to execute a proposal based on the old snapshot
        prop = Proposal(
            proposal_id="stale-proposal-01",
            target_channel=1,
            hypothesis="Legitimate vocal EQ change but based on stale snapshot",
            confidence=0.85,
            changes=[{"parameter": "/ch/01/eq/1/g", "from": 0.5, "to": 0.45}],
            expected_sha256=old_snap.sha256,
        )
        prop.approve(operator_id="operator_tim")

        with self.assertRaises(ProposalRejectedError) as ctx:
            self.executor.execute(prop, operator_id="operator_tim")
        self.assertIn("Mixer state has changed externally", str(ctx.exception))

        # Restore server state
        with self.server.lock:
            self.server.state["/ch/02/eq/2/g"] = 0.50

    def test_07_readback_mismatch_triggers_clean_rollback(self):
        """If a write fails readback verification, all changes must roll back cleanly."""
        snap = self.client.take_full_snapshot(max_channels=32)

        orig_ch1_eq1 = self.client.query("/ch/01/eq/1/g")[0]
        orig_ch1_eq2 = self.client.query("/ch/01/eq/2/g")[0]

        prop = Proposal(
            proposal_id="test-rollback-flow",
            target_channel=1,
            hypothesis="Two-band EQ adjustment with simulated hardware readback failure",
            confidence=0.90,
            changes=[
                {"parameter": "/ch/01/eq/1/g", "from": orig_ch1_eq1, "to": 0.42},
                {"parameter": "/ch/01/eq/2/g", "from": orig_ch1_eq2, "to": 0.48},
            ],
            expected_sha256=snap.sha256,
        )
        prop.approve(operator_id="operator_tim")

        # Mock the query response for the second parameter to simulate readback mismatch (only during readback)
        real_query = self.client.query
        call_count = 0
        def mock_query(addr, timeout=None):
            nonlocal call_count
            if addr == "/ch/01/eq/2/g":
                call_count += 1
                if call_count > 1: # 1st call is in take_full_snapshot, 2nd call is the readback!
                    return [0.99] # Mismatch! (Expected 0.48)
            return real_query(addr, timeout=timeout)

        with patch.object(self.client, 'query', side_effect=mock_query):
            with self.assertRaises(TransactionFailedError) as ctx:
                self.executor.execute(prop, operator_id="operator_tim")
            self.assertIn("Readback mismatch", str(ctx.exception))

        # Check client is safely back in READ_ONLY_MODE
        self.assertTrue(self.client.read_only_mode)

        # Check that band 1 was rolled back to its original value!
        current_eq1 = self.client.query("/ch/01/eq/1/g")[0]
        self.assertAlmostEqual(current_eq1, orig_ch1_eq1, places=2)

    def test_08_network_timeout_and_fault_resilience(self):
        """Client handles UDP timeouts gracefully without crashing."""
        # Querying an address with 0.1s timeout where nothing replies
        with self.assertRaises(X32ConnectionError):
            self.client.query("/nonexistent/address", timeout=0.1)

        # Client socket remains healthy and can query valid paths immediately
        info = self.client.query("/info")
        self.assertIsNotNone(info)
        self.assertIn("X32 Compact", info[2])

    def test_09_api_stop_auto_panic_lockdown(self):
        """API /api/v1/emergency/stop-auto halts automated processing and locks down mixer."""
        with TestClient(app) as test_client:
            # 1. Trigger STOP AUTO
            res = test_client.post("/api/v1/emergency/stop-auto")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "STOPPED")
            self.assertTrue(data["read_only_mode"])

            # 2. Check status reports stop_auto = True
            res = test_client.get("/api/v1/status")
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json()["stop_auto"])
            self.assertTrue(res.json()["read_only_mode"])

            # 3. Attempting to apply a proposal while STOP AUTO is engaged must be rejected
            res_apply = test_client.post("/api/v1/proposals/apply", json={
                "proposal_id": "prop-test-during-panic",
                "operator_id": "operator_tim",
            })
            self.assertEqual(res_apply.status_code, 403)
            self.assertIn("STOP AUTO", res_apply.json()["detail"])

            # 4. Resume normal observe mode
            res_resume = test_client.post("/api/v1/emergency/resume-auto")
            self.assertEqual(res_resume.status_code, 200)


if __name__ == "__main__":
    unittest.main()
