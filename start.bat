@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 英语词汇学习助手

REM 若存在虚拟环境则自动激活（可选，未创建则跳过）
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"

echo ============================================
echo   英语词汇学习助手 - 正在启动...
echo   本机访问:  http://127.0.0.1:8000
echo   手机访问:  http://^<本机局域网IP^>:8000
echo   停止服务:  在此窗口按 Ctrl+C
echo ============================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo [服务已退出]
pause
