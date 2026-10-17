"""Cancellation and actual-value limits, using in-memory fixtures only."""
import copy
import hashlib
import json
import unittest
from contextlib import nullcontext
from unittest.mock import Mock

from packages.mock_x32.server import MockX32Server
from packages.safety_controller.modes import SafetyModeManager, OperatorMode, DisengageReason
from packages.safety_controller.transaction import Proposal, TransactionExecutor, ProposalRejectedError, TransactionFailedError
from packages.x32_osc_adapter.client import Snapshot, X32Client


class FixtureClient:
    def __init__(self):
        self.state = copy.deepcopy(MockX32Server().state)
        self.read_only_mode = True
        self.write_authorizer = None
        self.on_snapshot = None
        self.on_write = None
        self.writes = []

    def snapshot(self):
        params = copy.deepcopy(self.state)
        sha = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        return Snapshot(0, "fixture", {}, sha, 32, params)

    def take_full_snapshot(self, max_channels=32):
        snapshot = self.snapshot()
        if self.on_snapshot:
            callback, self.on_snapshot = self.on_snapshot, None
            callback()
        return snapshot

    def query(self, path):
        return [self.state[path]]

    def send_write(self, path, args):
        if self.read_only_mode:
            raise PermissionError("Fixture is read-only")
        with self.write_authorizer(path, args) if self.write_authorizer else nullcontext():
            self.writes.append((path, args[0]))
            self.state[path] = args[0]
            if self.on_write:
                callback, self.on_write = self.on_write, None
                callback()
        return args


class TestTransactionCancellation(unittest.TestCase):
    def setUp(self):
        self.client = FixtureClient()
        self.manager = SafetyModeManager()
        self.manager.set_mode(OperatorMode.ASSIST)
        self.executor = TransactionExecutor(self.client, mode_manager=self.manager)

    def proposal(self, changes):
        return Proposal("fixture", 1, "fixture", 1, changes, self.client.snapshot().sha256, True, "operator")

    def stop(self):
        self.client.read_only_mode = True
        self.manager.trigger_auto_disengage(DisengageReason.PANIC_BUTTON)

    def test_stop_during_snapshot_prevents_first_write(self):
        self.client.on_snapshot = self.stop
        proposal = self.proposal([{"parameter":"/ch/01/eq/1/g","from":0.5,"to":0.45}])
        with self.assertRaises(ProposalRejectedError): self.executor.execute(proposal,"operator")
        self.assertEqual(self.client.writes, [])
        self.assertTrue(self.client.read_only_mode)

    def test_stop_then_resume_does_not_reauthorize_old_transaction(self):
        def change_mode():
            self.stop()
            self.manager.set_mode(OperatorMode.ASSIST)
        self.client.on_snapshot = change_mode
        with self.assertRaises(ProposalRejectedError):
            self.executor.execute(self.proposal([{"parameter":"/ch/01/eq/1/g","from":0.5,"to":0.45}]),"operator")
        self.assertEqual(self.client.writes, [])

    def test_stop_after_write_restores_only_attempted_values(self):
        self.client.on_write = self.stop
        proposal = self.proposal([
            {"parameter":"/ch/01/eq/1/g","from":0.5,"to":0.45},
            {"parameter":"/ch/01/eq/2/g","from":0.5,"to":0.4},
        ])
        with self.assertRaises(TransactionFailedError): self.executor.execute(proposal,"operator")
        self.assertEqual(self.client.writes,[("/ch/01/eq/1/g",0.45),("/ch/01/eq/1/g",0.5)])
        self.assertEqual(self.executor.audit_log[-1]["status"],"ROLLED_BACK")
        self.assertTrue(self.client.read_only_mode)

    def test_packet_permission_rechecked_inside_socket_lock(self):
        client = X32Client(read_only_mode=False)
        client.sock = Mock()
        revision = self.manager.authorization_revision()
        client.write_authorizer = lambda path,args: self.manager.authorize_write(revision)
        self.manager.trigger_auto_disengage(DisengageReason.PANIC_BUTTON)
        with self.assertRaises(PermissionError): client.send_write('/ch/01/mix/on',[1])
        client.sock.sendto.assert_not_called()

    def test_actual_fader_delta_not_declared_delta_is_enforced(self):
        proposal = self.proposal([{"parameter":"/ch/01/mix/fader","from":0.10,"to":0.15}])
        with self.assertRaises(ProposalRejectedError): self.executor.execute(proposal,"operator")
        self.assertEqual(self.client.writes, [])

    def test_actual_eq_delta_is_enforced(self):
        self.client.state['/ch/01/eq/1/g'] = 0.9
        proposal = self.proposal([{"parameter":"/ch/01/eq/1/g","from":0.5,"to":0.45}])
        with self.assertRaises(ProposalRejectedError): self.executor.execute(proposal,"operator")
        self.assertEqual(self.client.writes, [])

    def test_first_packet_timeout_still_rolls_back(self):
        original = self.client.send_write
        calls = 0
        def timeout(path,args):
            nonlocal calls
            calls += 1
            result = original(path,args)
            if calls == 1: raise TimeoutError("packet reached fixture but echo lost")
            return result
        self.client.send_write = timeout
        with self.assertRaises(TransactionFailedError):
            self.executor.execute(self.proposal([{"parameter":"/ch/01/eq/1/g","from":0.5,"to":0.45}]),"operator")
        self.assertEqual(self.client.state['/ch/01/eq/1/g'],0.5)
        self.assertEqual(self.executor.audit_log[-1]['status'],'ROLLED_BACK')

    def test_stop_cancels_entire_batch_before_writes(self):
        proposals=[self.proposal([{"parameter":"/ch/01/mix/on","from":1,"to":0}])]
        self.client.on_snapshot=self.stop
        with self.assertRaises(ProposalRejectedError):self.executor.execute_batch(proposals,"operator","batch")
        self.assertEqual(self.client.writes,[])
