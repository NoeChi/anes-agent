"""測試共用設定：每次測試都重建一個乾淨的 PostgreSQL 測試資料庫（預設 anes_test）。

需要先啟動資料庫：在專案資料夾執行 `docker compose up -d db`。
可用環境變數 TEST_DATABASE_URL 指定其他資料庫。
"""
from __future__ import annotations

import asyncio
import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://anes:anes@127.0.0.1:55432/anes_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


async def _recreate_database() -> None:
    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DATABASE_URL)
    admin = await asyncpg.connect(user=url.username, password=url.password, host=url.host, port=url.port,
                                  database="postgres")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
def fresh_database():
    try:
        asyncio.run(_recreate_database())
    except Exception as exc:
        pytest.exit(f"無法建立測試資料庫 {TEST_DATABASE_URL}：{exc}（請先執行 docker compose up -d db）", returncode=1)


@pytest.fixture(scope="session")
def client(fresh_database):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(TEST_DATABASE_URL)) as c:
        yield c


@pytest.fixture(scope="session")
def state(client):
    return client.app.state.S


@pytest.fixture(scope="session")
def run(client):
    """在應用程式自己的事件迴圈中執行協程（資料庫連線綁定在該迴圈上）。"""
    def _run(fn, *args):
        return client.portal.call(fn, *args)
    return _run
