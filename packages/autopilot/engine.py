"""
Autopilot ("Lái tự động") — bounded autonomous mixing assistance.

Turning the autopilot on puts the Safety Engine in LIMITED_AUTO. That is the
operator's PRE-APPROVAL for adjustments inside the limits in
configs/safety-defaults.yaml (autopilot section). Anything outside those limits
is only reported; a human decides (AGENTS.md rule 7, as amended).

Principles that protect the natural sound:
- The machine never designs the sound. It keeps the mix near the operator's
  reference (segment reference fader, or the fader position when enabled).
- Levels and narrow cuts only. Never an EQ boost, never preamp/routing/main bus.
- Small, slow steps with per-feature budgets; never raise a level during silence
  (Silence Hold) or while any feedback is detected.
- If the operator moves a fader by hand, the autopilot follows the new position
  instead of fighting it.
- Every write goes through TransactionExecutor (snapshot lock, talkback
  invariant, paced writes, readback, rollback) and is audit-logged.
- STOP, any mode change or auto-disengage pauses the autopilot immediately.

Features:
- speech_rider:  keeps speech microphones (role PASTOR_SPEECH) at a steady level.
- auto_notch:    applies a narrow notch for confident feedback, with a budget,
                 only into a free EQ band; never overwrites a band in use.
- livestream:    keeps the livestream bus near its loudness target (only with a
                 verified livestream-bus measurement, or in the simulator).
- clip_watch:    warns about input clipping (preamp is never touched).
"""

from __future__ import annotations

import collections
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Deque, Dict, List, Optional

from packages.autopilot.x32_scale import db_to_fader, fader_to_db
from packages.feedback_detector.detector import FeedbackCandidate
from packages.safety_controller.modes import OperatorMode
from packages.safety_controller.routing import get_talkback_channel
from packages.safety_controller.transaction import Proposal

FEATURES = ("speech_rider", "auto_notch", "livestream", "clip_watch")

DEFAULT_CONFIG: Dict[str, Any] = {
    "livestream_bus": 5,
    "speech_rider": {"max_offset_db": 3.0, "step_db": 0.5, "min_interval_s": 2.0, "target_level_dbfs": -18.0,
                     "deadband_db": 2.0, "speech_threshold_dbfs": -45.0, "min_speech_s": 1.5},
    "auto_notch": {"budget_per_channel": 2, "min_confidence": 0.85, "allowed_severities": ["MEDIUM", "HIGH"]},
    "livestream": {"target_lufs": -16.0, "deadband_db": 2.0, "step_db": 0.5, "min_interval_s": 5.0, "max_offset_db": 6.0},
    "clip_watch": {"peak_dbfs": -1.0, "frames": 3},
}

# Hard ceilings: config files cannot loosen these.
HARD_CAPS = {
    ("speech_rider", "max_offset_db"): 6.0,
    ("speech_rider", "step_db"): 1.0,
    ("speech_rider", "min_interval_s"): -1.0,   # negative = floor: at least 1.0 s between moves
    ("auto_notch", "budget_per_channel"): 3,
    ("livestream", "max_offset_db"): 9.0,
    ("livestream", "step_db"): 1.0,
}
MIXER_REFRESH_S = 5.0
SPEECH_ROLE = "PASTOR_SPEECH"
NOTCH_SPACING_OCT = 1.0 / 6.0
MIN_RIDE_FADER = 0.0625  # below −60 dB the operator has the channel parked; do not ride it


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    try:
        import yaml
        path = path or os.path.join(os.path.dirname(__file__), "..", "..", "configs", "safety-defaults.yaml")
        with open(path, "r", encoding="utf-8") as f:
            raw = (yaml.safe_load(f) or {}).get("autopilot") or {}
        for key, value in raw.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    except Exception:
        pass
    return apply_hard_caps(cfg)


def apply_hard_caps(cfg: Dict[str, Any]) -> Dict[str, Any]:
    for (section, key), cap in HARD_CAPS.items():
        value = cfg.get(section, {}).get(key)
        if value is None:
            continue
        if cap < 0:
            cfg[section][key] = max(abs(cap), float(value))
        else:
            cfg[section][key] = min(cap, value)
    return cfg


def _octaves_apart(a: float, b: float) -> float:
    return abs(math.log2(max(a, 1.0) / max(b, 1.0)))


class Autopilot:
    def __init__(
        self,
        get_client: Callable[[], Any],
        get_executor: Callable[[], Any],
        mode_manager,
        channel_provider: Callable[[], List[Dict[str, Any]]],
        recommender,
        is_simulator: Callable[[], bool],
        reference_provider: Optional[Callable[[Dict[str, Any]], Dict[int, float]]] = None,
        loudness_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        audit: Optional[Callable[..., Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        run_inline: bool = False,
    ):
        self._get_client = get_client
        self._get_executor = get_executor
        self.mode_manager = mode_manager
        self._channels = channel_provider
        self._recommender = recommender
        self._is_simulator = is_simulator
        self._reference_provider = reference_provider
        self._loudness = loudness_provider
        self._audit = audit
        self.config = apply_hard_caps(config) if config else load_config()
        self._clock = clock
        self._run_inline = run_inline
        self._pool = None if run_inline else ThreadPoolExecutor(max_workers=1, thread_name_prefix="autopilot")
        self._lock = threading.RLock()
        self._busy = False

        self.enabled = False
        self.enabled_by: Optional[str] = None
        self.features = {name: True for name in FEATURES}
        self.inactive_reason = "Chưa bật lái tự động."
        self.log: Deque[Dict[str, Any]] = collections.deque(maxlen=200)
        self.alerts: Dict[str, Dict[str, Any]] = {}

        self._params: Dict[str, Any] = {}
        self._params_sha: Optional[str] = None
        self._params_at = -math.inf
        self.riders: Dict[int, Dict[str, Any]] = {}
        self.notches: List[Dict[str, Any]] = []
        self.livestream_state: Dict[str, Any] = {"anchor": None, "offset_db": 0.0, "last_action": -math.inf,
                                                 "lufs": None, "status": "Chưa đo."}
        self._clip_history: Dict[int, Deque[bool]] = {}
        self._last_source: Dict[str, Any] = {}
        mode_manager.add_listener(self._on_mode_change)

    # ------------------------------------------------------------------ control
    def enable(self, operator: str, features: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        if self._get_client() is None or self._get_executor() is None:
            raise RuntimeError("Chưa kết nối mixer.")
        with self._lock:
            if features:
                for name, on in features.items():
                    if name in FEATURES:
                        self.features[name] = bool(on)
            self.riders.clear()
            self.livestream_state.update(anchor=None, offset_db=0.0, last_action=-math.inf)
            self._clip_history.clear()
            self.alerts.clear()
        self.mode_manager.set_mode(OperatorMode.LIMITED_AUTO, operator=operator)
        with self._lock:
            self.enabled = True
            self.enabled_by = operator
            self.inactive_reason = ""
        self._refresh_mixer(force=True)
        self._log("system", None, f"Bật lái tự động ({operator}). Máy chỉ chỉnh trong giới hạn đã duyệt trước.", "INFO")
        self._audit_event(operator, "AUTOPILOT_ENABLED", "ENGAGED", {"features": dict(self.features)})
        return self.status()

    def disable(self, operator: str, reason: str = "Người vận hành tắt lái tự động.") -> Dict[str, Any]:
        with self._lock:
            was = self.enabled
            self.enabled = False
            self.inactive_reason = reason
        if was:
            self.mode_manager.set_mode(OperatorMode.OBSERVE, operator=operator)
            self._log("system", None, reason, "INFO")
            self._audit_event(operator, "AUTOPILOT_DISABLED", "DISENGAGED", {"reason": reason})
        return self.status()

    def set_feature(self, name: str, enabled: bool, operator: str) -> Dict[str, Any]:
        if name not in FEATURES:
            raise ValueError(f"Tính năng không hợp lệ: {name}")
        with self._lock:
            self.features[name] = bool(enabled)
        self._log(name, None, f"{'Bật' if enabled else 'Tắt'} tính năng ({operator}).", "INFO")
        return self.status()

    def _on_mode_change(self, state) -> None:
        stopped = False
        with self._lock:
            if not self.enabled:
                return
            if state.current_mode != OperatorMode.LIMITED_AUTO or state.is_disengaged:
                self.enabled = False
                stopped = True
                if state.is_disengaged:
                    self.inactive_reason = f"Tự ngắt an toàn: {state.disengage_detail or state.disengage_reason}"
                else:
                    self.inactive_reason = f"Chế độ đổi sang {state.current_mode.value} — lái tự động đã dừng."
        if stopped:
            self._log("system", None, self.inactive_reason, "STOPPED")

    # ------------------------------------------------------------------ tick
    def tick(self, meters: List[Dict[str, Any]], alerts: List[Dict[str, Any]], source: Dict[str, Any]) -> None:
        """Called from the telemetry loop (~10 Hz). Decides quickly; writes happen in a worker."""
        now = self._clock()
        self._last_source = source or {}
        if self.features.get("clip_watch"):
            self._watch_clips(meters)
        if not self.enabled:
            return
        if not self._measurement_trusted(source):
            self.inactive_reason = "Đang chờ dữ liệu đo hợp lệ (đúng kênh X32) — tạm không chỉnh."
            return
        self.inactive_reason = ""

        task = None
        with self._lock:
            if self._busy:
                self._update_rider_levels(meters, now)
                return
            if self.features.get("auto_notch"):
                task = self._plan_notch(alerts)
            if task is None and self.features.get("speech_rider"):
                task = self._plan_rider(meters, alerts, now)
            if (task is None and self.features.get("livestream")
                    and now - self.livestream_state["last_action"] >= self.config["livestream"]["min_interval_s"]):
                task = ("livestream", None)
            if task is None and now - self._params_at >= MIXER_REFRESH_S:
                task = ("refresh", None)
            if task is not None:
                self._busy = True
        if task is not None:
            self._dispatch(task)

    def _measurement_trusted(self, source: Dict[str, Any]) -> bool:
        if not source or not source.get("valid"):
            return False
        if source.get("simulated"):
            return bool(self._is_simulator())
        # Real data must map to X32 channels; an unmapped USB input must never drive a fader.
        return bool(source.get("mapping_verified"))

    def _dispatch(self, task) -> None:
        if self._run_inline:
            self._run_task(task)
        else:
            self._pool.submit(self._run_task, task)

    def _run_task(self, task) -> None:
        kind, arg = task
        try:
            if kind == "refresh":
                self._refresh_mixer(force=True)
            elif kind == "rider":
                self._do_rider(*arg)
            elif kind == "notch":
                self._do_notch(arg)
            elif kind == "livestream":
                self._do_livestream()
        except Exception as exc:  # never let a worker exception kill the loop
            self._log(kind, None, f"Lỗi: {exc}", "FAILED")
        finally:
            with self._lock:
                self._busy = False

    # ------------------------------------------------------------------ mixer state
    def _refresh_mixer(self, force: bool = False) -> Dict[str, Any]:
        now = self._clock()
        if not force and now - self._params_at < 1.5 and self._params:
            return self._params
        client = self._get_client()
        snap = client.take_full_snapshot(max_channels=32)
        with self._lock:
            self._params = snap.parameters
            self._params_sha = snap.sha256
            self._params_at = now
            self._sync_riders()
        return self._params

    def _sync_riders(self) -> None:
        """Track which speech mics are open; respect manual fader moves by re-anchoring."""
        tb = get_talkback_channel()
        speech = {int(c["channel"]): c.get("name", f"Kênh {c['channel']}") for c in self._channels()
                  if c.get("role") == SPEECH_ROLE and int(c["channel"]) != tb}
        refs: Dict[int, float] = {}
        if self._reference_provider:
            try:
                refs = self._reference_provider(self._params) or {}
            except Exception:
                refs = {}
        for ch, name in speech.items():
            on = int(self._params.get(f"/ch/{ch:02d}/mix/on", 0)) == 1
            fader = self._params.get(f"/ch/{ch:02d}/mix/fader")
            if fader is None:
                continue
            fader = float(fader)
            r = self.riders.get(ch)
            if r is None:
                anchor = float(refs.get(ch, fader))
                self.riders[ch] = r = {"channel": ch, "name": name, "anchor": anchor, "offset_db": 0.0,
                                       "expected": fader, "ema": None, "speaking_since": None,
                                       "last_action": -math.inf, "level": None, "on": on}
                if abs(anchor - fader) > 1e-3 and anchor > 0 and fader > 0:
                    r["offset_db"] = fader_to_db(fader) - fader_to_db(anchor)
            r["on"] = on
            r["name"] = name
            if abs(fader - r["expected"]) > 0.006:  # ~0.25 dB near unity: the operator moved it by hand
                r["anchor"] = fader
                r["offset_db"] = 0.0
                self._log("speech_rider", ch, f"Người vận hành chỉnh tay {name} — máy giữ theo mức mới.", "INFO")
            r["expected"] = fader
        for ch in list(self.riders):
            if ch not in speech:
                del self.riders[ch]

    # ------------------------------------------------------------------ speech rider
    def _update_rider_levels(self, meters, now) -> None:
        cfg = self.config["speech_rider"]
        by_ch = {int(m["channel"]): m for m in meters or []}
        for ch, r in self.riders.items():
            m = by_ch.get(ch)
            level = None
            if m is not None:
                level = m.get("rms_dbfs") if m.get("rms_dbfs") is not None else m.get("meter_dbfs")
            r["level"] = level
            if level is None or level < cfg["speech_threshold_dbfs"] or not r["on"]:
                r["speaking_since"] = None  # silence → Silence Hold
                continue
            if r["speaking_since"] is None:
                r["speaking_since"] = now
            r["ema"] = level if r["ema"] is None else 0.85 * r["ema"] + 0.15 * level

    def _plan_rider(self, meters, alerts, now):
        cfg = self.config["speech_rider"]
        self._update_rider_levels(meters, now)
        any_feedback = bool(alerts)
        for ch, r in self.riders.items():
            if not r["on"] or r["speaking_since"] is None or r["ema"] is None or r["anchor"] < MIN_RIDE_FADER:
                continue
            if now - r["speaking_since"] < cfg["min_speech_s"] or now - r["last_action"] < cfg["min_interval_s"]:
                continue
            # Input meters are pre-fader: the heard level ≈ input + our fader offset.
            error = cfg["target_level_dbfs"] - (r["ema"] + r["offset_db"])
            if abs(error) <= cfg["deadband_db"]:
                continue
            if error > 0 and any_feedback:
                continue  # never raise while feedback is present
            step = math.copysign(min(cfg["step_db"], abs(error)), error)
            new_offset = max(-cfg["max_offset_db"], min(cfg["max_offset_db"], r["offset_db"] + step))
            if abs(new_offset - r["offset_db"]) < 0.05:
                self._set_alert(f"rider-limit-{ch}", "speech_rider", ch,
                                f"{r['name']}: đã chạm giới hạn ±{cfg['max_offset_db']:.0f} dB. Cần người kiểm tra gain/vị trí micro.")
                continue
            return ("rider", (ch, new_offset))
        return None

    def _do_rider(self, ch: int, new_offset: float) -> None:
        params = self._refresh_mixer()
        with self._lock:
            r = self.riders.get(ch)
            if r is None or not r["on"]:
                return
            current = params.get(f"/ch/{ch:02d}/mix/fader")
            target = db_to_fader(fader_to_db(r["anchor"]) + new_offset)
            name = r["name"]
        if current is None or abs(target - float(current)) < 0.002:
            return
        proposal = Proposal(
            proposal_id=f"AUTO_RIDE_CH{ch:02d}_{int(time.time() * 1000)}",
            target_channel=ch,
            hypothesis=f"Lái tự động: giữ giọng {name} đều (lệch {new_offset:+.1f} dB so với mức chuẩn)",
            confidence=1.0,
            changes=[{"parameter": f"/ch/{ch:02d}/mix/fader", "from": float(current), "to": target}],
            expected_sha256=self._params_sha,
        )
        if self._execute(proposal, "speech_rider", ch):
            with self._lock:
                old = r["offset_db"]
                r["offset_db"] = new_offset
                r["expected"] = target
                r["last_action"] = self._clock()
                self._params[f"/ch/{ch:02d}/mix/fader"] = target
                self._params_at = -math.inf  # SHA changed; refresh before the next action
            self._log("speech_rider", ch, f"{name}: {'tăng' if new_offset > old else 'giảm'} {abs(new_offset - old):.1f} dB "
                      f"(lệch {new_offset:+.1f} dB so với chuẩn).", "APPLIED")

    # ------------------------------------------------------------------ auto notch
    def _plan_notch(self, alerts):
        cfg = self.config["auto_notch"]
        allowed = [s.upper() for s in cfg["allowed_severities"]]
        for a in alerts or []:
            if a.get("simulated") and not self._is_simulator():
                continue
            if str(a.get("severity", "")).upper() not in allowed:
                continue
            if float(a.get("confidence", 0)) < cfg["min_confidence"]:
                continue
            ch, freq = int(a["channel_id"]), float(a["freq_hz"])
            if ch == get_talkback_channel():
                continue
            mine = [n for n in self.notches if n["channel"] == ch]
            if any(_octaves_apart(n["freq_hz"], freq) < NOTCH_SPACING_OCT for n in mine):
                continue
            if len(mine) >= cfg["budget_per_channel"]:
                self._set_alert(f"notch-budget-{ch}", "auto_notch", ch,
                                f"Kênh {ch}: đã dùng hết {cfg['budget_per_channel']} lần cắt tự động. Cần người xử lý vị trí micro/loa.")
                continue
            if f"notch-noband-{ch}-{int(freq)}" in self.alerts:
                continue
            return ("notch", a)
        return None

    def _do_notch(self, alert: Dict[str, Any]) -> None:
        params = self._refresh_mixer(force=True)
        ch, freq = int(alert["channel_id"]), float(alert["freq_hz"])
        cand = FeedbackCandidate(channel_id=ch, freq_hz=freq, confidence=float(alert.get("confidence", 0.9)),
                                 severity=str(alert.get("severity", "HIGH")), level_dbfs=float(alert.get("level_dbfs") or -20.0),
                                 persistence_frames=4, is_musical_note=False, evidence=list(alert.get("evidence") or []),
                                 recommended_action="auto notch")
        proposal = self._recommender.recommend_feedback_notch(cand, expected_sha256=self._params_sha, current_parameters=params)
        if "GHI ĐÈ" in proposal.hypothesis:
            self._set_alert(f"notch-noband-{ch}-{int(freq)}", "auto_notch", ch,
                            f"Kênh {ch}: hú {freq:.0f} Hz nhưng không còn dải EQ trống — máy không ghi đè EQ, cần người quyết định.")
            return
        proposal.proposal_id = f"AUTO_NOTCH_CH{ch:02d}_{int(freq)}_{int(time.time() * 1000)}"
        proposal.hypothesis = "Lái tự động: " + proposal.hypothesis
        band = int(proposal.changes[0]["parameter"].split("/")[4])
        original = {c["parameter"]: c["from"] for c in proposal.changes}
        if self._execute(proposal, "auto_notch", ch):
            with self._lock:
                self.notches.append({"channel": ch, "band": band, "freq_hz": freq, "original": original,
                                     "applied": {c["parameter"]: c["to"] for c in proposal.changes}, "applied_at": time.time()})
                self._params_at = -math.inf
            self._log("auto_notch", ch, f"Kênh {ch}: cắt hẹp −3.5 dB tại {freq:.0f} Hz (band {band}). Sau lễ hãy xem có nên giữ.", "APPLIED")

    # ------------------------------------------------------------------ livestream
    def _do_livestream(self) -> None:
        cfg = self.config["livestream"]
        st = self.livestream_state
        st["last_action"] = self._clock()
        if self._loudness is None:
            st["status"] = "Chưa có nguồn đo độ to livestream."
            return
        m = self._loudness() or {}
        lufs = m.get("short_term_lufs")
        st["lufs"] = lufs
        usable = bool(m.get("valid")) and lufs is not None and math.isfinite(lufs) and (
            m.get("scope") == "LIVESTREAM_BUS" or (m.get("simulated") and self._is_simulator()))
        if not usable:
            st["status"] = "Tạm khóa: chưa có số đo đã xác minh của chính bus livestream."
            return
        bus = int(self.config["livestream_bus"])
        params = self._refresh_mixer()
        current = params.get(f"/bus/{bus:02d}/mix/fader")
        if current is None:
            current = self._get_client().query(f"/bus/{bus:02d}/mix/fader")[0]
        if st["anchor"] is None:
            st["anchor"] = float(current)
        error = cfg["target_lufs"] - lufs
        if abs(error) <= cfg["deadband_db"]:
            st["status"] = f"Ổn định: {lufs:.1f} LUFS (mục tiêu {cfg['target_lufs']:.0f})."
            return
        step = math.copysign(min(cfg["step_db"], abs(error)), error)
        new_offset = max(-cfg["max_offset_db"], min(cfg["max_offset_db"], st["offset_db"] + step))
        if abs(new_offset - st["offset_db"]) < 0.05:
            st["status"] = f"Đã chạm giới hạn ±{cfg['max_offset_db']:.0f} dB — cần người kiểm tra mix livestream."
            self._set_alert("livestream-limit", "livestream", None, st["status"])
            return
        target = db_to_fader(fader_to_db(st["anchor"]) + new_offset)
        proposal = Proposal(
            proposal_id=f"AUTO_LIVESTREAM_BUS{bus:02d}_{int(time.time() * 1000)}",
            target_channel=0, target_bus=bus,
            hypothesis=f"Lái tự động: đưa livestream về {cfg['target_lufs']:.0f} LUFS (đang {lufs:.1f})",
            confidence=1.0,
            changes=[{"parameter": f"/bus/{bus:02d}/mix/fader", "from": float(current), "to": target}],
            expected_sha256=self._params_sha,
        )
        if self._execute(proposal, "livestream", None):
            st["offset_db"] = new_offset
            st["status"] = f"Đã chỉnh bus {bus}: {'tăng' if step > 0 else 'giảm'} {abs(step):.1f} dB (đang {lufs:.1f} LUFS)."
            self._params_at = -math.inf
            self._log("livestream", None, st["status"], "APPLIED")

    # ------------------------------------------------------------------ clip watch
    def _watch_clips(self, meters) -> None:
        cfg = self.config["clip_watch"]
        for m in meters or []:
            ch = int(m["channel"])
            peak = m.get("meter_dbfs")
            hist = self._clip_history.setdefault(ch, collections.deque(maxlen=5))
            hist.append(peak is not None and peak >= cfg["peak_dbfs"])
            key = f"clip-{ch}"
            if sum(hist) >= cfg["frames"]:
                if key not in self.alerts:
                    self._set_alert(key, "clip_watch", ch,
                                    f"Kênh {ch} ({m.get('name', '')}) sát vỡ tiếng ({peak:.1f} dBFS). Giảm gain preamp trên bàn — máy không được chỉnh preamp.")
            elif not any(hist) and key in self.alerts:
                del self.alerts[key]

    # ------------------------------------------------------------------ revert
    def revert(self, operator: str) -> Dict[str, Any]:
        """Undo every autopilot change (faders back to reference, notch bands restored).
        Requires a write-enabled mode; steps respect the Safety Gate limits."""
        if self._get_executor() is None:
            raise RuntimeError("Chưa kết nối mixer.")
        if self.mode_manager.is_read_only():
            raise PermissionError("Cần chế độ Hỗ trợ trở lên để hoàn tác.")
        undone = 0
        params = self._refresh_mixer(force=True)
        for n in list(reversed(self.notches)):
            changes = [{"parameter": p, "from": params.get(p, n["applied"].get(p)), "to": v} for p, v in n["original"].items()]
            prop = Proposal(f"AUTO_REVERT_NOTCH_CH{n['channel']:02d}_{int(time.time() * 1000)}", n["channel"],
                            "Hoàn tác cắt hú của lái tự động", 1.0, changes, self._params_sha)
            if self._execute(prop, "revert", n["channel"], operator=operator):
                self.notches.remove(n)
                undone += 1
            params = self._refresh_mixer(force=True)
        for ch, r in list(self.riders.items()):
            undone += self._step_to(f"/ch/{ch:02d}/mix/fader", r["anchor"], ch, None, operator)
            r["offset_db"] = 0.0
            r["expected"] = r["anchor"]
        st = self.livestream_state
        if st["anchor"] is not None:
            bus = int(self.config["livestream_bus"])
            undone += self._step_to(f"/bus/{bus:02d}/mix/fader", st["anchor"], None, bus, operator)
            st["offset_db"] = 0.0
        self._log("revert", None, f"Đã hoàn tác {undone} thay đổi của lái tự động ({operator}).", "APPLIED")
        self._audit_event(operator, "AUTOPILOT_REVERT", "COMMITTED", {"undone": undone})
        return self.status()

    def _step_to(self, path, target, ch, bus, operator) -> int:
        # Stay clearly under the Safety Gate slew limits (0.05 bus / 0.1 channel):
        # mixer readback is float32, so a step of exactly the limit can be rejected.
        max_delta = 0.045 if bus is not None else 0.09
        steps = 0
        for _ in range(40):
            params = self._refresh_mixer(force=True)
            current = params.get(path)
            if current is None:  # bus faders are not part of the snapshot: read them directly
                current = self._get_client().query(path)[0]
            current = float(current)
            if abs(current - target) < 0.002:
                break
            nxt = current + max(-max_delta, min(max_delta, target - current))
            prop = Proposal(f"AUTO_REVERT_{int(time.time() * 1000)}", ch or 0, "Hoàn tác lái tự động", 1.0,
                            [{"parameter": path, "from": current, "to": round(nxt, 4)}], self._params_sha, target_bus=bus)
            if not self._execute(prop, "revert", ch, operator=operator):
                break
            steps += 1
        return 1 if steps else 0

    # ------------------------------------------------------------------ plumbing
    def _execute(self, proposal: Proposal, feature: str, ch: Optional[int], operator: Optional[str] = None) -> bool:
        executor = self._get_executor()
        if executor is None:
            return False
        actor = operator or f"AUTOPILOT (duyệt trước bởi {self.enabled_by or '—'})"
        proposal.approve(actor)
        try:
            executor.execute(proposal, actor)
        except Exception as exc:
            self._log(feature, ch, f"Không áp dụng được: {exc}", "FAILED")
            self._audit_event(actor, f"AUTOPILOT_{feature.upper()}", "REJECTED",
                              {"proposal_id": proposal.proposal_id, "reason": str(exc)})
            with self._lock:
                self._params_at = -math.inf
            return False
        self._audit_event(actor, f"AUTOPILOT_{feature.upper()}", "COMMITTED",
                          {"proposal_id": proposal.proposal_id, "hypothesis": proposal.hypothesis, "changes": proposal.changes})
        return True

    def _set_alert(self, key, feature, ch, message) -> None:
        if key not in self.alerts:
            self.alerts[key] = {"key": key, "feature": feature, "channel": ch, "message": message, "at": time.time()}
            self._log(feature, ch, message, "ALERT")

    def _log(self, feature, ch, message, status) -> None:
        self.log.appendleft({"at": time.time(), "feature": feature, "channel": ch, "message": message, "status": status})

    def _audit_event(self, actor, action, status, details) -> None:
        if self._audit:
            try:
                self._audit(actor=actor, action=action, status=status, details=details)
            except Exception:
                pass

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "enabled_by": self.enabled_by,
                "mode": self.mode_manager.get_mode().value,
                "inactive_reason": self.inactive_reason,
                "features": dict(self.features),
                "config": self.config,
                "source": {k: self._last_source.get(k) for k in ("label", "valid", "simulated", "mapping_verified", "tap_point")},
                "riders": [{
                    "channel": r["channel"], "name": r["name"], "on": r["on"],
                    "reference_db": round(fader_to_db(r["anchor"]), 1) if r["anchor"] > 0 else None,
                    "offset_db": round(r["offset_db"], 1),
                    "level_dbfs": None if r["level"] is None else round(r["level"], 1),
                    "speaking": r["speaking_since"] is not None,
                } for r in sorted(self.riders.values(), key=lambda x: x["channel"])],
                "notches": [{k: n[k] for k in ("channel", "band", "freq_hz", "applied_at")} for n in self.notches],
                "notch_budget": self.config["auto_notch"]["budget_per_channel"],
                "livestream": {"bus": self.config["livestream_bus"], "offset_db": round(self.livestream_state["offset_db"], 1),
                               "lufs": self.livestream_state["lufs"], "status": self.livestream_state["status"],
                               "target_lufs": self.config["livestream"]["target_lufs"]},
                "alerts": sorted(self.alerts.values(), key=lambda a: -a["at"]),
                "log": list(self.log)[:60],
            }
