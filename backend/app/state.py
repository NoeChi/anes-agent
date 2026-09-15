"""應用程式狀態：組裝資料庫、模擬器、工具庫、技能、查房與 AI 助理，並管理背景工作。"""
from __future__ import annotations

import asyncio
import math
import time

from .agent.actions import ActionStore
from .agent.chat import ChatAgent
from .agent.llm import LLMClient
from .agent.offline import OfflineResponder
from .agent.rounds import RoundManager
from .agent.toolbox import AgentToolbox
from .bus import EventBus
from .config import DATABASE_URL, Settings
from .db.migrate import migrate, wait_for_database
from .db.seed import seed_database
from .db.session import Database
from .ml import trainer
from .repositories import agent_records as records
from .repositories import knowledge
from .services.recorder import Recorder
from .simulator.engine import SimulationEngine
from .skills.manager import SkillManager
from .tools.registry import ToolRegistry

BUILTIN_MODEL_IDS = {"ioh_predictor", "deterioration_nn", "anomaly_detector"}


class AppState:
    def __init__(self, database_url: str | None = None):
        self.db = Database(database_url or DATABASE_URL)
        sm = self.db.sessionmaker
        self.settings = Settings(sm)
        self.engine = SimulationEngine(n_patients=50, record=True)
        self.bus = EventBus()
        self.recorder = Recorder(self.engine, self.db)
        self.registry = ToolRegistry(self.settings, sm)
        self.skills = SkillManager(sm)
        self.llm = LLMClient(self.settings)
        self.rounds = RoundManager(self.engine, self.registry, self.skills, self.llm, self.settings, self.bus, sm,
                                   self.recorder)
        self.actions = ActionStore(self.engine, sm, self.recorder)
        self.toolbox = AgentToolbox(self.engine, self.registry, self.skills, self.rounds, self.actions, self.settings,
                                    self.bus)
        self.chat = ChatAgent(self.llm, self.toolbox, self.skills, OfflineResponder(self.toolbox), self.bus,
                              self.engine, sm)
        self.ml = {"state": "ready", "progress": 1.0, "message": "", "dataset_ready": trainer.DATASET_FILE.exists()}
        self._dataset = None
        self.ml_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._db_label: str | None = None

    # ---------- 生命週期 ----------
    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def startup(self) -> None:
        await wait_for_database(self.db)
        await migrate(self.db)
        seeded = await seed_database(self.db)
        if any(seeded.values()):
            print(f"[startup] 已匯入示範資料：{seeded}")
        await self.settings.load()
        sim = self.settings.section("simulation")
        self.engine.speed, self.engine.event_rate = sim["speed"], sim["event_rate"]
        await self.skills.reload()
        await self.registry.reload()
        await records.expire_pending_actions(self.db.sessionmaker)
        await self.rounds.startup()
        await self.recorder.flush()
        for coro in (self.sim_loop(), self.rounds.loop(), self.recorder.loop(), self.prepare_models()):
            self.spawn(coro)
        # 開機後先做一次查房，讓畫面一開始就有結果
        self.spawn(self.rounds.run_round("manual", ai_summary="off"))

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self.recorder.flush()
        except Exception as exc:
            print(f"[shutdown] 最後一次寫入資料庫失敗：{exc}")
        await self.db.dispose()

    # ---------- 狀態 ----------
    def patients_payload(self) -> list[dict]:
        out = []
        for p in self.engine.sorted_patients():
            b = p.brief()
            st = self.rounds.patient_status.get(p.pid)
            b["status"] = st["severity"] if st else "unchecked"
            b["alert_titles"] = st["titles"] if st else []
            b["acknowledged"] = bool(st) and all(
                a.acknowledged for a in self.rounds.alerts.values() if a.pid == p.pid and a.status == "active")
            out.append(b)
        return out

    async def db_status(self) -> dict:
        if not await self.db.ping():
            return {"ok": False, "backend": self.db.safe_url, "tables": {}}
        if self._db_label is None:
            self._db_label = f"{await self.db.server_version()}・{self.db.safe_url}"
        return {"ok": True, "backend": self._db_label, "tables": await self.db.table_counts(),
                "recorder": self.recorder.status()}

    async def dataset(self):
        if self._dataset is None:
            loop = asyncio.get_running_loop()

            def progress(frac, msg):
                self.ml.update(progress=round(frac, 2), message=msg)
                loop.call_soon_threadsafe(lambda: self.spawn(self.bus.publish("ml_status", dict(self.ml))))

            self._dataset = await asyncio.to_thread(trainer.load_dataset, progress)
            self.ml["dataset_ready"] = True
        return self._dataset

    # ---------- 背景工作 ----------
    async def sim_loop(self) -> None:
        last = time.monotonic()
        log_seen = 0.0
        while True:
            await asyncio.sleep(1.0)
            try:
                cfg = self.settings.section("simulation")
                self.engine.speed = cfg["speed"]
                self.engine.event_rate = cfg["event_rate"]
                now = time.monotonic()
                real_dt = min(5.0, now - last)
                last = now
                if cfg["running"]:
                    dt = real_dt * self.engine.speed
                    n = max(1, math.ceil(dt / 10))
                    for _ in range(n):
                        self.engine.step(dt / n)
                new_logs = [e for e in self.engine.log if e["t"] > log_seen]
                if new_logs:
                    log_seen = new_logs[-1]["t"]
                await self.bus.publish("tick", {
                    "sim_time": self.engine.t,
                    "running": cfg["running"],
                    "speed": cfg["speed"],
                    "patients": self.patients_payload(),
                    "schedule": self.rounds.schedule_info(),
                    "log": new_logs[-20:],
                    "pending_actions": self.actions.pending_count(),
                    "active_alerts": self.rounds.active_alert_count(),
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[sim] 錯誤：{type(exc).__name__}: {exc}")

    async def prepare_models(self) -> None:
        """資料庫缺少內建 AI 模型（例如 seeds 被刪除）時，自動重新訓練並存入資料庫。"""
        if BUILTIN_MODEL_IDS <= set(self.registry.tools):
            return
        async with self.ml_lock:
            self.ml.update(state="training", progress=0.0, message="第一次啟動：準備 AI 模型")
            await self.bus.publish("ml_status", dict(self.ml))
            try:
                df = await self.dataset()
                results = await asyncio.to_thread(trainer.train_builtin_models, df)
                for meta, artifact in results:
                    await knowledge.upsert_model(self.db.sessionmaker, meta, artifact, "builtin")
                await self.registry.reload()
                self.ml.update(state="ready", progress=1.0, message="AI 模型已就緒")
                await self.bus.publish("tools_changed", {})
            except Exception as exc:
                self.ml.update(state="error", message=f"模型訓練失敗：{exc}")
            await self.bus.publish("ml_status", dict(self.ml))
