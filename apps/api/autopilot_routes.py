"""
REST API for the autopilot ("Lái tự động").

GET  /api/v1/autopilot                       -> status (riders, notches, livestream, alerts, log)
POST /api/v1/autopilot/enable                {operator_id, features?: {name: bool}}
POST /api/v1/autopilot/disable               {operator_id}
PUT  /api/v1/autopilot/features/{name}       {enabled, operator_id}
POST /api/v1/autopilot/revert                {operator_id}   undo all autopilot changes (needs ASSIST+)
GET  /api/v1/segments/{segment_id}/drift     faders that moved >= 3 dB from the segment reference
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class EnableRequest(BaseModel):
    operator_id: str = "Operator"
    features: Optional[Dict[str, bool]] = None


class OperatorRequest(BaseModel):
    operator_id: str = "Operator"


class FeatureRequest(BaseModel):
    enabled: bool
    operator_id: str = "Operator"


def build_router(get_autopilot: Callable, get_client: Callable, get_segment_store: Callable,
                 is_stopped: Callable[[], bool]) -> APIRouter:
    router = APIRouter()

    def _ap():
        ap = get_autopilot()
        if ap is None:
            raise HTTPException(status_code=503, detail="Lái tự động chưa sẵn sàng (chưa kết nối mixer).")
        return ap

    @router.get("/api/v1/autopilot")
    def autopilot_status():
        return _ap().status()

    @router.post("/api/v1/autopilot/enable")
    def autopilot_enable(req: EnableRequest):
        if is_stopped():
            raise HTTPException(status_code=403, detail="Hệ thống đang khóa khẩn cấp (STOP). Mở khóa trước khi bật lái tự động.")
        try:
            return _ap().enable(req.operator_id, req.features)
        except (RuntimeError, PermissionError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/api/v1/autopilot/disable")
    def autopilot_disable(req: OperatorRequest):
        return _ap().disable(req.operator_id)

    @router.put("/api/v1/autopilot/features/{name}")
    def autopilot_feature(name: str, req: FeatureRequest):
        try:
            return _ap().set_feature(name, req.enabled, req.operator_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/api/v1/autopilot/revert")
    def autopilot_revert(req: OperatorRequest):
        if is_stopped():
            raise HTTPException(status_code=403, detail="Hệ thống đang khóa khẩn cấp (STOP).")
        try:
            return _ap().revert(req.operator_id)
        except (RuntimeError, PermissionError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/api/v1/segments/{segment_id}/drift")
    def segment_drift(segment_id: str, threshold_db: float = 3.0):
        client = get_client()
        if client is None:
            raise HTTPException(status_code=503, detail="X32 Client not initialized")
        store = get_segment_store()
        params = client.take_full_snapshot(max_channels=32).parameters
        return {"segment_id": segment_id, "has_reference": bool(store.reference_faders(segment_id)),
                "drift": store.drift(segment_id, params, threshold_db=threshold_db)}

    return router
