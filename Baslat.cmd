@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Once kurulum yapin: python -m venv .venv
  echo .venv\Scripts\python -m pip install -e .
  pause
  exit /b 1
)
.venv\Scripts\python scripts\local_search.py ensure
if errorlevel 1 (
  pause
  exit /b 1
)
.venv\Scripts\python app.py
pause
