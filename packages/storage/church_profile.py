"""
Church Channel Profile and Custom Map Management.
Allows churches to customize names, roles, and colors of 32 channels while strictly
preserving the DL16 In 11 Talkback protection invariant.
"""
from __future__ import annotations
import os
import json

from packages.safety_controller.routing import get_talkback_channel
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional


@dataclass
class ChurchChannelProfile:
    channel: int
    name: str
    role: str
    color: str
    icon: str
    is_protected: bool = False
    notes: str = ""


DEFAULT_CHURCH_CHANNELS: List[Dict[str, Any]] = [
    {"channel": 1, "name": "Pastor Mic", "role": "PASTOR_SPEECH", "color": "amber", "icon": "microphone-lines", "is_protected": False, "notes": "Micro bục giảng chính của Mục sư"},
    {"channel": 2, "name": "Phụ Lễ / MC", "role": "PASTOR_SPEECH", "color": "yellow", "icon": "microphone", "is_protected": False, "notes": "Micro phụ lễ hoặc cầu nguyện"},
    {"channel": 3, "name": "Nữ Đơn Ca (Lead)", "role": "LEAD_VOCAL_FEMALE", "color": "purple", "icon": "music", "is_protected": False, "notes": "Ca sĩ hướng dẫn thờ phượng nữ"},
    {"channel": 4, "name": "Nam Đơn Ca", "role": "LEAD_VOCAL_MALE", "color": "indigo", "icon": "music", "is_protected": False, "notes": "Ca sĩ đơn ca nam baritone/tenor"},
    {"channel": 5, "name": "Ca Đoàn Tổng Hợp", "role": "CHOIR_OVERHEAD", "color": "cyan", "icon": "users", "is_protected": False, "notes": "Cặp micro thu ca đoàn từ trên cao"},
    {"channel": 6, "name": "Acoustic Guitar", "role": "ACOUSTIC_GUITAR", "color": "emerald", "icon": "guitar", "is_protected": False, "notes": "Đàn guitar mộc DI box"},
    {"channel": 7, "name": "Piano L", "role": "PIANO_KEYS", "color": "blue", "icon": "keyboard", "is_protected": False, "notes": "Đàn piano phím trái"},
    {"channel": 8, "name": "Piano R", "role": "PIANO_KEYS", "color": "blue", "icon": "keyboard", "is_protected": False, "notes": "Đàn piano phím phải"},
    {"channel": 9, "name": "Bass Guitar", "role": "BASS_GUITAR", "color": "violet", "icon": "bolt", "is_protected": False, "notes": "Đàn bass 4/5 dây qua DI box"},
    {"channel": 10, "name": "Synth / Pad", "role": "PIANO_KEYS", "color": "teal", "icon": "wave-square", "is_protected": False, "notes": "Tiếng không gian pad phụ trợ"},
    {"channel": 11, "name": "Talkback Band", "role": "TALKBACK_BAND", "color": "red", "icon": "shield-halved", "is_protected": True, "notes": "CỔNG BẢO VỆ: DL16 In 11 chỉ gửi P16, cách ly 100% khỏi FOH"},
    {"channel": 12, "name": "Kick Drum", "role": "DRUMS", "color": "orange", "icon": "drum", "is_protected": False, "notes": "Trống kick"},
    {"channel": 13, "name": "Snare Drum", "role": "DRUMS", "color": "orange", "icon": "drum", "is_protected": False, "notes": "Trống snare"},
    {"channel": 14, "name": "Hi-Hat", "role": "DRUMS", "color": "orange", "icon": "circle-dot", "is_protected": False, "notes": "Lá hi-hat"},
    {"channel": 15, "name": "Tom 1", "role": "DRUMS", "color": "orange", "icon": "drum", "is_protected": False, "notes": "Trống tom 1"},
    {"channel": 16, "name": "Overhead Drums", "role": "DRUMS", "color": "orange", "icon": "headphones", "is_protected": False, "notes": "Micro thu toàn bộ dàn trống"},
]

# Generate channels 17..32 as Aux / Spare
for c in range(17, 33):
    DEFAULT_CHURCH_CHANNELS.append({
        "channel": c,
        "name": f"Kênh {c}",
        "role": "GENERAL_INPUT",
        "color": "slate",
        "icon": "sliders",
        "is_protected": False,
        "notes": f"Đường vào dự phòng Line {c}",
    })


class ChurchProfileManager:
    """Manages reading and writing church channel layout configurations."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(root, "data")
            os.makedirs(data_dir, exist_ok=True)
            config_path = os.path.join(data_dir, "church_channels.json")

        self.config_path = config_path
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        if not os.path.exists(self.config_path):
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CHURCH_CHANNELS, f, indent=2, ensure_ascii=False)

    def get_channels(self) -> List[Dict[str, Any]]:
        """Retrieve all 32 church channel definitions."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                channels = json.load(f)
                # Enforce protection on channel 11
                for ch in channels:
                    if ch.get("channel") == 11:
                        ch["is_protected"] = True
                        ch["role"] = "TALKBACK_BAND"
                return channels
        except Exception:
            return DEFAULT_CHURCH_CHANNELS

    def get_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific channel profile by number."""
        channels = self.get_channels()
        for ch in channels:
            if ch.get("channel") == channel_id:
                return ch
        return None

    def update_channel(self, channel_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update custom channel properties (name, role, notes, color).
        Strict invariant: Channel 11 is permanently protected.
        """
        channels = self.get_channels()
        target = None
        for ch in channels:
            if ch["channel"] == channel_id:
                target = ch
                break

        if not target:
            raise ValueError(f"Channel {channel_id} not found in church configuration (must be 1..32)")

        # Enforce hard invariant: Talkback protection cannot be removed
        if channel_id == get_talkback_channel():
            updates.pop("is_protected", None)
            updates.pop("role", None)
            target["is_protected"] = True
            target["role"] = "TALKBACK_BAND"

        # Apply allowed updates
        for key in ["name", "role", "color", "icon", "notes"]:
            if key in updates:
                target[key] = updates[key]

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(channels, f, indent=2, ensure_ascii=False)

        return target

    def reset_to_default(self) -> List[Dict[str, Any]]:
        """Reset church channel layout back to standard default profile."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CHURCH_CHANNELS, f, indent=2, ensure_ascii=False)
        return self.get_channels()
