"""
ChurchMix Subjective Audio Quality Benchmark & A/B Listening Test Engine.
========================================================================
Implements:
1. 7-Criteria Listening Test Matrix (Master Plan Section 3.4):
   - Speech Intelligibility (Độ rõ lời) [Weight: 20%]
   - Natural Timbre (Độ tự nhiên chất giọng) [Weight: 20%]
   - Warmth & Body (Độ ấm & thân giọng) [Weight: 15%]
   - Harshness & Sibilance Control (Kiểm soát gắt & chói) [Weight: 15%]
   - Band/Instrument Balance (Cân bằng với ban nhạc) [Weight: 10%]
   - Hall Coverage Uniformity (Độ phủ đều hội trường) [Weight: 10%]
   - Feedback Safety Margin (Biên độ dự trữ chống hú) [Weight: 10%]

2. Double-Blind A/B Testing Session:
   - Randomizes Option A and Option B (Bypass/Dry vs Proposed Tuning).
   - Equal-Loudness Normalization (Fletcher-Munson compensation) to prevent
     psychoacoustic volume bias ("louder sounds better").

3. Mean Opinion Score (MOS 1.0 - 5.0) & Acceptance Recommendation:
   - Evaluates whether tuning is safe and beneficial to commit live.
   - Enforces veto: if any individual core score is < 2.5, tuning cannot
     be approved regardless of overall average.
"""
from __future__ import annotations
import math
import random
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
import numpy as np


@dataclass
class ListeningTestCriteria:
    intelligibility: float # 1.0 to 5.0 (Độ rõ lời)
    timbre_naturalness: float # 1.0 to 5.0 (Độ tự nhiên chất giọng)
    warmth_body: float # 1.0 to 5.0 (Độ ấm & thân giọng)
    harshness_control: float # 1.0 to 5.0 (Kiểm soát gắt & chói sibilance)
    band_balance: float # 1.0 to 5.0 (Cân bằng với nhạc nền)
    hall_coverage: float # 1.0 to 5.0 (Độ phủ đều hội trường)
    feedback_margin: float # 1.0 to 5.0 (Biên độ an toàn chống hú)

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class ListeningEvaluation:
    evaluation_id: str
    target_channel: int
    channel_name: str
    operator: str
    criteria: ListeningTestCriteria
    overall_mos: float # 1.0 to 5.0
    recommendation: str # RECOMMENDED_FOR_COMMIT | ACCEPTABLE_WITH_MONITORING | REJECT_OR_REFINE
    strengths_vi: List[str]
    weaknesses_vi: List[str]
    advice_vi: str
    loudness_compensation_db: float
    is_blind_test: bool
    proposal_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["criteria"] = self.criteria.to_dict() if hasattr(self.criteria, "to_dict") else self.criteria
        return d


@dataclass
class BlindABSession:
    session_id: str
    proposal_id: Optional[str]
    target_channel: int
    channel_name: str
    option_a_is_tuning: bool # True if A is Tuning, False if A is Dry
    loudness_compensation_db: float
    created_at: float = field(default_factory=time.time)
    revealed: bool = False

    def to_dict(self, reveal_identity: bool = False) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "proposal_id": self.proposal_id,
            "target_channel": self.target_channel,
            "channel_name": self.channel_name,
            "loudness_compensation_db": round(self.loudness_compensation_db, 2),
            "revealed": reveal_identity or self.revealed,
            "option_a_identity": ("TUNING_PROPOSAL" if self.option_a_is_tuning else "DRY_ORIGINAL")
            if (reveal_identity or self.revealed) else "HIDDEN",
            "option_b_identity": ("DRY_ORIGINAL" if self.option_a_is_tuning else "TUNING_PROPOSAL")
            if (reveal_identity or self.revealed) else "HIDDEN",
        }


class ListeningTestEngine:
    """
    Core engine for conducting operator listening tests, calculating MOS,
    and managing double-blind A/B comparisons.
    """

    CRITERIA_WEIGHTS = {
        "intelligibility": 0.20,
        "timbre_naturalness": 0.20,
        "warmth_body": 0.15,
        "harshness_control": 0.15,
        "band_balance": 0.10,
        "hall_coverage": 0.10,
        "feedback_margin": 0.10,
    }

    # In-memory store for active blind sessions
    _active_blind_sessions: Dict[str, BlindABSession] = {}

    @classmethod
    def calculate_mos(cls, criteria: ListeningTestCriteria) -> Tuple[float, str, List[str], List[str], str]:
        """
        Calculate weighted Mean Opinion Score (1.0 to 5.0) and formulate
        acceptance recommendation and tactical commentary.
        """
        raw_scores = {
            "intelligibility": max(1.0, min(5.0, float(criteria.intelligibility))),
            "timbre_naturalness": max(1.0, min(5.0, float(criteria.timbre_naturalness))),
            "warmth_body": max(1.0, min(5.0, float(criteria.warmth_body))),
            "harshness_control": max(1.0, min(5.0, float(criteria.harshness_control))),
            "band_balance": max(1.0, min(5.0, float(criteria.band_balance))),
            "hall_coverage": max(1.0, min(5.0, float(criteria.hall_coverage))),
            "feedback_margin": max(1.0, min(5.0, float(criteria.feedback_margin))),
        }

        weighted_mos = sum(raw_scores[k] * cls.CRITERIA_WEIGHTS[k] for k in raw_scores)
        weighted_mos = round(weighted_mos, 2)

        strengths: List[str] = []
        weaknesses: List[str] = []

        labels_vi = {
            "intelligibility": "Độ rõ lời",
            "timbre_naturalness": "Độ tự nhiên chất giọng",
            "warmth_body": "Độ ấm & thân giọng",
            "harshness_control": "Kiểm soát gắt & chói",
            "band_balance": "Hòa quyện với ban nhạc",
            "hall_coverage": "Độ phủ đều hội trường",
            "feedback_margin": "Dự trữ chống hú",
        }

        for k, score in raw_scores.items():
            name = labels_vi[k]
            if score >= 4.0:
                strengths.append(f"{name} xuất sắc ({score:.1f}/5.0)")
            elif score <= 2.5:
                weaknesses.append(f"{name} chưa đạt yêu cầu ({score:.1f}/5.0)")

        # Safety & Veto Invariant:
        # If intelligibility or timbre < 2.5, or feedback margin < 2.5 -> REJECT
        has_critical_fail = any(raw_scores[k] < 2.5 for k in ["intelligibility", "timbre_naturalness", "feedback_margin"])

        if weighted_mos >= 4.0 and not has_critical_fail and len(weaknesses) == 0:
            recommendation = "RECOMMENDED_FOR_COMMIT"
            advice_vi = (
                f"Bản cân chỉnh đạt chuẩn chất lượng xuất sắc (MOS {weighted_mos}/5.0). "
                f"Đảm bảo giọng trung thực, rõ lời và an toàn feedback. Khuyến nghị áp dụng chính thức cho buổi lễ."
            )
        elif weighted_mos >= 3.2 and not has_critical_fail:
            recommendation = "ACCEPTABLE_WITH_MONITORING"
            advice_vi = (
                f"Bản cân chỉnh ở mức chấp nhận được (MOS {weighted_mos}/5.0). "
                f"Nên tiếp tục theo dõi thêm trong quá trình diễn ra buổi lễ để tinh chỉnh fader khi cần."
            )
        else:
            recommendation = "REJECT_OR_REFINE"
            crit_reasons = ", ".join(weaknesses) if weaknesses else "Điểm tổng thể dưới ngưỡng an toàn"
            advice_vi = (
                f"KHÔNG KHUYẾN NGHỊ ÁP DỤNG (MOS {weighted_mos}/5.0). "
                f"Lý do: {crit_reasons}. Cần hiệu chỉnh lại EQ hoặc xử lý vật lý (khoảng cách micro, vị trí loa) trước khi commit."
            )

        return weighted_mos, recommendation, strengths, weaknesses, advice_vi

    @classmethod
    def evaluate_listening(
        cls,
        target_channel: int,
        channel_name: str,
        operator: str,
        criteria: ListeningTestCriteria,
        proposal_id: Optional[str] = None,
        loudness_compensation_db: float = 0.0,
        is_blind_test: bool = False,
    ) -> ListeningEvaluation:
        """Create and return a completed ListeningEvaluation record."""
        mos, rec, strengths, weaknesses, advice = cls.calculate_mos(criteria)
        eval_id = f"eval-{target_channel:02d}-{uuid.uuid4().hex[:6]}"

        return ListeningEvaluation(
            evaluation_id=eval_id,
            target_channel=target_channel,
            channel_name=channel_name,
            operator=operator,
            criteria=criteria,
            overall_mos=mos,
            recommendation=rec,
            strengths_vi=strengths,
            weaknesses_vi=weaknesses,
            advice_vi=advice,
            loudness_compensation_db=round(loudness_compensation_db, 2),
            is_blind_test=is_blind_test,
            proposal_id=proposal_id,
        )

    @classmethod
    def create_blind_ab_session(
        cls,
        target_channel: int,
        channel_name: str,
        proposal_id: Optional[str] = None,
        dry_rms_dbfs: float = -20.0,
        processed_rms_dbfs: float = -18.5,
    ) -> BlindABSession:
        """
        Create a randomized double-blind A/B session with Fletcher-Munson
        equal-loudness compensation.
        """
        # Equal-loudness compensation delta (dB):
        # Subtract difference so processed matches dry RMS exactly
        loudness_delta_db = round(dry_rms_dbfs - processed_rms_dbfs, 2)

        # Randomize: 50% chance A is Tuning, 50% chance B is Tuning
        option_a_is_tuning = random.choice([True, False])
        session_id = f"blind-{target_channel:02d}-{uuid.uuid4().hex[:8]}"

        session = BlindABSession(
            session_id=session_id,
            proposal_id=proposal_id,
            target_channel=target_channel,
            channel_name=channel_name,
            option_a_is_tuning=option_a_is_tuning,
            loudness_compensation_db=loudness_delta_db,
        )

        cls._active_blind_sessions[session_id] = session
        return session

    @classmethod
    def reveal_blind_ab_session(cls, session_id: str) -> BlindABSession:
        """Reveal true identities of Option A and Option B for an active session."""
        if session_id not in cls._active_blind_sessions:
            raise KeyError(f"Blind A/B session '{session_id}' not found.")
        session = cls._active_blind_sessions[session_id]
        session.revealed = True
        return session

    @classmethod
    def get_session(cls, session_id: str) -> Optional[BlindABSession]:
        return cls._active_blind_sessions.get(session_id)
