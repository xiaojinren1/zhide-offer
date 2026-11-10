@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" start.py
if errorlevel 1 pause
