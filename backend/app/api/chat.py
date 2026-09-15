"""AI 助理對話與處置建議確認。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..state import AppState
from .deps import bad, get_state

router = APIRouter(tags=["AI 助理"])


@router.post("/chat")
async def chat(body: dict = Body(...), S: AppState = Depends(get_state)):
    text = str(body.get("message", "")).strip()
    if not text:
        bad("請輸入訊息")
    return await S.chat.handle(body.get("session_id"), text)


@router.get("/chat/{sid}")
async def chat_history(sid: str, S: AppState = Depends(get_state)):
    return {"session_id": sid, "messages": await S.chat.history(sid)}


@router.delete("/chat/{sid}")
async def chat_reset(sid: str, S: AppState = Depends(get_state)):
    await S.chat.reset(sid)
    return {"ok": True}


@router.get("/actions")
async def list_actions(status: str | None = None, S: AppState = Depends(get_state)):
    return await S.actions.list(status)


@router.post("/actions/{action_id}")
async def resolve_action(action_id: str, body: dict = Body(...), S: AppState = Depends(get_state)):
    try:
        action = await S.actions.resolve(action_id, bool(body.get("confirm")))
    except KeyError:
        bad("找不到此建議", 404)
    await S.bus.publish("action_resolved", action)
    return action
