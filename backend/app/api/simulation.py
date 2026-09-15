"""模擬控制與情境演練。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..config import SettingsError
from ..simulator.events import EVENTS, event_catalog, intervention_catalog
from ..state import AppState
from .deps import bad, get_state

router = APIRouter(tags=["模擬"])


@router.get("/catalog/interventions")
async def interventions():
    return intervention_catalog()


@router.get("/sim/events")
async def sim_events(S: AppState = Depends(get_state)):
    return {"catalog": event_catalog(), "active": S.engine.active_events(), "log": list(S.engine.log)[-60:]}


@router.post("/sim/control")
async def sim_control(body: dict = Body(...), S: AppState = Depends(get_state)):
    try:
        cfg = await S.settings.update("simulation", {k: v for k, v in body.items() if k in ("running", "speed", "event_rate")})
    except SettingsError as exc:
        bad(str(exc))
    await S.bus.publish("settings_changed", S.settings.public())
    return cfg


@router.post("/sim/reset")
async def sim_reset(S: AppState = Depends(get_state)):
    async with S.rounds.lock:
        S.engine.reset()
        await S.rounds.reset_run()
    await S.bus.publish("sim_reset", {})
    S.spawn(S.rounds.run_round("manual", ai_summary="off"))
    return {"ok": True}


@router.post("/sim/inject")
async def sim_inject(body: dict = Body(...), S: AppState = Depends(get_state)):
    ok, msg = S.engine.inject_event(body.get("pid", ""), body.get("event", ""))
    if not ok:
        bad(msg)
    return {"message": msg}


@router.post("/sim/demo")
async def sim_demo(body: dict = Body(...), S: AppState = Depends(get_state)):
    etype = body.get("event", "")
    if etype not in EVENTS:
        bad("未知的情境")
    candidates = [p for p in S.engine.sorted_patients() if p.eligible(etype)]
    if not candidates:
        bad(f"目前沒有適合「{EVENTS[etype]['label']}」的病人，請稍後再試或換一個情境")
    candidates.sort(key=lambda p: (len(p.events), p.phase() != "maintenance", -(p.planned_s - (p.t - p.or_start))))
    p = candidates[0]
    _, msg = S.engine.inject_event(p.pid, etype)
    return {"message": msg, "pid": p.pid}
