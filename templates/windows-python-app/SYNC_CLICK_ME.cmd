@echo off
setlocal
cd /d "%~dp0"
set "EXPECTED_SHA=%~1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\SYNC_CANDIDATE.ps1" -ExpectedRepo "<owner>/<repo>" -TargetBranch "<candidate-branch>" -ExpectedSha "%EXPECTED_SHA%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo SYNC SUCCEEDED.
) else (
  echo SYNC STOPPED.
)
echo Result: "%~dp0SYNC_RESULT.txt"
pause
exit /b %RC%
