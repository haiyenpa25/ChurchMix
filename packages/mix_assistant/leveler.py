"""
Church Speech Leveler, VAD & Anti-Clipping Guard.
Safety Constraints:
1. HARD RULE: No upward boost on silence (Silence Hold prevents pumping background noise).
2. Anti-Clipping: Instant warning and limited downward nudge when peak > -1.5 dBFS.
3. Downward-Only or Slow-Upward Hysteresis for Speech dynamics.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from packages.signal_analysis.dsp import AudioFrame, calculate_peak_dbfs, calculate_rms_dbfs, detect_clipping


@dataclass
class VoiceActivityState:
    channel_id: int
    is_active: bool
    is_silence_hold: bool
    rms_dbfs: float
    peak_dbfs: float
    consecutive_silent_frames: int
    consecutive_active_frames: int


@dataclass
class LevelerAction:
    channel_id: int
    action_type: str # "HOLD", "DOWNWARD_NUDGE", "UPWARD_NUDGE", "ANTI_CLIP"
    fader_delta: float
    rationale: str
    target_fader: float


class VoiceActivityDetector:
    def __init__(
        self,
        activity_threshold_db: float = -42.0,
        silence_hold_frames: int = 15, # ~1.5s at 10fps
    ):
        self.activity_threshold_db = activity_threshold_db
        self.silence_hold_frames = silence_hold_frames
        self.channel_states: Dict[int, Dict[str, Any]] = {}

    def process_frame(self, frame: AudioFrame) -> VoiceActivityState:
        ch = frame.channel_id
        if ch not in self.channel_states:
            self.channel_states[ch] = {
                "silent_count": 0,
                "active_count": 0,
                "is_active": False,
            }

        rms = calculate_rms_dbfs(frame.samples)
        peak = calculate_peak_dbfs(frame.samples)

        state = self.channel_states[ch]

        if rms >= self.activity_threshold_db:
            state["active_count"] += 1
            state["silent_count"] = 0
            state["is_active"] = True
        else:
            state["silent_count"] += 1
            state["active_count"] = 0
            if state["silent_count"] >= self.silence_hold_frames:
                state["is_active"] = False

        is_silence_hold = (not state["is_active"]) or (state["silent_count"] > 2)

        return VoiceActivityState(
            channel_id=ch,
            is_active=state["is_active"],
            is_silence_hold=is_silence_hold,
            rms_dbfs=round(rms, 1),
            peak_dbfs=round(peak, 1),
            consecutive_silent_frames=state["silent_count"],
            consecutive_active_frames=state["active_count"],
        )


class AntiClippingGuard:
    def __init__(self, clip_threshold_db: float = -1.5):
        self.clip_threshold_db = clip_threshold_db

    def check(self, frame: AudioFrame) -> Optional[LevelerAction]:
        clip_count, is_clipping = detect_clipping(frame.samples, threshold=0.99)
        peak_db = calculate_peak_dbfs(frame.samples)

        if is_clipping or peak_db >= self.clip_threshold_db:
            return LevelerAction(
                channel_id=frame.channel_id,
                action_type="ANTI_CLIP",
                fader_delta=-0.06, # ~ -2 dB downward nudge
                rationale=(
                    f"ANTI-CLIP: Peak reached {peak_db:.1f} dBFS with {clip_count} clipped samples. "
                    f"Nudging fader downward to preserve headroom."
                ),
                target_fader=0.0,
            )
        return None


class SpeechLeveler:
    def __init__(
        self,
        target_rms_db: float = -20.0,
        tolerance_db: float = 3.0,
        max_downward_step: float = 0.04,
        max_upward_step: float = 0.02, # Much slower upward than downward!
    ):
        self.target_rms_db = target_rms_db
        self.tolerance_db = tolerance_db
        self.max_downward_step = max_downward_step
        self.max_upward_step = max_upward_step
        self.vad = VoiceActivityDetector()
        self.anticlip = AntiClippingGuard()

    def process(self, frame: AudioFrame, current_fader: float) -> LevelerAction:
        """
        Evaluate audio frame and propose safe fader movement.
        Enforces:
        - Silence Hold (No upward movement during silence)
        - Anti-Clipping priority
        - Slower upward recovery than downward reduction
        """
        # 1. Anti-clipping priority
        clip_action = self.anticlip.check(frame)
        if clip_action:
            clip_action.target_fader = max(0.0, current_fader + clip_action.fader_delta)
            return clip_action

        # 2. Voice Activity Detection
        vad_state = self.vad.process_frame(frame)

        # HARD SAFETY RULE: When speaker is silent, FREEZE FADER!
        if vad_state.is_silence_hold:
            return LevelerAction(
                channel_id=frame.channel_id,
                action_type="HOLD",
                fader_delta=0.0,
                rationale="SILENCE HOLD: Speaker paused or silent. Fader frozen to prevent raising noise floor.",
                target_fader=current_fader,
            )

        # 3. Dynamic Leveling during active speech
        error_db = self.target_rms_db - vad_state.rms_dbfs

        if abs(error_db) <= self.tolerance_db:
            return LevelerAction(
                channel_id=frame.channel_id,
                action_type="HOLD",
                fader_delta=0.0,
                rationale=f"IN TARGET: Speech level is {vad_state.rms_dbfs:.1f} dBFS (Target: {self.target_rms_db} dBFS).",
                target_fader=current_fader,
            )

        if error_db < -self.tolerance_db:
            # Too loud! Nudge downward
            delta = -min(self.max_downward_step, abs(error_db) * 0.008)
            return LevelerAction(
                channel_id=frame.channel_id,
                action_type="DOWNWARD_NUDGE",
                fader_delta=round(delta, 3),
                rationale=f"SPEECH PEAK: Level is {vad_state.rms_dbfs:.1f} dBFS (Too loud). Nudging down {delta:.3f}.",
                target_fader=round(max(0.0, current_fader + delta), 3),
            )
        else:
            # Too quiet, but cautious upward step (half speed)
            delta = min(self.max_upward_step, abs(error_db) * 0.004)
            return LevelerAction(
                channel_id=frame.channel_id,
                action_type="UPWARD_NUDGE",
                fader_delta=round(delta, 3),
                rationale=f"GENTLE BOOST: Speech level is {vad_state.rms_dbfs:.1f} dBFS. Slow upward compensation +{delta:.3f}.",
                target_fader=round(min(1.0, current_fader + delta), 3),
            )
