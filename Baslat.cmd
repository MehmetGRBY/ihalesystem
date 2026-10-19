@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Once kurulum yapin: python -m venv .venv
  echo .venv\Scripts\python -m pip install -e .
  pause
  exit /b 1
)
.venv\Scripts\python app.py
pause
