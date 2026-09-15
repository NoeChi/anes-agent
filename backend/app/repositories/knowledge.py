"""設定、工具設定、規則、技能、AI 模型的資料存取。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import AppSetting, MLModel, Rule, Skill, ToolConfig

SessionMaker = async_sessionmaker[AsyncSession]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else ""


# ---------------- 設定 ----------------
async def load_settings(sm: SessionMaker) -> tuple[dict[str, dict], dict[str, dict]]:
    async with sm() as s:
        sections = {r.section: dict(r.data) for r in (await s.scalars(select(AppSetting))).all()}
        tools = {r.tool_id: {"enabled": r.enabled, "params": dict(r.params)} for r in (await s.scalars(select(ToolConfig))).all()}
    return sections, tools


async def save_setting_section(sm: SessionMaker, section: str, data: dict) -> None:
    async with sm() as s, s.begin():
        await s.merge(AppSetting(section=section, data=data, updated_at=_now()))


async def save_tool_config(sm: SessionMaker, tool_id: str, enabled: bool, params: dict) -> None:
    async with sm() as s, s.begin():
        await s.merge(ToolConfig(tool_id=tool_id, enabled=enabled, params=params, updated_at=_now()))


async def delete_tool_config(sm: SessionMaker, tool_id: str) -> None:
    async with sm() as s, s.begin():
        await s.execute(delete(ToolConfig).where(ToolConfig.tool_id == tool_id))


# ---------------- 規則 ----------------
RULE_COLUMNS = ("name", "description", "severity", "logic", "conditions", "locations", "message", "suggestion", "author")


def rule_to_spec(row: Rule) -> dict:
    spec = {"id": row.id, **{c: getattr(row, c) for c in RULE_COLUMNS}}
    spec["updated_at"] = _fmt(row.updated_at)
    return spec


async def list_rules(sm: SessionMaker) -> list[dict]:
    async with sm() as s:
        rows = (await s.scalars(select(Rule).order_by(Rule.created_at, Rule.id))).all()
    return [rule_to_spec(r) for r in rows]


async def upsert_rule(sm: SessionMaker, spec: dict) -> dict:
    async with sm() as s, s.begin():
        row = await s.get(Rule, spec["id"])
        if row is None:
            row = Rule(id=spec["id"], created_at=_now())
            s.add(row)
        for c in RULE_COLUMNS:
            setattr(row, c, spec[c])
        row.updated_at = _now()
    return rule_to_spec(row)


async def delete_rule(sm: SessionMaker, rule_id: str) -> bool:
    async with sm() as s, s.begin():
        result = await s.execute(delete(Rule).where(Rule.id == rule_id))
    return result.rowcount > 0


# ---------------- 技能 ----------------
def skill_to_dict(row: Skill) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "enabled": row.enabled,
        "triggers": {"tools": list(row.trigger_tools), "keywords": list(row.keywords), "always": row.always},
        "use_in": list(row.use_in),
        "author": row.author,
        "updated_at": _fmt(row.updated_at),
        "body": row.body,
    }


async def list_skills(sm: SessionMaker) -> list[dict]:
    async with sm() as s:
        rows = (await s.scalars(select(Skill).order_by(Skill.created_at, Skill.id))).all()
    return [skill_to_dict(r) for r in rows]


async def upsert_skill(sm: SessionMaker, skill: dict) -> dict:
    async with sm() as s, s.begin():
        row = await s.get(Skill, skill["id"])
        if row is None:
            row = Skill(id=skill["id"], created_at=_now())
            s.add(row)
        row.name = skill["name"]
        row.description = skill["description"]
        row.enabled = skill["enabled"]
        row.trigger_tools = list(skill["triggers"]["tools"])
        row.keywords = list(skill["triggers"]["keywords"])
        row.always = skill["triggers"]["always"]
        row.use_in = list(skill["use_in"])
        row.body = skill["body"]
        row.author = skill["author"]
        row.updated_at = _now()
    return skill_to_dict(row)


async def delete_skill(sm: SessionMaker, skill_id: str) -> bool:
    async with sm() as s, s.begin():
        result = await s.execute(delete(Skill).where(Skill.id == skill_id))
    return result.rowcount > 0


# ---------------- AI 模型 ----------------
async def list_models(sm: SessionMaker) -> list[MLModel]:
    async with sm() as s:
        return list((await s.scalars(select(MLModel).order_by(MLModel.created_at, MLModel.id))).all())


async def get_model_meta(sm: SessionMaker, model_id: str) -> dict | None:
    async with sm() as s:
        meta = await s.scalar(select(MLModel.meta).where(MLModel.id == model_id))
    return None if meta is None else dict(meta)


async def upsert_model(sm: SessionMaker, meta: dict, artifact: bytes, source: str) -> None:
    async with sm() as s, s.begin():
        row = await s.get(MLModel, meta["id"])
        if row is None:
            row = MLModel(id=meta["id"], created_at=_now())
            s.add(row)
        row.name = meta["name"]
        row.source = source
        row.kind = meta["kind"]
        row.meta = meta
        row.artifact = artifact
        row.updated_at = _now()


async def delete_model(sm: SessionMaker, model_id: str) -> bool:
    async with sm() as s, s.begin():
        result = await s.execute(delete(MLModel).where(MLModel.id == model_id, MLModel.source != "builtin"))
    return result.rowcount > 0
