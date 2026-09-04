@echo off
rem Update the distribution target (shared folder / HDD) with one click. Manual only.
rem The real work is in update_shared_folder.ps1: payload vs business data separated,
rem /MIR limited to the runtime dir, business data verified by SHA-256.
rem NOTE: keep this file ASCII-only. cmd.exe mis-parses non-ASCII comments under CP932.
setlocal
cd /d "%~dp0"
title <app-name> - Update shared folder
echo Updating the application files at the distribution target.
echo Business data and settings are preserved.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_shared_folder.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [SUCCESS] Distribution target updated.
) else (
  echo [ERROR] Update did not complete. See update_shared_folder_result.txt.
)
pause
endlocal & exit /b %RC%
