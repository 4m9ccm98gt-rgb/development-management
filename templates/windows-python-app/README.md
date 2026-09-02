# windows-python-app テンプレート

Python/Windows アプリに「起動」「ビルド」「配布更新」の3経路を一意に用意するための雛形。
[../../CAPABILITIES.md](../../CAPABILITIES.md) と [../../docs/decisions.md](../../docs/decisions.md)
の「ソース起動を標準とし、EXE は手動ビルド、配布更新もワンクリック化する」を実装する。

## 使い方

1. このフォルダの内容を対象リポジトリ直下へコピーする。
2. `project.toml` を実値へ書き換える（`name` / `python` / `entry` / `venv`、ビルド・配布の既存スクリプト名）。
3. 配布先の実パスなど秘密・環境依存値は `project.local.toml` に置く（`.gitignore` へ追加、Git 管理しない）。
4. 既に実績のあるビルド／配布スクリプトがある場合は、作り直さず `build.existing_cmd` /
   `dist.existing_cmd` で呼ぶ。名前が標準と違っていても互換性を優先してよい。

## 3経路

| 経路 | ワンクリック | 中身 | 必要能力 |
|---|---|---|---|
| 開発起動 | `RUN_DEV.cmd` | `.venv` から `python -m <entry>` | `windows-real` |
| EXE ビルド | `BUILD_EXE_CLICK_ME.cmd` | dirty tree 拒否 → 既存ビルド or nuitka/pyinstaller → 成果物の size/mtime/SHA-256/commit を表示 | `windows-real`（ユーザー手動） |
| 配布更新 | `UPDATE_SHARED_FOLDER.cmd` | 配布物と業務データを分離して更新（`/MIR` 禁止） | `windows-real` ＋ `shared-server` / `real-peripherals` |

いずれも `python scripts/dev.py <run|build|dist|doctor|check>` を呼ぶ薄いラッパー。
`scripts/dev.py` は標準ライブラリのみ（Python 3.11+）。Linux sandbox / CI でも
`doctor` と `check` は動く。

## 点検

`python scripts/dev.py check` で development-management の `scripts/check_standards.py`
をこのリポジトリへ適用する（3経路の有無・秘密パターン等）。

## 既存アプリへの後付け

稼働中アプリでは、まず `RUN_DEV.cmd` だけ追加する（最も安く、思想が一番依存する経路）。
既存の `BUILD_*` / `update_shared_folder.ps1` はそのまま活かし、ラッパーから呼ぶ。
ビルド・配布の挙動そのものは変えない。
