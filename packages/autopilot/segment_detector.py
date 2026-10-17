"""
Segment suggestion ("Tự nhận diện tiết mục"): guesses which service segment is
happening from which microphones / instruments carry sound, and SUGGESTS it.

It never switches anything (AGENTS.md rule 7): the operator taps the suggestion
and the normal preview + confirm + Safety Gate flow (switchToSegment) applies it.

How it works (every ~1 s, from MeterHistory):
1. For each managed channel (in some segment, not talkback, not a spare input)
   take the last WINDOW_S seconds of input levels.
2. A channel is ACTIVE when its level is sustained above a role threshold
   (>= MIN_ACTIVE_FRACTION of samples) AND its 90th percentile is within a
   role-specific margin of the loudest channel.
   Why relative: X32 input meters are post-preamp but PRE-fader and PRE-mute,
   so a muted pastor mic on stage still shows band bleed. Bleed is normally
   well below the source that is really playing, so we compare against the
   loudest channel. DI instruments (keys, bass, DI guitar) have no acoustic
   bleed and get a wide margin; choir overheads pick up everything and get a
   narrow one.
3. Each segment is scored by agreement of its ON/OFF set with the active set.
   Active channels weigh more than silent ones (silence is weak evidence: a
   pianist may simply rest during prayer).
4. A suggestion is published only if: data is trusted (valid source mapped to
   X32 channels, or the internal simulator), history covers >= WINDOW_S, the
   current segment is known, the best segment differs from it, scores >=
   MIN_SCORE, beats the current one by MARGIN and the runner-up by a little,
   and the same winner held for >= STABLE_S.

Limits (documented for operators, see reason_vi):
- Cannot tell two segments apart that open the same channels (e.g. Đơn ca vs
  Tốp ca with the same mics) or that differ only in channels with no signal.
- Loud stage bleed into a muted mic (singer next to a drum kit) can look active.
- Only sees channels that report a level; unpatched inputs are ignored.
- Total silence gives no suggestion.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

WINDOW_S = 8.0
STABLE_S = 5.0
MIN_SCORE = 0.75
MARGIN = 0.2            # best must beat the current segment by this much
RUNNER_UP_MARGIN = 0.05  # and be clearly better than the second best
EVAL_INTERVAL_S = 1.0
ACTIVE_REFRESH_S = 4.0
MIN_ACTIVE_FRACTION = 0.25
MIN_SAMPLES = 10

UNMANAGED_ROLES = {"TALKBACK_BAND", "GENERAL_INPUT"}

# role -> (absolute threshold dBFS, max dB below the loudest channel)
ROLE_RULES = {
    "PASTOR_SPEECH": (-42.0, 22.0),
    "LEAD_VOCAL_FEMALE": (-42.0, 20.0),
    "LEAD_VOCAL_MALE": (-42.0, 20.0),
    "CHOIR_OVERHEAD": (-40.0, 12.0),
    "DRUMS": (-38.0, 18.0),
    "PIANO_KEYS": (-48.0, 30.0),
    "BASS_GUITAR": (-48.0, 30.0),
    "ACOUSTIC_GUITAR": (-48.0, 28.0),
    "ELECTRIC_GUITAR": (-46.0, 24.0),
}
DEFAULT_RULE = (-42.0, 20.0)

W_ACTIVE = 1.0
W_SILENT = 0.4


def _p90(levels: List[float]) -> float:
    s = sorted(levels)
    return s[int(0.9 * (len(s) - 1))]


def classify_channels(history, channels: List[int], roles: Dict[int, str], window_s: float = WINDOW_S) -> Dict[int, Dict[str, Any]]:
    """{channel: {active, p90_dbfs, fraction}} for channels with enough samples."""
    raw = {}
    for ch in channels:
        levels = history.window(ch, window_s)
        if len(levels) >= MIN_SAMPLES:
            raw[ch] = levels
    if not raw:
        return {}
    p90s = {ch: _p90(lv) for ch, lv in raw.items()}
    loudest = max(p90s.values())
    out = {}
    for ch, levels in raw.items():
        threshold, margin = ROLE_RULES.get(roles.get(ch, ""), DEFAULT_RULE)
        fraction = sum(1 for lv in levels if lv >= threshold) / len(levels)
        active = fraction >= MIN_ACTIVE_FRACTION and p90s[ch] >= threshold and p90s[ch] >= loudest - margin
        out[ch] = {"active": active, "p90_dbfs": round(p90s[ch], 1), "fraction": round(fraction, 2)}
    return out


def score_segment(segment: Dict[str, Any], observed: Dict[int, Dict[str, Any]]) -> Optional[float]:
    """Weighted agreement 0..1 between the segment's ON/OFF set and the observed activity."""
    agree = total = 0.0
    for key, on in (segment.get("channels") or {}).items():
        obs = observed.get(int(key))
        if obs is None:
            continue
        w = W_ACTIVE if obs["active"] else W_SILENT
        total += w
        if bool(int(on)) == obs["active"]:
            agree += w
    return None if total == 0 else agree / total


class SegmentDetector:
    def __init__(self, history, segment_provider: Callable[[], List[Dict[str, Any]]],
                 channel_provider: Callable[[], List[Dict[str, Any]]],
                 trusted_provider: Callable[[], bool],
                 active_provider: Callable[[], Optional[str]],
                 talkback_provider: Callable[[], int] = lambda: 11,
                 clock=time.monotonic, wall_clock=time.time, run_inline: bool = False):
        self._history = history
        self._segments = segment_provider
        self._channels = channel_provider
        self._trusted = trusted_provider
        self._active_provider = active_provider
        self._talkback = talkback_provider
        self._clock = clock
        self._wall = wall_clock
        self._run_inline = run_inline
        self._lock = threading.Lock()
        self._last_eval = -float("inf")
        self._active_id: Optional[str] = None
        self._active_known = False
        self._active_at = -float("inf")
        self._refreshing = False
        self._candidate: Optional[str] = None
        self._candidate_since: Optional[float] = None
        self.suggestion: Optional[Dict[str, Any]] = None
        self.state: Dict[str, Any] = {"reason": "Đang khởi động", "scores": [], "active_channels": []}

    # ---------- current segment (mixer mute state, read-only) ----------
    def invalidate_active(self) -> None:
        """Call after a segment switch so the next tick re-reads the mixer."""
        with self._lock:
            self._active_at = -float("inf")
            self._candidate = None
            self._candidate_since = None
            self.suggestion = None

    def _refresh_active(self) -> None:
        try:
            value, known = self._active_provider(), True
        except Exception:
            value, known = None, False
        with self._lock:
            self._active_id, self._active_known = value, known
            self._active_at = self._clock()
            self._refreshing = False

    def _maybe_refresh_active(self, now: float) -> None:
        with self._lock:
            if self._refreshing or now - self._active_at < ACTIVE_REFRESH_S:
                return
            self._refreshing = True
        if self._run_inline:
            self._refresh_active()
        else:
            threading.Thread(target=self._refresh_active, daemon=True, name="SegmentDetectorActive").start()

    # ---------- main loop ----------
    def tick(self) -> Optional[Dict[str, Any]]:
        now = self._clock()
        if now - self._last_eval < EVAL_INTERVAL_S:
            return self.suggestion
        self._last_eval = now
        self._maybe_refresh_active(now)
        winner, state = self._evaluate()
        with self._lock:
            if winner is None:
                self._candidate = None
                self._candidate_since = None
                self.suggestion = None
            else:
                if winner["segment_id"] != self._candidate:
                    self._candidate = winner["segment_id"]
                    self._candidate_since = now
                held = now - self._candidate_since
                state["stable_s"] = round(held, 1)
                if held >= STABLE_S:
                    since = self._wall() - held
                    self.suggestion = {**winner, "since": round(since, 1)}
                else:
                    self.suggestion = None
                    state["reason"] = f"Đang chờ ổn định ({held:.0f}/{STABLE_S:.0f} giây)"
            self.state = state
        return self.suggestion

    def _evaluate(self):
        state: Dict[str, Any] = {"reason": "", "scores": [], "active_channels": [], "active_segment_id": None}
        if not self._trusted():
            state["reason"] = "Dữ liệu đo chưa đáng tin (chưa đúng kênh X32) — không đoán."
            return None, state
        coverage = self._history.coverage_s()
        if coverage < WINDOW_S:
            state["reason"] = f"Chưa đủ dữ liệu ({coverage:.0f}/{WINDOW_S:.0f} giây)."
            return None, state
        with self._lock:
            active_id, known = self._active_id, self._active_known
        state["active_segment_id"] = active_id
        if not known:
            state["reason"] = "Chưa đọc được trạng thái micro trên mixer."
            return None, state

        tb = self._talkback()
        chans = self._channels()
        roles = {int(c["channel"]): c.get("role", "GENERAL_INPUT") for c in chans}
        names = {int(c["channel"]): c.get("name", f"Kênh {c['channel']}") for c in chans}
        segments = self._segments()
        managed = sorted({int(k) for s in segments for k in (s.get("channels") or {})
                          if int(k) != tb and roles.get(int(k)) not in UNMANAGED_ROLES})
        observed = classify_channels(self._history, managed, roles)
        active = [ch for ch, o in observed.items() if o["active"]]
        state["active_channels"] = [{"channel": ch, "name": names.get(ch, f"Kênh {ch}"), **observed[ch]} for ch in sorted(active)]
        if not active:
            state["reason"] = "Không có micro nào đang có tiếng rõ — không đoán."
            return None, state

        scored = []
        for s in segments:
            sc = score_segment(s, observed)
            if sc is not None:
                scored.append((sc, s))
        scored.sort(key=lambda x: -x[0])
        state["scores"] = [{"segment_id": s["id"], "name": s.get("name", s["id"]), "score": round(sc, 2)} for sc, s in scored]
        if not scored:
            state["reason"] = "Không có tiết mục nào để so."
            return None, state
        best_score, best = scored[0]
        current_score = next((sc for sc, s in scored if s["id"] == active_id), 0.0)
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best["id"] == active_id:
            state["reason"] = "Mixer đang đúng tiết mục phù hợp nhất."
            return None, state
        if best_score < MIN_SCORE:
            state["reason"] = "Không tiết mục nào khớp đủ rõ."
            return None, state
        if best_score - current_score < MARGIN:
            state["reason"] = "Tiết mục hiện tại vẫn khớp gần bằng — không đổi."
            return None, state
        if best_score - runner_up < RUNNER_UP_MARGIN:
            state["reason"] = "Có hai tiết mục khớp gần như nhau — không đoán."
            return None, state

        heard = [names.get(ch, f"Kênh {ch}") for ch in sorted(active)]
        listed = ", ".join(heard[:4]) + (f" và {len(heard) - 4} kênh khác" if len(heard) > 4 else "")
        reason = f"Trong {WINDOW_S:.0f} giây qua có tiếng ở: {listed}."
        state["reason"] = "Có gợi ý."
        return {"segment_id": best["id"], "name": best.get("name", best["id"]),
                "confidence": round(best_score, 2), "reason_vi": reason}, state

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"suggestion": self.suggestion, **self.state}
