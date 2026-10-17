"""
ChurchMix Speech Automixer & Gain Sharing Controller.
=====================================================
Implements:
1. Dugan-Style Gain Sharing Algorithm:
   - Eliminates feedback, room noise multiplication, and comb filtering
     when multiple spoken-word microphones (Pastor, Podium, Assoc Pastor, Prayer mics)
     are open simultaneously.
   - Invariant: Total acoustic system gain is constrained to NOM = 1 (equivalent to 1 open mic),
     regardless of how many microphones are unmuted.
2. Silence Hold Invariant:
   - When all speakers pause, gain allocations freeze immediately to prevent
     ambient noise pumping (air conditioning, congregation movement).
3. Hard Safety Invariant Protection:
   - DL16 In 11 (Band Talkback) is strictly forbidden from entering any Automix group.
4. Behringer X32 / Midas M32 Native AutoMix Parameter Generator:
   - Formulates safe Proposals for /ch/{ch:02d}/automix/group and /ch/{ch:02d}/automix/weight.
"""
from __future__ import annotations
import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from packages.safety_controller.transaction import Proposal
from packages.safety_controller.routing import InvariantViolationError, get_talkback_channel


@dataclass
class ChannelAutomixState:
    channel_id: int
    channel_name: str
    role: str
    level_dbfs: float
    weight_db: float
    gain_sharing_attenuation_db: float
    is_speaking: bool
    effective_level_dbfs: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AutomixerReport:
    channels: List[ChannelAutomixState]
    total_system_gain_db: float # Constrained to <= 0.0 dB
    primary_speaker_id: Optional[int]
    active_speakers_count: int
    noise_reduction_savings_db: float # 10 * log10(N) savings
    silence_hold_engaged: bool
    talkback_safe: bool = True
    advice_vi: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["channels"] = [c.to_dict() if hasattr(c, "to_dict") else c for c in self.channels]
        return d


class DuganSpeechAutomixer:
    """
    Dugan speech automixer engine and gain-sharing calculator for church microphones.
    """

    SILENCE_THRESHOLD_DBFS = -50.0 # Below this, enter Silence Hold

    @classmethod
    def compute_gain_sharing(
        cls,
        channel_levels_dbfs: Dict[int, float],
        weights_db: Dict[int, float],
        channel_names: Optional[Dict[int, str]] = None,
        channel_roles: Optional[Dict[int, str]] = None,
        last_attenuations: Optional[Dict[int, float]] = None,
    ) -> AutomixerReport:
        """
        Compute Dugan gain sharing distribution across active speech channels.
        Formula:
          P_k = 10^((L_k + w_k) / 10)
          G_k = P_k / (sum(P_i) + P_floor)
          Attn_k = 10 * log10(G_k)  (clamped to [-18 dB, 0 dB])
        """
        names = channel_names or {}
        roles = channel_roles or {}

        # 1. Hard Invariant Check: Channel 11 must never be present
        if get_talkback_channel() in channel_levels_dbfs:
            raise InvariantViolationError(
                "HARD SAFETY INVARIANT VIOLATION: Channel 11 (Band Talkback) must NEVER be included in the Speech Automixer!"
            )

        active_channels = list(channel_levels_dbfs.keys())
        if not active_channels:
            return AutomixerReport(
                channels=[],
                total_system_gain_db=0.0,
                primary_speaker_id=None,
                active_speakers_count=0,
                noise_reduction_savings_db=0.0,
                silence_hold_engaged=True,
                talkback_safe=True,
                advice_vi="Không có kênh micro phát biểu nào được chọn cho Automixer.",
            )

        # 2. Check if all channels are silent (Silence Hold condition)
        max_level = max(channel_levels_dbfs.values()) if channel_levels_dbfs else -120.0
        if max_level < cls.SILENCE_THRESHOLD_DBFS:
            # Silence Hold engaged: preserve previous attenuations or divide equally
            ch_states = []
            eq_attn = round(-10.0 * math.log10(max(1, len(active_channels))), 1)
            for ch in active_channels:
                prev_attn = last_attenuations.get(ch, eq_attn) if last_attenuations else eq_attn
                lvl = channel_levels_dbfs[ch]
                ch_states.append(
                    ChannelAutomixState(
                        channel_id=ch,
                        channel_name=names.get(ch, f"Ch {ch:02d}"),
                        role=roles.get(ch, "SPEECH"),
                        level_dbfs=round(lvl, 1),
                        weight_db=weights_db.get(ch, 0.0),
                        gain_sharing_attenuation_db=round(prev_attn, 1),
                        is_speaking=False,
                        effective_level_dbfs=round(lvl + prev_attn, 1),
                    )
                )

            return AutomixerReport(
                channels=ch_states,
                total_system_gain_db=0.0,
                primary_speaker_id=None,
                active_speakers_count=0,
                noise_reduction_savings_db=round(10.0 * math.log10(len(active_channels)), 1),
                silence_hold_engaged=True,
                talkback_safe=True,
                advice_vi="Hội trường đang im lặng (Silence Hold kích hoạt). Khóa nguyên mức gain để chống bơm ồn nền.",
            )

        # 3. Calculate weighted linear powers
        # Offset to avoid float underflow: L_norm = max(-80, L)
        powers: Dict[int, float] = {}
        for ch in active_channels:
            lvl = max(-80.0, channel_levels_dbfs[ch])
            wt = weights_db.get(ch, 0.0)
            powers[ch] = 10.0 ** ((lvl + wt) / 10.0)

        total_power = sum(powers.values())
        if total_power <= 1e-12:
            total_power = 1e-12

        # 4. Calculate individual Dugan gains
        ch_states = []
        primary_ch = None
        max_active_p = -1.0
        active_count = 0

        for ch in active_channels:
            p_k = powers[ch]
            g_k = p_k / total_power # Normalization: sum(g_k) == 1.0
            g_k = max(1e-4, min(1.0, g_k))
            attn_db = 10.0 * math.log10(g_k)
            attn_db = max(-18.0, min(0.0, attn_db)) # Clamp attenuation floor -18 dB

            lvl = channel_levels_dbfs[ch]
            is_speaking = lvl > -38.0 and g_k >= 0.20
            if is_speaking:
                active_count += 1
                if p_k > max_active_p:
                    max_active_p = p_k
                    primary_ch = ch

            ch_states.append(
                ChannelAutomixState(
                    channel_id=ch,
                    channel_name=names.get(ch, f"Ch {ch:02d}"),
                    role=roles.get(ch, "SPEECH"),
                    level_dbfs=round(lvl, 1),
                    weight_db=weights_db.get(ch, 0.0),
                    gain_sharing_attenuation_db=round(attn_db, 1),
                    is_speaking=is_speaking,
                    effective_level_dbfs=round(lvl + attn_db, 1),
                )
            )

        # Theoretical ambient noise savings compared to N open mics un-attenuated
        n_mics = len(active_channels)
        savings_db = round(10.0 * math.log10(n_mics), 1) if n_mics > 1 else 0.0

        if primary_ch is not None:
            p_name = names.get(primary_ch, f"Ch {primary_ch:02d}")
            advice = (
                f"Người nói chính: {p_name} (Kênh {primary_ch:02d}). "
                f"Hệ thống tự động nén nhẹ các micro phụ còn lại để triệt tiêu tiếng vang hội trường và tiết kiệm {savings_db} dB ồn nền."
            )
        else:
            advice = f"Automixer đang giám sát {n_mics} micro phát biểu. Đảm bảo tổng Gain hệ thống duy trì ở mức NOM = 1."

        return AutomixerReport(
            channels=ch_states,
            total_system_gain_db=0.0,
            primary_speaker_id=primary_ch,
            active_speakers_count=active_count,
            noise_reduction_savings_db=savings_db,
            silence_hold_engaged=False,
            talkback_safe=True,
            advice_vi=advice,
        )

    @classmethod
    def generate_x32_automix_proposals(
        cls,
        channels: List[int],
        weights_db: Dict[int, float],
        current_sha256: str,
        group_id: int = 1, # 1 = Group X, 2 = Group Y
    ) -> List[Proposal]:
        """
        Formulate hardware proposals for native X32 Dugan AutoMix (/ch/{ch}/automix/*).
        """
        # Hard Invariant
        if get_talkback_channel() in channels:
            raise InvariantViolationError("HARD INVARIANT: Channel 11 (Band Talkback) must NEVER be included in Automix!")

        proposals = []
        for ch in channels:
            if ch < 1 or ch > 8:
                # X32 native hardware automixer supports channels 1-8
                continue

            wt = weights_db.get(ch, 0.0)
            # Map weight (-12 dB to +12 dB) to normalized float 0.0 to 1.0 (0.5 = 0 dB)
            norm_wt = round(max(0.0, min(1.0, 0.5 + (wt / 24.0))), 3)

            changes = [
                {
                    "parameter": f"/ch/{ch:02d}/automix/group",
                    "from": 0,
                    "to": group_id,
                    "detail": f"Gán Kênh {ch:02d} vào nhóm AutoMix {'X' if group_id == 1 else 'Y'}.",
                },
                {
                    "parameter": f"/ch/{ch:02d}/automix/weight",
                    "from": 0.5,
                    "to": norm_wt,
                    "detail": f"Cài đặt trọng số ưu tiên AutoMix Kênh {ch:02d} ở mức {wt:+.1f} dB.",
                },
            ]

            prop = Proposal(
                proposal_id=f"prop-automix-{ch:02d}-{uuid.uuid4().hex[:6]}",
                target_channel=ch,
                hypothesis=f"Kích hoạt Native Dugan AutoMix Kênh {ch:02d} (Trọng số {wt:+.1f} dB) để chống cộng hưởng và tăng độ rõ lời.",
                confidence=0.95,
                changes=changes,
                expected_sha256=current_sha256,
                operator_approved=False,
            )
            proposals.append(prop)

        return proposals
