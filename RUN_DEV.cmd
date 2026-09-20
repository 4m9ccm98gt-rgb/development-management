@echo off
rem Launch the Development Control Center from the tracked source. Standard library only.
rem NOTE: keep this file ASCII-only. cmd.exe mis-parses non-ASCII comments under CP932.
setlocal
cd /d "%~dp0"
title development-management - Development Control Center

where py >nul 2>nul
if errorlevel 1 goto :no_python

echo [START] Starting Development Control Center from source...
py -3 DEV_CONTROL_CENTER.pyw
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
