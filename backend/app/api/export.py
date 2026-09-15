"""資料集匯出（生命徵象時間序列從資料庫讀取）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..repositories import dataset
from ..state import AppState
from .deps import bad, get_state

router = APIRouter(tags=["匯出"])


@router.get("/export/vitals.csv")
async def export_vitals(minutes: float = 60, S: AppState = Depends(get_state)):
    await S.recorder.flush()
    if S.recorder.run_id is None:
        bad("資料尚未寫入資料庫，請稍候再試", 503)
    since = S.engine.t - max(5, min(24 * 60, minutes)) * 60
    content = await dataset.export_vitals_csv(S.db.sessionmaker, S.recorder.run_id, since)
    name = f"anes_vitals_{dataset.now_label()}.csv"
    return Response("﻿" + content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export/patients.json")
async def export_patients(S: AppState = Depends(get_state)):
    data = [S.engine.detail(p.pid) for p in S.engine.sorted_patients()]
    return Response(json.dumps(data, ensure_ascii=False, indent=1, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="anes_patients.json"'})


@router.get("/export/run")
async def run_overview(S: AppState = Depends(get_state)):
    """本次模擬已寫入資料庫的資料量。"""
    return await dataset.run_overview(S.db.sessionmaker, S.recorder.run_id)
