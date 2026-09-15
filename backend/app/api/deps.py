"""路由共用：取得應用程式狀態、回傳錯誤。"""
from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, Request

from ..state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.S


def bad(message: str, code: int = 400) -> NoReturn:
    raise HTTPException(status_code=code, detail=message)
