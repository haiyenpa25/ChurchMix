"""
REST API for the automatic line check and the automatic per-channel soundcheck.

POST /api/v1/line-check/analyze                 {seconds=30}  READ-ONLY classification of every used channel
GET  /api/v1/auto-soundcheck/channels           channels eligible for auto soundcheck (voices first)
POST /api/v1/auto-soundcheck/{ch}/analyze       {seconds=10}  -> {measurement, proposals, advice_vi, ...}
POST /api/v1/auto-soundcheck/{ch}/proposals     rebuild proposals from the last measurement on a fresh
                                                snapshot (after one of them was applied)

Nothing here writes to the mixer. Proposals are registered in the shared `active_proposals`
dict and applied only through POST /api/v1/proposals/apply (Safety Gate, AGENTS.md rules 3/7/11).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.autopilot import auto_soundcheck, line_check
from packages.safety_controller.routing import get_talkback_channel
from packages.safety_controller.transaction import ProposalRejectedError

MEASUREMENT_TTL_S = 15 * 60


class LineCheckRequest(BaseModel):
    seconds: float = Field(30.0, ge=5.0, le=30.0)


class SoundcheckRequest(BaseModel):
    seconds: float = Field(10.0, ge=5.0, le=30.0)


def build_router(get_client: Callable, meter_history, is_simulator: Callable[[], bool],
                 get_channels: Callable[[], List[Dict[str, Any]]], proposals: Dict[str, Any],
                 audit: Optional[Callable[..., Any]] = None) -> APIRouter:
    router = APIRouter()
    measurements: Dict[int, Dict[str, Any]] = {}

    def _snapshot():
        client = get_client()
        if client is None:
            raise HTTPException(status_code=503, detail="Chưa kết nối mixer — không đọc được trạng thái kênh.")
        try:
            return client.take_full_snapshot(max_channels=32)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Không đọc được trạng thái mixer: {e}")

    def _channel_params(snap, ch: int) -> Dict[str, Any]:
        """Snapshot parameters plus the digital trim, which the full snapshot does not carry (read-only query)."""
        params = dict(snap.parameters)
        path = f"/ch/{ch:02d}/preamp/trim"
        if path not in params:
            client = get_client()
            try:
                params[path] = float(client.query(path)[0])
            except Exception:
                pass  # plan_trim reports that trim could not be read
        return params

    def _profile(ch: int) -> Dict[str, Any]:
        return next((c for c in get_channels() if int(c.get("channel", 0)) == ch), {"channel": ch})

    def _drop_channel_proposals(ch: int) -> None:
        prefix = (f"autosc-trim-ch{ch:02d}-", f"autosc-hpf-ch{ch:02d}-")
        for pid in [p for p in proposals if p.startswith(prefix)]:
            proposals.pop(pid, None)

    def _register(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        snap = _snapshot()
        _drop_channel_proposals(result["channel"])
        try:
            built = auto_soundcheck.build_proposals(result, _channel_params(snap, result["channel"]), snap.sha256)
        except ProposalRejectedError as e:
            raise HTTPException(status_code=400, detail=f"Đề xuất bị Safety Gate từ chối: {e}")
        out = []
        for prop, meta in built:
            proposals[prop.proposal_id] = prop
            out.append(auto_soundcheck.proposal_payload(prop, meta))
        return out

    @router.post("/api/v1/line-check/analyze")
    def line_check_analyze(req: LineCheckRequest):
        tb = get_talkback_channel()
        params: Dict[str, Any] = {}
        client = get_client()
        if client is not None:
            try:
                params = client.take_full_snapshot(max_channels=32).parameters
            except Exception:
                params = {}
        return line_check.analyze(meter_history, get_channels(), params, req.seconds,
                                  trusted=meter_history.trusted_for(is_simulator()), talkback_channel=tb)

    @router.get("/api/v1/auto-soundcheck/channels")
    def soundcheck_channels():
        tb = get_talkback_channel()
        chans = line_check.checked_channels(get_channels(), tb)
        voice = [c for c in chans if c.get("role") in auto_soundcheck.VOICE_ROLES]
        rows = [{"channel": int(c["channel"]), "name": c.get("name"), "role": c.get("role"),
                 "voice": c.get("role") in auto_soundcheck.VOICE_ROLES,
                 "target_peak_dbfs": auto_soundcheck.target_peak_for(c.get("role")),
                 "hpf_target_hz": auto_soundcheck.HPF_BY_ROLE.get(c.get("role") or ""),
                 "role_eq": c.get("role") in auto_soundcheck.ROLE_EQ_ROLES} for c in chans]
        return {"channels": rows, "voice_order": [int(c["channel"]) for c in voice], "talkback_channel": tb,
                "assumption_vi": auto_soundcheck.ASSUMPTION_VI}

    @router.post("/api/v1/auto-soundcheck/{channel_id}/analyze")
    def soundcheck_analyze(channel_id: int, req: SoundcheckRequest):
        profile = _profile(channel_id)
        snap = _snapshot()
        try:
            result = auto_soundcheck.analyze(
                channel_id, meter_history, profile.get("role"), _channel_params(snap, channel_id), req.seconds,
                trusted=meter_history.trusted_for(is_simulator()), talkback_channel=get_talkback_channel(),
                protected=bool(profile.get("is_protected")), name=profile.get("name") or f"Kênh {channel_id}")
        except auto_soundcheck.SoundcheckRefused as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        measurements[channel_id] = result
        props = _register(result)
        if audit:
            try:
                audit(actor="System", action="AUTO_SOUNDCHECK_ANALYZE", status="PROPOSED",
                      details={"channel": channel_id, "measurement": result["measurement"],
                               "proposals": [p["proposal_id"] for p in props]})
            except Exception:
                pass
        return _response(result, props)

    @router.post("/api/v1/auto-soundcheck/{channel_id}/proposals")
    def soundcheck_rebuild(channel_id: int):
        result = measurements.get(channel_id)
        if not result or time.time() - result["created_at"] > MEASUREMENT_TTL_S:
            measurements.pop(channel_id, None)
            raise HTTPException(status_code=404, detail="Chưa có kết quả đo (hoặc đã quá 15 phút) — hãy đo lại kênh này.")
        return _response(result, _register(result))

    def _response(result: Dict[str, Any], props: List[Dict[str, Any]]) -> Dict[str, Any]:
        role = result.get("role")
        return {"channel": result["channel"], "name": result["name"], "role": role,
                "measurement": result["measurement"], "plan": result["plan"], "proposals": props,
                "advice_vi": result["advice_vi"], "assumption_vi": auto_soundcheck.ASSUMPTION_VI,
                "role_eq": {"available": role in auto_soundcheck.ROLE_EQ_ROLES, "role": role,
                            "endpoint": "/api/v1/proposals/generate-role"},
                "applies_via": "/api/v1/proposals/apply"}

    return router
