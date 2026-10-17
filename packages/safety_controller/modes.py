"""
Four-Tier Safety Engine Operating Modes & Auto-Disengage System (Master Plan 8.1 & 8.4)
========================================================================================
Implements:
1. Operator Modes:
   - OBSERVE: Read-only mode (default during church service). No OSC mutations allowed.
   - ASSIST: Read + write only for explicitly approved proposals through SafetyGate.
   - LIMITED_AUTO: Whitelisted bounded autonomous adjustments (Dugan Automix, Silence Hold, Expander).
   - ADMIN_MAINTENANCE: Privileged admin mode for system checks & maintenance with separate authorization.
     (Note: Hard Invariant DL16 #11 Band Talkback remains strictly enforced even in ADMIN mode!)

2. Auto-Disengage & Panic Freeze Trigger (Section 8.4):
   - Automatically drops mode back to OBSERVE and locks all writes upon:
     * OSC disconnect / heartbeat timeout / stale meters
     * Buffer overrun or clock drift
     * Excessive clipping (> 5 consecutive frames)
     * External console manipulation (snapshot SHA-256 divergence)
     * Scene recall detected
     * Feedback risk spike
     * Operator clicks STOP AUTO
"""
from __future__ import annotations
import enum
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Callable

from .routing import InvariantViolationError


class OperatorMode(str, enum.Enum):
    OBSERVE = "OBSERVE" # Default: Read-only, no mutations allowed
    ASSIST = "ASSIST" # Read + operator-approved proposals
    LIMITED_AUTO = "LIMITED_AUTO" # Bounded autonomous adjustments (Automix, Expander)
    ADMIN_MAINTENANCE = "ADMIN_MAINTENANCE" # High-privilege maintenance mode


class DisengageReason(str, enum.Enum):
    NONE = "NONE"
    PANIC_BUTTON = "PANIC_BUTTON"
    HEARTBEAT_LOST = "HEARTBEAT_LOST"
    STALE_METERS = "STALE_METERS"
    EXTERNAL_EDIT_DETECTED = "EXTERNAL_EDIT_DETECTED"
    EXCESSIVE_CLIPPING = "EXCESSIVE_CLIPPING"
    FEEDBACK_SPIKE = "FEEDBACK_SPIKE"
    AUDIO_FAULT = "AUDIO_FAULT"
    SCENE_RECALL = "SCENE_RECALL"


@dataclass
class SafetyModeState:
    current_mode: OperatorMode = OperatorMode.OBSERVE
    previous_mode: OperatorMode = OperatorMode.OBSERVE
    is_disengaged: bool = False
    disengage_reason: DisengageReason = DisengageReason.NONE
    disengage_detail: str = ""
    disengaged_at: Optional[float] = None
    last_mode_change_at: float = field(default_factory=time.time)
    changed_by: str = "System"
    consecutive_clips: int = 0
    last_telemetry_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_mode": self.current_mode.value,
            "previous_mode": self.previous_mode.value,
            "is_disengaged": self.is_disengaged,
            "disengage_reason": self.disengage_reason.value,
            "disengage_detail": self.disengage_detail,
            "disengaged_at": self.disengaged_at,
            "last_mode_change_at": self.last_mode_change_at,
            "changed_by": self.changed_by,
            "consecutive_clips": self.consecutive_clips,
            "read_only": self.current_mode == OperatorMode.OBSERVE or self.is_disengaged,
        }


class SafetyModeManager:
    """
    State machine controlling operator permissions and panic auto-disengagement.
    """
    ADMIN_DEFAULT_PIN = "7777" # Default Sunday admin security pin

    def __init__(self, admin_pin: str = ADMIN_DEFAULT_PIN):
        self.admin_pin = admin_pin
        self.state = SafetyModeState()
        self._listeners: List[Callable[[SafetyModeState], None]] = []
        self._authorization_lock = threading.RLock()
        self._authorization_revision = 0

    def authorization_revision(self) -> int:
        with self._authorization_lock:
            if self.is_read_only():
                raise PermissionError("Giao dịch bị khóa: hệ thống đang chỉ đọc.")
            return self._authorization_revision

    @contextmanager
    def authorize_write(self, revision: int):
        """Serialize the packet send with STOP/mode changes, never with readback."""
        with self._authorization_lock:
            if revision != self._authorization_revision or self.is_read_only():
                raise PermissionError("Giao dịch đã bị hủy bởi STOP hoặc thay đổi chế độ.")
            yield

    def add_listener(self, callback: Callable[[SafetyModeState], None]) -> None:
        """Register a callback invoked whenever the safety mode changes or disengages."""
        self._listeners.append(callback)

    def _notify(self) -> None:
        for listener in self._listeners:
            try:
                listener(self.state)
            except Exception:
                pass

    def get_mode(self) -> OperatorMode:
        if self.state.is_disengaged:
            return OperatorMode.OBSERVE
        return self.state.current_mode

    def is_read_only(self) -> bool:
        """Returns True if the system is strictly read-only."""
        return self.get_mode() == OperatorMode.OBSERVE or self.state.is_disengaged

    def set_mode(
        self,
        new_mode: OperatorMode,
        operator: str = "Operator",
        admin_pin: Optional[str] = None,
    ) -> SafetyModeState:
        """
        Transition between safety engine modes.
        Switching to ADMIN_MAINTENANCE requires admin_pin verification.
        """
        if new_mode == OperatorMode.ADMIN_MAINTENANCE:
            if admin_pin != self.admin_pin:
                raise PermissionError("ADMIN_PIN_INVALID: Switching to ADMIN_MAINTENANCE requires valid admin PIN.")

        # If previously disengaged and operator explicitly selects a new mode, clear disengaged flag
        with self._authorization_lock:
            self._authorization_revision += 1
            self.state.previous_mode = self.state.current_mode
            self.state.current_mode = new_mode
            self.state.is_disengaged = False
            self.state.disengage_reason = DisengageReason.NONE
            self.state.disengage_detail = ""
            self.state.disengaged_at = None
            self.state.last_mode_change_at = time.time()
            self.state.changed_by = operator

        self._notify()
        return self.state

    def trigger_auto_disengage(
        self,
        reason: DisengageReason,
        detail: str = "",
        operator: str = "SafetyWatchdog",
    ) -> SafetyModeState:
        """
        Instantly drop to OBSERVE mode and lock all OSC writes.
        """
        with self._authorization_lock:
            self._authorization_revision += 1
            self.state.previous_mode = self.state.current_mode
            self.state.current_mode = OperatorMode.OBSERVE
            self.state.is_disengaged = True
            self.state.disengage_reason = reason
            self.state.disengage_detail = detail
            self.state.disengaged_at = time.time()
            self.state.changed_by = operator

        self._notify()
        return self.state

    def record_telemetry_heartbeat(self, clip_detected: bool = False, feedback_spike: bool = False) -> None:
        """
        Telemetry watchdog called on every audio block / meter update.
        Monitors health invariants to trigger auto-disengage if necessary.
        """
        now = time.time()
        self.state.last_telemetry_timestamp = now

        # 1. Clipping monitor
        if clip_detected:
            self.state.consecutive_clips += 1
            if self.state.consecutive_clips >= 6:
                if self.state.current_mode in (OperatorMode.ASSIST, OperatorMode.LIMITED_AUTO):
                    self.trigger_auto_disengage(
                        reason=DisengageReason.EXCESSIVE_CLIPPING,
                        detail=f"Phát hiện vỡ tiếng liên tục ({self.state.consecutive_clips} khung tín hiệu). Đã khóa an toàn.",
                    )
        else:
            self.state.consecutive_clips = 0

        # 2. Feedback spike monitor
        if feedback_spike:
            if self.state.current_mode == OperatorMode.LIMITED_AUTO:
                self.trigger_auto_disengage(
                    reason=DisengageReason.FEEDBACK_SPIKE,
                    detail="Phát hiện tần số hú tăng đột biến. Tự động ngắt LIMITED_AUTO.",
                )

    def check_telemetry_liveness(self, timeout_sec: float = 3.0) -> bool:
        """
        Verifies telemetry is fresh. If stale, disengages to OBSERVE.
        """
        elapsed = time.time() - self.state.last_telemetry_timestamp
        if elapsed > timeout_sec:
            if self.state.current_mode != OperatorMode.OBSERVE and not self.state.is_disengaged:
                self.trigger_auto_disengage(
                    reason=DisengageReason.STALE_METERS,
                    detail=f"Mất tín hiệu telemetry đo đạc ({elapsed:.1f}s không có dữ liệu). Khóa an toàn.",
                )
            return False
        return True
