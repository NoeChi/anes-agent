"""工具庫、免寫程式規則、AI 模型訓練與上傳。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile

from ..ml import trainer
from ..ml.features import FEATURE_CATALOG
from ..state import AppState
from ..tools.context import PatientContext
from ..tools.rule_engine import RuleError, describe_condition, evaluate_condition, field_catalog, validate_rule
from .deps import bad, get_state

router = APIRouter(tags=["工具"])


@router.get("/tools")
async def list_tools(S: AppState = Depends(get_state)):
    return [S.registry.describe(t) for t in S.registry.list()]


@router.put("/tools/{tool_id}")
async def update_tool(tool_id: str, body: dict = Body(...), S: AppState = Depends(get_state)):
    try:
        d = await S.registry.update(tool_id, body.get("enabled"), body.get("params"))
    except KeyError:
        bad("找不到工具", 404)
    await S.bus.publish("tools_changed", {"id": tool_id})
    return d


@router.delete("/tools/{tool_id}")
async def delete_tool(tool_id: str, S: AppState = Depends(get_state)):
    if not await S.registry.delete_custom(tool_id):
        bad("只能刪除自訂規則或自訂模型")
    await S.bus.publish("tools_changed", {"id": tool_id})
    return {"ok": True}


@router.post("/tools/reload")
async def reload_tools(S: AppState = Depends(get_state)):
    await S.registry.reload()
    await S.bus.publish("tools_changed", {})
    return {"count": len(S.registry.list())}


# ---------------- 免寫程式規則 ----------------
@router.get("/rules/catalog")
async def rules_catalog():
    return field_catalog()


@router.post("/rules")
async def save_rule(body: dict = Body(...), S: AppState = Depends(get_state)):
    try:
        spec = await S.registry.add_rule(body)
    except RuleError as exc:
        bad(str(exc))
    await S.bus.publish("tools_changed", {"id": spec["id"]})
    return spec


@router.post("/rules/test")
async def test_rule(body: dict = Body(...), S: AppState = Depends(get_state)):
    try:
        spec = validate_rule({**body, "name": str(body.get("name") or "").strip() or "未命名規則"})
    except RuleError as exc:
        bad(str(exc))
    matches = []
    for p in S.engine.sorted_patients():
        if p.location not in spec["locations"]:
            continue
        ctx = PatientContext(p)
        results = [(c, *evaluate_condition(ctx, c)) for c in spec["conditions"]]
        hits = [ok for _, ok, _ in results]
        if all(hits) if spec["logic"] == "all" else any(hits):
            matches.append({"pid": p.pid, "bed": p.bed, "label": ctx.label(),
                            "values": [f"{describe_condition(c)}：目前 {actual}" for c, _, actual in results]})
    return {"matches": matches, "checked": len(S.engine.patients),
            "logic_text": ("，而且" if spec["logic"] == "all" else "，或").join(describe_condition(c) for c in spec["conditions"])}


# ---------------- AI 模型 ----------------
@router.get("/ml/catalog")
async def ml_catalog(S: AppState = Depends(get_state)):
    return {
        "targets": [{"id": k, "label": v["label"], "short": v["short"], "default_features": v["default_features"]}
                    for k, v in trainer.TARGETS.items()],
        "algorithms": [{"id": k, **v} for k, v in trainer.ALGORITHMS.items()],
        "features": [{"key": k, "label": label, "group": g} for k, label, g in FEATURE_CATALOG],
        "status": S.ml,
    }


@router.post("/ml/train")
async def train_model(body: dict = Body(...), S: AppState = Depends(get_state)):
    if S.ml["state"] == "training":
        bad("目前正在訓練其他模型，請稍候")
    async with S.ml_lock:
        S.ml.update(state="training", progress=0.0, message=f"訓練「{body.get('name', '')}」中")
        await S.bus.publish("ml_status", dict(S.ml))
        try:
            df = await S.dataset()
            S.ml.update(message="模型訓練中…", progress=0.95)
            await S.bus.publish("ml_status", dict(S.ml))
            threshold = body.get("threshold")
            meta, artifact = await asyncio.to_thread(
                trainer.train_custom_model, df, str(body.get("name", "")), body.get("target", ""),
                list(body.get("features") or []), body.get("algorithm", ""),
                None if threshold in (None, "") else float(threshold), str(body.get("description", "")))
            await S.registry.add_model(meta, artifact)
        except ValueError as exc:
            S.ml.update(state="ready", progress=1.0, message="")
            await S.bus.publish("ml_status", dict(S.ml))
            bad(str(exc))
        S.ml.update(state="ready", progress=1.0, message=f"「{meta['name']}」訓練完成")
    await S.bus.publish("ml_status", dict(S.ml))
    await S.bus.publish("tools_changed", {"id": meta["id"]})
    return meta


@router.post("/ml/upload")
async def upload_model(file: UploadFile = File(...), name: str = Form(...), features: str = Form(...),
                       threshold: float = Form(0.5), target_label: str = Form(""), description: str = Form(""),
                       suggestion: str = Form(""), S: AppState = Depends(get_state)):
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        bad("模型檔太大（上限 50MB）")
    try:
        meta = await S.registry.save_uploaded_model(content, name, json.loads(features), threshold, target_label,
                                                    description, suggestion)
    except (ValueError, json.JSONDecodeError) as exc:
        bad(str(exc))
    await S.bus.publish("tools_changed", {"id": meta["id"]})
    return meta
