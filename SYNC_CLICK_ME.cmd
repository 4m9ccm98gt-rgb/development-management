@echo off
setlocal
cd /d "%~dp0"
set "EXPECTED_SHA=%~1"
set "NO_PAUSE="
if /I "%~2"=="--no-pause" set "NO_PAUSE=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\SYNC_CANDIDATE.ps1" -ExpectedRepo "4m9ccm98gt-rgb/development-management" -TargetBranch "main" -ExpectedSha "%EXPECTED_SHA%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo SYNC SUCCEEDED.
) else (
  echo SYNC STOPPED.
)
echo Result: "%~dp0SYNC_RESULT.txt"
if not defined NO_PAUSE pause
exit /b %RC%
