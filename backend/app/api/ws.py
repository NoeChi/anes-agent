"""WebSocket：即時推送生命徵象、查房結果、警示與對話進度。"""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    S = ws.app.state.S
    await S.bus.connect(ws)
    try:
        hello = {"type": "hello", "data": {"settings": S.settings.public(), "llm": S.llm.status(), "ml": S.ml}}
        await ws.send_text(json.dumps(hello, ensure_ascii=False, default=str))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        S.bus.disconnect(ws)
