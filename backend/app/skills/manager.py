"""技能（Skill）管理。

技能就是「給 AI 看的標準作業流程（SOP）」：一份 Markdown 文件，加上何時使用的觸發條件。
- 查房時：當某病人的發現來自技能指定的工具（或文字含關鍵字），AI 會依照該技能的內容撰寫建議。
- 對話時：AI 會先看到所有技能的名稱與用途，需要時再讀取完整內容。
技能存在資料庫的 skills 資料表；記憶體保留一份快取，讓每次查房比對時不必查詢資料庫。
示範技能的原始檔在 backend/seeds/skills/*.md（開頭 YAML 設定＋ Markdown 內容），第一次啟動時匯入。
"""
from __future__ import annotations

import re
import time

import yaml

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,60}$")


class SkillError(ValueError):
    pass


def _normalize(meta: dict, body: str) -> dict:
    name = str(meta.get("name", "")).strip()
    if not name:
        raise SkillError("請輸入技能名稱")
    sid = str(meta.get("id", "")).strip()
    if not _ID.match(sid):
        raise SkillError("技能代碼格式錯誤")
    triggers = meta.get("triggers") or {}
    keywords = triggers.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k for k in re.split(r"[,，、\s]+", keywords) if k]
    use_in = [u for u in (meta.get("use_in") or ["rounds", "chat"]) if u in ("rounds", "chat")]
    body = str(body or "").strip()
    if not body:
        raise SkillError("技能內容不可空白")
    if len(body) > 20000:
        raise SkillError("技能內容太長（上限 20000 字）")
    return {
        "id": sid,
        "name": name[:40],
        "description": str(meta.get("description", "")).strip()[:300],
        "enabled": bool(meta.get("enabled", True)),
        "triggers": {
            "tools": [str(t) for t in (triggers.get("tools") or [])],
            "keywords": [str(k).strip() for k in keywords if str(k).strip()][:30],
            "always": bool(triggers.get("always", False)),
        },
        "use_in": use_in or ["rounds", "chat"],
        "author": str(meta.get("author", "使用者")).strip()[:40] or "使用者",
        "updated_at": str(meta.get("updated_at", "")),
        "body": body,
    }


def parse_skill_markdown(text: str, fallback_id: str) -> dict:
    """解析「--- YAML 設定 --- + Markdown 內容」格式的技能檔。"""
    m = _FRONT.match(text)
    if not m:
        raise SkillError("缺少 --- 開頭的設定區塊")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"設定區塊格式錯誤：{exc}") from None
    meta.setdefault("id", fallback_id)
    return _normalize(meta, m.group(2))


class SkillManager:
    def __init__(self, sessionmaker=None):
        self.sm = sessionmaker
        self.skills: dict[str, dict] = {}

    async def reload(self) -> None:
        if self.sm is None:
            return
        from ..repositories.knowledge import list_skills

        self.skills = {s["id"]: s for s in await list_skills(self.sm)}

    def list(self) -> list[dict]:
        return list(self.skills.values())

    def get(self, skill_id: str) -> dict | None:
        return self.skills.get(skill_id)

    async def save(self, data: dict) -> dict:
        data = dict(data)
        if not data.get("id"):
            data["id"] = f"skill-{int(time.time() * 1000):x}"
        skill = _normalize(data, data.get("body", ""))
        if self.sm is not None:
            from ..repositories.knowledge import upsert_skill

            skill = await upsert_skill(self.sm, skill)
        self.skills[skill["id"]] = skill
        return skill

    async def delete(self, skill_id: str) -> bool:
        if not _ID.match(skill_id):
            return False
        if self.sm is not None:
            from ..repositories.knowledge import delete_skill

            removed = await delete_skill(self.sm, skill_id)
        else:
            removed = skill_id in self.skills
        self.skills.pop(skill_id, None)
        return removed

    # ---- 觸發 ----
    def always_for_rounds(self) -> list[dict]:
        return [s for s in self.skills.values() if s["enabled"] and "rounds" in s["use_in"] and s["triggers"]["always"]]

    def match_findings(self, findings: list) -> list[dict]:
        """依查房發現（Finding 或 dict）找出適用的技能（不含 always 技能）。"""
        matched = []
        for s in self.skills.values():
            if not s["enabled"] or "rounds" not in s["use_in"] or s["triggers"]["always"]:
                continue
            tools = set(s["triggers"]["tools"])
            kws = s["triggers"]["keywords"]
            for f in findings:
                tool_id = f["tool_id"] if isinstance(f, dict) else f.tool_id
                text = (f["title"] + f["detail"]) if isinstance(f, dict) else (f.title + f.detail)
                if tool_id in tools or any(k in text for k in kws):
                    matched.append(s)
                    break
        return matched

    def match_text(self, text: str) -> list[dict]:
        return [s for s in self.skills.values()
                if s["enabled"] and "chat" in s["use_in"] and any(k in text for k in s["triggers"]["keywords"])]

    def catalog_text(self) -> str:
        lines = []
        for s in self.skills.values():
            if s["enabled"] and "chat" in s["use_in"]:
                lines.append(f"- {s['id']}：{s['name']} — {s['description']}")
        return "\n".join(lines) or "（目前沒有啟用的技能）"

    @staticmethod
    def checklist(skill: dict, max_items: int = 4, section_hint: str = "處置") -> list[str]:
        """離線模式使用：從技能內容擷取重點條列。優先取標題含「處置／建議」的段落。"""
        lines = skill["body"].splitlines()
        items, in_section = [], False
        for line in lines:
            if line.startswith("#"):
                in_section = section_hint in line or "建議" in line
                continue
            if in_section:
                m = re.match(r"^\s*(?:[-*]|\d+[.)、])\s+(.*)", line)
                if m:
                    items.append(m.group(1).strip())
            if len(items) >= max_items:
                break
        if not items:
            for line in lines:
                m = re.match(r"^\s*(?:[-*]|\d+[.)、])\s+(.*)", line)
                if m:
                    items.append(m.group(1).strip())
                if len(items) >= max_items:
                    break
        return items
