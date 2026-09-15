"""AI Agent 紀錄的資料存取：查房報告、警示、處置建議、對話訊息。

API 對外使用可讀的編號（R00012、AL00034、A0005），資料庫主鍵為整數。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.base import to_dt, to_ts
from ..db.models import ActionProposal, Alert, ChatMessage, RoundReport

SessionMaker = async_sessionmaker[AsyncSession]

TRIGGER_LABEL = {"scheduled": "排程查房", "manual": "手動查房", "recheck": "危急病人複查", "agent": "AI 助理發起"}


def code(prefix: str, db_id: int, width: int) -> str:
    return f"{prefix}{db_id:0{width}d}"


def parse_code(prefix: str, value: str) -> int | None:
    m = re.fullmatch(rf"{prefix}0*(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(obj):
    """確保可存成 JSON（例如 numpy 數值轉成 Python 數值）。"""
    return json.loads(json.dumps(obj, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


# ---------------- 查房報告 ----------------
REPORT_FIELDS = ("trigger", "scope", "duration_ms", "patients_checked", "tools_run", "n_critical", "n_warning", "n_info",
                 "new_alerts", "resolved_alerts", "resolved", "patients", "summary_md", "summary_source",
                 "summary_status", "summary_error", "summary_model")


def report_to_dict(row: RoundReport) -> dict:
    d = {"id": code("R", row.id, 5), "db_id": row.id, **{f: getattr(row, f) for f in REPORT_FIELDS}}
    d["trigger_label"] = TRIGGER_LABEL.get(row.trigger, row.trigger)
    d["wall_time"] = to_ts(row.started_at)
    d["sim_time"] = to_ts(row.sim_time)
    return d


async def insert_report(sm: SessionMaker, report: dict, run_id: int | None) -> int:
    async with sm() as s, s.begin():
        values = {f: report.get(f) for f in REPORT_FIELDS}
        values["patients"] = _jsonable(values["patients"])
        values["resolved"] = _jsonable(values["resolved"])
        row = RoundReport(run_id=run_id, started_at=to_dt(report["wall_time"]), sim_time=to_dt(report["sim_time"]), **values)
        s.add(row)
        await s.flush()
        return row.id


async def update_report(sm: SessionMaker, db_id: int, **fields) -> None:
    async with sm() as s, s.begin():
        await s.execute(update(RoundReport).where(RoundReport.id == db_id).values(**fields))


async def list_reports(sm: SessionMaker, limit: int = 60) -> list[dict]:
    async with sm() as s:
        rows = (await s.scalars(select(RoundReport).order_by(RoundReport.id.desc()).limit(limit))).all()
    return [report_to_dict(r) for r in rows]


async def get_report(sm: SessionMaker, db_id: int) -> dict | None:
    async with sm() as s:
        row = await s.get(RoundReport, db_id)
    return report_to_dict(row) if row else None


# ---------------- 警示 ----------------
ALERT_FIELDS = ("key", "pid", "bed", "tool_id", "tool_name", "severity", "title", "detail", "suggestion", "status",
                "acknowledged", "rounds_seen", "missed")
ALERT_TIME_FIELDS = ("first_seen", "last_seen", "sim_first", "sim_last", "resolved_at")


async def save_alerts(sm: SessionMaker, alerts: list, run_id: int | None) -> None:
    """新增或更新警示（alerts 為 agent.rounds.AlertState）；新增的會回填 db_id。"""
    if not alerts:
        return
    async with sm() as s, s.begin():
        new_rows = []
        for a in alerts:
            values = {f: getattr(a, f) for f in ALERT_FIELDS}
            values.update({f: to_dt(getattr(a, f)) for f in ALERT_TIME_FIELDS})
            if a.db_id is None:
                row = Alert(run_id=run_id, **values)
                s.add(row)
                new_rows.append((a, row))
            else:
                await s.execute(update(Alert).where(Alert.id == a.db_id).values(**values))
        await s.flush()
        for a, row in new_rows:
            a.db_id = row.id


async def close_active_alerts(sm: SessionMaker) -> None:
    async with sm() as s, s.begin():
        await s.execute(update(Alert).where(Alert.status == "active").values(status="resolved", resolved_at=_now()))


async def acknowledge_alerts(sm: SessionMaker, db_ids: list[int]) -> None:
    if db_ids:
        async with sm() as s, s.begin():
            await s.execute(update(Alert).where(Alert.id.in_(db_ids)).values(acknowledged=True))


# ---------------- 處置建議 ----------------
def action_to_dict(row: ActionProposal) -> dict:
    return {
        "id": code("A", row.id, 4), "db_id": row.id, "pid": row.pid, "bed": row.bed, "intervention": row.intervention,
        "label": row.label, "reason": row.reason, "source": row.source, "session_id": row.session_id,
        "status": row.status, "created_at": to_ts(row.created_at), "resolved_at": to_ts(row.resolved_at),
        "result": row.result,
    }


async def insert_action(sm: SessionMaker, action: dict, run_id: int | None) -> dict:
    async with sm() as s, s.begin():
        row = ActionProposal(run_id=run_id, created_at=_now(), status="pending",
                             **{k: action[k] for k in ("pid", "bed", "intervention", "label", "reason", "source", "session_id")})
        s.add(row)
        await s.flush()
        return action_to_dict(row)


async def resolve_action(sm: SessionMaker, db_id: int, status: str, result: str) -> dict | None:
    async with sm() as s, s.begin():
        row = await s.get(ActionProposal, db_id)
        if row is None:
            return None
        if row.status == "pending":
            row.status, row.result, row.resolved_at = status, result, _now()
        return action_to_dict(row)


async def get_action(sm: SessionMaker, db_id: int) -> dict | None:
    async with sm() as s:
        row = await s.get(ActionProposal, db_id)
    return action_to_dict(row) if row else None


async def list_actions(sm: SessionMaker, status: str | None = None, limit: int = 50) -> list[dict]:
    stmt = select(ActionProposal).order_by(ActionProposal.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(ActionProposal.status == status)
    async with sm() as s:
        rows = (await s.scalars(stmt)).all()
    return [action_to_dict(r) for r in rows]


async def expire_pending_actions(sm: SessionMaker) -> None:
    async with sm() as s, s.begin():
        await s.execute(update(ActionProposal).where(ActionProposal.status == "pending")
                        .values(status="expired", result="系統重新啟動，建議已失效", resolved_at=_now()))


# ---------------- 對話 ----------------
async def add_chat_message(sm: SessionMaker, session_id: str, role: str, text: str, steps: list | None = None,
                           mode: str | None = None, error: str | None = None) -> None:
    async with sm() as s, s.begin():
        s.add(ChatMessage(session_id=session_id, role=role, text=text, steps=_jsonable(steps or []), mode=mode,
                          error=error, created_at=_now()))


async def list_chat_messages(sm: SessionMaker, session_id: str, limit: int = 200) -> list[dict]:
    async with sm() as s:
        rows = (await s.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
                                .order_by(ChatMessage.id.desc()).limit(limit))).all()
    return [{"role": r.role, "text": r.text, "steps": r.steps, "mode": r.mode, "error": r.error,
             "t": to_ts(r.created_at)} for r in reversed(rows)]


async def delete_chat_session(sm: SessionMaker, session_id: str) -> None:
    async with sm() as s, s.begin():
        await s.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
