"""
Safety Hardening Regression Suite:
- Talkback leak detection through Mono/Center, Bus -> Main/Mono and Bus -> Matrix
- Snapshot actually captures every talkback routing path (no blind defaults)
- Fail-closed on incomplete routing data and on DL16 -> X32 patch mismatch
- Configurable talkback channel (AGENTS.md rule #6)
- EQ gain delta limit enforcement
- Rollback pre-reads, readback-verified restore, unreadable-parameter refusal
- API rejects cross-origin mutating requests
"""

import unittest
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.x32_osc_adapter.client import X32Client
from packages.mock_x32.server import MockX32Server
from packages.safety_controller.routing import (
    RoutingGraph,
    InvariantViolationError,
    talkback_routing_paths,
)
from packages.safety_controller.transaction import (
    SafetyPolicy,
    Proposal,
    TransactionExecutor,
    ProposalRejectedError,
    TransactionFailedError,
)


class TestTalkbackRoutingGraph(unittest.TestCase):
    """Pure graph tests on synthetic parameter dictionaries."""

    def _safe_state(self, tb_ch: int = 11):
        params = {p: 0 for p in talkback_routing_paths(tb_ch)}
        params[f"/ch/{tb_ch:02d}/config/name"] = "Talkback Band"
        params["/outputs/p16/11/src"] = tb_ch
        return params

    def test_safe_state_passes(self):
        ok, msg = RoutingGraph(self._safe_state(), require_complete=True).verify_talkback_invariant()
        self.assertTrue(ok, msg)

    def test_mono_center_leak_detected(self):
        params = self._safe_state()
        params["/ch/11/mix/mono"] = 1
        ok, msg = RoutingGraph(params).verify_talkback_invariant()
        self.assertFalse(ok)
        self.assertIn("Mono/Center", msg)

    def test_bus_to_matrix_leak_detected(self):
        params = self._safe_state()
        params["/ch/11/mix/07/on"] = 1
        params["/bus/07/mix/03/on"] = 1
        ok, msg = RoutingGraph(params).verify_talkback_invariant()
        self.assertFalse(ok)
        self.assertIn("Matrix 03", msg)

    def test_bus_to_main_leak_detected_even_at_zero_send_level(self):
        params = self._safe_state()
        params["/ch/11/mix/05/on"] = 1
        params["/ch/11/mix/05/level"] = 0.0
        params["/bus/05/mix/st"] = 1
        ok, msg = RoutingGraph(params).verify_talkback_invariant()
        self.assertFalse(ok)
        self.assertIn("Bus 05", msg)

    def test_bus_send_off_is_not_a_leak(self):
        params = self._safe_state()
        params["/ch/11/mix/05/on"] = 0
        params["/bus/05/mix/st"] = 1
        ok, msg = RoutingGraph(params).verify_talkback_invariant()
        self.assertTrue(ok, msg)

    def test_incomplete_snapshot_fails_closed(self):
        params = self._safe_state()
        del params["/bus/09/mix/st"]
        ok, msg = RoutingGraph(params, require_complete=True).verify_talkback_invariant()
        self.assertFalse(ok)
        self.assertIn("UNVERIFIABLE ROUTING", msg)

    def test_patch_mismatch_fails_closed(self):
        params = self._safe_state()
        params["/ch/11/config/name"] = "Choir L"
        params["/ch/14/config/name"] = "Talkback Band"
        ok, msg = RoutingGraph(params).verify_talkback_invariant()
        self.assertFalse(ok)
        self.assertIn("PATCH MISMATCH", msg)

    def test_configured_talkback_channel_override(self):
        params = self._safe_state(tb_ch=14)
        params["/outputs/p16/11/src"] = 14
        graph = RoutingGraph(params, talkback_channel=14, require_complete=True)
        self.assertEqual(graph.dl16_talkback_channel, 14)
        ok, msg = graph.verify_talkback_invariant()
        self.assertTrue(ok, msg)

        params["/ch/14/mix/st"] = 1
        ok, _ = RoutingGraph(params, talkback_channel=14).verify_talkback_invariant()
        self.assertFalse(ok)

    def test_diff_opening_bus_leak_is_rejected(self):
        params = self._safe_state()
        params["/bus/06/mix/st"] = 1
        diff = {"changed": {"/ch/11/mix/06/on": {"before": 0, "after": 1}}, "added": {}}
        with self.assertRaises(InvariantViolationError):
            RoutingGraph(params).validate_diff_invariants(diff)


class TestEqGainPolicy(unittest.TestCase):
    def _proposal(self, frm, to):
        return Proposal(
            proposal_id="EQ_LIMIT",
            target_channel=1,
            hypothesis="test",
            confidence=0.9,
            changes=[{"parameter": "/ch/01/eq/2/g", "from": frm, "to": to}],
            expected_sha256="x",
        )

    def test_eq_gain_jump_above_limit_rejected(self):
        with self.assertRaises(ProposalRejectedError):
            SafetyPolicy(max_eq_gain_delta=0.2).validate_proposal(self._proposal(0.5, 0.25))

    def test_eq_gain_jump_at_limit_allowed(self):
        SafetyPolicy(max_eq_gain_delta=0.2).validate_proposal(self._proposal(0.5, 0.3))


class TestLiveSafetyGate(unittest.TestCase):
    SERVER_PORT = 10041

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

    def _approved(self, changes, sha):
        p = Proposal(
            proposal_id=f"P_{time.time_ns()}",
            target_channel=1,
            hypothesis="test",
            confidence=0.9,
            changes=changes,
            expected_sha256=sha,
        )
        p.approve("operator_test")
        return p

    def test_snapshot_contains_all_talkback_routing_paths(self):
        snap = self.client.take_full_snapshot(max_channels=32)
        missing = [p for p in talkback_routing_paths(11) if p not in snap.parameters]
        self.assertEqual(missing, [])

    def test_console_side_matrix_leak_blocks_all_writes(self):
        # Someone on the console surface sends talkback to bus 07, which feeds Matrix 02
        with self.server.lock:
            self.server.state["/ch/11/mix/07/on"] = 1
            self.server.state["/bus/07/mix/02/on"] = 1
        snap = self.client.take_full_snapshot(max_channels=32)
        proposal = self._approved([{"parameter": "/ch/01/eq/1/g", "from": 0.5, "to": 0.45}], snap.sha256)
        with self.assertRaises(InvariantViolationError):
            self.executor.execute(proposal, "operator_test")
        self.assertEqual(self.server.state["/ch/01/eq/1/g"], 0.5)
        self.assertTrue(self.client.read_only_mode)

    def test_trim_rollback_restores_pre_read_value(self):
        snap = self.client.take_full_snapshot(max_channels=32)
        self.assertNotIn("/ch/01/preamp/trim", snap.parameters)

        original_query = self.client.query
        state = {"trim_reads": 0}

        def corrupt_post_write_readback(address, timeout=None):
            # 1st trim read = pre-read (real), 2nd = post-write readback (corrupted)
            if address == "/ch/01/preamp/trim":
                state["trim_reads"] += 1
                if state["trim_reads"] == 2:
                    return [0.123]
            return original_query(address, timeout)

        self.client.query = corrupt_post_write_readback
        proposal = self._approved([{"parameter": "/ch/01/preamp/trim", "from": 0.5, "to": 0.6}], snap.sha256)
        with self.assertRaises(TransactionFailedError):
            self.executor.execute(proposal, "operator_test")
        self.client.query = original_query

        self.assertEqual(self.executor.audit_log[-1]["status"], "ROLLED_BACK")
        self.assertAlmostEqual(self.client.query("/ch/01/preamp/trim")[0], 0.5, places=3)
        self.assertTrue(self.client.read_only_mode)

    def test_unreadable_parameter_is_refused_before_any_write(self):
        snap = self.client.take_full_snapshot(max_channels=32)
        # /ch/01/eq/1/type is whitelisted (EQ) but never captured in the snapshot;
        # remove it from the mock so the pre-read cannot get a value.
        with self.server.lock:
            del self.server.state["/ch/01/eq/1/type"]
        proposal = self._approved([{"parameter": "/ch/01/eq/1/type", "from": 1, "to": 2}], snap.sha256)
        self.client.default_timeout = 0.2
        with self.assertRaises(ProposalRejectedError):
            self.executor.execute(proposal, "operator_test")
        self.assertNotIn("/ch/01/eq/1/type", self.server.state)

    def test_success_result_exposes_sha256(self):
        snap = self.client.take_full_snapshot(max_channels=32)
        proposal = self._approved([{"parameter": "/ch/01/eq/1/g", "from": 0.5, "to": 0.45}], snap.sha256)
        result = self.executor.execute(proposal, "operator_test")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["sha256"]), 64)


class TestApiOriginGuard(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        self.client = TestClient(app)

    def test_cross_origin_mutation_rejected(self):
        res = self.client.post(
            "/api/v1/proposals/apply",
            headers={"Origin": "https://evil.example.com"},
            json={"proposal_id": "x", "operator_id": "attacker"},
        )
        self.assertEqual(res.status_code, 403)

    def test_same_origin_mutation_reaches_endpoint(self):
        res = self.client.post(
            "/api/v1/proposals/apply",
            headers={"Origin": "http://127.0.0.1:8080"},
            json={"proposal_id": "does-not-exist", "operator_id": "op"},
        )
        self.assertNotEqual(res.status_code, 403)

    def test_cors_does_not_allow_foreign_origin(self):
        res = self.client.get("/api/v1/status", headers={"Origin": "https://evil.example.com"})
        self.assertNotIn(res.headers.get("access-control-allow-origin"), ("*", "https://evil.example.com"))


if __name__ == "__main__":
    unittest.main()
