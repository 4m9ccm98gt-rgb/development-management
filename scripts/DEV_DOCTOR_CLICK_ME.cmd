@echo off
rem DEV DOCTOR - check this machine's development environment (read-only).
rem Read the Summary at the bottom. Then paste the whole report into ChatGPT
rem etc. for a diagnosis. The full report is also saved to:
rem   %USERPROFILE%\DEV_DOCTOR_report.txt
rem NOTE: keep this file ASCII-only.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0DEV_DOCTOR.ps1" %*
echo.
echo ----------------------------------------------------------------------
echo Full report saved to: %USERPROFILE%\DEV_DOCTOR_report.txt
echo Paste that file's contents to ChatGPT to get a diagnosis.
echo.
pause
endlocal
