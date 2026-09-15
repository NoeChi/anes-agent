"""把模擬器產生的即時資料寫進資料庫。

模擬器本身不碰資料庫，只把「發生了什麼」放進 outbox（入院、轉床、檢驗、事件、處置、備註）以及生命徵象佇列；
本服務每隔幾秒批次寫入。寫入失敗時資料會放回佇列，下次再試。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import insert, update

from ..db.base import to_dt
from ..db.models import (ClinicalEvent, Intervention, LabResult, Patient, PatientNote, SimulationRun, VitalSign)
from ..db.session import Database
from ..simulator.engine import SimulationEngine

LAB_KEYS = ("ph", "paco2", "pao2", "hco3", "be", "hb", "k", "na", "glucose", "lactate", "ica")
VITAL_KEYS = ("hr", "sbp", "dbp", "map", "spo2", "etco2", "rr", "temp", "bis", "ppeak", "pain")
BATCH = 2000


class Recorder:
    def __init__(self, engine: SimulationEngine, db: Database, interval: float = 3.0):
        self.engine = engine
        self.db = db
        self.interval = interval
        self.run_id: int | None = None
        self.patient_ids: dict[str, int] = {}
        self.event_ids: dict[int, int] = {}
        self.lock = asyncio.Lock()
        self.rows_written = 0
        self.last_error: str | None = None

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            await self.flush()

    async def flush(self) -> None:
        async with self.lock:
            events, vitals = self.engine.drain_outbox()
            if not events and not vitals:
                return
            pending_patients: dict[str, int] = {}
            pending_events: dict[int, int] = {}
            state = {"run_id": self.run_id}
            try:
                async with self.db.session() as s, s.begin():
                    for kind, data in events:
                        await self._apply(s, kind, data, state, pending_patients, pending_events)
                    lookup = pending_patients if state["run_id"] != self.run_id else {**self.patient_ids, **pending_patients}
                    rows = []
                    for v in vitals:
                        patient_id = lookup.get(v["pid"])
                        if patient_id is None or v["run_seq"] != self.engine.run_seq:
                            continue
                        rows.append({
                            "patient_id": patient_id, "recorded_at": to_dt(v["t"]), "location": v["location"],
                            "bed": v["bed"], "phase": v["phase"], **{k: v.get(k) for k in VITAL_KEYS},
                            "ebl_ml": v.get("ebl"), "urine_ml": v.get("uo"), "fluids_ml": v.get("fluids"),
                            "case_min": v.get("case_min"), "event_level": v.get("evt") or 0.0,
                        })
                    for i in range(0, len(rows), BATCH):
                        await s.execute(insert(VitalSign), rows[i:i + BATCH])
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(f"[recorder] 寫入資料庫失敗，稍後重試：{self.last_error}")
                self.engine.requeue_outbox(events, vitals)
                return
            if state["run_id"] != self.run_id:
                self.patient_ids, self.event_ids = {}, {}
                self.run_id = state["run_id"]
            self.patient_ids.update(pending_patients)
            self.event_ids.update(pending_events)
            self.rows_written += len(rows)
            self.last_error = None

    async def _apply(self, s, kind: str, d: dict, state: dict, pending_patients: dict, pending_events: dict) -> None:
        same_run = state["run_id"] == self.run_id

        def patient_id(pid: str) -> int | None:
            return pending_patients.get(pid) or (self.patient_ids.get(pid) if same_run else None)

        def event_id(uid: int) -> int | None:
            return pending_events.get(uid) or (self.event_ids.get(uid) if same_run else None)

        if kind == "run_start":
            if state["run_id"] is not None:
                await s.execute(update(SimulationRun).where(SimulationRun.id == state["run_id"])
                                .values(ended_at=to_dt(d["wall_t"])))
            run = SimulationRun(n_patients=d["n_patients"], seed=d.get("seed"), sim_started_at=to_dt(d["t"]),
                                started_at=to_dt(d["wall_t"]))
            s.add(run)
            await s.flush()
            state["run_id"] = run.id
            pending_patients.clear()
            pending_events.clear()
            same_run = False
            return
        if state["run_id"] is None:
            return
        if kind == "admit":
            p = d["profile"]
            row = Patient(
                run_id=state["run_id"], pid=p["pid"], mrn=p["mrn"], name=p["name"], sex=p["sex"], age=p["age"],
                height_cm=p["height_cm"], weight_kg=p["weight_kg"], bmi=p["bmi"], asa=p["asa"], surgery=p["surgery"],
                specialty=p["specialty"], anes_code=p["anes_code"], anes_label=p["anes_label"],
                comorbidities=p["comorbidities"], allergies=p["allergies"], profile=p, location=d["location"],
                bed=d["bed"], admitted_at=to_dt(d["t"]), pacu_at=to_dt(d.get("pacu_t")),
            )
            s.add(row)
            await s.flush()
            pending_patients[p["pid"]] = row.id
            return
        pid = patient_id(d["pid"]) if "pid" in d else None
        if kind == "transfer" and pid:
            await s.execute(update(Patient).where(Patient.id == pid).values(location="PACU", bed=d["bed"], pacu_at=to_dt(d["t"])))
        elif kind == "discharge" and pid:
            await s.execute(update(Patient).where(Patient.id == pid).values(discharged_at=to_dt(d["t"])))
        elif kind == "lab" and pid:
            labs = d["labs"]
            s.add(LabResult(patient_id=pid, drawn_at=to_dt(labs["t"]), reason=labs["reason"], **{k: labs.get(k) for k in LAB_KEYS}))
        elif kind == "event_start" and pid:
            row = ClinicalEvent(patient_id=pid, event_uid=d["uid"], event_type=d["type"], label=d["label"],
                                injected=d["injected"], peak=d["peak"], started_at=to_dt(d["t"]), treatments=[])
            s.add(row)
            await s.flush()
            pending_events[d["uid"]] = row.id
        elif kind == "event_update":
            eid = event_id(d["uid"])
            if eid:
                values = {"treatments": d["treatments"]}
                if d.get("ended_t") is not None:
                    values["ended_at"] = to_dt(d["ended_t"])
                await s.execute(update(ClinicalEvent).where(ClinicalEvent.id == eid).values(**values))
        elif kind == "intervention" and pid:
            s.add(Intervention(patient_id=pid, type=d["type"], label=d["label"], performed_by=d["by"],
                               performed_at=to_dt(d["t"]), affected=d.get("affected", [])))
        elif kind == "note" and pid:
            s.add(PatientNote(patient_id=pid, text=d["text"], author=d["by"], noted_at=to_dt(d["t"])))

    def status(self) -> dict:
        return {"run_id": self.run_id, "rows_written": self.rows_written, "last_error": self.last_error}
