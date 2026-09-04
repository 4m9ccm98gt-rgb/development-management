@echo off
rem Build the official EXE with one click. Run manually, only when needed.
rem Do not ask Codex to run this. A dirty working tree is refused.
rem NOTE: keep this file ASCII-only. cmd.exe mis-parses non-ASCII comments under CP932.
setlocal
cd /d "%~dp0"
title <app-name> - Manual EXE build
echo This script is for a USER-INITIATED manual build.
echo.

rem --- refuse a dirty working tree (a formal build must be from a commit) ---
for /f "delims=" %%S in ('git status --porcelain 2^>nul') do (
  echo [ERROR] Uncommitted changes present. Commit before a formal build.
  echo         For a throwaway check build, comment out this guard.
  goto :pause_failed
)

if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 goto :no_python
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto :failed

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
rem Match the method the project actually uses (PyInstaller onedir / Nuitka standalone).
rem For PySide6 compare food-cost's Nuitka track (see REUSE_MAP.md).
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name <AppName> app.py
if errorlevel 1 goto :failed

set "EXE_PATH=%CD%\dist\<AppName>\<AppName>.exe"
if not exist "%EXE_PATH%" goto :missing_exe
for %%F in ("%EXE_PATH%") do set "EXE_SIZE=%%~zF"
for /f "tokens=*" %%H in ('powershell -NoProfile -Command "(Get-FileHash -LiteralPath $env:EXE_PATH -Algorithm SHA256).Hash"') do set "EXE_SHA256=%%H"
for /f "tokens=*" %%C in ('git rev-parse HEAD 2^>nul') do set "SRC_COMMIT=%%C"
echo.
echo [SUCCESS] Build complete.
echo EXE:      %EXE_PATH%
echo Size:     %EXE_SIZE% bytes
echo SHA-256:  %EXE_SHA256%
echo Source:   %SRC_COMMIT%
echo.
pause
endlocal
exit /b 0

:no_python
echo [ERROR] Python 3 was not found.
goto :pause_failed

:missing_exe
echo [ERROR] The build ran but no EXE was produced.
goto :pause_failed

:failed
echo [ERROR] Build stopped. Review the messages above.

:pause_failed
echo.
pause
endlocal
exit /b 1
