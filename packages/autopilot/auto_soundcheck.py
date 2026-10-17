"""
Automatic per-channel soundcheck ("Soundcheck tự động").

A volunteer speaks/sings naturally into ONE microphone for ~10 s. From the X32 input meters
collected in `MeterHistory` this module measures the channel and formulates PROPOSALS only
(AGENTS.md rule 7): nothing here writes to the mixer. Each proposal is applied later through
POST /api/v1/proposals/apply -> TransactionExecutor (full Safety Gate).

Proposals
  (a) Digital TRIM (/ch/NN/preamp/trim, -18..+18 dB, 0.5 = 0 dB) so the typical speech/vocal
      peak lands near -12 dBFS (instruments -15). The step is clamped below the Safety Gate
      trim limit (0.20 normalized ~ 7.2 dB) and a clipping channel is never made louder.
      Analog preamp gain / headamp / phantom are FORBIDDEN and only ever given as advice.
  (b) HPF on + frequency by role, only when not already set sensibly. Bass and drums: unchanged.

Meter assumption: X32 input meters (/meters/1) are read post-preamp and post-digital-trim
(trim acts at the very start of the channel input stage, before the meter tap), pre-fader and
pre-mute. A trim change of N dB therefore moves the measured level by N dB.
NOTE: the internal mock mixer does NOT model this — its meter levels ignore trim.

Targets are stored as ABSOLUTE values (trim dB at measurement + delta), so proposals can be
rebuilt from the same measurement on a fresh snapshot after one of them was applied.
"""

from __future__ import annotations

import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from packages.eq_optimizer.recommender import freq_to_x32, x32_to_freq
from packages.mix_assistant.gain_staging import trim_to_x32, x32_to_trim
from packages.safety_controller.transaction import Proposal, SafetyPolicy

# --- Targets and limits ------------------------------------------------------------------
VOICE_ROLES = ("PASTOR_SPEECH", "LEAD_VOCAL_FEMALE", "LEAD_VOCAL_MALE", "CHOIR_OVERHEAD")
VOICE_TARGET_PEAK_DBFS = -12.0
INSTRUMENT_TARGET_PEAK_DBFS = -15.0
MAX_TRUE_PEAK_DBFS = -3.0       # the loudest sample must keep >= 3 dB headroom after the change
CLIP_DBFS = -1.0
MAX_TRIM_STEP_DB = 7.0          # Safety Gate allows 0.20 normalized (= 7.2 dB); keep a margin
TRIM_DEADBAND_DB = 1.0          # smaller corrections are not worth a mixer write
TRIM_MIN_DB, TRIM_MAX_DB = -18.0, 18.0
NO_SOUND_DBFS = -60.0           # peak below this: the person did not make sound
ACTIVE_DBFS = -60.0             # samples above this count as "speaking/singing"
MIN_SAMPLES = 20
MIN_COVERAGE_RATIO = 0.7
HPF_MIN_HZ, HPF_MAX_HZ = 20.0, 400.0   # X32 /preamp/hpf: log scale 20..400 Hz
HPF_SENSIBLE_RANGE = (0.8, 1.25)       # current frequency within this ratio of the target = OK

# None = do not change the HPF for this role.
HPF_BY_ROLE: Dict[str, Optional[float]] = {
    "PASTOR_SPEECH": 100.0,
    "LEAD_VOCAL_FEMALE": 100.0,
    "LEAD_VOCAL_MALE": 80.0,
    "CHOIR_OVERHEAD": 100.0,
    "ACOUSTIC_GUITAR": 80.0,
    "PIANO_KEYS": 40.0,
    "BASS_GUITAR": None,
    "DRUMS": None,           # kick lives below 100 Hz; leave the drum channels alone
}
ROLE_EQ_ROLES = ("PASTOR_SPEECH", "LEAD_VOCAL_FEMALE", "LEAD_VOCAL_MALE", "CHOIR_OVERHEAD",
                 "ACOUSTIC_GUITAR", "PIANO_KEYS", "BASS_GUITAR")

ROLE_LABEL_VI = {
    "PASTOR_SPEECH": "giọng nói", "LEAD_VOCAL_FEMALE": "giọng hát nữ", "LEAD_VOCAL_MALE": "giọng hát nam",
    "CHOIR_OVERHEAD": "ca đoàn", "ACOUSTIC_GUITAR": "guitar mộc", "PIANO_KEYS": "piano/phím",
    "BASS_GUITAR": "đàn bass", "DRUMS": "trống",
}

ASSUMPTION_VI = ("Giả định: meter đầu vào X32 đo SAU preamp và SAU digital trim (trước fader, trước mute), "
                 "nên chỉnh trim N dB thì mức đo đổi N dB.")


class SoundcheckRefused(Exception):
    """Analysis refused; `detail` is shown verbatim to the volunteer."""

    def __init__(self, code: str, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def target_peak_for(role: Optional[str]) -> float:
    return VOICE_TARGET_PEAK_DBFS if role in VOICE_ROLES else INSTRUMENT_TARGET_PEAK_DBFS


def _round_half(x: float) -> float:
    return math.copysign(math.floor(abs(x) * 2.0 + 0.5) / 2.0, x)


def hpf_norm_to_hz(v: float) -> float:
    return x32_to_freq(float(v), HPF_MIN_HZ, HPF_MAX_HZ)


def hpf_hz_to_norm(hz: float) -> float:
    return freq_to_x32(float(hz), HPF_MIN_HZ, HPF_MAX_HZ)


# --- Measurement -------------------------------------------------------------------------
def measure(meter_history, channel: int, seconds: float, *, trusted: bool) -> Dict[str, Any]:
    """Peak / typical peak / median of one channel over the last `seconds`. Raises SoundcheckRefused."""
    if not trusted:
        raise SoundcheckRefused("UNTRUSTED", "Dữ liệu meter chưa tin cậy (giả lập hoặc chưa ánh xạ kênh X32) — "
                                             "không thể đo. Kiểm tra kết nối mixer rồi thử lại.")
    coverage = float(meter_history.coverage_s())
    if coverage < MIN_COVERAGE_RATIO * float(seconds):
        raise SoundcheckRefused("INSUFFICIENT", f"Mới có {coverage:.0f} giây dữ liệu meter, cần khoảng {seconds:.0f} giây. "
                                                "Đợi vài giây rồi đo lại.")
    levels = meter_history.window(channel, min(float(seconds), coverage))
    if len(levels) < MIN_SAMPLES:
        raise SoundcheckRefused("INSUFFICIENT", "Không đủ mẫu meter cho kênh này — đo lại.")
    s = sorted(levels)
    peak = s[-1]
    if peak < NO_SOUND_DBFS:
        raise SoundcheckRefused("NO_SOUND", f"Không nghe thấy tiếng ở kênh {channel} (đỉnh {peak:.0f} dBFS). "
                                            "Hãy nói/hát gần micro, kiểm tra pin, dây và nút mute trên micro, rồi đo lại.",
                                status_code=422)
    active = sorted(l for l in s if l > ACTIVE_DBFS)
    typical = active[int(0.95 * (len(active) - 1))] if len(active) >= 5 else peak
    return {
        "channel": int(channel), "count": len(s), "window_s": round(min(float(seconds), coverage), 1),
        "peak_dbfs": round(peak, 1), "typical_peak_dbfs": round(typical, 1),
        "median_dbfs": round(active[len(active) // 2] if active else s[len(s) // 2], 1),
        "active_ratio": round(len(active) / len(s), 2),
        "clipping": peak >= CLIP_DBFS,
    }


# --- Plan (absolute targets) -------------------------------------------------------------
def plan_trim(measurement: Dict[str, Any], role: Optional[str], trim_norm: Optional[float]) -> Dict[str, Any]:
    """Trim target in absolute dB. Returns {'change': bool, ...} plus advice."""
    target_peak = target_peak_for(role)
    advice: List[str] = []
    if trim_norm is None:
        return {"change": False, "target_peak_dbfs": target_peak,
                "advice": ["Không đọc được digital trim của kênh — bỏ qua đề xuất trim."]}
    trim_db = x32_to_trim(float(trim_norm))
    wanted = target_peak - measurement["typical_peak_dbfs"]
    headroom_cap = MAX_TRUE_PEAK_DBFS - measurement["peak_dbfs"]
    delta = min(wanted, headroom_cap)
    if measurement["clipping"]:
        delta = min(delta, 0.0)  # never make a clipping channel louder
        advice.append("Kênh đang chạm ngưỡng méo (clip). Nếu vẫn quá to sau khi giảm trim, hãy giảm gain preamp trên bàn "
                      "(người vận hành tự chỉnh — ChurchMix không đụng gain analog).")
    clamped = False
    if abs(delta) > MAX_TRIM_STEP_DB:
        delta = math.copysign(MAX_TRIM_STEP_DB, delta)
        clamped = True
    raw_delta = delta
    delta = _round_half(delta)
    target_db = max(TRIM_MIN_DB, min(TRIM_MAX_DB, trim_db + delta))
    delta = round(target_db - trim_db, 2)
    if clamped:
        advice.append(f"Cần chỉnh nhiều hơn giới hạn an toàn {MAX_TRIM_STEP_DB:.0f} dB mỗi lần — sau khi áp dụng hãy đo lại.")
    if wanted > 0 and target_db >= TRIM_MAX_DB:
        advice.append("Trim đã ở mức tối đa. Tín hiệu vẫn nhỏ: đưa micro gần miệng hơn hoặc tăng gain preamp trên bàn.")
    if wanted > 9.0 and not measurement["clipping"]:
        advice.append("Tín hiệu nhỏ hơn nhiều so với mức chuẩn — kiểm tra vị trí micro (cách miệng 5–15 cm) trước khi tăng trim.")
    change = abs(raw_delta) >= TRIM_DEADBAND_DB and abs(delta) >= TRIM_DEADBAND_DB
    if not change and not measurement["clipping"]:
        advice.append("Mức tín hiệu đã gần chuẩn — không cần chỉnh trim.")
    return {"change": change, "current_trim_db": trim_db, "target_trim_db": round(target_db, 2), "delta_db": delta,
            "wanted_delta_db": round(wanted, 1), "target_peak_dbfs": target_peak,
            "never_louder": bool(measurement["clipping"]), "clamped": clamped, "advice": advice}


def plan_hpf(role: Optional[str], hpon: Optional[float], hpf_norm: Optional[float]) -> Dict[str, Any]:
    target = HPF_BY_ROLE.get(role or "")
    label = ROLE_LABEL_VI.get(role or "", "kênh này")
    if target is None:
        return {"change": False, "target_hz": None,
                "advice": [f"Giữ nguyên lọc trầm (HPF) cho {label} — cần giữ dải trầm."] if role in ("BASS_GUITAR", "DRUMS") else []}
    if hpon is None or hpf_norm is None:
        return {"change": False, "target_hz": target, "advice": ["Không đọc được HPF của kênh — bỏ qua đề xuất HPF."]}
    on = int(round(float(hpon))) == 1
    current_hz = round(hpf_norm_to_hz(hpf_norm), 1)
    freq_ok = HPF_SENSIBLE_RANGE[0] * target <= current_hz <= HPF_SENSIBLE_RANGE[1] * target
    if on and freq_ok:
        return {"change": False, "target_hz": target, "current_hz": current_hz, "current_on": True,
                "advice": [f"Lọc trầm (HPF) đã hợp lý ({current_hz:.0f} Hz)."]}
    return {"change": True, "target_hz": target, "current_hz": current_hz, "current_on": on,
            "set_on": not on, "set_freq": not freq_ok, "advice": []}


def analyze(channel: int, meter_history, role: Optional[str], mixer_params: Dict[str, Any], seconds: float = 10.0, *,
            trusted: bool, talkback_channel: Optional[int], protected: bool = False, name: str = "") -> Dict[str, Any]:
    """Measure one channel and plan trim/HPF. Raises SoundcheckRefused (talkback, untrusted, no sound)."""
    channel = int(channel)
    if not 1 <= channel <= 32:
        raise SoundcheckRefused("BAD_CHANNEL", "Kênh phải từ 1 đến 32.", status_code=400)
    if (talkback_channel is not None and channel == int(talkback_channel)) or protected or role == "TALKBACK_BAND":
        raise SoundcheckRefused("TALKBACK", f"Kênh {channel} là Talkback ban nhạc (chỉ vào tai nghe P16) — được bảo vệ, "
                                            "không soundcheck tự động.", status_code=403)
    m = measure(meter_history, channel, seconds, trusted=trusted)
    p = mixer_params or {}
    prefix = f"/ch/{channel:02d}"
    trim = plan_trim(m, role, p.get(f"{prefix}/preamp/trim"))
    hpf = plan_hpf(role, p.get(f"{prefix}/preamp/hpon"), p.get(f"{prefix}/preamp/hpf"))
    m.update(target_peak_dbfs=trim["target_peak_dbfs"], role=role, name=name)
    return {"channel": channel, "name": name, "role": role, "measurement": m,
            "plan": {"trim": trim, "hpf": hpf}, "advice_vi": trim["advice"] + hpf["advice"],
            "created_at": time.time()}


# --- Proposals (rebuilt on a fresh snapshot) ----------------------------------------------
def build_proposals(result: Dict[str, Any], mixer_params: Dict[str, Any], sha256: str,
                    policy: Optional[SafetyPolicy] = None) -> List[Tuple[Proposal, Dict[str, Any]]]:
    """Proposals for the planned changes against the CURRENT mixer values. Each passes SafetyPolicy."""
    policy = policy or SafetyPolicy()
    ch = int(result["channel"])
    prefix = f"/ch/{ch:02d}"
    label = ROLE_LABEL_VI.get(result.get("role") or "", "kênh")
    m = result["measurement"]
    out: List[Tuple[Proposal, Dict[str, Any]]] = []

    trim = result["plan"]["trim"]
    cur_trim = mixer_params.get(f"{prefix}/preamp/trim")
    if trim.get("change") and isinstance(cur_trim, (int, float)):
        cur = float(cur_trim)
        to = trim_to_x32(trim["target_trim_db"])
        max_step = MAX_TRIM_STEP_DB / 36.0
        to = round(max(cur - max_step, min(cur + max_step, to)), 4)
        if trim.get("never_louder"):
            to = min(to, cur)
        delta_db = round((to - cur) * 36.0, 1)
        if abs(delta_db) >= TRIM_DEADBAND_DB:
            new_peak = m["typical_peak_dbfs"] + delta_db
            prop = Proposal(
                proposal_id=f"autosc-trim-ch{ch:02d}-{uuid.uuid4().hex[:6]}", target_channel=ch,
                hypothesis=f"Chỉnh digital trim {delta_db:+.1f} dB để đỉnh {label} về khoảng {trim['target_peak_dbfs']:.0f} dBFS.",
                confidence=0.85, expected_sha256=sha256,
                changes=[{"parameter": f"{prefix}/preamp/trim", "from": cur, "to": to,
                          "detail": f"Digital trim {x32_to_trim(cur):+.1f} dB → {x32_to_trim(to):+.1f} dB"}])
            explanation = (f"{'Giảm' if delta_db < 0 else 'Tăng'} {abs(delta_db):.1f} dB ở digital trim. "
                           f"Đỉnh thường gặp đang {m['typical_peak_dbfs']:.0f} dBFS, sau khi chỉnh khoảng {new_peak:.0f} dBFS.")
            tradeoffs = [explanation,
                         "Đây là trim số trên kênh X32 — không đụng gain preamp analog, phantom hay định tuyến.",
                         "Fader và các bus monitor nhận tín hiệu sau trim cũng to/nhỏ theo — nghe lại sau khi áp dụng."]
            out.append((prop, {"kind": "TRIM", "explanation_vi": explanation, "tradeoffs": tradeoffs}))

    hpf = result["plan"]["hpf"]
    hpon_cur = mixer_params.get(f"{prefix}/preamp/hpon")
    hpf_cur = mixer_params.get(f"{prefix}/preamp/hpf")
    if hpf.get("change") and isinstance(hpon_cur, (int, float)) and isinstance(hpf_cur, (int, float)):
        target = float(hpf["target_hz"])
        cur_hz = hpf_norm_to_hz(hpf_cur)
        changes = []
        if int(round(hpon_cur)) != 1:
            changes.append({"parameter": f"{prefix}/preamp/hpon", "from": int(round(hpon_cur)), "to": 1,
                            "detail": "Bật lọc trầm (HPF)"})
        if not HPF_SENSIBLE_RANGE[0] * target <= cur_hz <= HPF_SENSIBLE_RANGE[1] * target:
            changes.append({"parameter": f"{prefix}/preamp/hpf", "from": float(hpf_cur), "to": hpf_hz_to_norm(target),
                            "detail": f"HPF {cur_hz:.0f} Hz → {target:.0f} Hz"})
        if changes:
            prop = Proposal(
                proposal_id=f"autosc-hpf-ch{ch:02d}-{uuid.uuid4().hex[:6]}", target_channel=ch,
                hypothesis=f"Bật lọc trầm {target:.0f} Hz cho {label} để bớt ù, tiếng gió và tiếng chạm micro.",
                confidence=0.8, expected_sha256=sha256, changes=changes)
            explanation = (f"Lọc bớt âm trầm dưới {target:.0f} Hz — {label} không cần dải này; "
                           "giảm ù sân khấu, tiếng thở/gió và nguy cơ hú tần số thấp.")
            tradeoffs = [explanation, "Không làm mỏng giọng/nhạc cụ ở tần số này; nếu nghe thiếu ấm có thể hoàn tác."]
            out.append((prop, {"kind": "HPF", "explanation_vi": explanation, "tradeoffs": tradeoffs}))

    for prop, _ in out:
        policy.validate_proposal(prop)  # raises ProposalRejectedError: never register an invalid proposal
    return out


def proposal_payload(prop: Proposal, meta: Dict[str, Any]) -> Dict[str, Any]:
    return {"proposal_id": prop.proposal_id, "target_channel": prop.target_channel, "hypothesis": prop.hypothesis,
            "confidence": prop.confidence, "changes": prop.changes, "expected_sha256": prop.expected_sha256,
            "kind": meta["kind"], "explanation_vi": meta["explanation_vi"],
            "tuning_detail": {"expected_tradeoffs": meta["tradeoffs"]}}
