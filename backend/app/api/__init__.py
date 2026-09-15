"""REST API 與 WebSocket 路由（依功能分檔）。"""
from fastapi import APIRouter

from . import chat, export, patients, rounds, settings, simulation, skills, tools, ws

api_router = APIRouter(prefix="/api")
for module in (patients, simulation, tools, skills, rounds, settings, chat, export):
    api_router.include_router(module.router)

ws_router = ws.router
