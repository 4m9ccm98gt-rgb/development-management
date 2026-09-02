@echo off
rem 正式 EXE をワンクリックでビルドする。ユーザーが必要なときだけ手動実行する。
rem dirty working tree では正式ビルドしない（scripts\dev.py が拒否する）。
rem 実績のある既存ビルドスクリプトがある場合は project.toml の build.existing_cmd で呼ぶ。
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% scripts\dev.py build %*
set RC=%ERRORLEVEL%
echo.
echo [BUILD] 終了コード %RC%
pause
endlocal & exit /b %RC%
