@echo off
setlocal
cd /d "%~dp0"
set "EXPECTED_SHA=%~1"
set "NO_PAUSE_ARG="
if /I "%~2"=="--no-pause" set "NO_PAUSE_ARG=-NoPause"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\SYNC_CANDIDATE.ps1" -ExpectedRepo "<owner>/<repo>" -TargetBranch "<candidate-branch>" -ExpectedSha "%EXPECTED_SHA%" %NO_PAUSE_ARG% & exit /b
