"""即時生理訊號模擬引擎。

每位病人都有：基本資料、麻醉階段（誘導／維持／甦醒／恢復室）、生命徵象（含雜訊與平滑變化）、
出血量／尿量／輸液、檢驗值、臨床事件，以及處置紀錄。手術結束會轉入恢復室，恢復室病人轉出後
會有新病人進入手術室，因此系統內永遠維持固定人數。
"""
from __future__ import annotations

import csv
import io
import math
import random
import time
from collections import defaultdict, deque
from datetime import datetime

import numpy as np

from .events import EVENTS, INTERVENTIONS
from .profiles import generate_profile

FIELDS = ["hr", "sbp", "dbp", "map", "spo2", "etco2", "rr", "temp", "bis", "ppeak", "pain",
          "ebl", "uo", "fluids", "phase", "case_min", "evt"]
PHASE_CODE = {"induction": 0, "maintenance": 1, "emergence": 2, "pacu": 3}
PHASE_LABEL = {"induction": "麻醉誘導", "maintenance": "麻醉維持", "emergence": "手術結束／甦醒", "pacu": "恢復室"}
BLEED_RATE = {"none": 0.0, "low": 0.3, "mid": 1.0, "high": 2.5}  # 背景手術出血 mL/min
AIRWAY_LABEL = {"ETT": "氣管內管", "LMA": "喉罩", "NC": "鼻導管氧氣"}

# field, 平滑時間常數(秒), 雜訊標準差, 下限, 上限
SMOOTHING = [
    ("hr", 30, 1.6, 25, 220),
    ("map", 45, 1.8, 25, 170),
    ("pp", 45, 1.0, 12, 110),
    ("spo2", 40, 0.35, 50, 100),
    ("etco2", 40, 0.6, 8, 110),
    ("rr", 40, 0.5, 3, 45),
    ("bis", 60, 2.0, 5, 98),
    ("ppeak", 30, 0.4, 5, 60),
    ("pain", 180, 0.15, 0, 10),
]
NOISE_TAU = 60.0


class RingBuffer:
    def __init__(self, capacity: int, fields: list[str]):
        self.cap = capacity
        self.fields = fields
        self.t = np.zeros(capacity)
        self.v = np.full((capacity, len(fields)), np.nan)
        self.n = 0
        self.head = 0

    def append(self, t: float, row: dict) -> None:
        self.t[self.head] = t
        self.v[self.head] = [np.nan if row.get(f) is None else row[f] for f in self.fields]
        self.head = (self.head + 1) % self.cap
        self.n = min(self.n + 1, self.cap)

    def arrays(self, since: float | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        if self.n < self.cap:
            t = self.t[: self.n].copy()
            v = self.v[: self.n].copy()
        else:
            order = np.r_[self.head:self.cap, 0:self.head]
            t = self.t[order]
            v = self.v[order]
        if since is not None:
            start = int(np.searchsorted(t, since))
            t, v = t[start:], v[start:]
        return t, {f: v[:, i] for i, f in enumerate(self.fields)}


class ActiveEvent:
    def __init__(self, etype: str, t0: float, rng: random.Random, onset_min: float | None = None,
                 duration_min: float | None = None, peak: float | None = None):
        spec = EVENTS[etype]
        self.type = etype
        self.label = spec["label"]
        self.t0 = t0
        self.onset = (onset_min if onset_min is not None else rng.uniform(*spec["onset"])) * 60
        if duration_min is not None:
            self.duration = duration_min * 60
        elif spec["duration"]:
            self.duration = rng.uniform(*spec["duration"]) * 60
        else:
            self.duration = None
        self.peak = peak if peak is not None else rng.uniform(0.75, 1.0)
        self.factor = 1.0
        self.factor_target = 1.0
        self.ended_t: float | None = None
        self.treatments: list[str] = []
        self.uid = 0

    def update(self, t: float, dt: float) -> None:
        self.factor += (self.factor_target - self.factor) * (1 - math.exp(-dt / 90))
        if self.ended_t is None:
            if self.duration is not None and t - self.t0 > self.duration:
                self.ended_t = t
            elif self.factor_target < 0.12:
                self.ended_t = t

    def level(self, t: float) -> float:
        ramp = min(1.0, max(0.0, (t - self.t0) / self.onset))
        tail = 1.0 if self.ended_t is None else max(0.0, 1 - (t - self.ended_t) / 300)
        return self.peak * ramp * self.factor * tail

    def finished(self, t: float) -> bool:
        return self.ended_t is not None and t - self.ended_t >= 300

    def treat(self, intervention: str) -> bool:
        eff = EVENTS[self.type]["treatments"].get(intervention)
        if not eff:
            return False
        self.factor_target *= 1 - eff
        self.treatments.append(intervention)
        return True


class Transient:
    def __init__(self, t0: float, effects: dict, duration: float):
        self.t0 = t0
        self.effects = effects
        self.duration = duration

    def level(self, t: float) -> float:
        e = t - self.t0
        if e < 0 or e >= self.duration:
            return 0.0
        return min(1.0, e / 30) * (1 - e / self.duration)


class Patient:
    def __init__(self, engine: "SimulationEngine", profile: dict, location: str, bed: str, t_now: float,
                 progress: float = 0.0):
        rng = engine.rng
        self.engine = engine
        self.p = profile
        self.pid = profile["pid"]
        self.location = location
        self.bed = bed
        self.t = t_now
        self.planned_s = profile["planned_min"] * 60
        self.pacu_planned_s = rng.uniform(40, 80) * 60
        if location == "OR":
            self.or_start = t_now - progress * self.planned_s
            self.pacu_start = None
            elapsed = t_now - self.or_start
        else:
            self.pacu_start = t_now - progress * self.pacu_planned_s
            self.or_start = self.pacu_start - self.planned_s
            elapsed = self.planned_s
        w = profile["weight_kg"]
        self.ebl = BLEED_RATE[profile["bleed"]] * max(0, elapsed - 600) / 60 * rng.uniform(0.6, 1.2)
        self.ebl_rate = 0.0
        self.fluids = 300 + w * 6 * elapsed / 3600
        self.blood = 0.0
        self.uo = w * 1.0 * elapsed / 3600 if profile["foley"] else None
        base = profile["baseline"]
        cooling = 0.35 if profile["anes_class"] == "GA" and elapsed > 3600 else 0.2 * min(1, elapsed / 3600)
        self.temp = base["temp"] - cooling
        self.warming = profile["planned_min"] >= 120
        self.airway = profile["airway"] if location == "OR" else "NC"
        self.volatile_on = profile["volatile"]
        self.events: list[ActiveEvent] = []
        self.transients: list[Transient] = []
        self.state: dict[str, float | None] = {}
        self.noise: dict[str, float] = defaultdict(float)
        self.display: dict[str, float | None] = {}
        self.eff: dict[str, float] = defaultdict(float)
        self.rhythm = "竇性心律"
        self.ponv = False
        self.labs: dict | None = None
        self.lab_history: list[dict] = []
        self.auto_lab_times: list[float] = []
        periodic = profile["anes_class"] == "GA" and (profile["planned_min"] >= 150 or profile["bleed"] == "high")
        self.next_lab_t = t_now + rng.uniform(5, 40) * 60 if (periodic or "糖尿病" in profile["comorbidities"]) else None
        self.interventions: list[dict] = []
        self.notes: list[dict] = []
        self.history = RingBuffer(engine.history_cap, FIELDS)
        self.last_hist_t = -math.inf
        self.pain_base = rng.uniform(1.5, 4.0)
        self.bis_offset = rng.uniform(-5, 5)
        self.map_personal = rng.uniform(0.96, 1.04)
        self._init_state(t_now)

    # ---------- 階段 ----------
    def phase(self, t: float | None = None) -> str:
        t = self.t if t is None else t
        if self.location == "PACU":
            return "pacu"
        e = t - self.or_start
        if e < 600:
            return "induction"
        if e >= self.planned_s - 600:
            return "emergence"
        return "maintenance"

    def minutes_in_location(self, t: float | None = None) -> float:
        t = self.t if t is None else t
        start = self.pacu_start if self.location == "PACU" else self.or_start
        return (t - start) / 60

    # ---------- 生理目標值 ----------
    def _base_targets(self, t: float) -> dict:
        p = self.p
        b = p["baseline"]
        base_map = (b["sbp"] + 2 * b["dbp"]) / 3
        pp = b["sbp"] - b["dbp"]
        ph = self.phase(t)
        cls = p["anes_class"]
        T = {"hr": b["hr"], "map": base_map, "pp": pp, "spo2": b["spo2"], "etco2": 38.0, "rr": b["rr"],
             "bis": None, "ppeak": None, "pain": None}
        mf = 1.0
        if self.location == "OR":
            e = t - self.or_start
            if cls == "GA":
                ppeak = (17 if self.airway == "ETT" else 13) + max(0, p["bmi"] - 25) * 0.4
                if ph == "induction":
                    T["bis"] = 95 - 50 * min(1, e / 180) + self.bis_offset * min(1, e / 180)
                    mf = 1 - 0.25 * (e / 180) if e < 180 else 0.75 + 0.1 * min(1, (e - 180) / 420)
                    T["hr"] = b["hr"] * 0.95
                    if 150 < e < 330:  # 插管刺激
                        s = math.sin(math.pi * (e - 150) / 180)
                        T["hr"] += 14 * s
                        mf += 0.12 * s
                    T["spo2"] = 100
                    T["etco2"] = 36 if e > 120 else 30
                    T["rr"] = 12
                    T["ppeak"] = ppeak if e > 150 else None
                elif ph == "maintenance":
                    T["bis"] = 45 + self.bis_offset
                    mf = 0.86
                    T["hr"] = b["hr"] * 0.92
                    T["spo2"] = min(100, b["spo2"] + 3)
                    T["etco2"] = 36
                    T["rr"] = 12
                    T["ppeak"] = ppeak
                else:
                    y = min(1, max(0, (e - (self.planned_s - 600)) / 600))
                    T["bis"] = 45 + self.bis_offset + 40 * y
                    mf = 0.86 + 0.16 * y
                    T["hr"] = b["hr"] * (0.92 + 0.18 * y)
                    T["spo2"] = min(100, b["spo2"] + 3 - y)
                    T["etco2"] = 36 + 6 * y
                    T["rr"] = 12 + 3 * y
                    T["ppeak"] = ppeak * (1 - 0.3 * y)
            elif cls == "NEURAXIAL":
                mf = 1 - 0.16 * min(1, e / 480) if ph == "induction" else (0.86 if ph == "maintenance" else 0.9)
                T["hr"] = b["hr"] * 0.95
                T["spo2"] = min(100, b["spo2"] + 1)
                T["etco2"] = 34
                T["rr"] = 16
            else:  # MAC
                mf = 0.93
                T["hr"] = b["hr"] * 0.97
                T["bis"] = 72 + self.bis_offset
                T["etco2"] = 39
                T["rr"] = 13
        else:
            e = t - self.pacu_start
            y = min(1, e / 1800)
            mf = 0.95 + 0.08 * y
            T["hr"] = b["hr"] * 1.04
            T["spo2"] = min(100, b["spo2"] + (1 if e < 2400 else 0))
            T["etco2"] = 38
            T["rr"] = 16
            T["pain"] = self.pain_base * (1 - 0.45 * y)
        T["map"] = base_map * mf * self.map_personal
        T["pp"] = pp * math.sqrt(mf)
        return T

    def _event_effects(self, t: float) -> tuple[dict, str | None]:
        eff: dict[str, float] = defaultdict(float)
        rhythm, rhythm_level = None, 0.0
        for ev in self.events:
            lv = ev.level(t)
            if lv <= 0:
                continue
            for key, val in EVENTS[ev.type]["effects"].items():
                if key == "rhythm":
                    if lv > 0.4 and lv > rhythm_level:
                        rhythm, rhythm_level = val, lv
                else:
                    eff[key] += val * lv
        for tr in self.transients:
            lv = tr.level(t)
            if lv > 0:
                for key, val in tr.effects.items():
                    eff[key] += val * lv
        return eff, rhythm

    def _targets(self, t: float) -> tuple[dict, dict, str | None]:
        T = self._base_targets(t)
        eff, rhythm = self._event_effects(t)
        T["hr"] += eff["hr"]
        mult = max(0.3, 1 + eff["map_pct"])
        T["map"] *= mult
        T["pp"] *= math.sqrt(mult)
        T["spo2"] = min(100, T["spo2"] + eff["spo2"])
        T["etco2"] += eff["etco2"]
        ventilated = self.location == "OR" and self.p["anes_class"] == "GA" and self.phase(t) != "emergence"
        if not ventilated:
            T["rr"] += eff["rr"]
        if T["bis"] is not None:
            T["bis"] += eff["bis"]
        if T["ppeak"] is not None:
            T["ppeak"] += eff["ppeak"]
        if T["pain"] is not None:
            T["pain"] += eff["pain"]
        return T, eff, rhythm

    def _init_state(self, t: float) -> None:
        T, eff, _ = self._targets(t)
        for f, _tau, _sd, lo, hi in SMOOTHING:
            v = T.get(f)
            self.state[f] = None if v is None else min(hi, max(lo, v))
            self.display[f] = self.state[f]
        self._compose_display(eff)

    def _compose_display(self, eff: dict) -> None:
        d = self.display
        if d.get("map") is not None and self.state.get("pp") is not None:
            pp = self.state["pp"]
            d["sbp"] = d["map"] + 2 / 3 * pp
            d["dbp"] = d["map"] - 1 / 3 * pp
        d["temp"] = self.temp

    # ---------- 每一步 ----------
    def step(self, t: float, dt: float) -> None:
        rng = self.engine.rng
        self.t = t
        for ev in self.events:
            ev.update(t, dt)
            if ev.finished(t):
                self.engine._emit("event_update", uid=ev.uid, ended_t=ev.ended_t, treatments=list(ev.treatments))
        self.events = [ev for ev in self.events if not ev.finished(t)]
        self.transients = [tr for tr in self.transients if t - tr.t0 < tr.duration]

        T, eff, rhythm = self._targets(t)
        self.eff = eff
        for f, tau, sd, lo, hi in SMOOTHING:
            tgt = T.get(f)
            if tgt is None:
                self.state[f] = None
                self.display[f] = None
                continue
            tgt = min(hi, max(lo, tgt))
            cur = self.state.get(f)
            cur = tgt if cur is None else cur + (tgt - cur) * (1 - math.exp(-dt / tau))
            self.state[f] = cur
            rho = math.exp(-dt / NOISE_TAU)
            self.noise[f] = self.noise[f] * rho + rng.gauss(0, sd) * math.sqrt(1 - rho * rho)
            val = cur + self.noise[f]
            if f == "hr" and eff["hr_noise"] > 0:
                val += rng.gauss(0, eff["hr_noise"])
            self.display[f] = min(hi, max(lo, val))

        ph = self.phase(t)
        cls = self.p["anes_class"]
        base_temp = self.p["baseline"]["temp"]
        if self.location == "OR":
            e = t - self.or_start
            drift = {"GA": -0.35 if e < 3600 else -0.1, "NEURAXIAL": -0.2, "MAC": -0.1}[cls]
            if self.warming:
                drift += 0.35
        else:
            drift = 0.5 if self.temp < base_temp else 0.0
        if self.temp > base_temp + 0.2 and eff["temp_rate"] <= 0:
            drift = min(drift, -0.3)
        self.temp += drift * dt / 3600 + eff["temp_rate"] * dt / 60 + rng.gauss(0, 0.004)
        self.temp = min(43.0, max(32.0, self.temp))

        bleed_bg = BLEED_RATE[self.p["bleed"]] if (self.location == "OR" and ph == "maintenance") else 0.0
        self.ebl_rate = bleed_bg * (0.6 + 0.8 * rng.random()) + eff["ebl_rate"]
        self.ebl += self.ebl_rate * dt / 60
        w = self.p["weight_kg"]
        self.fluids += w * (6 if self.location == "OR" else 1.5) * dt / 3600
        if self.uo is not None:
            f = max(0.05, 1 + eff["uo_factor"])
            if (self.display.get("map") or 80) < 65:
                f *= 0.5
            rate = (1.0 if self.location == "OR" else 0.8) * f
            self.uo += rate * w * dt / 3600 * (0.7 + 0.6 * rng.random())

        self._compose_display(eff)
        hr = self.display["hr"]
        self.rhythm = rhythm or ("竇性心搏過速" if hr > 100 else "竇性心搏過緩" if hr < 50 else "竇性心律")
        self.ponv = eff["ponv"] > 0.3

        if self.next_lab_t is not None and t >= self.next_lab_t:
            self.draw_labs(t, "例行檢驗")
            self.next_lab_t = t + 3600
        if self.auto_lab_times and t >= self.auto_lab_times[0]:
            self.auto_lab_times.pop(0)
            self.draw_labs(t, "病況變化加驗")

        if t - self.last_hist_t >= self.engine.hist_interval:
            self.last_hist_t = t
            rec = self.record()
            self.history.append(t, rec)
            self.engine._record_vital(self, t, rec)

    def record(self) -> dict:
        d = self.display
        evt = sum(ev.level(self.t) for ev in self.events)
        return {
            "hr": d["hr"], "sbp": d.get("sbp"), "dbp": d.get("dbp"), "map": d["map"], "spo2": d["spo2"],
            "etco2": d["etco2"], "rr": d["rr"], "temp": self.temp, "bis": d["bis"], "ppeak": d["ppeak"],
            "pain": d["pain"], "ebl": self.ebl, "uo": self.uo, "fluids": self.fluids + self.blood,
            "phase": PHASE_CODE[self.phase()], "case_min": (self.t - self.or_start) / 60, "evt": evt,
        }

    # ---------- 檢驗 ----------
    def draw_labs(self, t: float, reason: str) -> dict:
        rng = self.engine.rng
        l0 = self.p["labs0"]
        eff = self.eff
        w = self.p["weight_kg"]
        ebv = w * (70 if self.p["sex"] == "M" else 65)
        crystalloid = max(0.0, self.fluids - 300)
        hb = l0["hb"] * (1 - 0.85 * max(0.0, self.ebl - self.blood) / ebv) - 0.6 * crystalloid / ebv
        mapv = self.display.get("map") or 80
        lactate = l0["lactate"] + eff["lactate"] + max(0.0, 62 - mapv) * 0.04
        k = l0["k"] + eff["k"] + self.blood * 0.0006
        glucose = l0["glucose"] + eff["glucose"] + (15 if self.location == "OR" else 5)
        etco2 = self.display.get("etco2") or 38
        paco2 = etco2 + rng.uniform(3, 7)
        hco3 = 24.5 - (lactate - 1.0) * 0.9
        ph = 6.1 + math.log10(hco3 / (0.03 * paco2))
        spo2 = self.display.get("spo2") or 97
        fio2_high = self.location == "OR" and self.p["anes_class"] == "GA"
        pao2 = (rng.uniform(220, 320) if fio2_high else rng.uniform(90, 140)) if spo2 >= 95 else 55 + (spo2 - 85) * 4
        labs = {
            "t": t,
            "reason": reason,
            "ph": round(ph + rng.gauss(0, 0.01), 2),
            "paco2": round(paco2),
            "pao2": round(max(40, pao2)),
            "hco3": round(hco3 + rng.gauss(0, 0.4), 1),
            "be": round(hco3 - 24.5 + rng.gauss(0, 0.5), 1),
            "hb": round(max(4.0, hb + rng.gauss(0, 0.2)), 1),
            "k": round(k + rng.gauss(0, 0.1), 1),
            "na": round(l0["na"] + rng.gauss(0, 1)),
            "glucose": round(glucose + rng.gauss(0, 6)),
            "lactate": round(max(0.4, lactate + rng.gauss(0, 0.1)), 1),
            "ica": round(1.18 - self.blood * 0.0002 + rng.gauss(0, 0.02), 2),
        }
        self.labs = labs
        self.lab_history.append(labs)
        self.lab_history = self.lab_history[-12:]
        self.engine._emit("lab", pid=self.pid, labs=dict(labs))
        return labs

    # ---------- 事件與處置 ----------
    def eligible(self, etype: str) -> bool:
        spec = EVENTS[etype]
        if self.location not in spec["locations"]:
            return False
        if "anes" in spec and self.p["anes_class"] not in spec["anes"]:
            return False
        if "phases" in spec and self.phase() not in spec["phases"]:
            return False
        req = spec.get("requires")
        comorb = self.p["comorbidities"]
        if req == "bleed_risk" and self.p["bleed"] not in ("mid", "high"):
            return False
        if req == "volatile" and not self.volatile_on:
            return False
        if req == "ckd" and "慢性腎臟病" not in comorb:
            return False
        if req == "dm" and "糖尿病" not in comorb:
            return False
        if req == "foley" and self.uo is None:
            return False
        if req == "age55" and self.p["age"] < 55:
            return False
        if any(ev.type == etype for ev in self.events):
            return False
        return True

    def add_event(self, etype: str, t: float, injected: bool = False, **kwargs) -> ActiveEvent:
        ev = ActiveEvent(etype, t, self.engine.rng, **kwargs)
        ev.uid = self.engine.next_event_uid()
        self.events.append(ev)
        self.engine._emit("event_start", pid=self.pid, uid=ev.uid, type=etype, label=ev.label, peak=ev.peak,
                          injected=injected, t=ev.t0)
        if any(k in EVENTS[etype]["effects"] for k in ("k", "glucose", "lactate")):
            self.auto_lab_times.append(t + ev.onset + 120)
            self.auto_lab_times.sort()
        return ev

    def apply_intervention(self, itype: str, t: float, by: str = "使用者") -> dict:
        spec = INTERVENTIONS[itype]
        treated_events = [ev for ev in self.events if ev.ended_t is None and ev.treat(itype)]
        treated = [ev.label for ev in treated_events]
        if "transient" in spec:
            effects, dur = spec["transient"]
            self.transients.append(Transient(t, effects, dur))
        self.fluids += spec.get("fluids", 0)
        self.blood += spec.get("blood", 0)
        if itype == "warming":
            self.warming = True
        if itype == "stop_volatile":
            self.volatile_on = False
        if itype == "draw_abg":
            self.draw_labs(t, "臨床抽血")
        entry = {"t": t, "type": itype, "label": spec["label"], "by": by}
        self.interventions.append(entry)
        self.engine._emit("intervention", pid=self.pid, type=itype, label=spec["label"], by=by, t=t, affected=treated)
        for ev in treated_events:
            self.engine._emit("event_update", uid=ev.uid, ended_t=ev.ended_t, treatments=list(ev.treatments))
        return {"entry": entry, "affected": treated}

    # ---------- 輸出 ----------
    def drugs(self) -> list[str]:
        p = self.p
        out = []
        if self.location == "OR":
            if p["anes_class"] == "GA":
                if self.volatile_on:
                    out.append("Sevoflurane 1.8–2.2%（約 0.9 MAC）")
                else:
                    out.append("Propofol TCI 3.0 mcg/mL")
                out.append("Remifentanil 0.1 mcg/kg/min")
                out.append("Rocuronium（依肌張力追加）")
            elif p["anes_class"] == "NEURAXIAL":
                out.append("Bupivacaine 0.5% heavy 2.6 mL（" + ("脊椎" if p["anes_code"] == "SA" else "硬脊膜外") + "）")
                out.append("Dexmedetomidine 0.3 mcg/kg/h（輕度鎮靜）")
            else:
                out.append("Propofol 30 mcg/kg/min（鎮靜）")
                out.append("Fentanyl 25 mcg IV PRN")
        else:
            out.append("O₂ 鼻導管 3 L/min")
            if p["planned_min"] >= 120:
                out.append("IV PCA（Morphine）")
        recent = {i["type"] for i in self.interventions if self.t - i["t"] < 1800}
        if "vasopressor" in recent:
            out.append("Norepinephrine 0.05 mcg/kg/min")
        if "insulin" in recent:
            out.append("Regular Insulin 2 U/h")
        return out

    def vitals(self) -> dict:
        d = self.display

        def r(v, nd=0):
            return None if v is None else (round(v, nd) if nd else int(round(v)))

        return {
            "hr": r(d["hr"]), "sbp": r(d.get("sbp")), "dbp": r(d.get("dbp")), "map": r(d["map"]),
            "spo2": r(d["spo2"]), "etco2": r(d["etco2"]), "rr": r(d["rr"]), "temp": r(self.temp, 1),
            "bis": r(d["bis"]), "ppeak": r(d["ppeak"]), "pain": r(d["pain"]),
        }

    def brief(self) -> dict:
        p = self.p
        ph = self.phase()
        return {
            "pid": self.pid, "bed": self.bed, "name": p["name"], "age": p["age"], "sex": p["sex"],
            "asa": p["asa"], "surgery": p["surgery"], "anes_label": p["anes_label"], "anes_class": p["anes_class"],
            "location": self.location, "phase": ph, "phase_label": PHASE_LABEL[ph],
            "minutes": round(self.minutes_in_location()), "vitals": self.vitals(), "rhythm": self.rhythm,
            "ebl": round(self.ebl), "uo": None if self.uo is None else round(self.uo), "ponv": self.ponv,
        }


class SimulationEngine:
    def __init__(self, n_patients: int = 50, seed: int | None = None, history_cap: int = 2200,
                 hist_interval: float = 5.0, warmup_minutes: float = 30.0, seed_events: bool = True,
                 speed: float = 5.0, event_rate: float = 1.0, record: bool = False):
        self.n_patients = n_patients
        # record=True 時，資料變化會放進 outbox，由 services.recorder 批次寫入資料庫
        self.record = record
        self.outbox: list[tuple[str, dict]] = []
        self.vital_outbox: list[dict] = []
        self.run_seq = 0
        self.event_uid = 0
        self.history_cap = history_cap
        self.hist_interval = hist_interval
        self.warmup_minutes = warmup_minutes
        self.seed_events = seed_events
        self.speed = speed
        self.event_rate = event_rate
        self.running = True
        self.on_discharge = None  # callback(patient)
        self.reset(seed)

    # ---------- 初始化 ----------
    def reset(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.pid_counter = 0
        self.run_seq += 1
        self.t = datetime.now().replace(microsecond=0).timestamp() - self.warmup_minutes * 60
        n = self.n_patients
        self._emit("run_start", n_patients=n, seed=seed, t=self.t, wall_t=time.time())
        self.or_beds = [f"OR-{i:02d}" for i in range(1, math.ceil(n * 0.8) + 5)]
        self.pacu_beds = [f"PACU-{i:02d}" for i in range(1, math.ceil(n * 0.4) + 1)]
        self.patients: dict[str, Patient] = {}
        self.log: deque[dict] = deque(maxlen=200)
        n_or = round(n * 0.72)
        for i in range(n):
            if i < n_or:
                bed = self.or_beds[i]
                self._admit(bed, "OR", progress=self.rng.uniform(0.05, 0.95))
            else:
                bed = self.pacu_beds[i - n_or]
                self._admit(bed, "PACU", progress=self.rng.uniform(0.0, 0.8))
        if self.seed_events:
            self._seed_initial_events()
        steps = int(self.warmup_minutes * 60 / 10)
        for _ in range(steps):
            self.step(10.0, allow_random=False)
        self.log.clear()
        self._log(None, "模擬開始：共 %d 位病人（手術室 %d、恢復室 %d）" % (
            len(self.patients), self.count("OR"), self.count("PACU")))

    def _next_pid(self) -> str:
        self.pid_counter += 1
        return f"P{self.pid_counter:03d}"

    def _admit(self, bed: str, location: str, progress: float = 0.0) -> Patient:
        profile = generate_profile(self.rng, self._next_pid())
        patient = Patient(self, profile, location, bed, self.t, progress)
        self.patients[patient.pid] = patient
        self._emit("admit", profile=profile, location=location, bed=bed, t=patient.or_start, pacu_t=patient.pacu_start)
        return patient

    def _seed_initial_events(self) -> None:
        wanted = ["hypotension", "hypotension", "hemorrhage", "light_anesthesia", "hypothermia", "bradycardia",
                  "desaturation", "hyperglycemia", "pacu_pain", "resp_depression", "oliguria",
                  "atrial_fibrillation", "hypertension", "ponv"]
        pool = list(self.patients.values())
        self.rng.shuffle(pool)
        used = set()
        for etype in wanted:
            for p in pool:
                if p.pid in used:
                    continue
                # 暖機期間階段可能改變，先用暖機結束時的階段判斷
                if p.eligible(etype) and (p.location == "PACU" or p.minutes_in_location() + 45 < p.p["planned_min"]):
                    start = self.t + self.rng.uniform(0, self.warmup_minutes * 0.8) * 60
                    p.add_event(etype, start)
                    used.add(p.pid)
                    break

    def count(self, location: str) -> int:
        return sum(1 for p in self.patients.values() if p.location == location)

    def _log(self, pid: str | None, text: str, level: str = "info") -> None:
        self.log.append({"t": self.t, "pid": pid, "text": text, "level": level})

    # ---------- 資料紀錄（給資料庫） ----------
    def _emit(self, kind: str, **data) -> None:
        if self.record:
            self.outbox.append((kind, data))

    def _record_vital(self, p: "Patient", t: float, rec: dict) -> None:
        if self.record:
            self.vital_outbox.append({**rec, "t": t, "pid": p.pid, "bed": p.bed, "location": p.location,
                                      "phase": p.phase(t), "run_seq": self.run_seq})

    def next_event_uid(self) -> int:
        self.event_uid += 1
        return self.event_uid

    def drain_outbox(self) -> tuple[list, list]:
        events, vitals = self.outbox, self.vital_outbox
        self.outbox, self.vital_outbox = [], []
        return events, vitals

    def requeue_outbox(self, events: list, vitals: list, max_vitals: int = 200_000) -> None:
        """寫入資料庫失敗時把資料放回佇列（生命徵象最多保留 max_vitals 筆，避免記憶體無限增加）。"""
        self.outbox = events + self.outbox
        self.vital_outbox = (vitals + self.vital_outbox)[-max_vitals:]

    # ---------- 時間推進 ----------
    def step(self, dt: float, allow_random: bool = True) -> None:
        self.t += dt
        for p in list(self.patients.values()):
            p.step(self.t, dt)
            if allow_random:
                self._maybe_random_event(p, dt)
        self._flow()

    def _maybe_random_event(self, p: Patient, dt: float) -> None:
        if self.event_rate <= 0 or len([e for e in p.events if e.ended_t is None]) >= 2:
            return
        hazard = 0.15 * self.event_rate * dt / 3600
        if self.rng.random() >= hazard:
            return
        options = [e for e in EVENTS if p.eligible(e)]
        if not options:
            return
        etype = self.rng.choices(options, weights=[EVENTS[e]["weight"] for e in options])[0]
        p.add_event(etype, self.t)

    def _flow(self) -> None:
        for p in list(self.patients.values()):
            if p.location == "OR" and self.t - p.or_start >= p.planned_s:
                free = self._free_beds("PACU")
                if free:
                    self._transfer_to_pacu(p, free[0])
            elif p.location == "PACU" and self.t - p.pacu_start >= p.pacu_planned_s:
                if any(ev.level(self.t) > 0.3 for ev in p.events):
                    p.pacu_planned_s += 600
                else:
                    self._discharge(p)

    def _free_beds(self, location: str) -> list[str]:
        used = {p.bed for p in self.patients.values()}
        beds = self.or_beds if location == "OR" else self.pacu_beds
        return [b for b in beds if b not in used]

    def _transfer_to_pacu(self, p: Patient, bed: str) -> None:
        old = p.bed
        p.location = "PACU"
        p.bed = bed
        p.pacu_start = self.t
        p.airway = "NC"
        for ev in p.events:
            if "PACU" not in EVENTS[ev.type]["locations"] and ev.ended_t is None:
                ev.ended_t = self.t
        self._emit("transfer", pid=p.pid, bed=bed, t=self.t)
        self._log(p.pid, f"{p.pid} 手術結束，由 {old} 轉入 {bed}")

    def _discharge(self, p: Patient) -> None:
        del self.patients[p.pid]
        for ev in p.events:
            self._emit("event_update", uid=ev.uid, ended_t=ev.ended_t or self.t, treatments=list(ev.treatments))
        self._emit("discharge", pid=p.pid, t=self.t)
        if self.on_discharge:
            self.on_discharge(p)
        self._log(p.pid, f"{p.pid} 由 {p.bed} 轉出恢復室")
        free = self._free_beds("OR")
        if free:
            newp = self._admit(free[0], "OR", progress=0.0)
            self._log(newp.pid, f"{newp.pid} 進入 {newp.bed}，開始麻醉誘導（{newp.p['surgery']}）")

    # ---------- 操作 ----------
    def get(self, pid: str) -> Patient | None:
        pid = pid.strip().upper()
        if pid in self.patients:
            return self.patients[pid]
        for p in self.patients.values():
            if p.bed.upper() == pid:
                return p
        return None

    def inject_event(self, pid: str, etype: str) -> tuple[bool, str]:
        p = self.get(pid)
        if not p:
            return False, "找不到此病人"
        if etype not in EVENTS:
            return False, "未知的事件類型"
        if not p.eligible(etype):
            return False, f"{p.pid}（{p.bed}）目前不適用「{EVENTS[etype]['label']}」情境，或已在進行中"
        ev = p.add_event(etype, self.t, peak=1.0, injected=True)
        self._log(p.pid, f"情境演練：{p.pid} 注入「{ev.label}」", "warning")
        return True, f"已在 {p.pid}（{p.bed}）注入「{ev.label}」，約 {ev.onset / 60:.0f} 分鐘（模擬時間）達高峰"

    def apply_intervention(self, pid: str, itype: str, by: str = "使用者") -> tuple[bool, str, dict | None]:
        p = self.get(pid)
        if not p:
            return False, "找不到此病人", None
        if itype not in INTERVENTIONS:
            return False, "未知的處置", None
        result = p.apply_intervention(itype, self.t, by)
        label = INTERVENTIONS[itype]["label"]
        msg = f"{p.pid} 已執行：{label}"
        if result["affected"]:
            msg += "（對「" + "、".join(result["affected"]) + "」有效）"
        self._log(p.pid, msg)
        return True, msg, result["entry"]

    def add_note(self, pid: str, text: str, by: str) -> bool:
        p = self.get(pid)
        if not p:
            return False
        note = {"t": self.t, "text": text[:500], "by": by}
        p.notes.append(note)
        self._emit("note", pid=p.pid, text=note["text"], by=by, t=self.t)
        return True

    def active_events(self) -> list[dict]:
        out = []
        for p in self.patients.values():
            for ev in p.events:
                out.append({
                    "pid": p.pid, "bed": p.bed, "type": ev.type, "label": ev.label,
                    "level": round(ev.level(self.t), 2), "minutes": round((self.t - ev.t0) / 60),
                    "ending": ev.ended_t is not None,
                    "treatments": [INTERVENTIONS[t]["label"] for t in ev.treatments],
                })
        return sorted(out, key=lambda e: -e["level"])

    # ---------- 查詢 ----------
    def sorted_patients(self) -> list[Patient]:
        return sorted(self.patients.values(), key=lambda p: (p.location != "OR", p.bed))

    def detail(self, pid: str) -> dict | None:
        p = self.get(pid)
        if not p:
            return None
        prof = p.p
        w = prof["weight_kg"]
        ebv = w * (70 if prof["sex"] == "M" else 65)
        out = p.brief()
        out.update({
            "mrn": prof["mrn"], "height_cm": prof["height_cm"], "weight_kg": w, "bmi": prof["bmi"],
            "comorbidities": prof["comorbidities"], "allergies": prof["allergies"], "smoker": prof["smoker"],
            "ponv_history": prof["ponv_history"], "specialty": prof["specialty"],
            "planned_min": prof["planned_min"], "case_minutes": round((p.t - p.or_start) / 60),
            "airway": AIRWAY_LABEL[p.airway], "baseline": prof["baseline"], "drugs": p.drugs(),
            "fluids": {"crystalloid_ml": round(p.fluids), "blood_ml": round(p.blood), "ebl_ml": round(p.ebl),
                       "ebl_pct": round(100 * p.ebl / ebv, 1), "urine_ml": None if p.uo is None else round(p.uo)},
            "labs": p.labs, "lab_history": p.lab_history[-5:],
            "interventions": p.interventions[-15:], "notes": p.notes[-15:],
            "sim_time": p.t,
        })
        return out

    def trend(self, pid: str, minutes: float = 60, fields: list[str] | None = None, max_points: int = 240) -> dict | None:
        p = self.get(pid)
        if not p:
            return None
        ts, cols = p.history.arrays(since=self.t - minutes * 60)
        fields = fields or ["hr", "sbp", "dbp", "map", "spo2", "etco2", "rr", "temp", "bis", "pain"]
        if len(ts) > max_points:
            idx = np.linspace(0, len(ts) - 1, max_points).astype(int)
            ts = ts[idx]
            cols = {k: v[idx] for k, v in cols.items()}
        out = {"t": [float(x) for x in ts]}
        for f in fields:
            if f in cols:
                out[f] = [None if np.isnan(x) else round(float(x), 1) for x in cols[f]]
        return out

    def export_csv(self, minutes: float = 60) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        cols_out = [f for f in FIELDS if f != "evt"]
        writer.writerow(["time", "pid", "bed", "location", "age", "sex", "asa", "surgery", "anesthesia"] + cols_out)
        for p in self.sorted_patients():
            ts, cols = p.history.arrays(since=self.t - minutes * 60)
            for i, t in enumerate(ts):
                row = [datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"), p.pid, p.bed, p.location,
                       p.p["age"], p.p["sex"], p.p["asa"], p.p["surgery"], p.p["anes_label"]]
                row += ["" if np.isnan(cols[f][i]) else round(float(cols[f][i]), 2) for f in cols_out]
                writer.writerow(row)
        return buf.getvalue()
