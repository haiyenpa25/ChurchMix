"""
Service program ("Chương trình lễ"): the ordered list of parts of one service,
each pointing at a service segment (Tiết mục), e.g.
    Thông báo đầu giờ -> Thờ phượng -> Cầu nguyện -> Giảng Lời Chúa -> ...

Safety design:
- The program is pure planning data. Nothing here talks to the mixer.
- "Current item" is only a marker. The UI moves it AFTER a successful segment
  switch (preview + confirm + Safety Gate batch in /api/v1/segments/{id}/apply);
  setting it never switches anything.

Storage: data/service_program.json (git-ignored, per church; path override via
CHURCHMIX_PROGRAM_PATH).
    {"version": 1, "items": [{"id": "a1b2c3d4", "segment_id": "PASTOR_SERMON",
      "title": "Giảng Lời Chúa", "note": ""}],
     "current_index": null, "updated_at": 1791800000.0, "updated_by": "Operator"}
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

MAX_ITEMS = 60
MAX_TITLE = 80
MAX_NOTE = 200

# (segment id, title) of the default order of service, built only from segments that exist.
DEFAULT_PROGRAM = [
    ("ANNOUNCEMENT", "Thông báo đầu giờ"),
    ("WORSHIP_TEAM", "Thờ phượng (hát chung)"),
    ("PRAYER", "Cầu nguyện"),
    ("PASTOR_SERMON", "Giảng Lời Chúa"),
    ("WORSHIP_TEAM", "Hát đáp ứng"),
    ("ANNOUNCEMENT", "Thông báo & chúc phước"),
]


class ProgramError(ValueError):
    """Invalid program definition."""


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class ServiceProgramStore:
    def __init__(self, segment_provider: Callable[[], List[Dict[str, Any]]], path: Optional[str] = None):
        """segment_provider: callable returning the segment list (ServiceSegmentStore.list)."""
        if path is None:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            path = os.path.join(root, "data", "service_program.json")
        self.path = path
        self._segments = segment_provider
        self._lock = threading.RLock()

    # ---------- persistence ----------
    def _default(self) -> Dict[str, Any]:
        ids = {s["id"] for s in self._segments()}
        items = [{"id": f"default{i}", "segment_id": sid, "title": title, "note": ""}
                 for i, (sid, title) in enumerate(DEFAULT_PROGRAM) if sid in ids]
        return {"items": items, "current_index": None, "updated_at": None, "updated_by": "System", "is_default": True}

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return self._default()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items")
            if not isinstance(items, list):
                return self._default()
            current = data.get("current_index")
            if not isinstance(current, int) or isinstance(current, bool) or not 0 <= current < len(items):
                current = None
            return {"items": items, "current_index": current, "updated_at": data.get("updated_at"),
                    "updated_by": data.get("updated_by") or "Operator", "is_default": False}
        except (OSError, ValueError, AttributeError):
            return self._default()

    def _write(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f"{self.path}.tmp"
        payload = {"version": 1, "items": data["items"], "current_index": data["current_index"],
                   "updated_at": data["updated_at"], "updated_by": data["updated_by"]}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------- validation ----------
    @staticmethod
    def _text(value: Any, field: str, max_len: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) > max_len:
            raise ProgramError(f"{field} quá dài (tối đa {max_len} ký tự).")
        return text

    def _clean_items(self, items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            raise ProgramError("Danh sách chương trình không hợp lệ.")
        if len(items) > MAX_ITEMS:
            raise ProgramError(f"Chương trình tối đa {MAX_ITEMS} mục.")
        names = {s["id"]: s.get("name", s["id"]) for s in self._segments()}
        cleaned, seen = [], set()
        for pos, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                raise ProgramError(f"Mục {pos} không hợp lệ.")
            sid = str(raw.get("segment_id") or "").strip()
            if sid not in names:
                raise ProgramError(f"Mục {pos}: tiết mục '{sid}' không tồn tại.")
            title = self._text(raw.get("title"), f"Tên mục {pos}", MAX_TITLE) or names[sid]
            note = self._text(raw.get("note"), f"Ghi chú mục {pos}", MAX_NOTE)
            item_id = str(raw.get("id") or "").strip()
            if not item_id or len(item_id) > 40 or not item_id.replace("_", "").replace("-", "").isalnum() or item_id in seen:
                item_id = _new_id()
            seen.add(item_id)
            cleaned.append({"id": item_id, "segment_id": sid, "title": title, "note": note})
        return cleaned

    # ---------- queries ----------
    def get(self) -> Dict[str, Any]:
        """Program with resolved segment names plus the current and next item."""
        with self._lock:
            data = self._read()
        names = {s["id"]: s.get("name", s["id"]) for s in self._segments()}
        items = [{**it, "segment_name": names.get(it.get("segment_id")),
                  "segment_missing": it.get("segment_id") not in names} for it in data["items"]]
        current = data["current_index"]
        nxt = (0 if current is None else current + 1) if items else None
        if nxt is not None and nxt >= len(items):
            nxt = None
        return {
            "items": items, "current_index": current, "next_index": nxt,
            "current": items[current] if current is not None else None,
            "next": items[nxt] if nxt is not None else None,
            "updated_at": data["updated_at"], "updated_by": data["updated_by"],
            "is_default": data["is_default"], "max_items": MAX_ITEMS,
        }

    # ---------- mutations ----------
    def replace(self, items: Any, author: str = "Operator") -> Dict[str, Any]:
        """Replace all items. The current marker follows its item (by id) or is cleared."""
        cleaned = self._clean_items(items)
        with self._lock:
            old = self._read()
            current_id = None
            if old["current_index"] is not None:
                current_id = old["items"][old["current_index"]].get("id")
            new_index = next((i for i, it in enumerate(cleaned) if current_id and it["id"] == current_id), None)
            self._write({"items": cleaned, "current_index": new_index, "updated_at": time.time(),
                         "updated_by": self._text(author, "Người sửa", 60) or "Operator"})
        return self.get()

    def set_current(self, index: Optional[int], author: str = "Operator", segment_id: Optional[str] = None) -> Dict[str, Any]:
        """Mark which item is running. Planning data only — never switches the mixer."""
        with self._lock:
            data = self._read()
            if index is not None:
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(data["items"]):
                    raise ProgramError("Vị trí trong chương trình không hợp lệ.")
                item = data["items"][index]
                if segment_id is not None and item.get("segment_id") != segment_id:
                    raise ProgramError("Mục này không khớp với tiết mục vừa chuyển. Tải lại chương trình rồi thử lại.")
            data["current_index"] = index
            data["updated_at"] = time.time()
            data["updated_by"] = self._text(author, "Người sửa", 60) or "Operator"
            self._write(data)
        return self.get()

    def reset(self, author: str = "Operator") -> Dict[str, Any]:
        """Start of a new service: nothing is current."""
        return self.set_current(None, author=author)

    def restore_default(self) -> Dict[str, Any]:
        with self._lock:
            if os.path.exists(self.path):
                os.remove(self.path)
        return self.get()
