"""
Hall Acoustic Profile & Multi-Sanctuary Baseline Comparison Manager.
Supports multi-hall church campuses (Main Sanctuary, Youth Chapel, Fellowship Hall, Outdoor Campus)
with versioned acoustic baselines, delay alignment checks, and deviation analysis.
"""
from __future__ import annotations
import os
import json
import time
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
import numpy as np


@dataclass
class HallProfile:
    id: str
    name: str
    capacity_seats: int
    target_rt60_seconds: float
    nominal_delay_ms: float
    ambient_noise_dbfs: float
    speaker_system: str
    target_curve_slope_db_per_oct: float
    safe_gain_limit_db: float
    version: int = 1
    updated_at: float = field(default_factory=time.time)
    notes: str = ""
    baseline_curve: Optional[List[Dict[str, float]]] = None # [{"freq": 100, "target_db": -1.5, "coherence": 0.9}]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HallProfile":
        return cls(**data)


DEFAULT_HALL_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "MAIN_SANCTUARY",
        "name": "Hội Trường Lớn (Main Sanctuary)",
        "capacity_seats": 800,
        "target_rt60_seconds": 1.6,
        "nominal_delay_ms": 3.5,
        "ambient_noise_dbfs": -62.0,
        "speaker_system": "Line Array FOH Treo + Front Fills Bục Giảng",
        "target_curve_slope_db_per_oct": -1.0,
        "safe_gain_limit_db": 4.5,
        "version": 1,
        "updated_at": 1728700000.0,
        "notes": "Hội trường thánh đường chính, trần cao vòm gỗ, âm học ấm và vang tự nhiên cho dàn hợp xướng.",
        "baseline_curve": [
            {"freq": 100.0, "target_db": 0.0, "coherence": 0.92},
            {"freq": 250.0, "target_db": -1.8, "coherence": 0.88},
            {"freq": 500.0, "target_db": 0.0, "coherence": 0.94},
            {"freq": 1000.0, "target_db": 0.0, "coherence": 0.96},
            {"freq": 2800.0, "target_db": 1.2, "coherence": 0.93},
            {"freq": 4000.0, "target_db": 0.0, "coherence": 0.91},
            {"freq": 8000.0, "target_db": -1.5, "coherence": 0.85},
            {"freq": 12000.0, "target_db": -3.0, "coherence": 0.80},
        ],
    },
    {
        "id": "YOUTH_CHAPEL",
        "name": "Phòng Nhóm Giới Trẻ (Youth Chapel)",
        "capacity_seats": 150,
        "target_rt60_seconds": 0.8,
        "nominal_delay_ms": 1.8,
        "ambient_noise_dbfs": -58.0,
        "speaker_system": "Cặp Loa Full Point-Source 12-inch + 18-inch Subwoofer",
        "target_curve_slope_db_per_oct": -0.8,
        "safe_gain_limit_db": 6.0,
        "version": 1,
        "updated_at": 1728700000.0,
        "notes": "Phòng nhóm âm thanh hiện đại, vách tiêu âm dày, thích hợp ban nhạc thờ phượng sôi động và trống acoustic.",
        "baseline_curve": [
            {"freq": 100.0, "target_db": 2.0, "coherence": 0.95},
            {"freq": 250.0, "target_db": 0.0, "coherence": 0.92},
            {"freq": 500.0, "target_db": 0.0, "coherence": 0.95},
            {"freq": 1000.0, "target_db": 0.0, "coherence": 0.97},
            {"freq": 2800.0, "target_db": 1.5, "coherence": 0.94},
            {"freq": 4000.0, "target_db": 0.5, "coherence": 0.92},
            {"freq": 8000.0, "target_db": -1.0, "coherence": 0.88},
            {"freq": 12000.0, "target_db": -2.0, "coherence": 0.84},
        ],
    },
    {
        "id": "FELLOWSHIP_HALL",
        "name": "Phòng Sinh Hoạt Đa Năng (Fellowship Hall)",
        "capacity_seats": 250,
        "target_rt60_seconds": 2.1,
        "nominal_delay_ms": 4.2,
        "ambient_noise_dbfs": -52.0,
        "speaker_system": "Hệ thống Loa Cột Column Array (Tăng độ tập trung)",
        "target_curve_slope_db_per_oct": -1.5,
        "safe_gain_limit_db": 3.0,
        "version": 1,
        "updated_at": 1728700000.0,
        "notes": "Sàn gạch phản xạ mạnh, trần thấp; cần kiểm soát chặt chẽ dải trung trầm và giảm âm lượng FOH để tránh dội tiếng.",
        "baseline_curve": [
            {"freq": 100.0, "target_db": -2.0, "coherence": 0.82},
            {"freq": 250.0, "target_db": -3.5, "coherence": 0.78},
            {"freq": 500.0, "target_db": -1.0, "coherence": 0.84},
            {"freq": 1000.0, "target_db": 0.0, "coherence": 0.89},
            {"freq": 2800.0, "target_db": 0.5, "coherence": 0.86},
            {"freq": 4000.0, "target_db": -1.0, "coherence": 0.80},
            {"freq": 8000.0, "target_db": -3.0, "coherence": 0.75},
            {"freq": 12000.0, "target_db": -5.0, "coherence": 0.68},
        ],
    },
    {
        "id": "OUTDOOR_CAMPUS",
        "name": "Điểm Nhóm Ngoài Trời (Outdoor Campus)",
        "capacity_seats": 1500,
        "target_rt60_seconds": 0.2,
        "nominal_delay_ms": 6.5,
        "ambient_noise_dbfs": -48.0,
        "speaker_system": "Hệ Thống Horn-Loaded PA Công Suất Lớn + Chống Gió",
        "target_curve_slope_db_per_oct": -0.5,
        "safe_gain_limit_db": 5.0,
        "version": 1,
        "updated_at": 1728700000.0,
        "notes": "Không gian tự do không có phản xạ tường; cần bù trừ suy hao tần số cao trong không khí và lọc gió chặt ở 100Hz.",
        "baseline_curve": [
            {"freq": 100.0, "target_db": -1.0, "coherence": 0.90},
            {"freq": 250.0, "target_db": 0.5, "coherence": 0.91},
            {"freq": 500.0, "target_db": 0.5, "coherence": 0.93},
            {"freq": 1000.0, "target_db": 0.0, "coherence": 0.95},
            {"freq": 2800.0, "target_db": 2.0, "coherence": 0.91},
            {"freq": 4000.0, "target_db": 1.5, "coherence": 0.88},
            {"freq": 8000.0, "target_db": 0.0, "coherence": 0.82},
            {"freq": 12000.0, "target_db": -1.5, "coherence": 0.76},
        ],
    },
]


class HallProfileManager:
    """Manages multi-sanctuary acoustic hall profiles, versions, and baseline diffs."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(root, "data")
            os.makedirs(data_dir, exist_ok=True)
            config_path = os.path.join(data_dir, "hall_profiles.json")

        self.config_path = config_path
        self._active_hall_id = "MAIN_SANCTUARY"
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        if not os.path.exists(self.config_path):
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "active_hall_id": self._active_hall_id,
                    "halls": DEFAULT_HALL_PROFILES,
                }, f, indent=2, ensure_ascii=False)
        else:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._active_hall_id = data.get("active_hall_id", "MAIN_SANCTUARY")
            except Exception:
                self._active_hall_id = "MAIN_SANCTUARY"

    def get_all_halls(self) -> List[HallProfile]:
        """List all configured sanctuary hall acoustic profiles."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [HallProfile.from_dict(h) for h in data.get("halls", DEFAULT_HALL_PROFILES)]
        except Exception:
            return [HallProfile.from_dict(h) for h in DEFAULT_HALL_PROFILES]

    def get_hall(self, hall_id: str) -> Optional[HallProfile]:
        """Fetch a specific hall profile by ID."""
        halls = self.get_all_halls()
        for h in halls:
            if h.id == hall_id:
                return h
        return None

    def get_active_hall(self) -> HallProfile:
        """Get the currently active sanctuary hall."""
        hall = self.get_hall(self._active_hall_id)
        if not hall:
            halls = self.get_all_halls()
            return halls[0] if halls else HallProfile.from_dict(DEFAULT_HALL_PROFILES[0])
        return hall

    def set_active_hall(self, hall_id: str) -> HallProfile:
        """Switch active hall and persist selection."""
        hall = self.get_hall(hall_id)
        if not hall:
            raise ValueError(f"Hall profile '{hall_id}' not found.")

        self._active_hall_id = hall_id
        halls = self.get_all_halls()

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({
                "active_hall_id": self._active_hall_id,
                "halls": [h.to_dict() for h in halls],
            }, f, indent=2, ensure_ascii=False)

        return hall

    def save_hall(self, profile: HallProfile) -> HallProfile:
        """Create or update a versioned hall acoustic profile."""
        halls = self.get_all_halls()
        existing_idx = None
        for i, h in enumerate(halls):
            if h.id == profile.id:
                existing_idx = i
                break

        profile.updated_at = time.time()
        if existing_idx is not None:
            profile.version = halls[existing_idx].version + 1
            halls[existing_idx] = profile
        else:
            profile.version = 1
            halls.append(profile)

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({
                "active_hall_id": self._active_hall_id,
                "halls": [h.to_dict() for h in halls],
            }, f, indent=2, ensure_ascii=False)

        return profile

    def compare_measurement_against_baseline(
        self,
        hall_id: Optional[str] = None,
        measurement_curve: Optional[List[Dict[str, Any]]] = None,
        delay_ms: float = 3.5,
    ) -> Dict[str, Any]:
        """
        Compare current live transfer function measurement against the Hall's Baseline Target.
        Computes RMS error (dB), delay drift (ms), coherence degradation, and critical deviations.
        """
        hall = self.get_hall(hall_id) if hall_id else self.get_active_hall()
        if not hall:
            hall = self.get_active_hall()

        baseline = hall.baseline_curve or []
        if not baseline or not measurement_curve:
            return {
                "hall_id": hall.id,
                "hall_name": hall.name,
                "baseline_available": bool(baseline),
                "measurement_available": bool(measurement_curve),
                "rms_deviation_db": 0.0,
                "delay_drift_ms": 0.0,
                "status": "INSUFFICIENT_DATA",
                "critical_deviations": [],
                "recommendations_vi": ["Thực hiện đo đạc âm học H1 để bắt đầu so sánh với baseline."],
            }

        # Calculate deviation across baseline points
        deviations: List[Dict[str, Any]] = []
        diffs = []

        for b_pt in baseline:
            b_freq = b_pt["freq"]
            b_target = b_pt["target_db"]

            # Find nearest measurement point
            nearest_m = min(measurement_curve, key=lambda m: abs(m.get("freq", 0) - b_freq))
            m_val = nearest_m.get("magnitude_db", 0.0)
            m_coh = nearest_m.get("coherence", 1.0)

            diff = m_val - b_target
            diffs.append(diff)

            # Flag if deviation is significant (> 2.5 dB)
            is_significant = abs(diff) > 2.5
            deviations.append({
                "freq_hz": b_freq,
                "baseline_target_db": b_target,
                "measured_db": round(float(m_val), 1),
                "delta_db": round(float(diff), 1),
                "coherence": round(float(m_coh), 2),
                "is_significant": is_significant,
            })

        rms_err = math.sqrt(sum(d**2 for d in diffs) / max(1, len(diffs)))
        delay_drift = delay_ms - hall.nominal_delay_ms

        # Generate tactical audio recommendations
        recommendations = []
        if abs(delay_drift) > 0.8:
            recommendations.append(
                f"Độ trễ loa lệch {delay_drift:+.1f}ms so với chuẩn phòng ({hall.nominal_delay_ms}ms). "
                "Cần kiểm tra vị trí đặt micro đo hoặc kiểm tra lại DSP/cục đẩy."
            )

        high_deltas = [d for d in deviations if d["delta_db"] > 3.0]
        if high_deltas:
            freq_str = ", ".join([f"{d['freq_hz']:.0f}Hz ({d['delta_db']:+.1f}dB)" for d in high_deltas])
            recommendations.append(
                f"Phát hiện tăng dải tần quá ngưỡng tại {freq_str}. "
                "Có rủi ro cộng hưởng phòng hoặc micro bị dội sàn; cần kiểm tra EQ cut."
            )

        low_deltas = [d for d in deviations if d["delta_db"] < -3.5]
        if low_deltas:
            freq_str = ", ".join([f"{d['freq_hz']:.0f}Hz ({d['delta_db']:+.1f}dB)" for d in low_deltas])
            recommendations.append(
                f"Phát hiện suy hao sâu tại {freq_str}. "
                "LƯU Ý QUY TẮC NO-BOOST-IN-NULLS: Tuyệt đối không kích EQ bù hố triệt tiêu pha."
            )

        if not recommendations:
            recommendations.append("Đáp tuyến âm học bám sát chuẩn Baseline phòng (RMS Error < 2.0 dB). Trạng thái tối ưu!")

        return {
            "hall_id": hall.id,
            "hall_name": hall.name,
            "capacity_seats": hall.capacity_seats,
            "target_rt60_seconds": hall.target_rt60_seconds,
            "nominal_delay_ms": hall.nominal_delay_ms,
            "measured_delay_ms": delay_ms,
            "delay_drift_ms": round(delay_drift, 2),
            "rms_deviation_db": round(rms_err, 2),
            "status": "HEALTHY" if rms_err < 2.5 else "DEVIATED",
            "point_comparisons": deviations,
            "recommendations_vi": recommendations,
        }
