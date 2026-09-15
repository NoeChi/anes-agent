#!/bin/bash
# 麻醉 AI 查房助理 — 關閉系統（資料會保留，下次啟動可繼續使用）
cd "$(dirname "$0")" || exit 1
docker compose down
echo "系統已關閉。"
sleep 3
