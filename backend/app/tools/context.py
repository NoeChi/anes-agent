"""PatientContext：工具讀取病人資料的唯一入口（只讀、不含模擬器內部的「答案」）。"""
from __future__ import annotations

import math
from functools import cached_property

import numpy as np

from ..ml.features import compute_features, compute_sequence
from ..simulator.engine import PHASE_LABEL, Patient

OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


class PatientContext:
    HISTORY_MINUTES = 90

    def __init__(self, patient: Patient):
        p = patient
        prof = p.p
        self.pid = p.pid
        self.bed = p.bed
        self.t = p.t
        self.profile = prof
        self.name = prof["name"]
        self.age = prof["age"]
        self.sex = prof["sex"]
        self.weight = prof["weight_kg"]
        self.asa = prof["asa"]
        self.comorbidities = list(prof["comorbidities"])
        self.anes_class = prof["anes_class"]
        self.anes_label = prof["anes_label"]
        self.surgery = prof["surgery"]
        self.location = p.location
        self.phase = p.phase()
        self.phase_label = PHASE_LABEL[self.phase]
        self.minutes_in_location = p.minutes_in_location()
        self.case_minutes = (p.t - p.or_start) / 60
        self.baseline = dict(prof["baseline"])
        self.vitals = p.vitals()
        self.rhythm = p.rhythm
        self.ponv = p.ponv
        self.ebl = p.ebl
        self.urine = p.uo
        self.fluids = p.fluids + p.blood
        self.has_foley = p.uo is not None
        self.labs = dict(p.labs) if p.labs else None
        self.labs_age_min = (p.t - p.labs["t"]) / 60 if p.labs else None
        self.ts, self.cols = p.history.arrays(since=p.t - self.HISTORY_MINUTES * 60)

    # ---- 基本 ----
    @property
    def ebv(self) -> float:
        return self.weight * (70 if self.sex == "M" else 65)

    @property
    def baseline_map(self) -> float:
        b = self.baseline
        return (b["sbp"] + 2 * b["dbp"]) / 3

    def label(self) -> str:
        return f"{self.pid}（{self.bed}，{self.age}歲{'男' if self.sex == 'M' else '女'}，{self.surgery}）"

    # ---- 歷史資料 ----
    def series(self, field: str, minutes: float) -> tuple[np.ndarray, np.ndarray]:
        if field not in self.cols or len(self.ts) == 0:
            return np.array([]), np.array([])
        start = int(np.searchsorted(self.ts, self.t - minutes * 60))
        return self.ts[start:], self.cols[field][start:]

    def sustained_minutes(self, field: str, op: str, value: float) -> float:
        """條件從現在往回「連續」成立了幾分鐘。"""
        if field not in self.cols or len(self.ts) == 0:
            return 0.0
        x = self.cols[field]
        cmp = OPS[op]
        i = len(x) - 1
        while i >= 0 and not math.isnan(x[i]) and cmp(x[i], value):
            i -= 1
        if i == len(x) - 1:
            return 0.0
        start_t = self.ts[i + 1] if i >= 0 else self.ts[0]
        return (self.t - start_t) / 60 + (self.ts[1] - self.ts[0] if len(self.ts) > 1 else 0) / 60

    def change_over(self, field: str, minutes: float) -> float | None:
        ts, x = self.series(field, minutes)
        m = ~np.isnan(x)
        if m.sum() < 2:
            return None
        return float(x[m][-1] - x[m][0])

    def mean(self, field: str, minutes: float) -> float | None:
        _, x = self.series(field, minutes)
        x = x[~np.isnan(x)]
        return float(x.mean()) if x.size else None

    def urine_rate(self, minutes: float = 60) -> float | None:
        """尿量 mL/kg/h（近 N 分鐘）。"""
        if not self.has_foley:
            return None
        ts, x = self.series("uo", minutes)
        m = ~np.isnan(x)
        if m.sum() < 2:
            return None
        hours = (ts[m][-1] - ts[m][0]) / 3600
        if hours < 0.25:
            return None
        return float((x[m][-1] - x[m][0]) / self.weight / hours)

    def ebl_over(self, minutes: float) -> float | None:
        return self.change_over("ebl", minutes)

    @cached_property
    def features(self) -> dict[str, float]:
        if len(self.ts) < 3:
            return {}
        return compute_features(self.ts, self.cols, len(self.ts) - 1, self.profile)

    @cached_property
    def sequence(self) -> dict[str, float]:
        if len(self.ts) < 3:
            return {}
        return compute_sequence(self.ts, self.cols, len(self.ts) - 1)

    def lab(self, key: str, max_age_min: float = 120) -> float | None:
        if not self.labs or self.labs_age_min is None or self.labs_age_min > max_age_min:
            return None
        return self.labs.get(key)
