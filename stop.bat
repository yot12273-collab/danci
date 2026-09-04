@echo off
chcp 65001 >nul
setlocal
title 停止英语词汇学习助手

set "PORT=8000"
set "PID="

REM 查找占用 8000 端口且处于监听状态的进程 PID（取第一个）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr LISTENING') do (
    if not defined PID set "PID=%%a"
)

if not defined PID (
    echo [信息] 未发现占用 %PORT% 端口的服务，可能已经停止。
    pause
    exit /b 0
)

echo 正在停止占用 %PORT% 端口的进程 PID=%PID% ...
taskkill /F /PID %PID%

echo 完成。
pause
