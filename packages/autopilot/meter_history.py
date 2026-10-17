"""
Rolling per-channel meter history (last ~30 s), fed by the telemetry loop.

Shared by the phase-2 features (segment detection, automatic line check,
automatic soundcheck). Read-only: it only stores what the meters reported.

Each sample: (monotonic_ts, peak_dbfs | None). Only samples from a VALID source
are stored; the source id/label of the latest frame is kept so consumers can
refuse to conclude anything from simulated or unmapped data.
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Tuple

DEFAULT_WINDOW_S = 30.0


class MeterHistory:
    def __init__(self, window_s: float = DEFAULT_WINDOW_S, clock=time.monotonic):
        self.window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._samples: Dict[int, Deque[Tuple[float, Optional[float]]]] = collections.defaultdict(collections.deque)
        self.source: Dict[str, Any] = {}
        self.source_since: Optional[float] = None

    def add(self, meters: List[Dict[str, Any]], source: Dict[str, Any]) -> None:
        now = self._clock()
        with self._lock:
            if not source or not source.get("valid"):
                self.source = dict(source or {})
                self.source_since = None
                return
            if source.get("id") != self.source.get("id") or self.source_since is None:
                self._samples.clear()   # never mix measurements from different sources
                self.source_since = now
            self.source = {k: source.get(k) for k in ("id", "label", "valid", "simulated", "mapping_verified", "tap_point")}
            for m in meters or []:
                level = m.get("meter_dbfs")
                if level is not None and not math.isfinite(level):
                    level = None
                dq = self._samples[int(m["channel"])]
                dq.append((now, level))
                cutoff = now - self.window_s
                while dq and dq[0][0] < cutoff:
                    dq.popleft()

    def window(self, channel: int, seconds: float) -> List[float]:
        """Measured levels (dBFS) of one channel in the last `seconds` (None values dropped)."""
        cutoff = self._clock() - seconds
        with self._lock:
            return [lvl for t, lvl in self._samples.get(int(channel), ()) if t >= cutoff and lvl is not None]

    def coverage_s(self) -> float:
        """Seconds of continuous history from the current valid source."""
        if self.source_since is None:
            return 0.0
        return min(self.window_s, self._clock() - self.source_since)

    def stats(self, channel: int, seconds: float) -> Dict[str, Any]:
        levels = self.window(channel, seconds)
        if not levels:
            return {"channel": channel, "count": 0}
        s = sorted(levels)
        n = len(s)
        return {
            "channel": channel,
            "count": n,
            "peak_dbfs": round(s[-1], 1),
            "p90_dbfs": round(s[int(0.9 * (n - 1))], 1),
            "median_dbfs": round(s[n // 2], 1),
            "min_dbfs": round(s[0], 1),
            "spread_db": round(s[int(0.9 * (n - 1))] - s[int(0.1 * (n - 1))], 1),
        }

    def trusted_for(self, is_simulator: bool) -> bool:
        """Conclusions are allowed only from valid data mapped to X32 channels (or the mock)."""
        s = self.source
        if not s.get("valid"):
            return False
        if s.get("simulated"):
            return bool(is_simulator)
        return bool(s.get("mapping_verified"))
