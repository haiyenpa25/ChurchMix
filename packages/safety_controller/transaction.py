"""
Transaction Executor & Safety Gate for X32 Sound Engineer.
Implements:
- Whitelist and Denylist safety policies
- Invariant & optimistic locking revision checks
- Operator explicit approval verification
- Rate-limited parameter writes
- Readback verification & automatic rollback upon any mismatch
- Tamper-evident Audit Logging
"""

from __future__ import annotations
import time
import math
import threading
from dataclasses import dataclass, field, replace
from contextlib import nullcontext
from weakref import WeakKeyDictionary
from typing import Dict, Any, List, Optional, Tuple

from packages.x32_osc_adapter.client import X32Client, Snapshot
from .routing import RoutingGraph, InvariantViolationError, get_talkback_channel

WRITE_PACING_S = 0.02  # 20ms minimum between OSC writes (AGENTS.md rule #11)

# One lock per X32Client: the read-only flag lives on the shared client, so two
# transactions (or a transaction and another writer) must never overlap.
_client_locks = WeakKeyDictionary()
_client_locks_guard = threading.Lock()


def _transaction_lock_for(client: X32Client) -> threading.Lock:
    with _client_locks_guard:
        return _client_locks.setdefault(client, threading.Lock())


def _values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return math.isclose(float(actual), float(expected), abs_tol=0.01)
        except (TypeError, ValueError):
            return False
    return actual == expected
from .modes import SafetyModeManager, OperatorMode, DisengageReason


class ProposalRejectedError(PermissionError):
    """Raised when a proposal violates safety policy or lacks required approval."""
    pass


class TransactionFailedError(RuntimeError):
    """Raised when a transaction fails execution or verification, triggering rollback."""
    pass


@dataclass
class Proposal:
    proposal_id: str
    target_channel: int
    hypothesis: str
    confidence: float
    changes: List[Dict[str, Any]] # [{"parameter": "/ch/01/eq/1/g", "from": 0.5, "to": 0.45}]
    expected_sha256: str
    operator_approved: bool = False
    approved_by: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    # Set ONLY for bus-master proposals (e.g. livestream loudness); target_channel is then ignored.
    target_bus: Optional[int] = None

    def approve(self, operator_id: str):
        self.operator_approved = True
        self.approved_by = operator_id


def _configured_bus_faders() -> set:
    """Bus masters whose fader may be adjusted: only the livestream bus from
    configs/safety-defaults.yaml (autopilot.livestream_bus). Empty if not configured."""
    try:
        import os
        import yaml
        path = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "safety-defaults.yaml")
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        bus = (cfg.get("autopilot") or {}).get("livestream_bus")
        return {int(bus)} if bus is not None and 1 <= int(bus) <= 16 else set()
    except Exception:
        return set()


class SafetyPolicy:
    def __init__(self, max_fader_delta: float = 0.1, max_eq_gain_delta: float = 0.2,
                 allowed_bus_faders: Optional[set] = None, max_bus_fader_delta: float = 0.05):
        self.max_fader_delta = max_fader_delta
        self.max_eq_gain_delta = max_eq_gain_delta
        self.allowed_bus_faders = set(allowed_bus_faders) if allowed_bus_faders is not None else _configured_bus_faders()
        self.max_bus_fader_delta = max_bus_fader_delta
        self.denied_prefixes = [
            "/config/routing",
            "/outputs/p16",
            "/main/st",
            "/-action",
            "/-show",
        ]

    def _validate_bus_proposal(self, proposal: Proposal) -> None:
        """Bus-master fader only, on an explicitly allowed (livestream) bus, small steps."""
        bus = proposal.target_bus
        if type(bus) is not int or bus not in self.allowed_bus_faders:
            raise ProposalRejectedError(
                f"SAFETY DENIAL: Bus {bus} is not an allowed bus for fader adjustments (allowed: {sorted(self.allowed_bus_faders)})."
            )
        path = f"/bus/{bus:02d}/mix/fader"
        for change in proposal.changes:
            if change["parameter"] != path:
                raise ProposalRejectedError(f"SAFETY DENIAL: Bus proposal may only change '{path}', not '{change['parameter']}'.")
            for value in (change["from"], change["to"]):
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                    raise ProposalRejectedError(f"SAFETY DENIAL: '{path}' requires a finite fader value 0..1.")
            if abs(change["to"] - change["from"]) > self.max_bus_fader_delta + 1e-9:
                raise ProposalRejectedError(
                    f"SAFETY LIMIT: Bus fader delta {abs(change['to'] - change['from']):.3f} exceeds {self.max_bus_fader_delta}."
                )

    def validate_proposal(self, proposal: Proposal) -> None:
        """Validate all proposed changes against safety rules."""
        if proposal.target_bus is not None:
            self._validate_bus_proposal(proposal)
            return
        ch = proposal.target_channel
        if type(ch) is not int or not 1 <= ch <= 32:
            raise ProposalRejectedError("SAFETY DENIAL: Target channel must be an integer between 1 and 32.")
        ch_str = f"/ch/{ch:02d}"
        eq_paths = {f"{ch_str}/eq/on"} | {
            f"{ch_str}/eq/{band}/{parameter}"
            for band in range(1, 5) for parameter in ("f", "g", "q")
        }
        automix_paths = {f"{ch_str}/automix/{parameter}" for parameter in ("group", "weight")}
        gate_paths = {f"{ch_str}/gate/{parameter}" for parameter in (
            "on", "mode", "thr", "range", "filter/on", "filter/f",
        )}

        for change in proposal.changes:
            param = change["parameter"]
            to_val = change["to"]
            from_val = change["from"]

            # 1. Deny-list check
            for denied in self.denied_prefixes:
                if param.startswith(denied):
                    raise ProposalRejectedError(
                        f"SAFETY DENIAL: Parameter '{param}' belongs to strictly protected system configuration."
                    )

            # 2. Channel isolation check (proposal can only modify its target channel)
            if not param.startswith(ch_str):
                raise ProposalRejectedError(
                    f"SAFETY DENIAL: Proposal targets Channel {ch}, but attempts to mutate '{param}'."
                )

            # 3. Whitelist check for allowed channel parameters:
            # EQ, HPF, limited fader, channel mute (mix/on), digital trim (preamp/trim), automix, gate/expander, or mixbus sends
            is_eq = param in eq_paths
            is_hpf = param in (f"{ch_str}/preamp/hpon", f"{ch_str}/preamp/hpf")
            is_fader = param == f"{ch_str}/mix/fader"
            is_mute = param == f"{ch_str}/mix/on"
            is_trim = param == f"{ch_str}/preamp/trim"
            is_automix = param in automix_paths
            is_gate = param in gate_paths

            # Mixbus sends: /ch/{ch}/mix/{bus}/level or /ch/{ch}/mix/{bus}/on
            is_bus_send = False
            bus_num = None
            if param.startswith(f"{ch_str}/mix/"):
                parts = param.split("/")
                if len(parts) == 6 and parts[3] == "mix" and parts[5] in ("level", "on"):
                    try:
                        bus_num = int(parts[4])
                        if 1 <= bus_num <= 16 and parts[4] == f"{bus_num:02d}":
                            is_bus_send = True
                    except ValueError:
                        pass

            # Hard Invariant: the Band Talkback channel must NEVER be in Automix or Gate
            tb_ch = get_talkback_channel()
            if ch == tb_ch and is_automix:
                raise ProposalRejectedError(
                    f"SAFETY INVARIANT DENIAL: Channel {tb_ch} (Band Talkback) must NEVER be assigned to Automix groups."
                )

            if ch == tb_ch and is_gate:
                raise ProposalRejectedError(
                    f"SAFETY INVARIANT DENIAL: Channel {tb_ch} (Band Talkback) must NEVER have gate/expander modified for FOH."
                )

            # Hard Invariant: Channel 11 must NEVER send signal to Stage Wedges (Bus 1-4) or FX
            if ch == tb_ch and is_bus_send and bus_num is not None:
                if (1 <= bus_num <= 4 or bus_num >= 13) and (to_val > 0.0 or (param.endswith("/on") and to_val == 1)):
                    raise ProposalRejectedError(
                        f"SAFETY INVARIANT DENIAL: Channel {tb_ch} (Band Talkback) must NEVER send signal to Stage Wedge/FX Bus {bus_num:02d}."
                    )

            if not (is_eq or is_hpf or is_fader or is_mute or is_trim or is_automix or is_gate or is_bus_send):
                raise ProposalRejectedError(
                    f"SAFETY DENIAL: Parameter '{param}' is not in the allowed Channel Tuning whitelist."
                )

            # Non-finite or non-numeric values can bypass delta comparisons.
            for value in (from_val, to_val):
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ProposalRejectedError(
                        f"SAFETY DENIAL: Parameter '{param}' requires finite numeric values."
                    )

            # 4. Slew-rate / Jump limits
            if is_fader and isinstance(to_val, (int, float)) and isinstance(from_val, (int, float)):
                if abs(to_val - from_val) > self.max_fader_delta:
                    raise ProposalRejectedError(
                        f"SAFETY LIMIT: Fader delta {abs(to_val - from_val):.3f} exceeds maximum safe limit {self.max_fader_delta}."
                    )

            is_eq_gain = param.startswith(f"{ch_str}/eq/") and param.endswith("/g")
            if is_eq_gain and isinstance(to_val, (int, float)) and isinstance(from_val, (int, float)):
                if abs(to_val - from_val) > self.max_eq_gain_delta + 1e-9:
                    raise ProposalRejectedError(
                        f"SAFETY LIMIT: EQ gain delta {abs(to_val - from_val):.3f} exceeds maximum safe limit "
                        f"{self.max_eq_gain_delta} (~{self.max_eq_gain_delta * 30:.1f} dB)."
                    )

            if is_bus_send and param.endswith("/level") and isinstance(to_val, (int, float)) and isinstance(from_val, (int, float)):
                if abs(to_val - from_val) > 0.25: # Max ~6 dB jump
                    raise ProposalRejectedError(
                        f"SAFETY LIMIT: Mix bus send level delta {abs(to_val - from_val):.3f} exceeds maximum safe limit 0.25 (~6 dB)."
                    )

            if is_trim and isinstance(to_val, (int, float)) and isinstance(from_val, (int, float)):
                if abs(to_val - from_val) > 0.20:
                    raise ProposalRejectedError(
                        f"SAFETY LIMIT: Trim delta {abs(to_val - from_val):.3f} exceeds maximum safe limit 0.20 (~7.2 dB)."
                    )

            if is_gate and param == f"{ch_str}/gate/range" and isinstance(to_val, (int, float)):
                if to_val > 0.40: # Max 24 dB attenuation range
                    raise ProposalRejectedError(
                        f"SAFETY LIMIT: Expander attenuation range {to_val:.3f} exceeds maximum safe limit 0.40 (~24 dB)."
                    )



class TransactionExecutor:
    def __init__(
        self,
        client: X32Client,
        policy: SafetyPolicy | None = None,
        mode_manager: SafetyModeManager | None = None,
    ):
        self.client = client
        self.policy = policy or SafetyPolicy()
        self.mode_manager = mode_manager
        self.audit_log: List[Dict[str, Any]] = []

    def _authorization_revision(self):
        try:
            return self.mode_manager.authorization_revision() if self.mode_manager else None
        except PermissionError as exc:
            raise ProposalRejectedError(str(exc)) from exc

    def _assert_active(self, revision):
        if self.mode_manager:
            try:
                with self.mode_manager.authorize_write(revision):
                    pass
            except PermissionError as exc:
                raise ProposalRejectedError(str(exc)) from exc

    def execute(self, proposal: Proposal, operator_id: str) -> Dict[str, Any]:
        """
        Execute a proposal through the 6-stage Safety Gate:
        0. Mode authorization check (Must not be in OBSERVE/disengaged)
        1. Authorization check
        2. Policy whitelist validation
        3. Optimistic revision lock check
        4. Invariant check on routing graph
        5. Write with rate-limiting
        6. Readback verify + automatic rollback on failure
        """
        # Stage 0: Operator Mode Check
        if self.mode_manager:
            current_mode = self.mode_manager.get_mode()
            if self.mode_manager.is_read_only():
                raise ProposalRejectedError(
                    f"SAFETY DENIAL: Cannot apply proposal in {current_mode.value} mode (Read-Only). Switch to ASSIST or LIMITED_AUTO mode."
                )

        # Stage 1: Explicit operator approval
        if not proposal.operator_approved or not proposal.approved_by:
            raise ProposalRejectedError(
                f"REJECTED: Proposal '{proposal.proposal_id}' has not been approved by an operator."
            )

        # Stage 2: Policy validation
        self.policy.validate_proposal(proposal)
        if len({c["parameter"] for c in proposal.changes}) != len(proposal.changes):
            raise ProposalRejectedError("A parameter may only appear once in a transaction.")
        revision = self._authorization_revision()

        # Stages 3-6 run under a per-client lock so the read-only flag and the
        # snapshot/write/readback sequence can never interleave with another writer.
        with _transaction_lock_for(self.client):
            return self._execute_locked(proposal, operator_id, revision)

    def execute_batch(self, proposals: List[Proposal], operator_id: str, batch_id: str, hypothesis: str = "") -> Dict[str, Any]:
        """
        Apply several single-channel proposals as ONE transaction (e.g. a service
        segment switching mutes on many channels). Each proposal passes the same
        stage 0-2 checks as execute(); writes then run in the given order against a
        single snapshot, with readback per write and rollback of ALL writes on any
        failure or invariant violation.
        """
        if not proposals:
            raise ProposalRejectedError("REJECTED: Empty batch.")

        if self.mode_manager and self.mode_manager.is_read_only():
            raise ProposalRejectedError(
                f"SAFETY DENIAL: Cannot apply proposal in {self.mode_manager.get_mode().value} mode (Read-Only). Switch to ASSIST or LIMITED_AUTO mode."
            )
        revision = self._authorization_revision()

        expected = {p.expected_sha256 for p in proposals}
        if len(expected) != 1:
            raise ProposalRejectedError("REJECTED: Batch proposals were prepared against different mixer snapshots.")

        seen_params = set()
        changes: List[Dict[str, Any]] = []
        for p in proposals:
            if not p.operator_approved or not p.approved_by:
                raise ProposalRejectedError(f"REJECTED: Proposal '{p.proposal_id}' has not been approved by an operator.")
            self.policy.validate_proposal(p)
            for change in p.changes:
                if change["parameter"] in seen_params:
                    raise ProposalRejectedError(f"REJECTED: Parameter '{change['parameter']}' appears twice in one batch.")
                seen_params.add(change["parameter"])
                changes.append(change)

        merged = Proposal(
            proposal_id=batch_id,
            target_channel=0,
            hypothesis=hypothesis or f"Batch of {len(proposals)} proposals",
            confidence=1.0,
            changes=changes,
            expected_sha256=expected.pop(),
            operator_approved=True,
            approved_by=operator_id,
        )
        with _transaction_lock_for(self.client):
            return self._execute_locked(merged, operator_id, revision)

    def _execute_locked(self, proposal: Proposal, operator_id: str, revision=None) -> Dict[str, Any]:
        self._assert_active(revision)
        # Stage 3: Snapshot & Optimistic lock check
        current_snapshot = self.client.take_full_snapshot(max_channels=32)
        if current_snapshot.sha256 != proposal.expected_sha256:
            raise ProposalRejectedError(
                f"REJECTED: Mixer state has changed externally since proposal was prepared! "
                f"Expected SHA: {proposal.expected_sha256[:8]}, Current SHA: {current_snapshot.sha256[:8]}."
            )

        # Stage 4: Invariant check (Routing & DL16 Talkback isolation).
        # require_complete: a snapshot missing any routing path freezes writes.
        routing_graph = RoutingGraph(current_snapshot.parameters, require_complete=True)
        ok, msg = routing_graph.verify_talkback_invariant()
        if not ok:
            raise InvariantViolationError(f"HARD INVARIANT ABORT: {msg}")

        # Capture original values for rollback. Parameters outside the snapshot
        # (trim, gate, automix, sends...) are read directly; if one cannot be read,
        # the transaction is refused because it could not be rolled back.
        original_values: Dict[str, Any] = {}
        for change in proposal.changes:
            param = change["parameter"]
            if param in current_snapshot.parameters:
                original_values[param] = current_snapshot.parameters[param]
                continue
            try:
                original_values[param] = self.client.query(param)[0]
            except Exception as exc:
                raise ProposalRejectedError(
                    f"REJECTED: Cannot read current value of '{param}' ({exc}); rollback would be impossible."
                )

        # Validate slew limits against observed values, never an estimated `from`.
        for change in proposal.changes:
            actual_change = {**change, "from": original_values[change["parameter"]]}
            kind, number = change["parameter"].split("/")[1:3]
            if kind == "bus":
                self.policy.validate_proposal(replace(proposal, target_bus=int(number), changes=[actual_change]))
            else:
                self.policy.validate_proposal(replace(proposal, target_bus=None, target_channel=int(number), changes=[actual_change]))
        self._assert_active(revision)

        # Stage 5 & 6: Transaction execution with rollback support
        executed_writes: List[Tuple[str, Any]] = []
        previous_authorizer = getattr(self.client, "write_authorizer", None)
        allowed_writes = {c["parameter"]: c["to"] for c in proposal.changes}
        def permit(path, args):
            if path not in allowed_writes or len(args) != 1 or args[0] != allowed_writes[path]:
                raise ProposalRejectedError("Parameter outside approved transaction.")
            return self.mode_manager.authorize_write(revision) if self.mode_manager else nullcontext()
        self.client.write_authorizer = permit

        # Temporarily enable writes for this verified transaction
        self.client.read_only_mode = False
        try:
            for change in proposal.changes:
                self._assert_active(revision)
                param = change["parameter"]
                to_val = change["to"]

                # Send write
                executed_writes.append((param, to_val))
                try:
                    self.client.send_write(param, [to_val])
                except PermissionError:
                    # A permission denial happens before packet dispatch.
                    executed_writes.pop()
                    raise
                time.sleep(WRITE_PACING_S)

                # Readback verification
                echo_val = self.client.query(param)[0]
                if not _values_match(to_val, echo_val):
                    raise TransactionFailedError(
                        f"Readback mismatch on '{param}': expected {to_val}, got {echo_val}"
                    )

            # Post-execution Invariant check
            self._assert_active(revision)
            post_snapshot = self.client.take_full_snapshot(max_channels=32)
            post_routing = RoutingGraph(post_snapshot.parameters, require_complete=True)
            post_ok, post_msg = post_routing.verify_talkback_invariant()
            if not post_ok:
                raise InvariantViolationError(f"Post-apply invariant failure: {post_msg}")

            # Commit audit event
            audit_entry = {
                "timestamp": time.time(),
                "proposal_id": proposal.proposal_id,
                "operator": operator_id,
                "status": "COMMITTED",
                "changes_applied": proposal.changes,
                "before_sha256": current_snapshot.sha256,
                "after_sha256": post_snapshot.sha256,
            }
            self.audit_log.append(audit_entry)

            return {
                "status": "SUCCESS",
                "proposal_id": proposal.proposal_id,
                "sha256": post_snapshot.sha256,
                "audit": audit_entry,
            }

        except Exception as exc:
            # ROLLBACK IMMEDIATELY, in reverse order, paced and verified by readback
            # Cancellation permits only restoration to this approved snapshot;
            # no new proposed values can pass this rollback guard.
            def restore_only(path, args):
                if path not in original_values or len(args) != 1 or not _values_match(original_values[path], args[0]):
                    raise ProposalRejectedError("Rollback may only restore the pre-transaction snapshot.")
                return nullcontext()
            self.client.write_authorizer = restore_only
            self.client.read_only_mode = False
            rollback_errors = self._rollback(original_values, executed_writes) if executed_writes else []

            audit_entry = {
                "timestamp": time.time(),
                "proposal_id": proposal.proposal_id,
                "operator": operator_id,
                "status": "ROLLED_BACK" if not rollback_errors else "ROLLBACK_FAILED",
                "reason": str(exc),
                "rollback_errors": rollback_errors,
            }
            self.audit_log.append(audit_entry)

            # If mode manager is active, trigger auto-disengage back to OBSERVE on execution failure
            if self.mode_manager:
                self.mode_manager.trigger_auto_disengage(
                    reason=DisengageReason.AUDIO_FAULT,
                    detail=f"Lỗi thực thi giao dịch '{proposal.proposal_id}'. Đã tự động ngắt về OBSERVE.",
                    operator=operator_id,
                )

            raise TransactionFailedError(
                f"Transaction aborted and rolled back due to error: {exc}. "
                f"Rollback status: {'Clean' if not rollback_errors else rollback_errors}"
            )
        finally:
            self.client.write_authorizer = previous_authorizer
            # Always restore strict read-only mode after transaction
            self.client.read_only_mode = self.mode_manager.is_read_only() if self.mode_manager else True

    def _rollback(self, original_values: Dict[str, Any], executed_writes: List[Tuple[str, Any]]) -> List[str]:
        """
        Restore every parameter that was (or may have been) written.
        The write that raised is included: it may have reached the mixer.
        Returns a list of errors; empty means every value was restored and verified.
        """
        errors: List[str] = []
        attempted = [p for p, _ in executed_writes]
        for param in reversed(attempted):
            orig_val = original_values.get(param)
            if orig_val is None:
                errors.append(f"No original value recorded for {param}; manual check required.")
                continue
            try:
                self.client.send_write(param, [orig_val])
                time.sleep(WRITE_PACING_S)
                echo_val = self.client.query(param)[0]
                if not _values_match(orig_val, echo_val):
                    errors.append(f"Rollback readback mismatch on {param}: expected {orig_val}, got {echo_val}")
            except Exception as rb_exc:
                errors.append(f"Failed to rollback {param}: {rb_exc}")
        return errors
