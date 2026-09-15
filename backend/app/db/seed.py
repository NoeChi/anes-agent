"""第一次啟動時，把示範的規則、技能與 AI 模型（backend/seeds/）寫入資料庫。

- 規則、技能、自訂模型：只有在資料表完全沒有資料時才匯入（使用者刪除的示範資料不會再出現）。
- 內建模型：資料庫沒有、或 seeds 內的模型比較新（trained_at 不同）時更新。
"""
from __future__ import annotations

import json

from sqlalchemy import func, select

from ..config import SEEDS_DIR
from ..repositories import knowledge
from ..skills.manager import SkillError, parse_skill_markdown
from ..tools.rule_engine import RuleError, validate_rule
from .models import MLModel, Rule, Skill
from .session import Database


async def seed_database(db: Database) -> dict:
    sm = db.sessionmaker
    summary = {"rules": 0, "skills": 0, "models": 0}
    async with sm() as s:
        n_rules = await s.scalar(select(func.count()).select_from(Rule))
        n_skills = await s.scalar(select(func.count()).select_from(Skill))
        n_custom = await s.scalar(select(func.count()).select_from(MLModel).where(MLModel.source != "builtin"))
        builtin_meta = {mid: meta for mid, meta in (await s.execute(
            select(MLModel.id, MLModel.meta).where(MLModel.source == "builtin"))).all()}

    if not n_rules:
        for path in sorted((SEEDS_DIR / "rules").glob("*.json")):
            try:
                await knowledge.upsert_rule(sm, validate_rule(json.loads(path.read_text(encoding="utf-8"))))
                summary["rules"] += 1
            except (RuleError, json.JSONDecodeError) as exc:
                print(f"[seed] 略過規則 {path.name}：{exc}")

    if not n_skills:
        for path in sorted((SEEDS_DIR / "skills").glob("*.md")):
            try:
                await knowledge.upsert_skill(sm, parse_skill_markdown(path.read_text(encoding="utf-8"), path.stem))
                summary["skills"] += 1
            except SkillError as exc:
                print(f"[seed] 略過技能 {path.name}：{exc}")

    for folder, source_default, only_if_empty in (("builtin", "builtin", False), ("custom", "no-code-trainer", True)):
        if only_if_empty and n_custom:
            continue
        for meta_path in sorted((SEEDS_DIR / "models" / folder).glob("*.json")):
            artifact = meta_path.with_suffix(".joblib")
            if not artifact.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            source = "builtin" if folder == "builtin" else meta.get("source", source_default)
            if folder == "builtin" and builtin_meta.get(meta["id"], {}).get("trained_at") == meta.get("trained_at"):
                continue
            await knowledge.upsert_model(sm, meta, artifact.read_bytes(), source)
            summary["models"] += 1
    return summary
