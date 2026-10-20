@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python scripts\install_desktop_shortcut.py
) else (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 (
    py -3 scripts\install_desktop_shortcut.py
  ) else (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if errorlevel 1 (
      echo Python 3.11 veya uzeri kurup tekrar deneyin: https://www.python.org/downloads/
      pause
      exit /b 1
    )
    python scripts\install_desktop_shortcut.py
  )
)
if errorlevel 1 (
  pause
  exit /b 1
)
echo Masaustu kisayolu hazir. Artik Ihale Bulucu simgesine cift tiklayabilirsiniz.
pause
