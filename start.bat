@echo off
rem Usage: start.bat        start (same as start.py start)
rem        start.bat stop   stop
rem See RUNBOOK.md for setup, DEPLOY.md for server deployment.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [!] 未找到项目 Python 环境，请先按 RUNBOOK.md 完成安装。
  pause
  exit /b 1
)
if /i "%~1"=="stop" (
  ".venv\Scripts\python.exe" start.py stop
) else (
  ".venv\Scripts\python.exe" start.py start
)
if errorlevel 1 pause
