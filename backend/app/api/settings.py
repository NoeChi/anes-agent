"""系統狀態、設定與 AI 連線測試。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..agent.llm import friendly_error
from ..config import PROVIDERS, SettingsError
from ..state import AppState
from .deps import bad, get_state

router = APIRouter(tags=["設定"])


@router.get("/state")
async def state(S: AppState = Depends(get_state)):
    return {
        "settings": S.settings.public(),
        "llm": S.llm.status(),
        "ml": S.ml,
        "schedule": S.rounds.schedule_info(),
        "sim": {"time": S.engine.t, **S.settings.section("simulation"), "or": S.engine.count("OR"),
                "pacu": S.engine.count("PACU")},
        "counts": {"patients": len(S.engine.patients), "tools": len(S.registry.list()), "skills": len(S.skills.list())},
        "db": await S.db_status(),
    }


@router.get("/settings")
async def get_settings(S: AppState = Depends(get_state)):
    return S.settings.public()


@router.put("/settings/{section}")
async def update_settings(section: str, body: dict = Body(...), S: AppState = Depends(get_state)):
    if section not in ("rounds", "llm", "simulation"):
        bad("無法修改此設定")
    try:
        await S.settings.update(section, body)
    except SettingsError as exc:
        bad(str(exc))
    public = S.settings.public()
    await S.bus.publish("settings_changed", public)
    return public


@router.post("/llm/test")
async def test_llm(S: AppState = Depends(get_state)):
    if not S.llm.available:
        bad("尚未設定 API 金鑰")
    try:
        return await S.llm.test()
    except Exception as exc:
        bad(friendly_error(exc))


@router.get("/llm/models")
async def llm_models(provider: str | None = None, S: AppState = Depends(get_state)):
    """向供應商查詢這把金鑰實際可用的模型（OpenAI 的模型清單會因帳號而異）。"""
    if provider is not None and provider not in PROVIDERS:
        bad("未知的供應商")
    try:
        return await S.llm.list_models(provider)
    except Exception as exc:
        bad(friendly_error(exc))
