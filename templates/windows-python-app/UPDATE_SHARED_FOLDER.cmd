@echo off
rem 配布先（共有フォルダ / HDD 等）をワンクリックで更新する。手動実行専用。
rem 配布物と業務データを分離する。共有フォルダ全体への robocopy /MIR は使わない。
rem 実績のある既存の update_shared_folder.ps1 等がある場合は project.toml の
rem dist.existing_cmd で呼ぶ。配布先の実値は project.local.toml（Git 管理外）に置く。
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% scripts\dev.py dist %*
set RC=%ERRORLEVEL%
echo.
echo [DIST] 終了コード %RC%
pause
endlocal & exit /b %RC%
