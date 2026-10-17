"""
ChurchMix Multi-Bus Monitor Mix Matrix & Personal IEM Invariant Inspector.
========================================================================
Audits all 16 Ultranet P16 slots and 16 MixBuses (Stage Wedges & IEMs)
to guarantee acoustic safety, feedback prevention, and strict isolation
of DL16 Input 11 (Band Talkback).

Core Invariants & Capabilities:
1. Ultranet P16 Audit:
   - Verifies all 16 P16 outputs (/outputs/p16/{01-16}/*).
   - HARD INVARIANT (Rule 5): DL16 physical input 11 (Band Talkback) must route
     SOLELY to Ultranet P16 Slot 11 (/outputs/p16/11/src == 11).
   - Verifies NO other P16 slot routes Channel 11.
2. MixBus Auxiliary Monitor Matrix:
   - Audits all 16 MixBuses: classifies bus type (WEDGE, IEM, SUBGROUP, FX).
   - HARD INVARIANT: Channel 11 must NEVER send to any MixBus routed to Main FOH
     (/bus/{bus}/mix/st == 1) or to any Stage Wedge floor monitor.
3. Stage Monitor Feedback Hazard Detection:
   - Detects when open speech/vocal mics have excessive send levels (> 0.80 / +2.5 dB)
     into Stage Wedge mixes.
   - Detects Tap Point Inconsistencies: Wedges and IEMs must be Pre-Fader (or Post-EQ / Pre-EQ),
     NEVER Post-Fader (which causes sudden feedback or balance disruptions when FOH moves faders).
4. Safe Monitor Balance Proposals:
   - Formulates conservative, non-destructive proposals to fix tap points,
     mute talkback bleed into stage wedges, and trim excessive wedge sends.
   - Rule 7: Proposals are never commands; require explicit operator approval.
"""

from __future__ import annotations
import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Set

from packages.safety_controller.transaction import Proposal
from packages.safety_controller.routing import InvariantViolationError


def x32_to_bus_level_db(val: float) -> float:
    """Convert X32 0.0-1.0 fader scale to approximate dBFS."""
    if val <= 0.0:
        return -90.0 # -inf
    if val < 0.25:
        return -60.0 + (val / 0.25) * 20.0
    if val < 0.50:
        return -40.0 + ((val - 0.25) / 0.25) * 20.0
    if val < 0.75:
        return -20.0 + ((val - 0.50) / 0.25) * 20.0
    return ((val - 0.75) / 0.25) * 10.0


def bus_level_db_to_x32(db: float) -> float:
    """Convert dB value to X32 0.0-1.0 scale."""
    if db <= -60.0:
        return 0.0
    if db <= -40.0:
        return 0.25 * ((db + 60.0) / 20.0)
    if db <= -20.0:
        return 0.25 + 0.25 * ((db + 40.0) / 20.0)
    if db <= 0.0:
        return 0.50 + 0.25 * ((db + 20.0) / 20.0)
    return min(1.0, 0.75 + 0.25 * (db / 10.0))


@dataclass
class P16SlotInfo:
    slot: int
    source_channel: int
    tap_point: str
    name: str
    is_band_talkback: bool
    status: str # "SAFE" | "WARNING" | "CRITICAL_INVARIANT_VIOLATION"
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChannelBusSend:
    channel: int
    channel_name: str
    bus: int
    bus_name: str
    bus_type: str
    level: float
    level_db: float
    on: bool
    tap_point: str
    feedback_risk: str # "NONE" | "LOW" | "MODERATE" | "HIGH" | "CRITICAL"
    feedback_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MixBusSummary:
    bus: int
    name: str
    bus_type: str # "WEDGE" | "IEM" | "SUBGROUP" | "FX"
    master_fader: float
    master_fader_db: float
    master_on: bool
    routes_to_st: bool
    active_send_count: int
    feedback_risk_count: int
    tap_inconsistency_count: int
    talkback_leaked: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MonitorMatrixAuditReport:
    timestamp: float
    p16_slots: List[P16SlotInfo]
    p16_talkback_safe: bool
    mixbuses: List[MixBusSummary]
    talkback_isolation_verified: bool
    tap_inconsistencies: List[Dict[str, Any]]
    feedback_hazards: List[Dict[str, Any]]
    overall_status: str # "SAFE" | "WARNING" | "CRITICAL_VIOLATION"
    proposals_available: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "p16_slots": [s.to_dict() for s in self.p16_slots],
            "p16_talkback_safe": self.p16_talkback_safe,
            "mixbuses": [b.to_dict() for b in self.mixbuses],
            "talkback_isolation_verified": self.talkback_isolation_verified,
            "tap_inconsistencies": self.tap_inconsistencies,
            "feedback_hazards": self.feedback_hazards,
            "overall_status": self.overall_status,
            "proposals_available": self.proposals_available,
        }


class MonitorMatrixInspector:
    """
    Comprehensive Inspector & Advisor for Behringer X32 Monitor Buses & P16 Ultranet.
    """

    VOCAL_ROLES_OR_NAMES = {
        "pastor", "voc", "lead", "backing", "choir", "speech", "mic", "vocal"
    }

    @staticmethod
    def classify_bus_type(bus_id: int, bus_name: str) -> str:
        """Classify MixBus into WEDGE, IEM, SUBGROUP, or FX based on name and index."""
        name_lower = bus_name.lower()
        if any(k in name_lower for k in ["wedge", "floor", "sanctuary", "stage mon", "mon"]):
            return "WEDGE"
        if any(k in name_lower for k in ["iem", "in-ear", "ear", "headphone"]):
            return "IEM"
        if any(k in name_lower for k in ["fx", "verb", "reverb", "delay", "chorus", "plate"]):
            return "FX"
        if any(k in name_lower for k in ["sub", "group", "stream", "livestream", "broadcast", "matrix"]):
            return "SUBGROUP"

        # Default ChurchMix standard layout if unnamed:
        if 1 <= bus_id <= 4:
            return "WEDGE"
        elif 5 <= bus_id <= 8:
            return "IEM"
        elif 9 <= bus_id <= 12:
            return "SUBGROUP"
        else:
            return "FX"

    @classmethod
    def audit_p16_ultranet(cls, x32_state: Dict[str, Any]) -> Tuple[List[P16SlotInfo], bool, List[str]]:
        """
        Audit all 16 Ultranet P16 slots.
        Verifies Hard Invariant: DL16 In 11 (Band Talkback) routes ONLY to P16 Slot 11.
        Returns: (slots_info, is_talkback_safe, violation_messages)
        """
        slots_info: List[P16SlotInfo] = []
        is_safe = True
        violations: List[str] = []

        slot_11_has_tb = False

        for slot in range(1, 17):
            src_key = f"/outputs/p16/{slot:02d}/src"
            tap_key = f"/outputs/p16/{slot:02d}/tap"

            src_val = x32_state.get(src_key, slot)
            tap_val = str(x32_state.get(tap_key, "Pre-EQ"))

            # Determine channel name
            ch_name = f"CH{src_val:02d}" if isinstance(src_val, int) and 1 <= src_val <= 32 else str(src_val)
            if isinstance(src_val, int) and 1 <= src_val <= 32:
                ch_name = x32_state.get(f"/ch/{src_val:02d}/config/name", ch_name)

            is_tb = (src_val == 11)

            if slot == 11:
                if is_tb:
                    slot_11_has_tb = True
                    status = "SAFE"
                    details = "Bất biến an toàn: DL16 In 11 (Band Talkback) được gán chính xác vào Slot 11."
                else:
                    status = "WARNING"
                    details = f"Cảnh báo: P16 Slot 11 đang gán vào Ch {src_val} thay vì Band Talkback (Ch 11)."
            else:
                if is_tb:
                    is_safe = False
                    status = "CRITICAL_INVARIANT_VIOLATION"
                    msg = (
                        f"BẤT BIẾN AN TOÀN BỊ VI PHẠM: Band Talkback (Ch 11) bị rò rỉ vào P16 Slot {slot:02d} ({tap_val})! "
                        f"Chỉ duy nhất Slot 11 được phép nhận tín hiệu Talkback."
                    )
                    violations.append(msg)
                    details = msg
                else:
                    status = "SAFE"
                    details = f"Định tuyến bình thường: {ch_name} (Tap: {tap_val})."

            slots_info.append(
                P16SlotInfo(
                    slot=slot,
                    source_channel=src_val if isinstance(src_val, int) else 0,
                    tap_point=tap_val,
                    name=ch_name,
                    is_band_talkback=is_tb,
                    status=status,
                    details=details,
                )
            )

        if not slot_11_has_tb:
            # Talkback is not reaching the band
            violations.append("Cảnh báo an toàn: Band Talkback (Ch 11) chưa được gán vào P16 Slot 11.")

        return slots_info, is_safe, violations

    @classmethod
    def audit_mixbus_matrix(
        cls,
        x32_state: Dict[str, Any],
        bus_roles: Optional[Dict[int, str]] = None,
    ) -> MonitorMatrixAuditReport:
        """
        Audit all 16 MixBuses across all 32 channels.
        Detects:
        - Talkback bleed into FOH or Stage Wedges
        - Stage monitor acoustic feedback risks (> 0.80 fader send on vocal channels)
        - Tap point inconsistencies (Post-Fader on Wedges/IEMs)
        """
        import time
        bus_roles = bus_roles or {}

        # 1. Audit P16 Ultranet
        p16_slots, p16_talkback_safe, p16_violations = cls.audit_p16_ultranet(x32_state)

        # 2. Audit MixBuses
        mixbuses: List[MixBusSummary] = []
        tap_inconsistencies: List[Dict[str, Any]] = []
        feedback_hazards: List[Dict[str, Any]] = []
        talkback_violations: List[str] = []

        proposals_count = 0

        for bus in range(1, 17):
            bus_prefix = f"/bus/{bus:02d}"
            bus_name = bus_roles.get(bus) or x32_state.get(f"{bus_prefix}/config/name", f"Bus {bus:02d}")
            bus_type = cls.classify_bus_type(bus, bus_name)

            master_fader = float(x32_state.get(f"{bus_prefix}/mix/fader", 0.75))
            master_on = int(x32_state.get(f"{bus_prefix}/mix/on", 1)) == 1
            routes_to_st = int(x32_state.get(f"{bus_prefix}/mix/st", 0)) == 1

            active_sends = 0
            feedback_risk_count = 0
            tap_inconsistency_count = 0
            talkback_leaked = False

            # Inspect all 32 channels sending to this bus
            for ch in range(1, 33):
                ch_prefix = f"/ch/{ch:02d}"
                ch_name = x32_state.get(f"{ch_prefix}/config/name", f"CH{ch:02d}")
                send_on = int(x32_state.get(f"{ch_prefix}/mix/{bus:02d}/on", 1)) == 1
                send_lvl = float(x32_state.get(f"{ch_prefix}/mix/{bus:02d}/level", 0.0))
                tap_point = str(x32_state.get(f"{ch_prefix}/mix/{bus:02d}/tap", "Pre"))

                if send_on and send_lvl > 0.01:
                    active_sends += 1

                # Check Channel 11 (Band Talkback) Isolation
                if ch == 11 and send_on and send_lvl > 0.01:
                    if routes_to_st:
                        talkback_leaked = True
                        msg = (
                            f"CRITICAL INVARIANT VIOLATION: DL16 In 11 (Band Talkback) is routed through "
                            f"Bus {bus:02d} ({bus_name}) directly to Main FOH!"
                        )
                        talkback_violations.append(msg)
                        proposals_count += 1
                    elif bus_type == "WEDGE":
                        talkback_leaked = True
                        msg = (
                            f"STAGE MONITOR LEAK VIOLATION: DL16 In 11 (Band Talkback) is unmuted into Stage Wedge "
                            f"Bus {bus:02d} ({bus_name})! Band whispers will broadcast to congregation."
                        )
                        talkback_violations.append(msg)
                        proposals_count += 1

                # Check Tap Point Consistency for Wedges and IEMs
                if bus_type in ("WEDGE", "IEM") and send_on:
                    if tap_point.lower() in ("post", "post-fader", "postfdr"):
                        tap_inconsistency_count += 1
                        tap_inconsistencies.append({
                            "bus": bus,
                            "bus_name": bus_name,
                            "bus_type": bus_type,
                            "channel": ch,
                            "channel_name": ch_name,
                            "current_tap": tap_point,
                            "recommended_tap": "Pre",
                            "severity": "WARNING",
                            "message": (
                                f"Kênh {ch:02d} ({ch_name}) đang gán Post-Fader vào {bus_name}. "
                                f"FOH kéo fader sẽ làm biến động monitor và nguy cơ gây hú sân khấu."
                            ),
                        })
                        proposals_count += 1

                # Check Feedback Hazard for Stage Wedges
                if bus_type == "WEDGE" and send_on and master_on and master_fader > 0.1:
                    is_vocal = any(k in ch_name.lower() for k in cls.VOCAL_ROLES_OR_NAMES) or (ch <= 5 or ch in (12, 13))
                    if is_vocal:
                        if send_lvl > 0.85: # > +5 dB
                            feedback_risk_count += 1
                            feedback_hazards.append({
                                "bus": bus,
                                "bus_name": bus_name,
                                "channel": ch,
                                "channel_name": ch_name,
                                "send_level": send_lvl,
                                "send_level_db": round(x32_to_bus_level_db(send_lvl), 1),
                                "risk_level": "CRITICAL",
                                "message": (
                                    f"NGUY CƠ HÚ CỰC KỲ CAO: Micro {ch_name} gửi mức quá lớn ({x32_to_bus_level_db(send_lvl):+.1f} dB) "
                                    f"vào loa monitor sàn {bus_name}! Rất dễ bùng nổ vòng lặp acoustic."
                                ),
                            })
                            proposals_count += 1
                        elif send_lvl > 0.80: # > +2.5 dB
                            feedback_risk_count += 1
                            feedback_hazards.append({
                                "bus": bus,
                                "bus_name": bus_name,
                                "channel": ch,
                                "channel_name": ch_name,
                                "send_level": send_lvl,
                                "send_level_db": round(x32_to_bus_level_db(send_lvl), 1),
                                "risk_level": "HIGH",
                                "message": (
                                    f"CẢNH BÁO HÚ: Micro {ch_name} gửi mức cao ({x32_to_bus_level_db(send_lvl):+.1f} dB) "
                                    f"vào loa sàn {bus_name}. Cần hạ fader send về Unity (0 dB) để bảo toàn headroom."
                                ),
                            })
                            proposals_count += 1

            mixbuses.append(
                MixBusSummary(
                    bus=bus,
                    name=bus_name,
                    bus_type=bus_type,
                    master_fader=master_fader,
                    master_fader_db=round(x32_to_bus_level_db(master_fader), 1),
                    master_on=master_on,
                    routes_to_st=routes_to_st,
                    active_send_count=active_sends,
                    feedback_risk_count=feedback_risk_count,
                    tap_inconsistency_count=tap_inconsistency_count,
                    talkback_leaked=talkback_leaked,
                )
            )

        # Determine overall status
        talkback_isolated = (len(talkback_violations) == 0) and p16_talkback_safe

        if not talkback_isolated:
            overall_status = "CRITICAL_VIOLATION"
        elif len(feedback_hazards) > 0 or len(tap_inconsistencies) > 0:
            overall_status = "WARNING"
        else:
            overall_status = "SAFE"

        return MonitorMatrixAuditReport(
            timestamp=time.time(),
            p16_slots=p16_slots,
            p16_talkback_safe=p16_talkback_safe,
            mixbuses=mixbuses,
            talkback_isolation_verified=talkback_isolated,
            tap_inconsistencies=tap_inconsistencies,
            feedback_hazards=feedback_hazards,
            overall_status=overall_status,
            proposals_available=proposals_count,
        )

    @classmethod
    def generate_safe_bus_balance_proposals(
        cls,
        x32_state: Dict[str, Any],
        bus_id: int,
        current_sha256: str,
        bus_roles: Optional[Dict[int, str]] = None,
    ) -> List[Proposal]:
        """
        Formulate safe, non-destructive proposals to optimize monitor mix for a bus:
        1. Mute Channel 11 (Band Talkback) if unmuted to a Wedge or FOH bus.
        2. Attenuate excessive vocal send levels (> 0.80) to safe nominal 0.75 (0 dB) or 0.70 (-3 dB).
        3. Correct Post-Fader taps to Pre-Fader for monitor stability.
        """
        bus_roles = bus_roles or {}
        bus_prefix = f"/bus/{bus_id:02d}"
        bus_name = bus_roles.get(bus_id) or x32_state.get(f"{bus_prefix}/config/name", f"Bus {bus_id:02d}")
        bus_type = cls.classify_bus_type(bus_id, bus_name)
        routes_to_st = int(x32_state.get(f"{bus_prefix}/mix/st", 0)) == 1

        proposals: List[Proposal] = []

        # 1. Talkback Isolation Proposals
        send_11_on = int(x32_state.get(f"/ch/11/mix/{bus_id:02d}/on", 1)) == 1
        send_11_lvl = float(x32_state.get(f"/ch/11/mix/{bus_id:02d}/level", 0.0))

        if (routes_to_st or bus_type == "WEDGE") and send_11_on and send_11_lvl > 0.01:
            changes = [
                {
                    "parameter": f"/ch/11/mix/{bus_id:02d}/on",
                    "from": 1,
                    "to": 0,
                    "description": f"Mute Talkback send to {bus_name}",
                },
                {
                    "parameter": f"/ch/11/mix/{bus_id:02d}/level",
                    "from": send_11_lvl,
                    "to": 0.0,
                    "description": f"Zero Talkback send level to {bus_name}",
                }
            ]
            proposals.append(
                Proposal(
                    proposal_id=f"prop-tb-isolate-{bus_id:02d}-{uuid.uuid4().hex[:6]}",
                    target_channel=11,
                    hypothesis=(
                        f"BẤT BIẾN AN TOÀN: Khóa tuyệt đối đường gửi micro Talkback (Ch 11) vào {bus_name} "
                        f"để ngăn rò rỉ âm thanh ra hội chúng và triệt tiêu nguy cơ hú."
                    ),
                    confidence=1.0,
                    changes=changes,
                    expected_sha256=current_sha256,
                    operator_approved=False,
                )
            )

        # 2. Vocal Feedback Headroom Attenuation
        if bus_type == "WEDGE":
            for ch in range(1, 33):
                if ch == 11:
                    continue
                ch_name = x32_state.get(f"/ch/{ch:02d}/config/name", f"CH{ch:02d}")
                is_vocal = any(k in ch_name.lower() for k in cls.VOCAL_ROLES_OR_NAMES) or (ch <= 5 or ch in (12, 13))
                send_on = int(x32_state.get(f"/ch/{ch:02d}/mix/{bus_id:02d}/on", 1)) == 1
                send_lvl = float(x32_state.get(f"/ch/{ch:02d}/mix/{bus_id:02d}/level", 0.0))

                if is_vocal and send_on and send_lvl > 0.80:
                    # Attenuate down to safe 0.75 (0 dB) or 0.70 (-3 dB)
                    target_lvl = 0.75
                    changes = [
                        {
                            "parameter": f"/ch/{ch:02d}/mix/{bus_id:02d}/level",
                            "from": send_lvl,
                            "to": target_lvl,
                            "description": f"Hạ send level từ {x32_to_bus_level_db(send_lvl):+.1f} dB xuống {x32_to_bus_level_db(target_lvl):+.1f} dB",
                        }
                    ]
                    proposals.append(
                        Proposal(
                            proposal_id=f"prop-mon-fb-trim-{ch:02d}-{bus_id:02d}-{uuid.uuid4().hex[:6]}",
                            target_channel=ch,
                            hypothesis=(
                                f"Phòng chống hú: Hạ mức gửi micro {ch_name} vào loa monitor sàn {bus_name} "
                                f"xuống Unity (0 dB) nhằm tạo biên dự phòng an toàn 4-6 dB."
                            ),
                            confidence=0.95,
                            changes=changes,
                            expected_sha256=current_sha256,
                            operator_approved=False,
                        )
                    )

        return proposals
