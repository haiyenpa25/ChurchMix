"""
Sprint 25 Test Suite: Four-Tier Safety Engine Operating Modes & Auto-Disengage System.
======================================================================================
Tests:
1. Default system state: Starts strictly in OBSERVE (Read-only) mode.
2. Mode transitions between OBSERVE, ASSIST, and LIMITED_AUTO.
3. ADMIN_MAINTENANCE PIN protection: Requires valid security PIN, rejects invalid attempts.
4. Hard Safety Invariant preservation: Channel 11 Band Talkback remains protected even under ADMIN mode.
5. Auto-Disengage watchdog: Excessive clipping (> 5 frames) drops mode back to OBSERVE and locks writes.
6. Auto-Disengage watchdog: Feedback spike in LIMITED_AUTO mode instantly disengages.
7. TransactionExecutor integration: Blocks proposals when in OBSERVE or disengaged state.
8. REST API: GET /api/v1/safety/mode, POST /api/v1/safety/mode, and POST /api/v1/safety/disengage.
"""
import unittest
import time
from fastapi.testclient import TestClient

from packages.safety_controller.modes import (
    SafetyModeManager,
    OperatorMode,
    DisengageReason,
    SafetyModeState,
)
from packages.safety_controller.transaction import (
    SafetyPolicy,
    Proposal,
    TransactionExecutor,
    ProposalRejectedError,
)
from packages.mock_x32.server import MockX32Server
from packages.x32_osc_adapter.client import X32Client
from apps.api.main import app, safety_mode_mgr


class TestSprint25SafetyModesAndDisengage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_default_state_is_observe(self):
        """Verify SafetyModeManager defaults strictly to OBSERVE mode with read_only enabled."""
        mgr = SafetyModeManager()
        self.assertEqual(mgr.get_mode(), OperatorMode.OBSERVE)
        self.assertTrue(mgr.is_read_only())
        self.assertFalse(mgr.state.is_disengaged)
        self.assertEqual(mgr.state.disengage_reason, DisengageReason.NONE)

    def test_mode_transitions_assist_and_limited_auto(self):
        """Verify clean transitions to ASSIST and LIMITED_AUTO modes."""
        mgr = SafetyModeManager()

        # Transition to ASSIST
        state_assist = mgr.set_mode(OperatorMode.ASSIST, operator="LeadEngineer")
        self.assertEqual(mgr.get_mode(), OperatorMode.ASSIST)
        self.assertFalse(mgr.is_read_only())
        self.assertEqual(state_assist.changed_by, "LeadEngineer")

        # Transition to LIMITED_AUTO
        state_auto = mgr.set_mode(OperatorMode.LIMITED_AUTO, operator="AudioTech")
        self.assertEqual(mgr.get_mode(), OperatorMode.LIMITED_AUTO)
        self.assertFalse(mgr.is_read_only())
        self.assertEqual(state_auto.previous_mode, OperatorMode.ASSIST)

        # Transition back to OBSERVE
        mgr.set_mode(OperatorMode.OBSERVE, operator="LeadEngineer")
        self.assertEqual(mgr.get_mode(), OperatorMode.OBSERVE)
        self.assertTrue(mgr.is_read_only())

    def test_admin_maintenance_pin_protection(self):
        """Verify ADMIN_MAINTENANCE requires valid admin PIN to transition."""
        mgr = SafetyModeManager(admin_pin="7777")

        # 1. Invalid PIN should raise PermissionError
        with self.assertRaises(PermissionError):
            mgr.set_mode(OperatorMode.ADMIN_MAINTENANCE, admin_pin="0000")

        # 2. No PIN should raise PermissionError
        with self.assertRaises(PermissionError):
            mgr.set_mode(OperatorMode.ADMIN_MAINTENANCE, admin_pin=None)

        # 3. Valid PIN succeeds
        state = mgr.set_mode(OperatorMode.ADMIN_MAINTENANCE, admin_pin="7777", operator="ChurchAdmin")
        self.assertEqual(mgr.get_mode(), OperatorMode.ADMIN_MAINTENANCE)
        self.assertFalse(mgr.is_read_only())

    def test_auto_disengage_excessive_clipping(self):
        """Verify watchdog disengages to OBSERVE after 6 consecutive clipping frames."""
        mgr = SafetyModeManager()
        mgr.set_mode(OperatorMode.ASSIST, operator="SoundTech")
        self.assertFalse(mgr.is_read_only())

        # Feed 5 clipping frames (threshold is 6)
        for _ in range(5):
            mgr.record_telemetry_heartbeat(clip_detected=True)
            self.assertEqual(mgr.get_mode(), OperatorMode.ASSIST)

        # 6th clipping frame triggers auto-disengage
        mgr.record_telemetry_heartbeat(clip_detected=True)
        self.assertEqual(mgr.get_mode(), OperatorMode.OBSERVE)
        self.assertTrue(mgr.is_read_only())
        self.assertTrue(mgr.state.is_disengaged)
        self.assertEqual(mgr.state.disengage_reason, DisengageReason.EXCESSIVE_CLIPPING)
        self.assertIn("vỡ tiếng", mgr.state.disengage_detail)

    def test_auto_disengage_feedback_spike_in_limited_auto(self):
        """Verify sudden feedback spike in LIMITED_AUTO triggers auto-disengage."""
        mgr = SafetyModeManager()
        mgr.set_mode(OperatorMode.LIMITED_AUTO, operator="SoundTech")

        mgr.record_telemetry_heartbeat(feedback_spike=True)
        self.assertEqual(mgr.get_mode(), OperatorMode.OBSERVE)
        self.assertTrue(mgr.state.is_disengaged)
        self.assertEqual(mgr.state.disengage_reason, DisengageReason.FEEDBACK_SPIKE)

    def test_transaction_executor_blocks_in_observe_mode(self):
        """Verify TransactionExecutor blocks writes when mode is OBSERVE or disengaged."""
        mock = MockX32Server(port=10035)
        mock.start()
        client = X32Client(port=10035, read_only_mode=True)
        client.connect()

        mgr = SafetyModeManager() # starts in OBSERVE
        executor = TransactionExecutor(client=client, policy=SafetyPolicy(), mode_manager=mgr)

        snap = client.take_full_snapshot(max_channels=32)
        prop = Proposal(
            proposal_id="prop-obs-test",
            target_channel=1,
            hypothesis="Test proposal in OBSERVE mode",
            confidence=0.9,
            changes=[{"parameter": "/ch/01/mix/on", "from": 1, "to": 0}],
            expected_sha256=snap.sha256,
            operator_approved=True,
            approved_by="Operator",
        )

        # In OBSERVE mode -> MUST BE REJECTED
        with self.assertRaises(ProposalRejectedError) as cm:
            executor.execute(prop, operator_id="Operator")
        self.assertIn("OBSERVE mode (Read-Only)", str(cm.exception))

        # Switch to ASSIST mode -> EXECUTION SUCCEEDS
        mgr.set_mode(OperatorMode.ASSIST, operator="Operator")
        res = executor.execute(prop, operator_id="Operator")
        self.assertEqual(res["status"], "SUCCESS")

        client.close()
        mock.stop()

    def test_hard_safety_invariant_under_admin_mode(self):
        """Verify that even under ADMIN_MAINTENANCE mode, DL16 #11 talkback to FOH is forbidden."""
        from packages.safety_controller.routing import RoutingGraph, InvariantViolationError

        # Create a mock server and client
        mock = MockX32Server(port=10036)
        mock.start()
        client = X32Client(port=10036, read_only_mode=True)
        client.connect()

        # Admin mode active
        mgr = SafetyModeManager()
        mgr.set_mode(OperatorMode.ADMIN_MAINTENANCE, admin_pin="7777", operator="Admin")
        executor = TransactionExecutor(client=client, policy=SafetyPolicy(), mode_manager=mgr)

        snap = client.take_full_snapshot(max_channels=32)

        # Illegal proposal attempting to route channel 11 to main LR
        illegal_tb_prop = Proposal(
            proposal_id="prop-illegal-admin-tb",
            target_channel=11,
            hypothesis="Attempting illegal talkback leak to LR under admin mode",
            confidence=0.99,
            changes=[{"parameter": "/ch/11/mix/lr", "from": 0, "to": 1}],
            expected_sha256=snap.sha256,
            operator_approved=True,
            approved_by="Admin",
        )

        # Safety policy whitelist or routing check MUST abort
        with self.assertRaises((ProposalRejectedError, InvariantViolationError)):
            executor.execute(illegal_tb_prop, operator_id="Admin")

        client.close()
        mock.stop()

    def test_rest_api_safety_mode_flow(self):
        """Verify REST API GET and POST safety mode transitions."""
        # 1. GET current mode
        res = self.client.get("/api/v1/safety/mode")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("current_mode", data)
        self.assertIn("available_modes", data)
        self.assertIn("read_only", data)

        # 2. Switch to ASSIST
        res_post = self.client.post("/api/v1/safety/mode", json={"mode": "ASSIST", "operator": "TestTech"})
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()["current_mode"], "ASSIST")
        self.assertFalse(res_post.json()["read_only"])

        # 3. Switch to ADMIN_MAINTENANCE with wrong PIN -> 403 Forbidden
        res_admin_bad = self.client.post("/api/v1/safety/mode", json={"mode": "ADMIN_MAINTENANCE", "admin_pin": "9999"})
        self.assertEqual(res_admin_bad.status_code, 403)

        # 4. Switch to ADMIN_MAINTENANCE with correct PIN "7777" -> 200 OK
        res_admin_ok = self.client.post("/api/v1/safety/mode", json={"mode": "ADMIN_MAINTENANCE", "admin_pin": "7777"})
        self.assertEqual(res_admin_ok.status_code, 200)
        self.assertEqual(res_admin_ok.json()["current_mode"], "ADMIN_MAINTENANCE")

        # 5. Trigger emergency disengage
        res_dis = self.client.post("/api/v1/safety/disengage", json={"reason": "PANIC_BUTTON", "detail": "Test panic"})
        self.assertEqual(res_dis.status_code, 200)
        self.assertEqual(res_dis.json()["current_mode"], "OBSERVE")
        self.assertTrue(res_dis.json()["is_disengaged"])

        # 6. Resume standby
        res_res = self.client.post("/api/v1/emergency/resume-auto")
        self.assertEqual(res_res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
