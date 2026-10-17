"""
Service Segments (Tiết mục): named sets of channel ON/MUTE states, e.g.
"Mục sư giảng" = pastor mic open, band and choir muted.

Safety design:
- Only `/ch/NN/mix/on` is ever changed. Faders are never moved by a segment, so
  switching cannot boost a level (AGENTS.md rule 10).
- The protected talkback channel (configured, see routing.get_talkback_channel)
  can never be part of a segment.
- Channels not listed in a segment are left untouched.
- Applying is done by the API as one Safety Gate batch: mutes first, then
  unmutes, readback + rollback of the whole batch on any mismatch.

Storage: data/service_segments.json (git-ignored, per church).
    {"version": 1, "segments": [
        {"id": "PASTOR_SERMON", "name": "Mục sư giảng", "icon": "mic",
         "description": "...", "channels": {"1": 1, "3": 0}, "builtin": true,
         "updated_at": 1791800000.0, "updated_by": "System"}]}
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional

from packages.safety_controller.routing import get_talkback_channel

ALLOWED_ICONS = {"mic", "users", "church", "headphones", "volume", "disc", "broadcast", "hand", "sliders", "wave"}
MAX_SEGMENTS = 30
UNMANAGED_ROLES = {"TALKBACK_BAND", "GENERAL_INPUT"}
INSTRUMENT_ROLES = {"ACOUSTIC_GUITAR", "ELECTRIC_GUITAR", "PIANO_KEYS", "BASS_GUITAR"}
LEAD_VOCAL_ROLES = {"LEAD_VOCAL_FEMALE", "LEAD_VOCAL_MALE"}


class SegmentError(ValueError):
    """Invalid segment definition or unknown segment."""


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_").upper()
    return slug[:40] or "SEGMENT"


def build_default_segments(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the default segments from the church channel map (roles), not from
    fixed channel numbers, so a re-patched church keeps sensible defaults.
    """
    tb = get_talkback_channel()
    by_role: Dict[str, List[int]] = {}
    for c in channels:
        by_role.setdefault(c.get("role", "GENERAL_INPUT"), []).append(int(c["channel"]))
    for chs in by_role.values():
        chs.sort()

    managed = sorted(int(c["channel"]) for c in channels
                     if c.get("role") not in UNMANAGED_ROLES and int(c["channel"]) != tb)
    pastors = by_role.get("PASTOR_SPEECH", [])
    main_pastor = pastors[:1]
    mc = pastors[1:2] or main_pastor
    leads = [ch for r in sorted(LEAD_VOCAL_ROLES) for ch in by_role.get(r, [])]
    choir = by_role.get("CHOIR_OVERHEAD", [])
    keys = by_role.get("PIANO_KEYS", [])
    acoustic = by_role.get("ACOUSTIC_GUITAR", [])
    instruments = [ch for r in sorted(INSTRUMENT_ROLES) for ch in by_role.get(r, [])]
    drums = by_role.get("DRUMS", [])
    solo_voice = by_role.get("LEAD_VOCAL_FEMALE", [])[:1] or leads[:1]

    def states(on: List[int]) -> Dict[str, int]:
        on_set = set(on)
        return {str(ch): (1 if ch in on_set else 0) for ch in managed}

    now = time.time()
    specs = [
        ("PASTOR_SERMON", "Mục sư giảng", "mic",
         "Chỉ mở micro Mục sư. Tắt ban nhạc, ca đoàn và các micro khác để giọng giảng rõ và không hú.",
         main_pastor),
        ("WORSHIP_TEAM", "Ban hát thờ phượng", "users",
         "Mở ca sĩ, ca đoàn và toàn bộ nhạc cụ. Tắt micro Mục sư và MC.",
         leads + choir + instruments + drums),
        ("MINISTRY_GROUP", "Ban ngành", "church",
         "Ban ngành trình bày: mở micro ca đoàn/nhóm hát, ca sĩ, piano, guitar và micro MC để giới thiệu.",
         choir + leads + keys + acoustic + mc),
        ("SOLO", "Đơn ca", "headphones",
         "Một ca sĩ hát: mở micro đơn ca, piano và guitar mộc. Tắt các micro khác.",
         solo_voice + keys + acoustic),
        ("ENSEMBLE", "Tốp ca", "users",
         "Nhóm nhỏ hát: mở các micro ca sĩ, micro ca đoàn, piano và guitar mộc.",
         leads + choir + keys + acoustic),
        ("ANNOUNCEMENT", "Thông báo / MC", "broadcast",
         "Chỉ mở micro MC (phụ lễ) để thông báo.",
         mc),
        ("PRAYER", "Cầu nguyện", "hand",
         "Mở micro Mục sư/phụ lễ và piano đệm nhẹ. Tắt ban nhạc.",
         pastors + keys),
    ]
    return [{
        "id": sid, "name": name, "icon": icon, "description": desc,
        "channels": states(on), "builtin": True, "updated_at": now, "updated_by": "System",
    } for sid, name, icon, desc, on in specs]


class ServiceSegmentStore:
    def __init__(self, channel_provider, path: Optional[str] = None):
        """
        channel_provider: callable returning the church channel list
            [{"channel": int, "name": str, "role": str, ...}] (ChurchProfileManager.get_channels).
        """
        if path is None:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            path = os.path.join(root, "data", "service_segments.json")
        self.path = path
        self._channels = channel_provider
        self._lock = threading.RLock()

    # ---------- persistence ----------
    def _read(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return build_default_segments(self._channels())
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            segments = data.get("segments", [])
            return segments if isinstance(segments, list) else build_default_segments(self._channels())
        except (OSError, ValueError):
            return build_default_segments(self._channels())

    def _write(self, segments: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "segments": segments}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------- validation ----------
    def _clean_channels(self, channels: Dict[Any, Any]) -> Dict[str, int]:
        if not isinstance(channels, dict):
            raise SegmentError("channels phải là bảng {số kênh: 0|1}.")
        tb = get_talkback_channel()
        cleaned: Dict[str, int] = {}
        for key, value in channels.items():
            try:
                ch = int(key)
            except (TypeError, ValueError):
                raise SegmentError(f"Số kênh không hợp lệ: {key!r}")
            if not 1 <= ch <= 32:
                raise SegmentError(f"Kênh {ch} nằm ngoài 1–32.")
            if ch == tb:
                raise SegmentError(f"Kênh {ch} là Talkback ban nhạc (DL16 #11) — không được đưa vào tiết mục.")
            if isinstance(value, bool):
                value = int(value)
            if value not in (0, 1):
                raise SegmentError(f"Trạng thái kênh {ch} phải là 0 (tắt) hoặc 1 (bật).")
            cleaned[str(ch)] = int(value)
        return dict(sorted(cleaned.items(), key=lambda kv: int(kv[0])))

    @staticmethod
    def _clean_text(value: Any, field: str, max_len: int, required: bool = False) -> str:
        text = str(value or "").strip()
        if required and not text:
            raise SegmentError(f"{field} không được để trống.")
        if len(text) > max_len:
            raise SegmentError(f"{field} quá dài (tối đa {max_len} ký tự).")
        return text

    # ---------- queries ----------
    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._read()

    def get(self, segment_id: str) -> Dict[str, Any]:
        for s in self.list():
            if s["id"] == segment_id:
                return s
        raise SegmentError(f"Không tìm thấy tiết mục '{segment_id}'.")

    def active_id(self, parameters: Dict[str, Any]) -> Optional[str]:
        """First segment whose every listed channel matches the mixer's current ON state."""
        for s in self.list():
            chans = s.get("channels", {})
            if chans and all(parameters.get(f"/ch/{int(ch):02d}/mix/on") is not None
                             and int(parameters[f"/ch/{int(ch):02d}/mix/on"]) == int(on) for ch, on in chans.items()):
                return s["id"]
        return None

    def diff(self, segment_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """What applying the segment would change, given a snapshot's parameters."""
        seg = self.get(segment_id)
        names = {int(c["channel"]): c.get("name", f"Kênh {c['channel']}") for c in self._channels()}
        tb = get_talkback_channel()
        to_mute, to_unmute, unchanged = [], [], 0
        for key, target in seg.get("channels", {}).items():
            ch = int(key)
            if ch == tb:
                continue  # defence in depth: never touch talkback even if the file was edited by hand
            current = parameters.get(f"/ch/{ch:02d}/mix/on")
            if current is None:
                raise SegmentError(f"Không đọc được trạng thái kênh {ch} từ mixer.")
            item = {"channel": ch, "name": names.get(ch, f"Kênh {ch}"), "from": int(current), "to": int(target)}
            if int(current) == int(target):
                unchanged += 1
            elif int(target) == 0:
                to_mute.append(item)
            else:
                to_unmute.append(item)
        return {"segment_id": seg["id"], "name": seg["name"], "to_mute": to_mute, "to_unmute": to_unmute, "unchanged": unchanged}

    # ---------- mutations ----------
    def create(self, name: str, channels: Dict[Any, Any], description: str = "", icon: str = "mic", author: str = "Operator") -> Dict[str, Any]:
        name = self._clean_text(name, "Tên tiết mục", 60, required=True)
        segment = {
            "name": name,
            "icon": icon if icon in ALLOWED_ICONS else "mic",
            "description": self._clean_text(description, "Mô tả", 300),
            "channels": self._clean_channels(channels),
            "builtin": False,
            "updated_at": time.time(),
            "updated_by": self._clean_text(author, "Người tạo", 60) or "Operator",
        }
        with self._lock:
            segments = self._read()
            if len(segments) >= MAX_SEGMENTS:
                raise SegmentError(f"Tối đa {MAX_SEGMENTS} tiết mục.")
            base = _slug(name)
            existing = {s["id"] for s in segments}
            sid, n = base, 2
            while sid in existing:
                sid, n = f"{base}_{n}", n + 1
            segment = {"id": sid, **segment}
            segments.append(segment)
            self._write(segments)
        return segment

    def update(self, segment_id: str, fields: Dict[str, Any], author: str = "Operator") -> Dict[str, Any]:
        with self._lock:
            segments = self._read()
            for s in segments:
                if s["id"] != segment_id:
                    continue
                if fields.get("name") is not None:
                    s["name"] = self._clean_text(fields["name"], "Tên tiết mục", 60, required=True)
                if fields.get("description") is not None:
                    s["description"] = self._clean_text(fields["description"], "Mô tả", 300)
                if fields.get("icon") is not None:
                    s["icon"] = fields["icon"] if fields["icon"] in ALLOWED_ICONS else s.get("icon", "mic")
                if fields.get("channels") is not None:
                    s["channels"] = self._clean_channels(fields["channels"])
                s["updated_at"] = time.time()
                s["updated_by"] = self._clean_text(author, "Người sửa", 60) or "Operator"
                self._write(segments)
                return s
        raise SegmentError(f"Không tìm thấy tiết mục '{segment_id}'.")

    def capture(self, segment_id: str, parameters: Dict[str, Any], author: str = "Operator") -> Dict[str, Any]:
        """Save the mixer's current ON/MUTE state into the segment (for the channels it
        manages, or every non-protected, non-spare channel when it manages none yet)."""
        seg = self.get(segment_id)
        tb = get_talkback_channel()
        keys = [int(k) for k in seg.get("channels", {})] or [
            int(c["channel"]) for c in self._channels() if c.get("role") not in UNMANAGED_ROLES
        ]
        states = {}
        reference = {}
        for ch in keys:
            if ch == tb:
                continue
            value = parameters.get(f"/ch/{ch:02d}/mix/on")
            if value is None:
                raise SegmentError(f"Không đọc được trạng thái kênh {ch} từ mixer.")
            states[str(ch)] = int(value)
            fader = parameters.get(f"/ch/{ch:02d}/mix/fader")
            if fader is not None:
                reference[str(ch)] = {"fader": round(float(fader), 4)}
        seg = self.update(segment_id, {"channels": states}, author=author)
        # Reference mix ("bản mix chuẩn"): fader positions the operator approved for this
        # segment. Read-only data; the autopilot keeps levels within bounds around it.
        with self._lock:
            segments = self._read()
            for s in segments:
                if s["id"] == segment_id:
                    s["reference"] = reference
                    self._write(segments)
                    return s
        return seg

    def reference_faders(self, segment_id: Optional[str]) -> Dict[int, float]:
        """{channel: fader 0..1} saved with "Lưu từ mixer" for this segment (empty if none)."""
        if not segment_id:
            return {}
        try:
            seg = self.get(segment_id)
        except SegmentError:
            return {}
        return {int(ch): float(v["fader"]) for ch, v in (seg.get("reference") or {}).items()
                if isinstance(v, dict) and v.get("fader") is not None}

    def drift(self, segment_id: str, parameters: Dict[str, Any], threshold_db: float = 3.0) -> List[Dict[str, Any]]:
        """Channels whose fader moved more than threshold_db away from the segment reference."""
        from packages.autopilot.x32_scale import fader_to_db
        names = {int(c["channel"]): c.get("name", f"Kênh {c['channel']}") for c in self._channels()}
        out = []
        for ch, ref in self.reference_faders(segment_id).items():
            cur = parameters.get(f"/ch/{ch:02d}/mix/fader")
            if cur is None or ref <= 0 or float(cur) <= 0:
                continue
            delta = fader_to_db(float(cur)) - fader_to_db(ref)
            if abs(delta) >= threshold_db:
                out.append({"channel": ch, "name": names.get(ch, f"Kênh {ch}"), "delta_db": round(delta, 1)})
        return out

    def delete(self, segment_id: str) -> None:
        with self._lock:
            segments = self._read()
            remaining = [s for s in segments if s["id"] != segment_id]
            if len(remaining) == len(segments):
                raise SegmentError(f"Không tìm thấy tiết mục '{segment_id}'.")
            self._write(remaining)

    def reset_defaults(self) -> List[Dict[str, Any]]:
        with self._lock:
            segments = build_default_segments(self._channels())
            self._write(segments)
            return segments
