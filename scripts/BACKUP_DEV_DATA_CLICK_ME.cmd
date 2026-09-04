@echo off
rem One-click backup of all Git-excluded development data (DBs, real settings,
rem credentials, local-only files, business data). Read-only on every source.
rem Output goes to %USERPROFILE%\DevDataBackups and (if an external drive is
rem present) is copied there too. Keep the output OUT of Git.
rem NOTE: keep this file ASCII-only.
setlocal
cd /d "%~dp0"

set "SECOND="
if exist "E:\" set "SECOND=E:\DevDataBackups"
if exist "%USERPROFILE%\OneDrive\" if "%SECOND%"=="" set "SECOND=%USERPROFILE%\OneDrive\DevDataBackups"

if defined SECOND (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BACKUP_DEV_DATA.ps1" -SecondDest "%SECOND%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BACKUP_DEV_DATA.ps1"
)
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [DONE] Backup complete. Also keep a copy on an offline drive.
) else (
  echo [ERROR] Backup exited with %RC%. Review the messages above.
)
pause
endlocal & exit /b %RC%
