"""Bounded signal history and explainable threshold diagnostics."""
from collections import deque
from dataclasses import dataclass, asdict
import math
import threading
import time


@dataclass(frozen=True)
class Thresholds:
    warning_dbfs: float = -12.0
    critical_dbfs: float = -6.0
    clip_dbfs: float = -0.5

    def __post_init__(self):
        values = (self.warning_dbfs, self.critical_dbfs, self.clip_dbfs)
        if not all(math.isfinite(v) for v in values) or not -60 <= values[0] < values[1] < values[2] <= 0:
            raise ValueError("Ngưỡng phải thỏa -60 ≤ cảnh báo < nguy hiểm < sát clipping ≤ 0 dBFS.")


class SignalMonitor:
    """Up to 4Hz history for 120 seconds, 200 events, 32 inputs maximum.

    Durations describe sampled observations, not a sample-accurate clip counter.
    Sessions reset on source changes, threshold changes and invalid measurements.
    """
    def __init__(self):
        self.thresholds = Thresholds()
        self._lock = threading.RLock()
        self._signature = None
        self._latest = None
        self._history = deque(maxlen=480)
        self._events = deque(maxlen=200)
        self._stats = {}
        self._last_time = None
        self._last_history = -math.inf
        self._generation = 0

    def _reset(self):
        self._history.clear()
        self._events.clear()
        self._stats.clear()
        self._last_time = None
        self._last_history = -math.inf
        self._generation += 1

    def set_thresholds(self, thresholds):
        with self._lock:
            self.thresholds = thresholds
            self._reset()
            self._latest = None

    def classify(self, peak):
        if peak >= self.thresholds.clip_dbfs:
            return "CLIP_RISK"
        if peak >= self.thresholds.critical_dbfs:
            return "CRITICAL"
        if peak >= self.thresholds.warning_dbfs:
            return "WARNING"
        if peak < -60:
            return "SILENT"
        return "NORMAL"

    def ingest(self, meters, source, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            signature = (source.get("id"), source.get("valid"), source.get("sample_rate"))
            if signature != self._signature:
                self._reset()
                self._signature = signature
            delta = now - self._last_time if self._last_time is not None else 0
            if delta < 0 or delta > 1.0:
                self._reset()
                delta = 0
            self._last_time = now
            valid = bool(source.get("valid"))
            rows = []
            for meter in meters[:32]:
                ch = meter["channel"]
                peak, rms = meter.get("meter_dbfs"), meter.get("rms_dbfs")
                finite = lambda v: isinstance(v, (int, float)) and math.isfinite(v)
                # X32 meters carry peak only: rms None means "not provided", never invented.
                measured = valid and finite(peak) and (rms is None or finite(rms))
                status = self.classify(peak) if measured else "UNKNOWN"
                stats = self._stats.setdefault(ch, {"peak_hold_dbfs": None, "over_seconds": 0.0,
                    "critical_seconds": 0.0, "clip_events": 0, "status": "UNKNOWN", "streak_seconds": 0.0})
                previous = stats["status"]
                is_over = status in ("WARNING", "CRITICAL", "CLIP_RISK")
                if measured:
                    stats["peak_hold_dbfs"] = max(peak, stats["peak_hold_dbfs"] if stats["peak_hold_dbfs"] is not None else peak)
                    if is_over and previous in ("WARNING", "CRITICAL", "CLIP_RISK"):
                        stats["over_seconds"] += delta
                        stats["streak_seconds"] += delta
                    else:
                        stats["streak_seconds"] = 0.0
                    if status in ("CRITICAL", "CLIP_RISK") and previous in ("CRITICAL", "CLIP_RISK"):
                        stats["critical_seconds"] += delta
                    if status == "CLIP_RISK" and previous != "CLIP_RISK":
                        stats["clip_events"] += 1
                    if is_over and status != previous:
                        self._events.appendleft({"channel": ch, "name": meter.get("name", f"Input {ch}"),
                            "status": status, "peak_dbfs": peak, "timestamp": time.time()})
                else:
                    stats["streak_seconds"] = 0.0
                stats["status"] = status
                advice = {
                    "CLIP_RISK": "Tín hiệu sát giới hạn số. Kiểm tra gain ở nguồn và nghe méo tiếng; điều chỉnh thủ công sau khi xác nhận nguồn.",
                    "CRITICAL": "Headroom thấp. Kiểm tra các đoạn lớn nhất, kỹ thuật micro và gain nguồn trước khi cân chỉnh.",
                    "WARNING": "Mức peak vượt ngưỡng theo dõi. Quan sát diễn biến; một đỉnh ngắn chưa chứng minh thiết bị lỗi.",
                    "SILENT": "Đang ít hoặc không có tín hiệu. Có thể là khoảng nghỉ; không tự tăng fader.",
                    "UNKNOWN": "Không đủ dữ liệu hợp lệ. Kiểm tra kết nối, buffer và ánh xạ nguồn trước khi kết luận.",
                    "NORMAL": "Mức peak dưới ngưỡng theo dõi. Điều này không xác nhận routing an toàn hay không có nguy cơ hú.",
                }[status]
                rows.append({"channel": ch, "name": meter.get("name", f"Input {ch}"),
                    "peak_dbfs": peak if measured else None, "rms_dbfs": rms if measured else None,
                    "headroom_db": round(-peak, 1) if measured else None,
                    "crest_db": round(max(0, peak - rms), 1) if measured and rms is not None else None,
                    "status": status, "measured": measured,
                    **{k: round(v, 2) if isinstance(v, float) else v for k, v in stats.items() if k != "status"},
                    "advice": advice})
            counts = {s: sum(r["status"] == s for r in rows) for s in
                      ("NORMAL", "WARNING", "CRITICAL", "CLIP_RISK", "SILENT", "UNKNOWN")}
            self._latest = {"source": dict(source), "channels": rows, "counts": counts,
                "thresholds": asdict(self.thresholds), "session": self._generation,
                "sampled_at": time.time(), "history_window_s": 120,
                "duration_note": "Thời gian ước lượng từ các khung quan sát; không phải số sample clipping.",
                "_monotonic": now}
            if now - self._last_history >= 0.25:
                self._last_history = now
                self._history.append({"t": now, "levels": [
                    {"channel": r["channel"], "peak_dbfs": r["peak_dbfs"], "rms_dbfs": r["rms_dbfs"]} for r in rows]})
            return self.snapshot(now=now, include_history=False)

    def snapshot(self, channel=None, now=None, include_history=True):
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._latest is None:
                return {"source": {"valid": False, "label": "Chưa có dữ liệu", "reasons": ["Đang chờ khung đo"]},
                    "channels": [], "counts": {}, "history": [], "events": [],
                    "thresholds": asdict(self.thresholds), "session": self._generation}
            result = {k: v for k, v in self._latest.items() if k != "_monotonic"}
            result["age_s"] = round(max(0, now - self._latest["_monotonic"]), 2)
            result["stale"] = result["age_s"] > 1.0
            if result["stale"]:
                result["source"] = {**result["source"], "valid": False,
                    "reasons": ["Luồng đo không cập nhật quá 1 giây"]}
                result["channels"] = [{**r, "measured": False, "status": "UNKNOWN",
                    "peak_dbfs": None, "rms_dbfs": None, "headroom_db": None, "crest_db": None,
                    "advice": "Dữ liệu đã cũ; không kết luận từ mức tín hiệu trước đó."} for r in result["channels"]]
                result["counts"] = {"UNKNOWN": len(result["channels"])}
            result["history"] = [{"seconds_ago": round(max(0, now - frame["t"]), 2),
                "levels": [r for r in frame["levels"] if channel is None or r["channel"] == channel]}
                for frame in self._history if include_history and 0 <= now - frame["t"] <= 120]
            result["events"] = [dict(e) for e in self._events if channel is None or e["channel"] == channel]
            return result
