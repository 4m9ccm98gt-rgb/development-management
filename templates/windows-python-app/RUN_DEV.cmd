@echo off
rem 開発版をワンクリック起動する。正式ソースを .venv から直接実行する。
rem 日常の開発・UI・機能確認はこの経路を標準にする。EXE は作らない。
rem beverage-inventory-ordering-system/python_app/RUN_DEV.cmd が実績パターン。
setlocal
cd /d "%~dp0"
title <app-name> - Python development

if not exist ".venv\Scripts\python.exe" (
  echo [SETUP] 仮想環境を作成します...
  where py >nul 2>nul
  if errorlevel 1 goto :no_python
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

rem 依存関係チェック: 主要パッケージが import できなければ install する。
rem <import-check> を対象アプリのキーとなる import 文へ置き換える。
".venv\Scripts\python.exe" -c "<import-check>" >nul 2>nul
if errorlevel 1 (
  echo [SETUP] 依存パッケージをインストールします（初回とdependency変更時のみ）...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)

echo [START] Pythonソースから起動します...
rem エントリは app.py か `-m <package>` のどちらか。対象に合わせる。
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :failed
endlocal
exit /b 0

:no_python
echo.
echo [ERROR] Python 3 が見つかりません。Python 3 と py ランチャーを入れて再実行してください。
goto :pause_failed

:failed
echo.
echo [ERROR] 起動に失敗しました。上のメッセージを確認してください。

:pause_failed
echo.
pause
endlocal
exit /b 1
