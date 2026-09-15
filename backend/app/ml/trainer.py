"""模型訓練：用模擬器產生訓練資料，並提供「免寫程式」的模型訓練。

流程：
1. simulate_histories()：跑一個獨立的模擬器（較多病人、較高事件頻率），收集完整生命徵象時間序列。
2. build_dataset()：以每分鐘為一個樣本，計算特徵（features.py）與「未來是否發生某事件」的標籤。
3. train_model()：依使用者選擇的預測目標、特徵與演算法訓練，並以「不同病人」的測試集評估。
"""
from __future__ import annotations

import io
import json
import math
import re
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..config import CACHE_DIR, SEEDS_DIR
from ..simulator.engine import SimulationEngine
from .features import FEATURE_KEYS, FEATURE_LABELS, SEQ_KEYS, compute_features, compute_sequence

DATASET_FILE = CACHE_DIR / "training_windows.joblib"
BUILTIN_SEEDS_DIR = SEEDS_DIR / "models" / "builtin"

TARGETS: dict[str, dict] = {
    "y_ioh5": {
        "label": "5 分鐘內發生低血壓（MAP < 65 持續 1 分鐘）",
        "short": "低血壓",
        "now": "now_ioh",
        "suggestion": "提早評估麻醉深度與容積狀態，備妥升壓劑；確認動脈導管／血壓計量測正確。",
        "default_features": ["map_now", "map_mean5", "map_min5", "map_slope5", "map_slope10", "map_baseline_ratio",
                             "sbp_now", "pp_now", "hr_now", "hr_slope5", "shock_index", "bis_now", "ebl_rate15",
                             "age", "asa", "is_ga", "phase_code"],
    },
    "y_desat5": {
        "label": "5 分鐘內血氧下降（SpO₂ < 90）",
        "short": "低血氧",
        "now": "now_desat",
        "suggestion": "提高氧氣濃度，檢查氣道與呼吸狀態，準備呼吸道處置。",
        "default_features": ["spo2_now", "spo2_min5", "spo2_slope5", "etco2_now", "etco2_slope10", "rr_now",
                             "hr_now", "hr_slope5", "age", "bmi", "is_ga", "phase_code"],
    },
    "y_tachy5": {
        "label": "5 分鐘內心搏過速（HR > 120）",
        "short": "心搏過速",
        "now": "now_tachy",
        "suggestion": "評估疼痛、麻醉深度、出血與體溫；排除心律不整。",
        "default_features": ["hr_now", "hr_mean5", "hr_slope5", "hr_std5", "map_now", "map_slope5", "bis_now",
                             "temp_now", "etco2_now", "ebl_rate15", "age", "phase_code"],
    },
    "y_brady5": {
        "label": "5 分鐘內心搏過緩（HR < 45）",
        "short": "心搏過緩",
        "now": "now_brady",
        "suggestion": "注意手術刺激與藥物影響，備妥 Atropine。",
        "default_features": ["hr_now", "hr_mean5", "hr_slope5", "map_now", "map_slope5", "age", "asa", "phase_code"],
    },
    "y_deter10": {
        "label": "10 分鐘內病況惡化（MAP<60、SpO₂<90、HR>130 或 <45、EtCO₂>55 任一）",
        "short": "病況惡化",
        "now": "now_deter",
        "suggestion": "提高監測頻率並請麻醉醫師到床邊評估，預先準備可能需要的藥物與設備。",
        "default_features": ["map_now", "map_slope10", "hr_now", "hr_slope5", "spo2_now", "spo2_slope5",
                             "etco2_now", "etco2_slope10", "rr_now", "shock_index", "age", "asa", "phase_code"],
    },
}

ALGORITHMS: dict[str, dict] = {
    "logreg": {"label": "邏輯迴歸（Logistic Regression）", "family": "ml",
               "desc": "最容易解釋的統計模型：把每個特徵加權相加後換算成機率。訓練最快。"},
    "rf": {"label": "隨機森林（Random Forest）", "family": "ml",
           "desc": "由許多決策樹投票決定，穩定、不容易過度擬合。"},
    "gbt": {"label": "梯度提升樹（Gradient Boosting）", "family": "ml",
            "desc": "一棵接一棵修正前面錯誤的決策樹，通常準確度最好。"},
    "mlp": {"label": "神經網路（深度學習 MLP）", "family": "dl",
            "desc": "多層神經元組成的網路，能學習複雜的非線性關係；訓練較久。"},
}


def now_flags(f: dict) -> dict:
    def lt(key, v):
        x = f.get(key)
        return x is not None and not math.isnan(x) and x < v

    def gt(key, v):
        x = f.get(key)
        return x is not None and not math.isnan(x) and x > v

    return {
        "now_ioh": int(lt("map_now", 65)),
        "now_desat": int(lt("spo2_now", 90)),
        "now_tachy": int(gt("hr_now", 120)),
        "now_brady": int(lt("hr_now", 45)),
        "now_deter": int(lt("map_now", 60) or lt("spo2_now", 90) or gt("hr_now", 130) or lt("hr_now", 45) or gt("etco2_now", 55)),
    }


# ---------------- 資料產生 ----------------
def simulate_histories(n_patients: int = 200, hours: float = 8.0, seed: int = 7, dt: float = 10.0,
                       event_rate: float = 5.0, progress=None) -> list[tuple[dict, np.ndarray, dict]]:
    eng = SimulationEngine(n_patients=n_patients, seed=seed, history_cap=4000, hist_interval=dt,
                           warmup_minutes=0, seed_events=False, event_rate=event_rate)
    finished = []
    eng.on_discharge = finished.append
    steps = int(hours * 3600 / dt)
    for i in range(steps):
        eng.step(dt)
        if progress and i % 100 == 0:
            progress(0.6 * i / steps, "模擬病人資料中")
    patients = finished + list(eng.patients.values())
    return [(p.p, *p.history.arrays()) for p in patients]


def _longest_run_seconds(ts: np.ndarray, mask: np.ndarray) -> float:
    best, start = 0.0, None
    for k in range(len(mask)):
        if mask[k]:
            if start is None:
                start = k
            best = max(best, ts[k] - ts[start] + 10)
        else:
            start = None
    return best


def _future(ts, cols, i, horizon_s, cond, min_s) -> int:
    j = int(np.searchsorted(ts, ts[i] + horizon_s, side="right"))
    if j <= i + 1:
        return 0
    with np.errstate(invalid="ignore"):
        mask = cond({k: v[i + 1:j] for k, v in cols.items()})
    mask = np.nan_to_num(mask, nan=0).astype(bool)
    return int(_longest_run_seconds(ts[i + 1:j], mask) >= min_s)


def build_dataset(histories, stride: int = 6, progress=None) -> pd.DataFrame:
    rows = []
    n = len(histories)
    for pi, (profile, ts, cols) in enumerate(histories):
        if len(ts) < 130:
            continue
        group = f"{profile['pid']}"
        first = int(np.searchsorted(ts, ts[0] + 600))
        for i in range(first, len(ts), stride):
            if ts[-1] - ts[i] < 600:
                break
            f = compute_features(ts, cols, i, profile)
            f.update(compute_sequence(ts, cols, i))
            f.update(now_flags(f))
            f["y_ioh5"] = _future(ts, cols, i, 300, lambda c: c["map"] < 65, 60)
            f["y_desat5"] = _future(ts, cols, i, 300, lambda c: c["spo2"] < 90, 30)
            f["y_tachy5"] = _future(ts, cols, i, 300, lambda c: c["hr"] > 120, 60)
            f["y_brady5"] = _future(ts, cols, i, 300, lambda c: c["hr"] < 45, 60)
            f["y_deter10"] = _future(
                ts, cols, i, 600,
                lambda c: (c["map"] < 60) | (c["spo2"] < 90) | (c["hr"] > 130) | (c["hr"] < 45) | (c["etco2"] > 55), 60)
            f["evt_now"] = float(np.nan_to_num(cols["evt"][i]))
            f["group"] = group
            rows.append(f)
        if progress and pi % 20 == 0:
            progress(0.6 + 0.35 * pi / n, "計算特徵與標籤")
    return pd.DataFrame(rows)


def load_dataset(progress=None, rebuild: bool = False) -> pd.DataFrame:
    if DATASET_FILE.exists() and not rebuild:
        return joblib.load(DATASET_FILE)
    histories = simulate_histories(progress=progress)
    df = build_dataset(histories, progress=progress)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(df, DATASET_FILE, compress=3)
    if progress:
        progress(1.0, "資料集完成")
    return df


# ---------------- 訓練 ----------------
def make_estimator(algorithm: str, hidden=(64, 32, 16)):
    impute = ("impute", SimpleImputer(strategy="median", keep_empty_features=True))
    if algorithm == "logreg":
        return Pipeline([impute, ("scale", StandardScaler()),
                         ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))])
    if algorithm == "rf":
        return Pipeline([impute, ("clf", RandomForestClassifier(
            n_estimators=150, max_depth=12, min_samples_leaf=20, class_weight="balanced_subsample",
            n_jobs=-1, random_state=0))])
    if algorithm == "gbt":
        return Pipeline([("clf", HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.08, max_leaf_nodes=31, class_weight="balanced", random_state=0))])
    if algorithm == "mlp":
        return Pipeline([impute, ("scale", StandardScaler()), ("clf", MLPClassifier(
            hidden_layer_sizes=hidden, alpha=1e-3, early_stopping=True, max_iter=300, random_state=0))])
    raise ValueError(f"未知的演算法：{algorithm}")


def _threshold_metrics(y, p, th) -> dict:
    pred = p >= th
    tp = int(((pred == 1) & (y == 1)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    return {
        "sensitivity": round(tp / (tp + fn), 3) if tp + fn else None,
        "specificity": round(tn / (tn + fp), 3) if tn + fp else None,
        "ppv": round(tp / (tp + fp), 3) if tp + fp else None,
    }


def _importance(est, features) -> list[dict]:
    clf = est.named_steps["clf"]
    if hasattr(clf, "coef_"):
        vals = np.abs(clf.coef_[0])
    elif hasattr(clf, "feature_importances_"):
        vals = clf.feature_importances_
    else:
        return []
    if len(vals) != len(features):
        return []
    order = np.argsort(vals)[::-1][:6]
    total = float(vals.sum()) or 1.0
    return [{"feature": features[i], "label": FEATURE_LABELS.get(features[i], features[i]),
             "weight": round(float(vals[i]) / total, 3)} for i in order]


def train_model(df: pd.DataFrame, target: str, features: list[str], algorithm: str,
                threshold: float | None = None, hidden=(64, 32, 16), max_rows: int = 150000):
    if target not in TARGETS:
        raise ValueError("未知的預測目標")
    unknown = [f for f in features if f not in FEATURE_KEYS and f not in SEQ_KEYS]
    if unknown or not features:
        raise ValueError("請至少選擇一個有效的特徵")
    data = df[df[TARGETS[target]["now"]] == 0]
    if len(data) > max_rows:
        data = data.sample(max_rows, random_state=0)
    X, y, groups = data[features], data[target].to_numpy(), data["group"].to_numpy()
    if y.sum() < 20:
        raise ValueError("訓練資料中陽性樣本太少，無法訓練")
    split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=0)
    tr, te = next(split.split(X, y, groups))
    est = make_estimator(algorithm, hidden)
    started = time.time()
    est.fit(X.iloc[tr], y[tr])
    p = est.predict_proba(X.iloc[te])[:, 1]
    yt = y[te]
    auc = float(roc_auc_score(yt, p)) if 0 < yt.sum() < len(yt) else None
    # 建議門檻：特異度至少 95%（避免警示疲勞）的前提下，讓 Youden J 最大
    candidates = np.linspace(0.05, 0.95, 19)
    best_th, best_j = 0.5, -1.0
    for min_spec in (0.95, 0.0):
        for th in candidates:
            m = _threshold_metrics(yt, p, th)
            if m["sensitivity"] is None or m["specificity"] is None or m["specificity"] < min_spec:
                continue
            j = m["sensitivity"] + m["specificity"] - 1
            if j > best_j:
                best_th, best_j = float(th), j
        if best_j >= 0:
            break
    th = float(threshold) if threshold is not None else best_th
    metrics = {
        "auc": None if auc is None else round(auc, 3),
        "threshold": round(th, 2),
        "suggested_threshold": round(best_th, 2),
        **_threshold_metrics(yt, p, th),
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "patients_train": int(len(set(groups[tr]))),
        "patients_test": int(len(set(groups[te]))),
        "prevalence": round(float(y.mean()), 3),
        "train_seconds": round(time.time() - started, 1),
        "importance": _importance(est, features),
    }
    return est, metrics


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


def serialize_model(est) -> bytes:
    buf = io.BytesIO()
    joblib.dump(est, buf, compress=3)
    return buf.getvalue()


def write_seed_model(est, meta: dict, directory: Path) -> tuple[dict, bytes]:
    """內建模型：寫入 seeds（隨程式發佈），同時回傳給呼叫端存入資料庫。"""
    data = serialize_model(est)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{meta['id']}.joblib").write_bytes(data)
    (directory / f"{meta['id']}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta, data


def train_custom_model(df, name: str, target: str, features: list[str], algorithm: str,
                       threshold: float | None = None, description: str = "") -> tuple[dict, bytes]:
    if algorithm not in ALGORITHMS:
        raise ValueError("未知的演算法")
    name = name.strip()
    if not name:
        raise ValueError("請輸入模型名稱")
    est, metrics = train_model(df, target, features, algorithm, threshold)
    meta = {
        "id": f"model_{int(time.time() * 1000):x}",
        "name": name[:40],
        "kind": "classifier",
        "family": ALGORITHMS[algorithm]["family"],
        "algorithm": algorithm,
        "algorithm_label": ALGORITHMS[algorithm]["label"],
        "target": target,
        "target_label": TARGETS[target]["label"],
        "features": features,
        "threshold": metrics["threshold"],
        "critical_threshold": round(min(0.95, max(0.85, metrics["threshold"] + 0.3)), 2),
        "metrics": metrics,
        "description": description.strip()[:300] or f"預測「{TARGETS[target]['label']}」",
        "trained_at": time.strftime("%Y-%m-%d %H:%M"),
        "source": "no-code-trainer",
    }
    return meta, serialize_model(est)


# ---------------- 內建模型 ----------------
ANOMALY_FEATURES = ["map_baseline_ratio", "hr_now", "spo2_now", "etco2_now", "rr_now", "temp_now",
                    "shock_index", "hr_std5", "map_slope5", "spo2_slope5"]


def train_builtin_models(df: pd.DataFrame, progress=None) -> list[tuple[dict, bytes]]:
    metas = []

    def step(frac, msg):
        if progress:
            progress(frac, msg)

    step(0.05, "訓練低血壓預測模型（梯度提升樹）")
    target = "y_ioh5"
    feats = TARGETS[target]["default_features"]
    est, metrics = train_model(df, target, feats, "gbt")
    metas.append(write_seed_model(est, {
        "id": "ioh_predictor", "name": "低血壓預測 AI", "kind": "classifier", "family": "ml",
        "algorithm": "gbt", "algorithm_label": ALGORITHMS["gbt"]["label"], "target": target,
        "target_label": TARGETS[target]["label"], "features": feats, "threshold": metrics["threshold"],
        "critical_threshold": round(min(0.95, max(0.85, metrics["threshold"] + 0.25)), 2),
        "metrics": metrics, "locations": ["OR"],
        "description": "在血壓真正掉下來之前，預測未來 5 分鐘內發生術中低血壓的機率。",
        "trained_at": time.strftime("%Y-%m-%d %H:%M"), "source": "builtin",
    }, BUILTIN_SEEDS_DIR))

    step(0.4, "訓練病況惡化預測神經網路（深度學習）")
    target = "y_deter10"
    feats = SEQ_KEYS + ["map_baseline_ratio", "shock_index", "hr_slope5", "map_slope10", "spo2_slope5",
                        "etco2_slope10", "age", "asa", "is_ga", "phase_code"]
    est, metrics = train_model(df, target, feats, "mlp", hidden=(128, 64, 32))
    metas.append(write_seed_model(est, {
        "id": "deterioration_nn", "name": "病況惡化預測神經網路", "kind": "classifier", "family": "dl",
        "algorithm": "mlp", "algorithm_label": "多層神經網路（3 層隱藏層 128-64-32）", "target": target,
        "target_label": TARGETS[target]["label"], "features": feats, "threshold": metrics["threshold"],
        "critical_threshold": round(min(0.95, max(0.85, metrics["threshold"] + 0.25)), 2),
        "metrics": metrics, "input_desc": "近 15 分鐘每分鐘的心跳、MAP、SpO₂、EtCO₂、呼吸速率（共 75 個時間點）＋趨勢指標、年齡、ASA、麻醉方式、階段",
        "description": "讀取近 15 分鐘的生命徵象波形，預測未來 10 分鐘內病況惡化的機率。",
        "trained_at": time.strftime("%Y-%m-%d %H:%M"), "source": "builtin",
    }, BUILTIN_SEEDS_DIR))

    step(0.8, "訓練多參數異常偵測（Isolation Forest）")
    normal = df[df["evt_now"] < 0.05]
    if len(normal) > 40000:
        normal = normal.sample(40000, random_state=0)
    iso = Pipeline([
        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scale", StandardScaler()),
        ("clf", IsolationForest(n_estimators=200, contamination=0.02, random_state=0)),
    ])
    iso.fit(normal[ANOMALY_FEATURES])
    ref = np.sort(iso.score_samples(normal[ANOMALY_FEATURES].sample(min(3000, len(normal)), random_state=1)))
    eval_df = df.sample(min(20000, len(df)), random_state=2)
    s = -iso.score_samples(eval_df[ANOMALY_FEATURES])
    yt = (eval_df["evt_now"] > 0.3).astype(int).to_numpy()
    auc = float(roc_auc_score(yt, s)) if 0 < yt.sum() < len(yt) else None
    metas.append(write_seed_model(iso, {
        "id": "anomaly_detector", "name": "多參數異常偵測 AI", "kind": "anomaly", "family": "ml",
        "algorithm": "isolation_forest", "algorithm_label": "孤立森林（Isolation Forest，非監督式學習）",
        "target": "anomaly", "target_label": "生命徵象組合偏離「正常麻醉狀態」的程度",
        "features": ANOMALY_FEATURES, "threshold": 0.98, "critical_threshold": 0.999,
        "reference_scores": [round(float(x), 5) for x in ref[:: max(1, len(ref) // 500)]],
        "metrics": {"auc": None if auc is None else round(auc, 3), "n_train": int(len(normal)),
                    "note": "AUC 以『是否正在發生臨床事件』評估"},
        "description": "只學習「正常」的麻醉生命徵象組合；當多個數值同時出現不尋常的組合時提醒，即使單一數值尚未超過門檻。",
        "trained_at": time.strftime("%Y-%m-%d %H:%M"), "source": "builtin",
    }, BUILTIN_SEEDS_DIR))
    step(1.0, "內建模型訓練完成")
    return metas


def builtin_models_ready() -> bool:
    return all((BUILTIN_SEEDS_DIR / f"{mid}.joblib").exists()
               for mid in ("ioh_predictor", "deterioration_nn", "anomaly_detector"))


if __name__ == "__main__":
    def show(frac, msg):
        print(f"[{frac * 100:5.1f}%] {msg}", flush=True)

    t0 = time.time()
    data = load_dataset(progress=show, rebuild=True)
    print("dataset rows", len(data), "patients", data["group"].nunique(), f"{time.time() - t0:.0f}s")
    for key in TARGETS:
        print(key, "prevalence", round(float(data[data[TARGETS[key]['now']] == 0][key].mean()), 3))
    for m, _ in train_builtin_models(data, progress=show):
        print(m["id"], m["metrics"])
    print("已寫入 seeds/models/builtin；重新啟動系統時會自動更新資料庫中的內建模型。")
