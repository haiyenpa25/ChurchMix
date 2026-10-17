"""
Virtual Soundcheck Rehearsal Engine for ChurchMix.
Provides multi-track audio playback simulating realistic worship band and pastor speech
for offline tuning, feedback margin testing, and PEQ calibration without needing musicians on stage.
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import numpy as np


@dataclass
class VirtualSoundcheckSession:
    id: str
    name: str
    description: str
    tempo_bpm: float
    key: str
    active_channels: List[int]
    lead_source: str


SESSION_PRESETS: Dict[str, VirtualSoundcheckSession] = {
    "SUNDAY_WORSHIP_BALLAD": VirtualSoundcheckSession(
        id="SUNDAY_WORSHIP_BALLAD",
        name="Thờ Phượng Êm Dịu (Worship Ballad)",
        description="Bản thánh ca thờ phượng sâu lắng: Đàn Piano, Guitar mộc, Giọng nữ đơn ca và đệm pad nền mềm mại.",
        tempo_bpm=68.0,
        key="D Major",
        active_channels=[1, 3, 4, 6, 7, 8, 9, 10],
        lead_source="Lead Vocal Female (Ch 3)",
    ),
    "SUNDAY_UPTEMPO_PRAISE": VirtualSoundcheckSession(
        id="SUNDAY_UPTEMPO_PRAISE",
        name="Ngợi Khen Sôi Động (Uptempo Praise)",
        description="Ban nhạc thờ phượng đầy đủ: Trống cajon/acoustic, Bass guitar, Guitar acoustic, Đơn ca nam và bè ca đoàn.",
        tempo_bpm=124.0,
        key="G Major",
        active_channels=[1, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14],
        lead_source="Lead Vocal Male & Choir (Ch 4, 5)",
    ),
    "SERMON_PREACHING": VirtualSoundcheckSession(
        id="SERMON_PREACHING",
        name="Bài Giảng Mục Sư (Pastor Sermon)",
        description="Giọng giảng luận tự nhiên của Mục sư: có ngữ điệu, ngắt câu, khoảng lặng và tiếng vang phòng thực tế.",
        tempo_bpm=0.0,
        key="N/A",
        active_channels=[1],
        lead_source="Pastor Speech Mic (Ch 1)",
    ),
    "CONGREGATIONAL_PRAYER": VirtualSoundcheckSession(
        id="CONGREGATIONAL_PRAYER",
        name="Cầu Nguyện Chung (Congregational Prayer)",
        description="Giọng cầu nguyện nhỏ nhẹ kết hợp tiếng đệm đàn piano êm ái hỗ trợ kiểm tra ngưỡng nhạy gate và leveler.",
        tempo_bpm=60.0,
        key="C Major",
        active_channels=[1, 2, 7, 8],
        lead_source="Associate Pastor / Prayer (Ch 2)",
    ),
    "FEEDBACK_DRILL": VirtualSoundcheckSession(
        id="FEEDBACK_DRILL",
        name="Tập xử lý hú (Feedback Drill)",
        description="MÔ PHỎNG để luyện tập: micro ca sĩ (Kênh 3) thỉnh thoảng bị hú ở khoảng 3.15 kHz — tăng dần, kéo dài khoảng 10 giây rồi tắt. Dùng để tập nhận biết và xử lý hú; không phải tín hiệu thật.",
        tempo_bpm=72.0,
        key="D Major",
        active_channels=[1, 3, 6, 7, 8],
        lead_source="Lead Vocal Female (Ch 3) + feedback ring",
    ),
}

# Feedback drill timing (seconds within a repeating cycle) and ring frequency.
# 3150 Hz is deliberately not a harmonic of the 440 Hz drill vocal, so the
# detector's harmonic-exclusion rule does not hide it.
DRILL_CYCLE_S = 24.0
DRILL_RING_START_S = 4.0
DRILL_RING_FULL_S = 8.0
DRILL_RING_END_S = 18.0
DRILL_RING_HZ = 3150.0


class VirtualSoundcheckEngine:
    """Multi-track audio playback engine for virtual soundcheck and room calibration."""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self._is_active = False
        self._current_session_id: Optional[str] = None
        self._time_elapsed = 0.0
        self._total_blocks_streamed = 0

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def current_session(self) -> Optional[VirtualSoundcheckSession]:
        if self._current_session_id and self._current_session_id in SESSION_PRESETS:
            return SESSION_PRESETS[self._current_session_id]
        return None

    def start_session(self, session_id: str = "SUNDAY_WORSHIP_BALLAD") -> VirtualSoundcheckSession:
        """Start playing a multi-track soundcheck session."""
        if session_id not in SESSION_PRESETS:
            session_id = "SUNDAY_WORSHIP_BALLAD"

        self._current_session_id = session_id
        self._is_active = True
        self._time_elapsed = 0.0
        self._total_blocks_streamed = 0
        return SESSION_PRESETS[session_id]

    def stop(self):
        """Stop virtual soundcheck playback."""
        self._is_active = False
        self._current_session_id = None

    def generate_audio_block(self, block_size: int = 1024) -> np.ndarray:
        """
        Generate a 32-channel float32 audio frame representing realistic multitrack signals.
        Returns shape: (block_size, 32).
        """
        if not self._is_active or not self._current_session_id:
            # Silence
            return np.zeros((block_size, 32), dtype=np.float32)

        session = SESSION_PRESETS[self._current_session_id]
        dt = block_size / self.sample_rate
        t = np.linspace(self._time_elapsed, self._time_elapsed + dt, block_size, endpoint=False)
        out = np.zeros((block_size, 32), dtype=np.float32)

        # 1. Pastor Mic (Ch 1)
        if 1 in session.active_channels:
            if session.id == "SERMON_PREACHING":
                # Speech pattern: intermittent talking with 1.5s speech bursts and 0.8s pauses
                speech_cycle = math.fmod(self._time_elapsed, 4.0)
                if speech_cycle < 2.5:
                    f0 = 160.0 + 20.0 * math.sin(self._time_elapsed * 2.0)
                    sig = 0.28 * np.sin(2 * np.pi * f0 * t) + 0.14 * np.sin(2 * np.pi * (2 * f0) * t)
                    sig += 0.08 * np.sin(2 * np.pi * 2600 * t) # Formants
                    out[:, 0] = sig.astype(np.float32)
            elif session.id in ("SUNDAY_WORSHIP_BALLAD", "SUNDAY_UPTEMPO_PRAISE"):
                # Pastor standing quietly, occasional low ambient whisper
                out[:, 0] = (0.01 * np.sin(2 * np.pi * 180 * t) + np.random.normal(0, 0.002, block_size)).astype(np.float32)

        # 2. Associate Pastor / Prayer (Ch 2)
        if 2 in session.active_channels:
            sig = 0.18 * np.sin(2 * np.pi * 210 * t) + 0.08 * np.sin(2 * np.pi * 420 * t)
            out[:, 1] = sig.astype(np.float32)

        # 3. Female Lead Vocal (Ch 3)
        if 3 in session.active_channels:
            # Soprano singing around A4-E5 (440Hz - 660Hz) with natural vibrato and harmonics
            vibrato = 1.0 + 0.02 * np.sin(2 * np.pi * 5.5 * t)
            pitch = 440.0 * vibrato
            vocal = 0.32 * np.sin(2 * np.pi * pitch * t)
            vocal += 0.16 * np.sin(2 * np.pi * (2 * pitch) * t)
            vocal += 0.08 * np.sin(2 * np.pi * (3 * pitch) * t)
            if session.id == "FEEDBACK_DRILL":
                vocal = 0.4 * vocal + self._drill_ring(t)
            out[:, 2] = vocal.astype(np.float32)

        # 4. Male Lead Vocal (Ch 4)
        if 4 in session.active_channels:
            # Tenor singing around C3-G3 (130Hz - 196Hz)
            pitch = 196.0 * (1.0 + 0.015 * np.sin(2 * np.pi * 5.0 * t))
            vocal_m = 0.30 * np.sin(2 * np.pi * pitch * t) + 0.15 * np.sin(2 * np.pi * (2 * pitch) * t)
            out[:, 3] = vocal_m.astype(np.float32)

        # 5. Choir Overhead (Ch 5)
        if 5 in session.active_channels:
            # Dense multi-voice harmonic chorus
            c1 = np.sin(2 * np.pi * 330 * t) + np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 550 * t)
            out[:, 4] = (0.12 * c1).astype(np.float32)

        # 6. Acoustic Guitar (Ch 6)
        if 6 in session.active_channels:
            # Rhythmic strumming chords (D - G - A)
            strum_env = 0.5 + 0.5 * np.sin(2 * np.pi * (session.tempo_bpm / 60.0) * t)
            gtr = (np.sin(2 * np.pi * 146.8 * t) + np.sin(2 * np.pi * 220.0 * t) + np.sin(2 * np.pi * 293.7 * t))
            out[:, 5] = (0.22 * gtr * strum_env).astype(np.float32)

        # 7 & 8. Piano L/R (Ch 7, 8)
        if 7 in session.active_channels and 8 in session.active_channels:
            p_l = 0.20 * np.sin(2 * np.pi * 261.6 * t) + 0.10 * np.sin(2 * np.pi * 329.6 * t)
            p_r = 0.20 * np.sin(2 * np.pi * 392.0 * t) + 0.10 * np.sin(2 * np.pi * 523.2 * t)
            out[:, 6] = p_l.astype(np.float32)
            out[:, 7] = p_r.astype(np.float32)

        # 9. Bass Guitar (Ch 9)
        if 9 in session.active_channels:
            # Deep round 55 Hz (A1) or 73.4 Hz (D2)
            bass = 0.35 * np.sin(2 * np.pi * 73.4 * t) + 0.18 * np.sin(2 * np.pi * 146.8 * t)
            out[:, 8] = bass.astype(np.float32)

        # 10. Synthesizer / Pad (Ch 10)
        if 10 in session.active_channels:
            pad = 0.15 * np.sin(2 * np.pi * 110.0 * t) + 0.08 * np.sin(2 * np.pi * 164.8 * t)
            out[:, 9] = pad.astype(np.float32)

        # 11. Talkback Band (Ch 11 - DL16 Input 11) - STRICTLY ISOLATED
        # Whisper signal with negligible power (-55dBFS), never leak to FOH
        out[:, 10] = (0.003 * np.sin(2 * np.pi * 300 * t) + np.random.normal(0, 0.001, block_size)).astype(np.float32)

        # 12-14. Drums (Kick, Snare, Overhead) for Uptempo
        if 12 in session.active_channels:
            beat_env = np.maximum(0.0, np.sin(2 * np.pi * (session.tempo_bpm / 60.0) * t)) ** 8
            # Kick (Ch 12)
            out[:, 11] = (0.40 * np.sin(2 * np.pi * 55.0 * t) * beat_env).astype(np.float32)
            # Snare (Ch 13)
            out[:, 12] = (0.25 * np.random.normal(0, 0.5, block_size) * (1.0 - beat_env)).astype(np.float32)
            # Hi-Hat (Ch 14)
            out[:, 13] = (0.15 * np.sin(2 * np.pi * 8000.0 * t)).astype(np.float32)

        self._time_elapsed += dt
        self._total_blocks_streamed += 1
        return out

    def _drill_ring(self, t: np.ndarray) -> np.ndarray:
        """Sustained pure tone that builds up, holds, then stops — a simulated howl."""
        phase = math.fmod(self._time_elapsed, DRILL_CYCLE_S)
        if phase < DRILL_RING_START_S or phase >= DRILL_RING_END_S:
            return np.zeros_like(t)
        build = (phase - DRILL_RING_START_S) / (DRILL_RING_FULL_S - DRILL_RING_START_S)
        amplitude = 0.45 * min(1.0, max(0.05, build))
        return amplitude * np.sin(2 * np.pi * DRILL_RING_HZ * t)

    def get_status(self) -> Dict[str, Any]:
        """Return Virtual Soundcheck status metadata."""
        current = self.current_session
        return {
            "is_active": self._is_active,
            "session_id": current.id if current else None,
            "session_name": current.name if current else "None (Stopped)",
            "description": current.description if current else "Hệ thống đang ở chế độ micro trực tiếp thông thường.",
            "tempo_bpm": current.tempo_bpm if current else 0.0,
            "key": current.key if current else "N/A",
            "active_channels": current.active_channels if current else [],
            "lead_source": current.lead_source if current else "N/A",
            "time_elapsed_seconds": round(self._time_elapsed, 1),
            "total_blocks_streamed": self._total_blocks_streamed,
            "available_presets": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "lead_source": p.lead_source,
                    "tempo_bpm": p.tempo_bpm,
                }
                for p in SESSION_PRESETS.values()
            ],
        }
