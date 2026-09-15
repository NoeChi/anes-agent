@echo off
chcp 65001 >nul
rem 麻醉 AI 查房助理 — Windows 請直接雙擊這個檔案啟動（需要 Docker Desktop）
cd /d "%~dp0"
echo ==============================================
echo   麻醉 AI 查房助理 啟動中…
echo ==============================================
where docker >nul 2>nul
if errorlevel 1 (
  echo 找不到 Docker。請先安裝 Docker Desktop：https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo 正在開啟 Docker Desktop（第一次可能需要 1 分鐘）…
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  for /l %%i in (1,1,90) do (
    docker info >nul 2>nul && goto docker_ready
    timeout /t 2 >nul
  )
)
:docker_ready
echo 啟動資料庫與系統（第一次需要下載與建置，約 3–8 分鐘）…
docker compose up -d --build
if errorlevel 1 (
  echo 啟動失敗，請把上面的訊息提供給維護人員。
  pause
  exit /b 1
)
echo 等待系統就緒…
for /l %%i in (1,1,120) do (
  curl -fs http://127.0.0.1:8000/healthz >nul 2>nul && goto app_ready
  timeout /t 2 >nul
)
:app_ready
start "" http://127.0.0.1:8000
echo 系統已在背景執行：http://127.0.0.1:8000
echo 關閉系統：雙擊 stop.bat（資料會保留在資料庫中）
timeout /t 5 >nul
