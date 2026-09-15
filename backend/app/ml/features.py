"""機器學習特徵：即時查房與模型訓練共用同一套特徵計算，確保一致。"""
from __future__ import annotations

import math

import numpy as np

# key, 中文名稱, 分組
FEATURE_CATALOG: list[tuple[str, str, str]] = [
    ("map_now", "目前平均動脈壓 MAP", "血壓"),
    ("map_mean5", "近 5 分鐘 MAP 平均", "血壓"),
    ("map_min5", "近 5 分鐘 MAP 最低", "血壓"),
    ("map_slope5", "近 5 分鐘 MAP 變化速度（每分鐘）", "血壓"),
    ("map_slope10", "近 10 分鐘 MAP 變化速度（每分鐘）", "血壓"),
    ("map_baseline_ratio", "MAP 相對術前基準比例", "血壓"),
    ("sbp_now", "目前收縮壓", "血壓"),
    ("pp_now", "目前脈搏壓（收縮壓−舒張壓）", "血壓"),
    ("hr_now", "目前心跳", "心跳"),
    ("hr_mean5", "近 5 分鐘心跳平均", "心跳"),
    ("hr_slope5", "近 5 分鐘心跳變化速度", "心跳"),
    ("hr_std5", "近 5 分鐘心跳變異", "心跳"),
    ("shock_index", "休克指數（心跳/收縮壓）", "心跳"),
    ("spo2_now", "目前血氧 SpO₂", "呼吸"),
    ("spo2_min5", "近 5 分鐘血氧最低", "呼吸"),
    ("spo2_slope5", "近 5 分鐘血氧變化速度", "呼吸"),
    ("etco2_now", "目前呼氣末二氧化碳 EtCO₂", "呼吸"),
    ("etco2_slope10", "近 10 分鐘 EtCO₂ 變化速度", "呼吸"),
    ("rr_now", "目前呼吸速率", "呼吸"),
    ("temp_now", "目前體溫", "其他"),
    ("temp_slope30", "近 30 分鐘體溫變化速度", "其他"),
    ("bis_now", "目前 BIS 麻醉深度", "其他"),
    ("ebl_rate15", "近 15 分鐘出血速度（mL/分）", "其他"),
    ("age", "年齡", "病人特性"),
    ("asa", "ASA 分級", "病人特性"),
    ("bmi", "BMI", "病人特性"),
    ("sex_male", "男性", "病人特性"),
    ("is_ga", "全身麻醉", "病人特性"),
    ("phase_code", "麻醉階段（0誘導 1維持 2甦醒 3恢復室）", "病人特性"),
    ("case_min", "手術已進行分鐘數", "病人特性"),
]
FEATURE_KEYS = [f[0] for f in FEATURE_CATALOG]
FEATURE_LABELS = {k: label for k, label, _ in FEATURE_CATALOG}

SEQ_FIELDS = ["hr", "map", "spo2", "etco2", "rr"]
SEQ_MINUTES = 15
SEQ_KEYS = [f"seq_{f}_{i}" for f in SEQ_FIELDS for i in range(SEQ_MINUTES)]
SEQ_DEFAULTS = {"hr": 75.0, "map": 80.0, "spo2": 97.0, "etco2": 36.0, "rr": 14.0}


def _last(x: np.ndarray) -> float:
    valid = x[~np.isnan(x)]
    return float(valid[-1]) if valid.size else math.nan


def _mean(x: np.ndarray) -> float:
    valid = x[~np.isnan(x)]
    return float(valid.mean()) if valid.size else math.nan


def _min(x: np.ndarray) -> float:
    valid = x[~np.isnan(x)]
    return float(valid.min()) if valid.size else math.nan


def _std(x: np.ndarray) -> float:
    valid = x[~np.isnan(x)]
    return float(valid.std()) if valid.size > 1 else 0.0


def _slope(t: np.ndarray, x: np.ndarray) -> float:
    m = ~np.isnan(x)
    if m.sum() < 3:
        return 0.0
    tt = t[m] - t[m].mean()
    denom = float((tt * tt).sum())
    if denom <= 0:
        return 0.0
    return float((tt * (x[m] - x[m].mean())).sum() / denom * 60)


def compute_features(ts: np.ndarray, cols: dict[str, np.ndarray], end: int, profile: dict) -> dict[str, float]:
    """以 index `end`（含）為「現在」，計算特徵。ts 單位為秒。"""
    t_now = ts[end]

    def win(minutes: float) -> slice:
        start = int(np.searchsorted(ts, t_now - minutes * 60))
        return slice(start, end + 1)

    w5, w10, w15, w30 = win(5), win(10), win(15), win(30)
    b = profile["baseline"]
    base_map = (b["sbp"] + 2 * b["dbp"]) / 3
    map_now = _last(cols["map"][w5])
    sbp_now = _last(cols["sbp"][w5])
    hr_now = _last(cols["hr"][w5])
    ebl = cols["ebl"][w15]
    ebl_valid = ebl[~np.isnan(ebl)]
    span = (ts[end] - ts[w15.start]) / 60 if end > w15.start else 0
    ebl_rate = float((ebl_valid[-1] - ebl_valid[0]) / span) if ebl_valid.size > 1 and span > 0 else 0.0
    return {
        "map_now": map_now,
        "map_mean5": _mean(cols["map"][w5]),
        "map_min5": _min(cols["map"][w5]),
        "map_slope5": _slope(ts[w5], cols["map"][w5]),
        "map_slope10": _slope(ts[w10], cols["map"][w10]),
        "map_baseline_ratio": map_now / base_map if base_map else math.nan,
        "sbp_now": sbp_now,
        "pp_now": sbp_now - _last(cols["dbp"][w5]),
        "hr_now": hr_now,
        "hr_mean5": _mean(cols["hr"][w5]),
        "hr_slope5": _slope(ts[w5], cols["hr"][w5]),
        "hr_std5": _std(cols["hr"][w5]),
        "shock_index": hr_now / sbp_now if sbp_now and not math.isnan(sbp_now) else math.nan,
        "spo2_now": _last(cols["spo2"][w5]),
        "spo2_min5": _min(cols["spo2"][w5]),
        "spo2_slope5": _slope(ts[w5], cols["spo2"][w5]),
        "etco2_now": _last(cols["etco2"][w5]),
        "etco2_slope10": _slope(ts[w10], cols["etco2"][w10]),
        "rr_now": _last(cols["rr"][w5]),
        "temp_now": _last(cols["temp"][w5]),
        "temp_slope30": _slope(ts[w30], cols["temp"][w30]),
        "bis_now": _last(cols["bis"][w5]),
        "ebl_rate15": ebl_rate,
        "age": float(profile["age"]),
        "asa": float(profile["asa"]),
        "bmi": float(profile["bmi"]),
        "sex_male": 1.0 if profile["sex"] == "M" else 0.0,
        "is_ga": 1.0 if profile["anes_class"] == "GA" else 0.0,
        "phase_code": _last(cols["phase"][w5]),
        "case_min": _last(cols["case_min"][w5]),
    }


def compute_sequence(ts: np.ndarray, cols: dict[str, np.ndarray], end: int) -> dict[str, float]:
    """近 15 分鐘、每分鐘一點的時間序列（給神經網路模型用）。"""
    t_now = ts[end]
    start = int(np.searchsorted(ts, t_now - SEQ_MINUTES * 60 - 30))
    grid = t_now - np.arange(SEQ_MINUTES - 1, -1, -1) * 60.0
    out = {}
    for f in SEQ_FIELDS:
        x = cols[f][start:end + 1]
        t = ts[start:end + 1]
        m = ~np.isnan(x)
        if m.sum() >= 2:
            vals = np.interp(grid, t[m], x[m])
        elif m.sum() == 1:
            vals = np.full(SEQ_MINUTES, x[m][0])
        else:
            vals = np.full(SEQ_MINUTES, SEQ_DEFAULTS[f])
        for i, v in enumerate(vals):
            out[f"seq_{f}_{i}"] = float(v)
    return out
