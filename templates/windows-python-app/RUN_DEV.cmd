@echo off
rem 開発版をワンクリック起動する。正式ソースを .venv から直接実行する。
rem EXE は作らない。日常の開発・UI・機能確認はこの経路を標準にする。
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% scripts\dev.py run %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo [RUN_DEV] 終了コード %RC%
  pause
)
endlocal & exit /b %RC%
