"""待確認的處置建議（Human-in-the-loop）：AI 只能「建議」，必須由使用者按下確認才會執行。建議與結果都存入資料庫。"""
from __future__ import annotations

from ..repositories import agent_records as records
from ..simulator.engine import SimulationEngine
from ..simulator.events import INTERVENTIONS


class ActionStore:
    def __init__(self, engine: SimulationEngine, sessionmaker, recorder=None):
        self.engine = engine
        self.sm = sessionmaker
        self.recorder = recorder
        self.pending: set[int] = set()

    def pending_count(self) -> int:
        return len(self.pending)

    async def create(self, pid: str, intervention: str, reason: str, source: str, session_id: str | None = None) -> dict:
        p = self.engine.get(pid)
        if not p:
            raise ValueError(f"找不到病人 {pid}")
        if intervention not in INTERVENTIONS:
            raise ValueError(f"未知的處置：{intervention}")
        action = await records.insert_action(self.sm, {
            "pid": p.pid,
            "bed": p.bed,
            "intervention": intervention,
            "label": INTERVENTIONS[intervention]["label"],
            "reason": reason.strip()[:300],
            "source": source,
            "session_id": session_id,
        }, self.recorder.run_id if self.recorder else None)
        self.pending.add(action["db_id"])
        return action

    async def resolve(self, action_id: str, confirm: bool, by: str = "使用者") -> dict:
        db_id = records.parse_code("A", action_id)
        current = await records.get_action(self.sm, db_id) if db_id else None
        if current is None:
            raise KeyError(action_id)
        self.pending.discard(db_id)
        if current["status"] != "pending":
            return current
        if confirm:
            ok, msg, _ = self.engine.apply_intervention(current["pid"], current["intervention"], by=f"{by}（AI 建議）")
            status = "confirmed" if ok else "failed"
        else:
            status, msg = "rejected", "使用者未採納"
        return await records.resolve_action(self.sm, db_id, status, msg)

    async def list(self, status: str | None = None) -> list[dict]:
        return await records.list_actions(self.sm, status)
