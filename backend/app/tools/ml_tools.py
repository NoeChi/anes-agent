"""機器學習／深度學習模型工具：把資料庫中的模型（說明 meta + joblib 模型檔）包成查房工具。"""
from __future__ import annotations

import bisect
import io
import math

import joblib
import numpy as np
import pandas as pd

from ..ml.features import FEATURE_LABELS
from ..ml.trainer import TARGETS, now_flags
from .base import BaseTool, Finding, ParamSpec


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.1f}" if isinstance(v, float) and not float(v).is_integer() else f"{v:.0f}"


class ModelTool(BaseTool):
    def __init__(self, meta: dict, artifact: bytes, builtin: bool):
        self.meta = meta
        self._artifact = artifact
        self.builtin = builtin
        self.id = meta["id"]
        self.name = meta["name"]
        if builtin:
            self.category = "dl" if meta.get("family") == "dl" else "ml"
        else:
            self.category = "custom_model"
        self.description = meta.get("description", "")
        self.locations = tuple(meta.get("locations", ["OR", "PACU"]))
        m = meta.get("metrics", {})
        parts = [f"演算法：{meta.get('algorithm_label', meta.get('algorithm'))}。"]
        if meta["kind"] == "anomaly":
            parts.append("以大量「正常狀態」資料學習，計算目前生命徵象組合比多少比例的正常狀態更異常，超過門檻即提醒。")
        else:
            parts.append(f"預測目標：{meta.get('target_label', '')}。輸出 0–100% 機率，超過警示門檻即提醒。")
        if meta.get("input_desc"):
            parts.append(f"輸入：{meta['input_desc']}。")
        else:
            labels = [FEATURE_LABELS.get(f, f) for f in meta["features"][:8]]
            more = f" 等 {len(meta['features'])} 項" if len(meta["features"]) > 8 else ""
            parts.append("輸入特徵：" + "、".join(labels) + more + "。")
        if m.get("auc") is not None:
            perf = f"模型表現（以訓練時未看過的病人測試）：AUC {m['auc']}"
            if m.get("sensitivity") is not None:
                perf += f"，敏感度 {m['sensitivity'] * 100:.0f}%，特異度 {m['specificity'] * 100:.0f}%"
            parts.append(perf + "。")
        if meta.get("source") == "upload":
            parts.append("此模型由使用者上傳。")
        self.how_it_works = "".join(parts)
        if meta["kind"] == "anomaly":
            self.params = [
                ParamSpec("threshold", "警示門檻（比多少比例正常狀態更異常）", meta["threshold"], min=0.8, max=0.999, step=0.001),
                ParamSpec("critical", "危急門檻", meta.get("critical_threshold", 0.999), min=0.9, max=0.9999, step=0.0005),
            ]
        else:
            self.params = [
                ParamSpec("threshold", "警示門檻（機率）", meta["threshold"], min=0.05, max=0.95, step=0.05),
                ParamSpec("critical", "危急門檻（機率）", meta.get("critical_threshold", 0.9), min=0.1, max=0.99, step=0.05),
            ]
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = joblib.load(io.BytesIO(self._artifact))
        return self._model

    def _inputs(self, ctx) -> tuple[pd.DataFrame | None, dict]:
        feats = dict(ctx.features)
        if not feats:
            return None, {}
        if any(f.startswith("seq_") for f in self.meta["features"]):
            feats.update(ctx.sequence)
        row = [[feats.get(f, np.nan) for f in self.meta["features"]]]
        return pd.DataFrame(row, columns=self.meta["features"]), feats

    def run(self, ctx, prm):
        X, feats = self._inputs(ctx)
        if X is None:
            return self.result(ctx, "資料累積中")
        if self.meta["kind"] == "anomaly":
            return self._run_anomaly(ctx, prm, X, feats)
        target = self.meta.get("target")
        spec = TARGETS.get(target)
        if spec and now_flags(feats)[spec["now"]]:
            return self.result(ctx, f"目前已出現{spec['short']}，改由即時規則工具處理", [], {"skipped": True})
        prob = float(self.model.predict_proba(X)[0, 1])
        values = {"probability": round(prob, 3)}
        pct = "＞99%" if prob >= 0.995 else "＜1%" if prob < 0.005 else f"{prob * 100:.0f}%"
        findings = []
        if prob >= prm["threshold"]:
            sev = "critical" if prob >= prm["critical"] else "warning"
            short = spec["short"] if spec else self.meta.get("target_label", "目標事件")
            basis = [f"{FEATURE_LABELS.get(f, f)} {_fmt(feats.get(f))}" for f in self._explain_features()]
            detail = f"{self.meta.get('algorithm_label', '模型')}預測{self.meta.get('target_label', '')}機率 {pct}（門檻 {prm['threshold'] * 100:.0f}%）"
            if basis:
                detail += "。參考數值：" + "、".join(basis)
            suggestion = self.meta.get("suggestion") or (spec["suggestion"] if spec else "請臨床人員評估。")
            findings.append(Finding(sev, f"AI 預測：{short}風險 {pct}", detail, suggestion, values))
        return self.result(ctx, f"預測機率 {pct}", findings, values)

    def _explain_features(self) -> list[str]:
        imp = self.meta.get("metrics", {}).get("importance") or []
        keys = [i["feature"] for i in imp][:4]
        if not keys:
            keys = [f for f in self.meta["features"] if not f.startswith("seq_")][:4]
        return keys

    def _run_anomaly(self, ctx, prm, X, feats):
        score = float(self.model.score_samples(X)[0])
        ref = self.meta["reference_scores"]
        # 分數越低越異常；percentile = 有多少比例的正常樣本分數比目前高
        rank = bisect.bisect_left(ref, score)
        pct = 1 - rank / len(ref)
        values = {"anomaly_percentile": round(pct, 4)}
        findings = []
        if pct >= prm["threshold"]:
            sev = "critical" if pct >= prm["critical"] else "warning"
            scaler = self.model.named_steps["scale"]
            imputed = self.model.named_steps["impute"].transform(X)
            z = (imputed[0] - scaler.mean_) / scaler.scale_
            top = np.argsort(-np.abs(z))[:3]
            parts = []
            for i in top:
                f = self.meta["features"][i]
                direction = "偏高" if z[i] > 0 else "偏低"
                parts.append(f"{FEATURE_LABELS.get(f, f)} {_fmt(feats.get(f))}（{direction}）")
            findings.append(Finding(
                sev, "AI 偵測：生命徵象組合異常",
                f"目前生命徵象組合比 {pct * 100:.1f}% 的正常麻醉狀態更不尋常。最偏離的項目：" + "、".join(parts),
                "請檢視病人整體狀況與監測波形，確認是否有尚未被單一規則偵測到的變化（或量測干擾）。",
                values,
            ))
        return self.result(ctx, f"異常程度：高於 {pct * 100:.1f}% 的正常狀態", findings, values)

    def describe(self):
        d = super().describe()
        d["model"] = {k: v for k, v in self.meta.items() if k not in ("reference_scores",)}
        return d


def model_tools_from_rows(rows) -> list[ModelTool]:
    """由資料庫 ml_models 資料列建立模型工具（模型檔在需要時才載入）。"""
    tools = []
    for row in rows:
        try:
            tools.append(ModelTool(dict(row.meta), bytes(row.artifact), row.source == "builtin"))
        except (KeyError, TypeError) as exc:
            print(f"[models] 略過格式錯誤的模型 {row.id}: {exc}")
    return tools
