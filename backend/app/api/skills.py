"""技能庫。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..skills.manager import SkillError
from ..state import AppState
from .deps import bad, get_state

router = APIRouter(tags=["技能"])


@router.get("/skills")
async def list_skills(S: AppState = Depends(get_state)):
    return S.skills.list()


@router.post("/skills")
async def save_skill(body: dict = Body(...), S: AppState = Depends(get_state)):
    try:
        skill = await S.skills.save(body)
    except SkillError as exc:
        bad(str(exc))
    await S.bus.publish("skills_changed", {"id": skill["id"]})
    return skill


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, S: AppState = Depends(get_state)):
    if not await S.skills.delete(skill_id):
        bad("找不到技能", 404)
    await S.bus.publish("skills_changed", {"id": skill_id})
    return {"ok": True}
