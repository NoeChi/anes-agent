"""WebSocket 事件廣播：把模擬資料、查房結果、警示即時推送到瀏覽器。"""
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket


class EventBus:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def publish(self, type_: str, data) -> None:
        if not self.clients:
            return
        message = json.dumps({"type": type_, "data": data}, ensure_ascii=False, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(message), timeout=3)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
