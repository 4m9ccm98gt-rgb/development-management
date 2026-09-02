@echo off
rem 配布先（共有フォルダ / HDD 等）をワンクリックで更新する。手動実行専用。
rem 実処理は update_shared_folder.ps1（配布物と業務データを分離、/MIR はランタイムのみ、
rem 業務データの SHA-256 検証つき）。
setlocal
cd /d "%~dp0"
title <app-name> - Update shared folder
echo 配布先のアプリ本体を更新します。業務データと設定は保持されます。
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_shared_folder.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [SUCCESS] 配布先の更新が完了しました。
) else (
  echo [ERROR] 更新は完了しませんでした。update_shared_folder_result.txt を確認してください。
)
pause
endlocal & exit /b %RC%
