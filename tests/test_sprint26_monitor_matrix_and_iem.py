"""
Test Suite for Sprint 26: Multi-Bus Monitor Mix Matrix & Personal IEM Invariant Inspector.
Verifies:
- Ultranet P16 Slot Audit & Hard Invariant (DL16 In 11 Talkback -> Slot 11 ONLY)
- MixBus Auxiliary Matrix classification (WEDGE, IEM, SUBGROUP, FX)
- Detection of Talkback bleed into FOH or Stage Floor Wedges
- Acoustic feedback risk detection on high vocal sends (> 0.80) to stage wedges
- Tap point consistency audit (Pre-Fader vs Post-Fader)
- Non-destructive, safe monitor balance proposal generation
- SafetyGate policy enforcement on mixbus send mutations
- FastAPI REST API endpoints (/api/v1/monitors/*)
"""

import unittest
import copy
from fastapi.testclient import TestClient

from packages.mix_assistant.monitor_inspector import (
    MonitorMatrixInspector,
    P16SlotInfo,
    MixBusSummary,
    MonitorMatrixAuditReport,
    x32_to_bus_level_db,
    bus_level_db_to_x32,
)
from packages.safety_controller.transaction import Proposal, SafetyPolicy, ProposalRejectedError
from packages.safety_controller.modes import OperatorMode
from packages.mock_x32.server import MockX32Server
from packages.x32_osc_adapter.client import X32Client
from apps.api.main import app, x32_client, safety_mode_mgr


class TestSprint26MonitorMatrixAndIEM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set safety mode to ASSIST so proposals can be evaluated
        safety_mode_mgr.set_mode(OperatorMode.ASSIST)
        
        # Build base church state
        mock_server = MockX32Server()
        cls.base_state = copy.deepcopy(mock_server.state)

        # Trigger FastAPI lifespan
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_p16_audit_safe_default(self):
        """P16 audit passes when DL16 In 11 maps solely to P16 Slot 11."""
        state = copy.deepcopy(self.base_state)
        slots, is_safe, violations = MonitorMatrixInspector.audit_p16_ultranet(state)

        self.assertEqual(len(slots), 16)
        self.assertTrue(is_safe)
        self.assertEqual(len(violations), 0)

        # Slot 11 verification
        slot_11 = slots[10]
        self.assertEqual(slot_11.slot, 11)
        self.assertEqual(slot_11.source_channel, 11)
        self.assertTrue(slot_11.is_band_talkback)
        self.assertEqual(slot_11.status, "SAFE")

    def test_p16_audit_detects_talkback_leak_to_other_slot(self):
        """P16 audit flags CRITICAL_INVARIANT_VIOLATION if Ch 11 leaks to another slot."""
        state = copy.deepcopy(self.base_state)
        # Leak talkback to P16 Slot 5
        state["/outputs/p16/05/src"] = 11

        slots, is_safe, violations = MonitorMatrixInspector.audit_p16_ultranet(state)
        self.assertFalse(is_safe)
        self.assertTrue(any("Slot 05" in v for v in violations))
        self.assertEqual(slots[4].status, "CRITICAL_INVARIANT_VIOLATION")

    def test_p16_audit_warns_when_slot_11_missing_talkback(self):
        """P16 audit warns if Slot 11 is not routed to Channel 11."""
        state = copy.deepcopy(self.base_state)
        state["/outputs/p16/11/src"] = 1 # Assigned to Pastor instead of Talkback

        slots, is_safe, violations = MonitorMatrixInspector.audit_p16_ultranet(state)
        self.assertEqual(slots[10].status, "WARNING")
        self.assertTrue(any("Slot 11" in v for v in violations))

    def test_mixbus_matrix_talkback_to_foh_violation(self):
        """Mixbus audit flags CRITICAL_VIOLATION if Channel 11 sends to a bus feeding Main Stereo."""
        state = copy.deepcopy(self.base_state)
        # Bus 9 feeds Main Stereo Bus
        state["/bus/09/mix/st"] = 1
        state["/bus/09/config/name"] = "Drum Subgroup"
        # Accidentally unmute Channel 11 to Bus 9
        state["/ch/11/mix/09/on"] = 1
        state["/ch/11/mix/09/level"] = 0.75

        report = MonitorMatrixInspector.audit_mixbus_matrix(state)
        self.assertFalse(report.talkback_isolation_verified)
        self.assertEqual(report.overall_status, "CRITICAL_VIOLATION")
        bus_9 = next(b for b in report.mixbuses if b.bus == 9)
        self.assertTrue(bus_9.talkback_leaked)

    def test_mixbus_matrix_talkback_to_stage_wedge_violation(self):
        """Mixbus audit flags violation if Channel 11 sends to a Stage Wedge floor monitor."""
        state = copy.deepcopy(self.base_state)
        state["/bus/01/config/name"] = "Wedge Pastor"
        state["/ch/11/mix/01/on"] = 1
        state["/ch/11/mix/01/level"] = 0.50

        report = MonitorMatrixInspector.audit_mixbus_matrix(state)
        self.assertFalse(report.talkback_isolation_verified)
        self.assertEqual(report.overall_status, "CRITICAL_VIOLATION")
        bus_1 = next(b for b in report.mixbuses if b.bus == 1)
        self.assertTrue(bus_1.talkback_leaked)

    def test_mixbus_matrix_stage_wedge_feedback_hazard(self):
        """Mixbus audit identifies high feedback risk when vocal mic send exceeds 0.80."""
        state = copy.deepcopy(self.base_state)
        state["/bus/02/config/name"] = "Wedge Vocal"
        state["/bus/02/mix/fader"] = 0.75
        state["/bus/02/mix/on"] = 1
        # Set Lead Vocal 1 send to +5 dB (0.88)
        state["/ch/03/mix/02/on"] = 1
        state["/ch/03/mix/02/level"] = 0.88

        report = MonitorMatrixInspector.audit_mixbus_matrix(state)
        self.assertTrue(len(report.feedback_hazards) >= 1)
        hazard = next(h for h in report.feedback_hazards if h["channel"] == 3 and h["bus"] == 2)
        self.assertEqual(hazard["risk_level"], "CRITICAL")

    def test_mixbus_matrix_post_fader_tap_warning(self):
        """Mixbus audit warns about Post-Fader taps on stage monitors."""
        state = copy.deepcopy(self.base_state)
        state["/bus/01/config/name"] = "Wedge Pastor"
        state["/ch/01/mix/01/tap"] = "Post"

        report = MonitorMatrixInspector.audit_mixbus_matrix(state)
        self.assertTrue(len(report.tap_inconsistencies) >= 1)
        inconsistency = next(t for t in report.tap_inconsistencies if t["channel"] == 1 and t["bus"] == 1)
        self.assertEqual(inconsistency["current_tap"], "Post")
        self.assertEqual(inconsistency["recommended_tap"], "Pre")

    def test_generate_safe_bus_balance_proposals(self):
        """Proposals safely mute Talkback leak and attenuate excessive wedge sends."""
        state = copy.deepcopy(self.base_state)
        state["/bus/01/config/name"] = "Wedge 1 Pastor"
        # Leak talkback
        state["/ch/11/mix/01/on"] = 1
        state["/ch/11/mix/01/level"] = 0.60
        # Excessive vocal send on Ch 1
        state["/ch/01/mix/01/on"] = 1
        state["/ch/01/mix/01/level"] = 0.86

        proposals = MonitorMatrixInspector.generate_safe_bus_balance_proposals(
            x32_state=state,
            bus_id=1,
            current_sha256="test-sha256",
        )

        self.assertEqual(len(proposals), 2)

        # Talkback proposal
        tb_prop = next(p for p in proposals if p.target_channel == 11)
        self.assertTrue(any(c["parameter"] == "/ch/11/mix/01/on" and c["to"] == 0 for c in tb_prop.changes))
        self.assertTrue(any(c["parameter"] == "/ch/11/mix/01/level" and c["to"] == 0.0 for c in tb_prop.changes))

        # Vocal headroom proposal
        voc_prop = next(p for p in proposals if p.target_channel == 1)
        self.assertTrue(any(c["parameter"] == "/ch/01/mix/01/level" and c["to"] == 0.75 for c in voc_prop.changes))

    def test_safety_policy_enforcement_on_mixbuses(self):
        """SafetyPolicy validates safe bus level adjustments and rejects invariant violations."""
        policy = SafetyPolicy()

        # 1. Valid proposal within limits (0.80 -> 0.75 = -0.05 delta <= 0.25)
        valid_prop = Proposal(
            proposal_id="p-valid-bus",
            target_channel=3,
            hypothesis="Attenuate vocal send",
            confidence=0.9,
            changes=[{"parameter": "/ch/03/mix/01/level", "from": 0.80, "to": 0.75}],
            expected_sha256="test-sha",
        )
        policy.validate_proposal(valid_prop) # Should not raise

        # 2. Reject excessive jump (> 0.25 delta)
        jump_prop = Proposal(
            proposal_id="p-jump-bus",
            target_channel=3,
            hypothesis="Excessive jump",
            confidence=0.9,
            changes=[{"parameter": "/ch/03/mix/01/level", "from": 0.20, "to": 0.75}],
            expected_sha256="test-sha",
        )
        with self.assertRaises(ProposalRejectedError):
            policy.validate_proposal(jump_prop)

        # 3. Reject unmuting Channel 11 (Talkback) into Stage Wedge Bus 1
        tb_leak_prop = Proposal(
            proposal_id="p-tb-leak",
            target_channel=11,
            hypothesis="Unmute talkback to wedge",
            confidence=0.5,
            changes=[{"parameter": "/ch/11/mix/01/on", "from": 0, "to": 1}],
            expected_sha256="test-sha",
        )
        with self.assertRaises(ProposalRejectedError):
            policy.validate_proposal(tb_leak_prop)

    def test_rest_api_monitors_endpoints(self):
        """FastAPI REST API correctly returns monitor matrix, P16 audit, and balance proposals."""
        client = self.client

        # GET /api/v1/monitors/iem-matrix
        res1 = client.get("/api/v1/monitors/iem-matrix")
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertIn("mixbuses", data1)
        self.assertEqual(len(data1["mixbuses"]), 16)
        self.assertIn("p16_slots", data1)
        self.assertEqual(len(data1["p16_slots"]), 16)
        self.assertIn("overall_status", data1)

        # GET /api/v1/monitors/p16-audit
        res2 = client.get("/api/v1/monitors/p16-audit")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertIn("slots", data2)
        self.assertEqual(len(data2["slots"]), 16)
        self.assertTrue(data2["p16_talkback_safe"])

        # POST /api/v1/monitors/propose-bus-balance
        res3 = client.post("/api/v1/monitors/propose-bus-balance", json={"bus_id": 1, "operator": "SoundEngineer"})
        self.assertEqual(res3.status_code, 200)
        data3 = res3.json()
        self.assertEqual(data3["status"], "PROPOSED")
        self.assertEqual(data3["bus_id"], 1)
        self.assertIn("proposals", data3)


if __name__ == "__main__":
    unittest.main()
