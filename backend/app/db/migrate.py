"""啟動時自動把資料庫升級到最新結構（Alembic upgrade head），並等待資料庫可連線。"""
from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from ..config import BASE_DIR
from .session import Database


def _upgrade(url: str) -> None:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


async def wait_for_database(db: Database, timeout: float = 60.0) -> None:
    waited = 0.0
    while not await db.ping():
        if waited >= timeout:
            raise RuntimeError(
                f"無法連線到資料庫（{db.safe_url}）。請確認 PostgreSQL 已啟動："
                "在專案資料夾執行 docker compose up -d db，或設定正確的 DATABASE_URL。")
        await asyncio.sleep(2)
        waited += 2


async def migrate(db: Database) -> None:
    await asyncio.to_thread(_upgrade, db.url)
