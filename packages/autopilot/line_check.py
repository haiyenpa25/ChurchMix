"""
Automatic line check ("Kiểm tra micro tự động"). READ-ONLY: never writes to the mixer.

Volunteers speak/sing into each microphone in turn for ~30 s while the telemetry loop
fills `MeterHistory` with X32 input meters (peak dBFS, post-trim, pre-fader, pre-mute).
`analyze()` then classifies every used channel over that window:

    OK         signal present, plausible level
    NO_SIGNAL  never above NO_SIGNAL_DBFS (cable, wireless battery, mute switch on the mic)
    CONSTANT   level present but nearly flat (hum/buzz, noise, a mic touching something)
    CLIPPING   peaks at/above CLIP_DBFS (preamp gain too high)
    LOW        active but peaks below LOW_PEAK_DBFS (mic far from mouth or gain too low)
    UNKNOWN    data untrusted (simulated/unmapped source) or not enough samples

Conclusions are only drawn from trusted data (`MeterHistory.trusted_for(...)`, AGENTS.md rule 8).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Thresholds (dBFS / dB). Meters report true silence as -90 dBFS.
NO_SIGNAL_DBFS = -70.0      # never above this in the window -> no signal
CONSTANT_FLOOR_DBFS = -65.0  # median above this ...
CONSTANT_RANGE_DB = 2.0      # ... and (peak - p10) below this -> suspiciously constant
CLIP_DBFS = -1.0            # peaks at/above -> clipping
LOW_PEAK_DBFS = -45.0       # active but peaks below -> too quiet
MIN_SAMPLES = 10            # per channel
MIN_COVERAGE_RATIO = 0.6    # history must cover >= 60 % of the requested window
MIN_COVERAGE_S = 3.0

MESSAGES_VI = {
    "OK": "Có tín hiệu tốt.",
    "NO_SIGNAL": "Không có tín hiệu — kiểm tra dây, pin micro không dây, nút mute trên micro.",
    "CONSTANT": "Tín hiệu đều bất thường — có thể ù/rè, nhiễu, hoặc micro bị chạm.",
    "CLIPPING": "Quá to — giảm gain preamp trên bàn.",
    "LOW": "Rất nhỏ — mic xa miệng hoặc gain thấp.",
    "UNKNOWN": "Chưa đủ dữ liệu tin cậy để kết luận.",
}

SPARE_ROLE = "GENERAL_INPUT"


def _is_spare(ch: Dict[str, Any]) -> bool:
    """A spare input: GENERAL_INPUT role with its default name ("Kênh N")."""
    if ch.get("role") != SPARE_ROLE:
        return False
    name = str(ch.get("name") or "").strip()
    return not name or name == f"Kênh {ch.get('channel')}"


def checked_channels(channels: List[Dict[str, Any]], talkback_channel: Optional[int]) -> List[Dict[str, Any]]:
    """Named/used channels; spares and the protected talkback channel are skipped."""
    out = []
    for ch in channels or []:
        n = int(ch.get("channel", 0))
        if not 1 <= n <= 32:
            continue
        if talkback_channel is not None and n == int(talkback_channel):
            continue
        if ch.get("role") == "TALKBACK_BAND" or _is_spare(ch):
            continue
        out.append(ch)
    return sorted(out, key=lambda c: int(c["channel"]))


def _percentile(sorted_levels: List[float], q: float) -> float:
    return sorted_levels[int(q * (len(sorted_levels) - 1))]


def classify(levels: List[float]) -> Dict[str, Any]:
    """Status and numbers for one channel's levels (dBFS). Pure function, no trust check."""
    if len(levels) < MIN_SAMPLES:
        return {"status": "UNKNOWN", "count": len(levels), "reason": "too_few_samples"}
    s = sorted(levels)
    peak, median, p10, p90 = s[-1], s[len(s) // 2], _percentile(s, 0.1), _percentile(s, 0.9)
    numbers = {"count": len(s), "peak_dbfs": round(peak, 1), "median_dbfs": round(median, 1),
               "p10_dbfs": round(p10, 1), "p90_dbfs": round(p90, 1),
               "spread_db": round(p90 - p10, 1), "range_db": round(peak - p10, 1)}
    if peak < NO_SIGNAL_DBFS:
        status = "NO_SIGNAL"
    elif peak >= CLIP_DBFS:
        status = "CLIPPING"
    elif median > CONSTANT_FLOOR_DBFS and (peak - p10) < CONSTANT_RANGE_DB:
        status = "CONSTANT"
    elif peak < LOW_PEAK_DBFS:
        status = "LOW"
    else:
        status = "OK"
    return {"status": status, **numbers}


def analyze(meter_history, channels: List[Dict[str, Any]], mixer_params: Optional[Dict[str, Any]] = None,
            seconds: float = 30.0, *, trusted: bool, talkback_channel: Optional[int] = None) -> Dict[str, Any]:
    """Classify every used channel over the last `seconds` of meter history.

    `trusted` must come from `meter_history.trusted_for(is_internal_simulator)`; when False
    every channel is UNKNOWN. `mixer_params` (snapshot parameters) is optional and only used
    to flag channels that are muted on the desk (meters are pre-mute).
    """
    seconds = float(seconds)
    coverage = float(meter_history.coverage_s())
    enough = coverage >= max(MIN_COVERAGE_S, MIN_COVERAGE_RATIO * seconds)
    window = min(seconds, coverage) if enough else 0.0
    source = dict(getattr(meter_history, "source", {}) or {})
    if not trusted:
        reason_vi = "Nguồn meter chưa được xác nhận (giả lập hoặc chưa ánh xạ kênh X32) — không kết luận."
    elif not enough:
        reason_vi = f"Mới có {coverage:.0f} giây dữ liệu meter (cần khoảng {seconds:.0f} giây). Thử lại sau."
    else:
        reason_vi = ""

    items = []
    params = mixer_params or {}
    for ch in checked_channels(channels, talkback_channel):
        n = int(ch["channel"])
        if trusted and enough:
            result = classify(meter_history.window(n, window))
        else:
            result = {"status": "UNKNOWN", "count": 0, "reason": "untrusted" if not trusted else "insufficient_window"}
        on = params.get(f"/ch/{n:02d}/mix/on")
        muted = on is not None and int(on) == 0
        msg = MESSAGES_VI[result["status"]]
        if result["status"] == "UNKNOWN" and reason_vi:
            msg = reason_vi
        hint = "Kênh đang tắt tiếng (mute) trên bàn — có tín hiệu nhưng chưa ra loa." if muted and result["status"] in ("OK", "LOW") else ""
        items.append({"channel": n, "name": ch.get("name", f"Kênh {n}"), "role": ch.get("role"),
                      "muted": muted, "message_vi": msg, "hint_vi": hint, **result})

    counts: Dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    problems = [it for it in items if it["status"] not in ("OK",)]
    if not trusted or not enough:
        summary = reason_vi
    elif not problems:
        summary = f"Tất cả {len(items)} micro/kênh đang dùng đều có tín hiệu tốt."
    else:
        summary = f"{len(items) - len(problems)}/{len(items)} kênh tốt — {len(problems)} kênh cần kiểm tra."
    return {
        "trusted": bool(trusted), "enough_data": enough, "requested_s": seconds, "window_s": round(window, 1),
        "coverage_s": round(coverage, 1), "source": {k: source.get(k) for k in ("id", "label", "simulated", "tap_point")},
        "talkback_channel": talkback_channel, "items": items, "counts": counts, "summary_vi": summary,
        "thresholds": {"no_signal_dbfs": NO_SIGNAL_DBFS, "clip_dbfs": CLIP_DBFS, "low_peak_dbfs": LOW_PEAK_DBFS,
                       "constant_floor_dbfs": CONSTANT_FLOOR_DBFS, "constant_range_db": CONSTANT_RANGE_DB},
        "read_only": True,
    }
