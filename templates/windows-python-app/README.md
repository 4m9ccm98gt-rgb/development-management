# windows-python-app テンプレート

Python/Windows アプリに「同期」「起動」「ビルド」「配布更新」の4経路を一意に用意するための雛形。
[../../CAPABILITIES.md](../../CAPABILITIES.md) と [../../OPERATING_CONTRACT.md](../../OPERATING_CONTRACT.md)
の工程③〜⑤を実装する。

**実績パターンは既存各repoの RUN_DEV / BUILD / UPDATE 系スクリプト。**
既に同等経路があるリポジトリでは作り直さず、互換性を優先する。

## 使い方

1. このフォルダの内容を、対象アプリの置き場所（リポジトリ直下、または `python_app/` 等）へコピーする。
2. `pyproject.toml` と各 `.cmd` / `.ps1` の `<...>` プレースホルダを実値へ置き換える：
   - `<app-name>` / `<AppName>` — 表示名 / EXE 名
   - `<import-check>` — `RUN_DEV.cmd` の依存チェック用 import 文（例: `import PySide6`）
   - `<owner>/<repo>` — `SYNC_CLICK_ME.cmd` が検証する正式GitHub repo
   - `<candidate-branch>` — 工程③で同期する正式candidate branch。**`origin/HEAD` から推測しない**
   - `update_shared_folder.ps1` 冒頭の `$AppExeName` / `$BuildDirName` / `$RuntimeDir` / `$DataDirName`
3. `requirements.txt`（実行依存）と `requirements-dev.txt`（+ pytest, ビルドツール）を用意する。
4. `SYNC_RESULT.txt` を `.gitignore` に追加する。
5. 配布先の実パスは貼り付け入力。Git にもコード内定数にも書かない。

## アプリ種別

種別（`desktop` / `web` / `service` / `lib` / `archived`）は**アプリ側に置かない**。
[../../scripts/repo_types.toml](../../scripts/repo_types.toml) で一元管理する。
`check_standards.py` はそこの登録値で点検内容を切り替える。

| type | 必要な経路 |
|---|---|
| `desktop` | candidate同期 ＋ 開発起動 ＋ EXEビルド ＋ 配布更新（このテンプレートが対象） |
| `web` | candidate同期 ＋ 開発起動 ＋ デプロイ |
| `service` | candidate同期 ＋ 開発起動 ＋ 常駐登録 |
| `lib` | candidate同期のみ必要に応じて整備 |
| `archived` | 点検対象外 |

## 4経路（desktop）

| 経路 | ワンクリック | 中身 | 必要能力 |
|---|---|---|---|
| candidate同期 | `SYNC_CLICK_ME.cmd` | expected repo / branch / dirty / aheadを確認 → `fetch --prune` → expected SHAとorigin SHA一致確認 → `merge --ff-only` → HEAD一致確認 | `windows-real`（ユーザー） |
| 開発起動 | `RUN_DEV.cmd` | `.venv` 自動作成 → 依存チェック → `python app.py` | `windows-real`（ユーザー） |
| EXE ビルド | `BUILD_EXE_CLICK_ME.cmd` | dirty tree 拒否 → venv → `pytest -q` → build/dist 掃除 → PyInstaller onedir → EXE の size / SHA-256 / source commit 表示 | `windows-real`（ユーザー） |
| 配布更新 | `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` | 配布先パスは貼り付け → ランタイムのみ `/MIR` → EXE を atomic 差し替え → 業務データの SHA-256 と件数を更新前後で検証 | `windows-real` ＋ `shared-server` / `real-peripherals`（ユーザー） |

いずれも自己完結の Windows バッチ / PowerShell 5.1。Python 起動前に Python を要求しない。

## `SYNC_CLICK_ME.cmd` の安全境界

- 対象repoとcandidate branchは各repoへ**明示設定**する。default branchや`origin/HEAD`から推測しない。
- ChatGPTが工程②完了時に示したcandidate SHAを、ダブルクリック後のプロンプトへ貼り付ける。引数で渡すこともできる。
- tracked dirty、detached HEAD、wrong branch、wrong repo、local ahead、origin SHAとexpected SHAの不一致では停止する。
- 自動switch / stash / reset / rebase / forceを行わない。
- untracked fileは警告のみで変更しない。
- 成功条件は `HEAD == origin/<candidate-branch> == expected SHA` かつ tracked clean。
- 成否と repo / branch / SHA / ahead / behind は `SYNC_RESULT.txt` に出力する。
- 成功したら工程③はそこで終了。アプリ起動、GUI確認、テスト、build、deployへ進まない。

## 補助（Linux sandbox / CI でも動く）

`python scripts/dev.py doctor` — Python / `.venv` / Git 状態
`python scripts/dev.py check`  — development-management の `check_standards.py` をこのリポジトリへ適用

## .cmd を書くときの注意（実機で踏んだもの）

- **ASCII のみ**。`cmd.exe` は CP932 環境で非 ASCII のコメントを誤解釈することがある。
- **CRLF 改行**（`.gitattributes` の `*.cmd eol=crlf` で担保）。
- `if (...)` ブロック内の `echo` に **`(` `)` を入れない**。
- `python.exe -c "..."` の中で複数 import を **`,` で区切らない**（`;` を使う）。

## 既存アプリへの後付け

稼働中アプリでは既存の RUN_DEV / BUILD / UPDATE を壊さず、まず `SYNC_CLICK_ME.cmd` を追加する。
同期branchはrepoごとの正式candidate branchを明示設定する。特殊branchを使うrepoでは `main` 固定にしない。
標準と違う名前でも既存の運用互換性を優先してよい。
