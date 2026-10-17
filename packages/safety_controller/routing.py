"""
Routing Graph & Hard Invariant Checker for Behringer X32 and DL16.
Specifically enforces:
HARD INVARIANT: DL16 physical input 11 (Band Talkback) must route SOLELY
to the P16 Personal Monitoring system, and NEVER bleed into Main FOH or Matrix.

The X32 channel that carries DL16 input 11 is NOT assumed to be channel 11
(AGENTS.md rule #6). It is read from `configs/safety-defaults.yaml`
(`talkback_protection.x32_channel`) and cross-checked against channel names
found in the snapshot. Any ambiguity fails closed.
"""

from __future__ import annotations
import os
from functools import lru_cache
from typing import Dict, Any, List, Optional, Tuple


class InvariantViolationError(Exception):
    """Raised when an action or configuration violates a critical hardware/acoustic invariant."""
    pass


DEFAULT_TALKBACK_CHANNEL = 11
NUM_MIX_BUSES = 16
NUM_MATRICES = 6
NUM_P16_SLOTS = 16
TALKBACK_NAME_HINTS = ("talkback", "talk back", "talk-back")

_SAFETY_DEFAULTS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "configs", "safety-defaults.yaml"
)


@lru_cache(maxsize=1)
def get_talkback_channel() -> int:
    """
    Resolve the X32 channel that carries DL16 input 11 (Band Talkback).
    Source of truth: configs/safety-defaults.yaml -> talkback_protection.x32_channel.
    Falls back to channel 11 only when the config file is absent.
    """
    try:
        import yaml
        with open(_SAFETY_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, ImportError):
        return DEFAULT_TALKBACK_CHANNEL

    value = (cfg.get("talkback_protection") or {}).get("x32_channel", DEFAULT_TALKBACK_CHANNEL)
    ch = int(value)
    if not 1 <= ch <= 32:
        raise InvariantViolationError(
            f"Invalid talkback_protection.x32_channel={value!r} in safety-defaults.yaml (must be 1-32)."
        )
    return ch


def talkback_routing_paths(talkback_channel: int) -> List[str]:
    """
    Every OSC parameter the invariant checker needs to see in a snapshot to
    prove the talkback channel has no path to Main/Mono/Matrix FOH.
    """
    ch_str = f"/ch/{talkback_channel:02d}"
    paths = [f"{ch_str}/mix/st", f"{ch_str}/mix/mono"]
    for bus in range(1, NUM_MIX_BUSES + 1):
        paths.append(f"{ch_str}/mix/{bus:02d}/on")
        paths.append(f"{ch_str}/mix/{bus:02d}/level")
        b_str = f"/bus/{bus:02d}"
        paths.append(f"{b_str}/mix/st")
        paths.append(f"{b_str}/mix/mono")
        for mtx in range(1, NUM_MATRICES + 1):
            paths.append(f"{b_str}/mix/{mtx:02d}/on")
    for p in range(1, NUM_P16_SLOTS + 1):
        paths.append(f"/outputs/p16/{p:02d}/src")
    return paths


def _is_on(value: Any) -> bool:
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return False


class RoutingGraph:
    def __init__(
        self,
        parameters: Dict[str, Any],
        talkback_channel: Optional[int] = None,
        require_complete: bool = False,
    ):
        """
        parameters: flat OSC state (snapshot.parameters or imported scene).
        talkback_channel: override for the protected channel (defaults to config).
        require_complete: when True (live Safety Gate), any routing parameter
            missing from `parameters` is treated as an invariant failure instead
            of being assumed off.
        """
        self.params = parameters
        self.require_complete = require_complete
        self._dl16_in_11_channel: int = talkback_channel or get_talkback_channel()

    @property
    def dl16_talkback_channel(self) -> int:
        return self._dl16_in_11_channel

    def missing_routing_params(self) -> List[str]:
        return [p for p in talkback_routing_paths(self.dl16_talkback_channel) if p not in self.params]

    def _channel_name(self, ch: int) -> str:
        name = self.params.get(f"/ch/{ch:02d}/config/name")
        return str(name).strip().lower() if name is not None else ""

    def check_talkback_patch_consistency(self) -> Tuple[bool, str]:
        """
        Cross-check the configured talkback channel against channel names.
        Fails closed if another channel is named like a talkback while the
        configured one is not, i.e. the console patch probably moved.
        """
        tb_ch = self.dl16_talkback_channel
        tb_name = self._channel_name(tb_ch)
        if any(h in tb_name for h in TALKBACK_NAME_HINTS):
            return True, f"Channel {tb_ch} name '{tb_name}' matches talkback."

        others = [
            ch for ch in range(1, 33)
            if ch != tb_ch and any(h in self._channel_name(ch) for h in TALKBACK_NAME_HINTS)
        ]
        if others:
            return False, (
                f"PATCH MISMATCH: configured talkback channel {tb_ch} is named '{tb_name}', "
                f"but channel(s) {others} are named like a talkback. Verify the DL16 -> X32 patch "
                f"and update talkback_protection.x32_channel before any write."
            )
        return True, f"Channel {tb_ch} has no talkback name; no conflicting channel found."

    def is_channel_routed_to_foh(self, ch: int) -> Tuple[bool, List[str]]:
        """
        Check if a channel has any signal path leading to Main LR, Mono/Center or a Matrix.
        A send counts when it is switched on, regardless of its level, because a
        level of -inf can be raised from the console surface at any time.
        Returns: (is_routed_to_foh, path_trace)
        """
        ch_str = f"/ch/{ch:02d}"
        paths: List[str] = []

        # 1. Direct sends to Main Stereo and Mono/Center
        if _is_on(self.params.get(f"{ch_str}/mix/st", 0)):
            paths.append(f"{ch_str} -> Main Stereo Bus (/mix/st = 1)")
        if _is_on(self.params.get(f"{ch_str}/mix/mono", 0)):
            paths.append(f"{ch_str} -> Mono/Center Bus (/mix/mono = 1)")

        # 2. Sends through mix buses that feed Main, Mono or any Matrix
        for bus in range(1, NUM_MIX_BUSES + 1):
            if not _is_on(self.params.get(f"{ch_str}/mix/{bus:02d}/on", 0)):
                continue
            level = self.params.get(f"{ch_str}/mix/{bus:02d}/level", 0.0)
            b_str = f"/bus/{bus:02d}"
            via = f"{ch_str} -> Bus {bus:02d} (send level {level})"
            if _is_on(self.params.get(f"{b_str}/mix/st", 0)):
                paths.append(f"{via} -> Main Stereo Bus")
            if _is_on(self.params.get(f"{b_str}/mix/mono", 0)):
                paths.append(f"{via} -> Mono/Center Bus")
            for mtx in range(1, NUM_MATRICES + 1):
                if _is_on(self.params.get(f"{b_str}/mix/{mtx:02d}/on", 0)):
                    paths.append(f"{via} -> Matrix {mtx:02d}")

        return bool(paths), paths

    def is_channel_routed_to_p16(self, ch: int) -> Tuple[bool, List[str]]:
        """
        Check if channel is mapped to Ultranet P16 outputs.
        Returns: (is_routed_to_p16, slots)
        """
        slots = []
        for p in range(1, NUM_P16_SLOTS + 1):
            src = self.params.get(f"/outputs/p16/{p:02d}/src")
            tap = self.params.get(f"/outputs/p16/{p:02d}/tap", "Pre")
            if src == ch:
                slots.append(f"P16 Slot {p} (Tap: {tap})")
        return bool(slots), slots

    def verify_talkback_invariant(self) -> Tuple[bool, str]:
        """
        Verify the HARD INVARIANT:
        DL16 Input 11 (Talkback) MUST NOT have any path to FOH,
        and MUST be routed to P16 monitor.
        """
        tb_ch = self.dl16_talkback_channel

        # 0. Fail closed on incomplete routing state (live gate only)
        if self.require_complete:
            missing = self.missing_routing_params()
            if missing:
                preview = ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
                return False, (
                    f"UNVERIFIABLE ROUTING: {len(missing)} routing parameter(s) for talkback channel "
                    f"{tb_ch} are missing from the snapshot ({preview}). Writes frozen."
                )

        # 1. Configured channel must match the console patch
        patch_ok, patch_msg = self.check_talkback_patch_consistency()
        if not patch_ok:
            return False, patch_msg

        # 2. Ensure NO path to FOH
        has_foh, foh_paths = self.is_channel_routed_to_foh(tb_ch)
        if has_foh:
            msg = (
                f"CRITICAL INVARIANT VIOLATION: DL16 Input 11 (Channel {tb_ch}) is leaking into Main FOH! "
                f"Paths: {', '.join(foh_paths)}"
            )
            return False, msg

        # 3. Ensure routed to P16
        has_p16, p16_slots = self.is_channel_routed_to_p16(tb_ch)
        if not has_p16:
            msg = (
                f"WARNING: DL16 Input 11 (Channel {tb_ch}) is isolated from FOH, "
                f"but is not currently assigned to any P16 Ultranet slot."
            )
            return False, msg

        return True, f"VERIFIED SAFE: DL16 Input 11 is strictly isolated from FOH and feeding {', '.join(p16_slots)}."

    def validate_diff_invariants(self, diff: Dict[str, Any]) -> None:
        """
        Check if a set of proposed parameter modifications would violate
        any routing or DL16 talkback invariants.
        Raises InvariantViolationError if unsafe!
        """
        changed = diff.get("changed", {})
        added = diff.get("added", {})
        all_new_params = {**added, **{k: v.get("after") if isinstance(v, dict) else v for k, v in changed.items()}}

        # Check if anyone is trying to enable Main Stereo or Mono on the talkback channel
        tb_ch = self.dl16_talkback_channel
        ch_str = f"/ch/{tb_ch:02d}"
        for leak_param in (f"{ch_str}/mix/st", f"{ch_str}/mix/mono"):
            if leak_param in all_new_params and all_new_params[leak_param] != 0:
                raise InvariantViolationError(
                    f"REJECTED: Attempted to route Channel {tb_ch} (DL16 In 11 Talkback) "
                    f"to FOH ({leak_param} = {all_new_params[leak_param]})."
                )

        # Check if anyone is trying to alter P16 Ultranet routing
        for key in all_new_params:
            if key.startswith("/outputs/p16/"):
                raise InvariantViolationError(
                    f"REJECTED: Modification to P16 Ultranet routing '{key}' is strictly forbidden by policy."
                )
            if key.startswith("/config/routing/"):
                raise InvariantViolationError(
                    f"REJECTED: Modification to global routing '{key}' is strictly forbidden by policy."
                )

        # Applying the diff must not open any path from the talkback channel to FOH
        merged = {**self.params, **all_new_params}
        has_foh, foh_paths = RoutingGraph(merged, talkback_channel=tb_ch).is_channel_routed_to_foh(tb_ch)
        if has_foh:
            raise InvariantViolationError(
                f"REJECTED: Change would route Channel {tb_ch} (DL16 In 11 Talkback) to FOH: {', '.join(foh_paths)}"
            )
