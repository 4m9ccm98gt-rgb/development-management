@echo off
setlocal
cd /d "%~dp0"
title Bootstrap dev PC
echo ================================================================
echo   BOOTSTRAP_DEV_PC - rebuild the development environment
echo ================================================================
echo.
echo This clones the canonical repos into
echo   C:\Users\suisy\Documents\Development\repos
echo It NEVER overwrites an existing repo or restores databases /
echo credentials / settings. Safe to run again.
echo.
echo First: make sure git, Python and gh are installed and that
echo 'gh auth login' has been done (see docs\operator_runbook.md section 6).
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BOOTSTRAP_DEV_PC.ps1"
echo.
echo Done. If any [ERROR] lines appeared, fix them and run this again.
echo Next: run DEV_DOCTOR_CLICK_ME.cmd
echo.
pause
endlocal
