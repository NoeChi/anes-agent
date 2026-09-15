"""病人：清單、詳細資料、趨勢、模擬處置、工具判讀、備註。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..state import AppState
from ..tools.context import PatientContext
from .deps import bad, get_state

router = APIRouter(tags=["病人"])


@router.get("/patients")
async def list_patients(S: AppState = Depends(get_state)):
    return S.patients_payload()


@router.get("/patients/{pid}")
async def patient_detail(pid: str, S: AppState = Depends(get_state)):
    p = S.engine.get(pid)
    if not p:
        bad("找不到病人（可能已轉出）", 404)
    d = S.engine.detail(p.pid)
    d["status"] = S.rounds.patient_status.get(p.pid)
    d["alerts"] = [a for a in S.rounds.list_alerts("active") if a["pid"] == p.pid]
    return d


@router.get("/patients/{pid}/trend")
async def patient_trend(pid: str, minutes: float = 60, S: AppState = Depends(get_state)):
    tr = S.engine.trend(pid, max(5, min(180, minutes)))
    if tr is None:
        bad("找不到病人", 404)
    return tr


@router.post("/patients/{pid}/intervention")
async def patient_intervention(pid: str, body: dict = Body(...), S: AppState = Depends(get_state)):
    ok, msg, entry = S.engine.apply_intervention(pid, body.get("type", ""), by="使用者")
    if not ok:
        bad(msg)
    return {"message": msg, "entry": entry}


@router.post("/patients/{pid}/tools")
async def patient_tools(pid: str, body: dict = Body(default={}), S: AppState = Depends(get_state)):
    p = S.engine.get(pid)
    if not p:
        bad("找不到病人", 404)
    ctx = PatientContext(p)
    ids = body.get("tool_ids")
    tools = [S.registry.get(t) for t in ids] if ids else S.registry.list()
    return [S.registry.run(t, ctx).to_dict() | {"enabled": S.registry.enabled(t.id), "category": t.category}
            for t in tools if t]


@router.post("/patients/{pid}/note")
async def patient_note(pid: str, body: dict = Body(...), S: AppState = Depends(get_state)):
    text = str(body.get("text", "")).strip()
    if not text or not S.engine.add_note(pid, text, "使用者"):
        bad("找不到病人或內容空白")
    return {"ok": True}
