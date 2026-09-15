"""FastAPI 應用程式：REST API（/api）、WebSocket（/ws），並提供 Vue 前端建置後的網頁（frontend/dist）。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router, ws_router
from .config import FRONTEND_DIST
from .state import AppState

FRONTEND_MISSING = """<!doctype html><meta charset="utf-8"><title>麻醉 AI 查房助理</title>
<body style="font-family:sans-serif;max-width:640px;margin:60px auto;line-height:1.7">
<h2>前端尚未建置</h2>
<p>後端已啟動，但找不到 Vue 前端的建置結果（<code>frontend/dist</code>）。請擇一：</p>
<ul>
<li>一般使用：在專案資料夾雙擊 <b>start.command</b>（或執行 <code>docker compose up -d --build</code>）</li>
<li>開發：在 <code>frontend/</code> 執行 <code>npm install</code> 後 <code>npm run dev</code>，改用 Vite 提供的網址</li>
<li>或執行 <code>npm run build</code> 後重新整理本頁</li>
</ul></body>"""


def create_app(database_url: str | None = None) -> FastAPI:
    state = AppState(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await state.startup()
        yield
        await state.shutdown()

    app = FastAPI(title="麻醉 AI 查房助理", lifespan=lifespan)
    app.state.S = state

    @app.exception_handler(Exception)
    async def unhandled(request, exc):  # pragma: no cover - 保底
        return JSONResponse(status_code=500, content={"detail": f"伺服器錯誤：{type(exc).__name__}: {exc}"})

    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
    async def healthz():
        return "ok"

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = FRONTEND_DIST.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="找不到此 API")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse(FRONTEND_MISSING, status_code=503)


app = create_app()
