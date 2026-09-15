"""即時模擬資料集的查詢與匯出。"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.base import to_dt
from ..db.models import ClinicalEvent, LabResult, Patient, SimulationRun, VitalSign

SessionMaker = async_sessionmaker[AsyncSession]

VITAL_COLUMNS = ["hr", "sbp", "dbp", "map", "spo2", "etco2", "rr", "temp", "bis", "ppeak", "pain",
                 "ebl_ml", "urine_ml", "fluids_ml", "case_min"]


async def export_vitals_csv(sm: SessionMaker, run_id: int, since_ts: float) -> str:
    stmt = (
        select(VitalSign, Patient.pid, Patient.age, Patient.sex, Patient.asa, Patient.surgery, Patient.anes_label)
        .join(Patient, Patient.id == VitalSign.patient_id)
        .where(Patient.run_id == run_id, VitalSign.recorded_at >= to_dt(since_ts))
        .order_by(Patient.pid, VitalSign.recorded_at)
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "pid", "bed", "location", "phase", "age", "sex", "asa", "surgery", "anesthesia"] + VITAL_COLUMNS)
    async with sm() as s:
        for v, pid, age, sex, asa, surgery, anes in (await s.execute(stmt)).all():
            row = [v.recorded_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"), pid, v.bed, v.location, v.phase,
                   age, sex, asa, surgery, anes]
            row += ["" if getattr(v, c) is None else round(getattr(v, c), 2) for c in VITAL_COLUMNS]
            writer.writerow(row)
    return buf.getvalue()


async def run_overview(sm: SessionMaker, run_id: int | None) -> dict:
    if run_id is None:
        return {}
    async with sm() as s:
        run = await s.get(SimulationRun, run_id)
        patients = await s.scalar(select(func.count()).select_from(Patient).where(Patient.run_id == run_id))
        vitals = await s.scalar(select(func.count()).select_from(VitalSign).join(Patient).where(Patient.run_id == run_id))
        labs = await s.scalar(select(func.count()).select_from(LabResult).join(Patient).where(Patient.run_id == run_id))
        events = await s.scalar(select(func.count()).select_from(ClinicalEvent).join(Patient).where(Patient.run_id == run_id))
    return {
        "run_id": run_id,
        "started_at": run.started_at.astimezone().strftime("%Y-%m-%d %H:%M") if run and run.started_at else None,
        "patients": int(patients or 0), "vital_signs": int(vitals or 0), "lab_results": int(labs or 0),
        "clinical_events": int(events or 0),
    }


def now_label() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M")
