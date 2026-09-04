@echo off
rem Launch the development build with one click: run the official source from .venv.
rem Use this path for day-to-day dev / UI / feature checks. Do not build an EXE here.
rem NOTE: keep this file ASCII-only. cmd.exe mis-parses non-ASCII comments under CP932.
setlocal
cd /d "%~dp0"
title <app-name> - Python development

if not exist ".venv\Scripts\python.exe" (
  echo [SETUP] Creating the Python virtual environment...
  where py >nul 2>nul
  if errorlevel 1 goto :no_python
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

rem Dependency check: install if the key package(s) cannot be imported.
rem Replace <import-check> with real imports, e.g. "import PySide6".
rem Use ";" not "," to separate multiple imports (cmd mis-parses commas here).
rem Do NOT put "(" or ")" in echo lines inside an if-block; cmd ends the block early.
".venv\Scripts\python.exe" -c "<import-check>" >nul 2>nul
if errorlevel 1 (
  echo [SETUP] Installing dependencies - first run or after dependency changes...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)

echo [START] Starting from Python source...
rem Entry is app.py or "-m <package>". Adjust to this app.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :failed
endlocal
exit /b 0

:no_python
echo.
echo [ERROR] Python 3 was not found. Install Python 3 and the py launcher, then retry.
goto :pause_failed

:failed
echo.
echo [ERROR] Startup failed. Review the messages above.

:pause_failed
echo.
pause
endlocal
exit /b 1
