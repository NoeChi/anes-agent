"""啟動入口：python -m app  → 啟動伺服器並自動開啟瀏覽器。"""
from __future__ import annotations

import os
import socket
import threading
import webbrowser

import uvicorn


def _free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


def main() -> None:
    port = _free_port(int(os.environ.get("PORT", "8000")))
    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  麻醉 AI 查房助理（Demo）啟動中…")
    print(f"  瀏覽器網址：{url}")
    print("  關閉系統：直接關掉這個視窗，或按 Ctrl + C")
    print("=" * 60)
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(2.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"), port=port, log_level="warning")


if __name__ == "__main__":
    main()
