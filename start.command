#!/bin/bash
# 麻醉 AI 查房助理 — macOS 請直接雙擊這個檔案啟動（需要 Docker Desktop）
cd "$(dirname "$0")" || exit 1
echo "=============================================="
echo "  麻醉 AI 查房助理 啟動中…"
echo "=============================================="
if ! command -v docker >/dev/null 2>&1; then
  echo "找不到 Docker。請先安裝 Docker Desktop：https://www.docker.com/products/docker-desktop/"
  read -r -p "按 Enter 關閉…"; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "正在開啟 Docker Desktop（第一次可能需要 1 分鐘）…"
  if command -v open >/dev/null 2>&1; then open -a Docker; fi
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker 尚未就緒，請手動開啟 Docker Desktop 後再試一次。"
  read -r -p "按 Enter 關閉…"; exit 1
fi
echo "啟動資料庫與系統（第一次需要下載與建置，約 3–8 分鐘）…"
if ! docker compose up -d --build; then
  echo "啟動失敗，請把上面的訊息提供給維護人員。"
  read -r -p "按 Enter 關閉…"; exit 1
fi
echo "等待系統就緒…"
for _ in $(seq 1 120); do curl -fs http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break; sleep 2; done
URL=http://127.0.0.1:8000
if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
echo ""
echo "系統已在背景執行：$URL"
echo "關閉系統：雙擊 stop.command（資料會保留在資料庫中）"
sleep 5
