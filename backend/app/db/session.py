"""資料庫連線（非同步 SQLAlchemy + asyncpg）。"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import COUNTED_TABLES


class Database:
    def __init__(self, url: str):
        self.url = url
        kwargs = {"pool_pre_ping": True}
        if not url.startswith("sqlite"):
            kwargs.update(pool_size=10, max_overflow=10)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        return self.sessionmaker()

    @property
    def safe_url(self) -> str:
        return make_url(self.url).render_as_string(hide_password=True)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def server_version(self) -> str:
        if self.engine.dialect.name != "postgresql":
            return self.engine.dialect.name
        async with self.engine.connect() as conn:
            version = await conn.scalar(text("SHOW server_version"))
        return f"PostgreSQL {str(version).split()[0]}"

    async def table_counts(self, exact: bool = False) -> dict[str, int]:
        """各資料表筆數。PostgreSQL 預設用統計資訊估計（大型時間序列資料表也能即時回應）。"""
        names = [m.__tablename__ for m in COUNTED_TABLES]
        async with self.session() as s:
            if not exact and self.engine.dialect.name == "postgresql":
                rows = (await s.execute(text("SELECT relname, n_live_tup FROM pg_stat_user_tables"))).all()
                live = {name: int(n) for name, n in rows}
                return {n: live.get(n, 0) for n in names}
            return {m.__tablename__: int(await s.scalar(select(func.count()).select_from(m)) or 0) for m in COUNTED_TABLES}

    async def dispose(self) -> None:
        await self.engine.dispose()
