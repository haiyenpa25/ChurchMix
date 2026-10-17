"""
REST API for the service program ("Chương trình lễ") and segment suggestions.

GET  /api/v1/program                    -> {items:[{id, segment_id, title, note, segment_name, segment_missing}],
                                            current_index, next_index, current, next, updated_at, updated_by, is_default}
PUT  /api/v1/program                    {items:[{id?, segment_id, title?, note?}], operator_id}
POST /api/v1/program/current            {index, segment_id?, operator_id}  mark the running item
POST /api/v1/program/reset              {operator_id}   nothing current (start of a new service)
POST /api/v1/program/restore-default    {operator_id}   drop the saved program, use the default order
GET  /api/v1/segment-suggestion         -> {suggestion, reason, scores, active_channels, ...}

None of these endpoints writes to the mixer. /program/current is only a marker that
the UI sets AFTER a successful switch through /api/v1/segments/{id}/preview + /apply.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from packages.storage.service_program import ProgramError


class ProgramItemModel(BaseModel):
    id: Optional[str] = None
    segment_id: str
    title: str = ""
    note: str = ""


class ProgramUpdateRequest(BaseModel):
    items: List[ProgramItemModel]
    operator_id: str = "Operator"


class ProgramCurrentRequest(BaseModel):
    index: Optional[int] = None
    segment_id: Optional[str] = None
    operator_id: str = "Operator"


class OperatorRequest(BaseModel):
    operator_id: str = "Operator"


def build_router(get_program_store: Callable, get_detector: Callable,
                 audit: Optional[Callable[..., Any]] = None) -> APIRouter:
    router = APIRouter()

    def _audit(**kw):
        if audit:
            try:
                audit(**kw)
            except Exception:
                pass

    @router.get("/api/v1/program")
    def program_get():
        return get_program_store().get()

    @router.put("/api/v1/program")
    def program_put(req: ProgramUpdateRequest):
        try:
            result = get_program_store().replace([i.model_dump() for i in req.items], author=req.operator_id)
        except ProgramError as e:
            raise HTTPException(status_code=400, detail=str(e))
        _audit(actor=req.operator_id, action="PROGRAM_UPDATE", status="SAVED", details={"items": len(result["items"])})
        return result

    @router.post("/api/v1/program/current")
    def program_current(req: ProgramCurrentRequest):
        try:
            result = get_program_store().set_current(req.index, author=req.operator_id, segment_id=req.segment_id)
        except ProgramError as e:
            raise HTTPException(status_code=400, detail=str(e))
        detector = get_detector()
        if detector is not None:
            detector.invalidate_active()
        return result

    @router.post("/api/v1/program/reset")
    def program_reset(req: OperatorRequest):
        return get_program_store().reset(author=req.operator_id)

    @router.post("/api/v1/program/restore-default")
    def program_restore_default(req: OperatorRequest):
        result = get_program_store().restore_default()
        _audit(actor=req.operator_id, action="PROGRAM_RESTORE_DEFAULT", status="SAVED", details={})
        return result

    @router.get("/api/v1/segment-suggestion")
    def segment_suggestion() -> Dict[str, Any]:
        detector = get_detector()
        if detector is None:
            return {"suggestion": None, "reason": "Chưa sẵn sàng."}
        return detector.status()

    return router
