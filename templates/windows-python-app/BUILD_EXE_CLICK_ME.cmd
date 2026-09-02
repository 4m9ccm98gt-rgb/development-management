@echo off
rem 正式 EXE をワンクリックでビルドする。ユーザーが必要なときだけ手動実行する。
rem Codex には通常依頼しない。dirty working tree は正式ビルドしない。
setlocal
cd /d "%~dp0"
title <app-name> - Manual EXE build
echo This script is for a USER-INITIATED manual build.
echo.

rem --- dirty working tree 拒否（正式ビルドは commit 後） ---
for /f "delims=" %%S in ('git status --porcelain 2^>nul') do (
  echo [ERROR] 未コミットの変更があります。commit してから正式ビルドしてください。
  echo         確認用ビルドが必要なら、このチェックを一時的に外して実行します。
  goto :pause_failed
)

if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 goto :no_python
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto :failed

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
rem 方式はプロジェクトの実績に合わせる（PyInstaller onedir / Nuitka standalone 等）。
rem PySide6 では food-cost の Nuitka 実績も比較する（REUSE_MAP.md）。
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name <AppName> app.py
if errorlevel 1 goto :failed

set "EXE_PATH=%CD%\dist\<AppName>\<AppName>.exe"
if not exist "%EXE_PATH%" goto :missing_exe
for %%F in ("%EXE_PATH%") do set "EXE_SIZE=%%~zF"
for /f "tokens=*" %%H in ('powershell -NoProfile -Command "(Get-FileHash -LiteralPath $env:EXE_PATH -Algorithm SHA256).Hash"') do set "EXE_SHA256=%%H"
for /f "tokens=*" %%C in ('git rev-parse HEAD 2^>nul') do set "SRC_COMMIT=%%C"
echo.
echo [SUCCESS] Build complete.
echo EXE:      %EXE_PATH%
echo Size:     %EXE_SIZE% bytes
echo SHA-256:  %EXE_SHA256%
echo Source:   %SRC_COMMIT%
echo.
pause
endlocal
exit /b 0

:no_python
echo [ERROR] Python 3 が見つかりません。
goto :pause_failed

:missing_exe
echo [ERROR] ビルドは走りましたが EXE が生成されていません。
goto :pause_failed

:failed
echo [ERROR] ビルドを中止しました。上のメッセージを確認してください。

:pause_failed
echo.
pause
endlocal
exit /b 1
