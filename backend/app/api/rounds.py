"""查房報告與警示。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..state import AppState
from .deps import bad, get_state

router = APIRouter(tags=["查房"])


@router.get("/rounds")
async def list_rounds(S: AppState = Depends(get_state)):
    return [S.rounds.brief(r) for r in await S.rounds.list_reports()]


@router.get("/rounds/latest")
async def latest_round(S: AppState = Depends(get_state)):
    return S.rounds.latest(include_recheck=True)


@router.get("/rounds/{round_id}")
async def get_round(round_id: str, S: AppState = Depends(get_state)):
    report = await S.rounds.get_report(round_id)
    if not report:
        bad("找不到查房紀錄", 404)
    return report


@router.post("/rounds/run")
async def run_round(body: dict = Body(default={}), S: AppState = Depends(get_state)):
    report = await S.rounds.run_round("manual", scope=body.get("scope", "all"))
    return S.rounds.brief(report)


@router.get("/alerts")
async def list_alerts(status: str = "active", S: AppState = Depends(get_state)):
    return S.rounds.list_alerts(status)


@router.post("/alerts/ack-patient")
async def acknowledge_patient(body: dict = Body(...), S: AppState = Depends(get_state)):
    n = await S.rounds.acknowledge(pid=body.get("pid"))
    await S.bus.publish("alerts_changed", {"pid": body.get("pid")})
    return {"acknowledged": n}


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: str, S: AppState = Depends(get_state)):
    n = await S.rounds.acknowledge(alert_id=alert_id)
    await S.bus.publish("alerts_changed", {"id": alert_id})
    return {"acknowledged": n}
