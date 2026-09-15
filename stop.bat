@echo off
chcp 65001 >nul
cd /d "%~dp0"
docker compose down
echo 系統已關閉。
timeout /t 3 >nul
