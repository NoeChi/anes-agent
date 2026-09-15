"""工具庫：集中管理所有工具（內建、自訂規則、AI 模型、Python 外掛），以及啟用狀態與參數。

自訂規則與 AI 模型存在資料庫；每次變更後重新載入，記憶體中的工具清單供查房每位病人快速執行。
"""
from __future__ import annotations

import importlib.util
import io
import time
import traceback

import joblib
import numpy as np
import pandas as pd

from ..config import PLUGINS_DIR, Settings
from ..ml.features import FEATURE_KEYS, FEATURE_LABELS
from ..repositories import knowledge
from .base import BaseTool, ToolResult
from .builtin_rules import builtin_rule_tools
from .context import PatientContext
from .ml_tools import model_tools_from_rows
from .rule_engine import CustomRuleTool, RuleError, validate_rule
from .scores import builtin_score_tools

CATEGORY_ORDER = ["rule", "score", "ml", "dl", "custom_rule", "custom_model", "plugin"]


def load_plugins() -> list[BaseTool]:
    tools: list[BaseTool] = []
    if not PLUGINS_DIR.exists():
        return tools
    for path in sorted(PLUGINS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"anes_plugins.{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            print(f"[plugins] 載入 {path.name} 失敗：\n{traceback.format_exc()}")
            continue
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, BaseTool) and obj.__module__ == module.__name__ and obj.id:
                tool = obj()
                tool.category = "plugin"
                tool.builtin = False
                tools.append(tool)
    return tools


class ToolRegistry:
    def __init__(self, settings: Settings, sessionmaker=None):
        self.settings = settings
        self.sm = sessionmaker
        self.tools: dict[str, BaseTool] = {}
        self._build([], [])

    def _build(self, rule_specs: list[dict], model_rows: list) -> None:
        rule_tools = []
        for spec in rule_specs:
            try:
                rule_tools.append(CustomRuleTool(spec))
            except (KeyError, RuleError) as exc:
                print(f"[rules] 略過格式錯誤的規則 {spec.get('id')}: {exc}")
        tools = (builtin_rule_tools() + builtin_score_tools() + model_tools_from_rows(model_rows)
                 + rule_tools + load_plugins())
        ordered = sorted(enumerate(tools), key=lambda it: (CATEGORY_ORDER.index(it[1].category), it[0]))
        self.tools = {t.id: t for _, t in ordered}

    async def reload(self) -> None:
        if self.sm is None:
            self._build([], [])
            return
        self._build(await knowledge.list_rules(self.sm), await knowledge.list_models(self.sm))

    def list(self) -> list[BaseTool]:
        return list(self.tools.values())

    def get(self, tool_id: str) -> BaseTool | None:
        return self.tools.get(tool_id)

    def enabled(self, tool_id: str) -> bool:
        return self.settings.tool_enabled(tool_id)

    def params_for(self, tool: BaseTool) -> dict:
        stored = self.settings.tool_params(tool.id)
        out = {}
        for spec in tool.params:
            val = stored.get(spec.key, spec.default)
            try:
                if spec.type == "number":
                    val = float(val)
                    if spec.min is not None:
                        val = max(spec.min, val)
                    if spec.max is not None:
                        val = min(spec.max, val)
                elif spec.type == "bool":
                    val = bool(val)
            except (TypeError, ValueError):
                val = spec.default
            out[spec.key] = val
        return out

    def describe(self, tool: BaseTool) -> dict:
        d = tool.describe()
        d["enabled"] = self.enabled(tool.id)
        d["param_values"] = self.params_for(tool)
        return d

    async def update(self, tool_id: str, enabled: bool | None = None, params: dict | None = None) -> dict:
        tool = self.get(tool_id)
        if not tool:
            raise KeyError(tool_id)
        new_params = None
        if params is not None:
            known = {p.key for p in tool.params}
            new_params = {**self.settings.tool_params(tool_id), **{k: v for k, v in params.items() if k in known}}
        await self.settings.set_tool(tool_id, enabled=enabled, params=new_params)
        return self.describe(tool)

    def run(self, tool: BaseTool, ctx: PatientContext) -> ToolResult:
        ok, why = tool.applicable(ctx)
        if not ok:
            return ToolResult(tool.id, tool.name, ctx.pid, applicable=False, summary=why)
        try:
            return tool.run(ctx, self.params_for(tool))
        except Exception as exc:  # 工具錯誤不能讓整個查房中斷
            return ToolResult(tool.id, tool.name, ctx.pid, ok=False, summary="工具執行錯誤", error=f"{type(exc).__name__}: {exc}")

    def run_all(self, ctx: PatientContext, only_enabled: bool = True) -> list[ToolResult]:
        return [self.run(t, ctx) for t in self.list() if not only_enabled or self.enabled(t.id)]

    # ---- 自訂工具管理 ----
    async def add_rule(self, spec: dict) -> dict:
        saved = await knowledge.upsert_rule(self.sm, validate_rule(spec))
        await self.reload()
        return saved

    async def add_model(self, meta: dict, artifact: bytes) -> None:
        await knowledge.upsert_model(self.sm, meta, artifact, meta.get("source", "no-code-trainer"))
        await self.reload()

    async def delete_custom(self, tool_id: str) -> bool:
        tool = self.get(tool_id)
        if not tool or tool.builtin or tool.category == "plugin":
            return False
        if tool.category == "custom_rule":
            removed = await knowledge.delete_rule(self.sm, tool_id)
        elif tool.category == "custom_model":
            removed = await knowledge.delete_model(self.sm, tool_id)
        else:
            removed = False
        if removed:
            await self.settings.forget_tool(tool_id)
            await self.reload()
        return removed

    async def save_uploaded_model(self, content: bytes, name: str, features: list[str], threshold: float,
                                  target_label: str, description: str, suggestion: str) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("請輸入模型名稱")
        features = [f for f in features if f in FEATURE_KEYS]
        if not features:
            raise ValueError("請選擇模型使用的輸入特徵（順序需與訓練時一致）")
        try:
            model = joblib.load(io.BytesIO(content))
        except Exception as exc:
            raise ValueError(f"無法讀取模型檔（需為 scikit-learn 以 joblib 存檔的 .joblib）：{exc}") from None
        if not hasattr(model, "predict_proba"):
            raise ValueError("模型需要支援 predict_proba（輸出機率）")
        try:
            probe = pd.DataFrame([[np.float64(0.0)] * len(features)], columns=features)
            p = model.predict_proba(probe)
            assert p.shape[1] >= 2
        except Exception as exc:
            raise ValueError(f"模型與所選特徵不相符：{exc}") from None
        meta = {
            "id": f"model_{int(time.time() * 1000):x}",
            "name": name[:40],
            "kind": "classifier",
            "family": "ml",
            "algorithm": type(model).__name__,
            "algorithm_label": f"上傳模型（{type(model).__name__}）",
            "target": "custom",
            "target_label": target_label.strip()[:60] or "自訂預測目標",
            "features": features,
            "feature_labels": [FEATURE_LABELS[f] for f in features],
            "threshold": max(0.05, min(0.95, float(threshold))),
            "critical_threshold": 0.9,
            "metrics": {},
            "description": description.strip()[:300] or "使用者上傳的模型",
            "suggestion": suggestion.strip()[:300],
            "trained_at": time.strftime("%Y-%m-%d %H:%M"),
            "source": "upload",
        }
        await self.add_model(meta, content)
        return meta
