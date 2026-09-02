# windows-python-app テンプレート

Python/Windows アプリに「起動」「ビルド」「配布更新」の3経路を一意に用意するための雛形。
[../../CAPABILITIES.md](../../CAPABILITIES.md) と、[../../docs/decisions.md](../../docs/decisions.md)
の「ソース起動を標準とし、EXE は手動ビルド、配布更新もワンクリック化する」を実装する。

**実績パターンは `beverage-inventory-ordering-system/python_app/` の3スクリプト。**
このテンプレートはそれを汎用化したもの。既にそれらがあるリポジトリでは作り直さない。

## 使い方

1. このフォルダの内容を、対象アプリの置き場所（リポジトリ直下、または `python_app/` 等）へコピーする。
2. `pyproject.toml` と各 `.cmd` / `.ps1` の `<...>` プレースホルダを実値へ置き換える：
   - `<app-name>` / `<AppName>` — 表示名 / EXE 名
   - `<import-check>` — `RUN_DEV.cmd` の依存チェック用 import 文（例: `import PySide6`）
   - `update_shared_folder.ps1` 冒頭の `$AppExeName` / `$BuildDirName` / `$RuntimeDir` / `$DataDirName`
3. `requirements.txt`（実行依存）と `requirements-dev.txt`（+ pytest, ビルドツール）を用意する。
4. 配布先の実パスは貼り付け入力。Git にもコード内定数にも書かない。

## 3経路

| 経路 | ワンクリック | 中身 | 必要能力 |
|---|---|---|---|
| 開発起動 | `RUN_DEV.cmd` | `.venv` 自動作成 → 依存チェック → `python app.py` | `windows-real` |
| EXE ビルド | `BUILD_EXE_CLICK_ME.cmd` | dirty tree 拒否 → venv → `pytest -q` → build/dist 掃除 → PyInstaller onedir → EXE の size / SHA-256 / source commit 表示 | `windows-real`（ユーザー手動） |
| 配布更新 | `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` | 配布先パスは貼り付け → ランタイムのみ `/MIR` → EXE を atomic 差し替え → 業務データの SHA-256 と件数を更新前後で検証 | `windows-real` ＋ `shared-server` / `real-peripherals` |

いずれも自己完結の Windows バッチ / PowerShell 5.1。Python 起動前に Python を要求しない。

## 補助（Linux sandbox / CI でも動く）

`python scripts/dev.py doctor` — Python / `.venv` / Git 状態
`python scripts/dev.py check`  — development-management の `check_standards.py` をこのリポジトリへ適用

## 既存アプリへの後付け

稼働中アプリでは、まず `RUN_DEV.cmd` だけ追加する（最も安く、思想が一番依存する経路）。
既存の `BUILD_*` / `update_shared_folder.ps1` はそのまま活かし、挙動は変えない。
標準と違う名前でも互換性を優先してよい（`BUILD_俺伝_CLICK_ME.cmd` / `UPDATE_HDD_CLICK_ME.cmd` 等）。
