# Daily Log

日々の作業事実を簡潔に記録します。新しい日付を上に追加し、重要な判断は `docs/decisions.md`、再発防止の知見は `LESSONS_LEARNED.md` にも反映します。

## 2026-09-02

### 今日の目的

- 開発環境整備を、ChatGPT / Codex / Claude Code のどれでも効く形に立て直す（Phase 0）。

### 実施したこと

- 対象: `development-management`
- ローカル同期のズレを解消：ローカル未コミットだった `DEVELOPMENT_RULES.md`（俺伝リリース標準）/ `REUSE_MAP.md`（Nuitka・HDD再利用）を commit + push（`4293c5e`）。原因は「ChatGPTはGitHubへ直接、実機作業はローカルへ、を同期する担当が未定義」。
- `CAPABILITIES.md` 追加：担当をエージェント名でなくセッションの能力で判定。正式ローカルリポジトリの同期規約（作業前 pull・作業後 push）を必須化。軽量レーンも記載。
- `docs/decisions.md` に「能力ベースへの切り替え」を記録。`AGENTS.md` / `AI_STARTUP.md` にポインタと同期規約を追記。
- `templates/windows-python-app/` 追加：`RUN_DEV.cmd` / `BUILD_EXE_CLICK_ME.cmd` / `UPDATE_SHARED_FOLDER.cmd` + `update_shared_folder.ps1` + `pyproject.toml` + `scripts/dev.py`。`beverage-inventory-ordering-system/python_app/` の実績3スクリプトを汎用化したもの。
- `scripts/check_standards.py` 追加：3経路の有無（サブディレクトリ対応）・秘密パターン・`PROJECT_STATUS.md` 鮮度・`projects/*.md` 参照漏れを点検。stdlib、Windows/Linux/CI 共通。

### 確認結果

- `py_compile`: `check_standards.py` / `dev.py` 成功
- PowerShell parse: `update_shared_folder.ps1` 成功
- `python scripts/check_standards.py`: ERROR 0 / WARN 13
  - 主な WARN: `inventory-reconciliation-system` / `kitchen-calendar` / `qr-supply-ordering-system` は3経路なし、`food-cost-calculation-system` / `next-day-setup` は `RUN_DEV.cmd` なし、`next-day-setup` に実 `master_settings.json`、`menu-sheet-generator.md` が README 未参照。
  - `beverage-inventory-ordering-system` は `python_app/` に3経路完備のため対象外（当初 Phase 1 パイロット候補だったが、既に整備済みのため中止）。
- 実機 EXE ビルド / 配布更新 / 実プリンター: 未実施

### 決定事項

- [作業割り当てをエージェント名から「能力ベース」に切り替える](docs/decisions.md#作業割り当てをエージェント名から能力ベースに切り替える)

### 未確認・問題

- テンプレートを実アプリへ適用した動作確認は未実施（次フェーズ）。
- `check_standards.py` を GitHub Actions の PR チェックに載せる作業は未着手。

### 追記（Phase 1 立て直し）

- Phase 1 パイロット候補だった `beverage` は `python_app/` に3経路完備と判明。適用先ではなく手本側なので、テンプレートを `beverage/python_app/` の実績スクリプトへ寄せて作り直し（自己完結バッチ、`pyproject.toml`、`update_shared_folder.ps1` の業務データ SHA-256 検証）。
- `check_standards.py` をサブディレクトリ対応に修正。さらに **アプリ種別**（desktop / web / service / lib）を導入し、種別ごとに必要経路を切り替え。種別は `pyproject.toml` の `[tool.devstandards] type` → `scripts/repo_types.toml`（暫定）→ 依存関係の自動判定、の順で解決。
- 再点検: **WARN 13 → 8**。Webアプリ（`qr-supply-ordering-system`）への「EXEビルドが無い」等の的外れ警告が消えた。
- 正確化後の実バックログ:
  - `RUN_DEV.cmd` 未整備: `food-cost-calculation-system`(desktop) / `inventory-reconciliation-system`(service) / `next-day-setup`(desktop) / `qr-supply-ordering-system`(web)
  - `qr-supply-ordering-system`: デプロイ手順なし
  - `kitchen-calendar`: 種別未設定（自動判定不可、要確認）
  - `development-management`: `menu-sheet-generator.md` が README 未参照
  - `next-day-setup`: 実 `master_settings.json`

### 追記（種別情報の一元化）

- ユーザー確認で設計を統一：**種別情報は `development-management/scripts/repo_types.toml` を唯一の正**とし、アプリ側にはマーカーを置かない。`check_standards.py` は登録値だけを正式判定に使う（自動判定は未登録警告のヒント専用に降格）。`archived` 種別を追加し点検対象外にできるようにした。
- `repo_types.toml` に全8アプリを登録。`menu-sheet-generator = desktop`（対話型の帳票生成アプリ、ユーザー確認済み）、`kitchen-calendar = archived`（NDSへ取り込み済み・今後開発しない）。
- テンプレートの `pyproject.toml` から種別マーカーを削除。
- 再点検: WARN 8 → 7。的外れ・未確定がすべて消え、残りは実バックログのみ。
  - `RUN_DEV.cmd` 未整備: `food-cost-calculation-system` / `inventory-reconciliation-system` / `next-day-setup`
  - `qr-supply-ordering-system`: `RUN_DEV.cmd` とデプロイ手順
  - `development-management`: `menu-sheet-generator.md` が README 未参照
  - `next-day-setup`: 実 `master_settings.json`

### 追記（NDS パイロット実施）

- `next-day-setup` にブランチ `claude/standardize-run-dev` を作成、`RUN_DEV.cmd` のみ追加（種別マーカーは置かない）。Draft PR `next-day-setup#2`。
- テンプレート（`templates/windows-python-app/RUN_DEV.cmd`）をそのまま適用：`.venv` 自動作成 → 依存チェック（`openpyxl, reportlab, PIL`）→ `pip install -r requirements.txt` → `dinner_system\hotel_app.py` 起動。
- Windows 実機検証：`.venv` Python 3.13.14 / `pip install` OK / 依存 import OK / `hotel_app` import 解決 OK（v1.3.0）。GUI mainloop の実起動は実運用データ・ネットワークに触れうるため未実施（ユーザーがダブルクリックで確認）。
- `check_standards.py` 再実行：NDS の RUN_DEV 警告が解消（WARN 7 → 6）。
- 既存の「夕食料飲システムを起動.bat」は変更せず併存。アプリ本体・EXEビルド・配布・本番/共有には触れず。
- 結論：テンプレートは実アプリへ無改変で適用でき、標準化が機能した。

### 追記（NDS 起動時副作用の確認）

- ユーザー要請で、GUI 起動を手動ダブルクリックに移す前に `hotel_app.py` の起動時副作用を確認。
- 静的解析：実運用設定の書き換え・保存データ更新・ネットワーク/Google Sheets・印刷・共有フォルダ書き込みは **いずれも起動時には発生しない**（すべてアクション handler 経由）。唯一 `__init__` L552 の `audit_event("app_start")` がローカルの `dinner_system/保存データ/operation_audit_*.jsonl`（gitignore 対象・追記専用）へ1行書く。
- サンドボックス実起動（`dinner_system/` を一時コピー、socket 全ブロック、3.5秒自動クローズ）：ウィンドウ生成 True（`next-day-setup v1.3.0` / 1180x720）、mainloop 正常終了、ネットワーク接続試行 NONE、生成物は `*.pyc` と監査ログ1行のみ、正式ソース未変更。
- 検証スクリプトはスクラッチパッドの `verify_nds_gui_boot.py`。汎用化してテンプレートへ入れる価値あり（保留）。
- 結論：GUI 実起動確認は完了。PR #2 に全結果をコメント済み。merge 判断はユーザー。

### 追記（RUN_DEV.cmd の end-to-end 実機確認）

- ユーザー要請で `RUN_DEV.cmd` 一本通しを確認。一時 clone（短いパス）＋ socket ブロック shim（app 実行時のみ）＋ GUI 6秒自動クローズで、`cmd.exe /c RUN_DEV.cmd`（実ダブルクリック相当）を実行。
- 検出したバグ（`.cmd` 一般）：(1) 非 ASCII コメントを `cmd` が実行しようとする（日本語コメント不可）(2) `if (...)` ブロック内 `echo` の `(` `)` が早期にブロックを閉じ `... was unexpected at this time.` (3) `python -c "import a, b"` のカンマを cmd が誤分割。加えて (4) 深いパスで `python -m venv` の ensurepip が失敗（MAX_PATH）。
- 対応：NDS `RUN_DEV.cmd` を ASCII・`;` 区切り・括弧なし・CRLF へ修正。テンプレートの `.cmd` / `.ps1` も同様に修正。両リポジトリに `.gitattributes`（`*.cmd eol=crlf`）追加。`LESSONS_LEARNED.md` に記録。
- 修正後の結果（exit 0）：`RUN_DEV.cmd` → `py -3 -m venv .venv` 作成 → `pip install -r requirements.txt`（12パッケージ成功）→ `.venv` python で `dinner_system\hotel_app.py` 起動 → `next-day-setup v1.3.0` → **Tk ウィンドウ生成（1180x720、title 一致）** → ネットワーク試行 NONE → 6秒後に自動クローズ → 正常終了。
- 副作用：一時 clone 内のみ（`.venv/` と gitignore 対象の監査ログ1行）。正式ソース `next-day-setup` は未変更。
- 結論：**NDS パイロット成功**。RUN_DEV.cmd から開発版 GUI までの一本通しを実機確認。

### 追記（PR #2 merge）

- `next-day-setup#2` を squash merge（`277aa69`）、ブランチ削除。正式ローカルを `main` へ戻して pull 済み。`RUN_DEV.cmd` と `.gitattributes` が main に入った。NDS パイロット完了。

### 追記（food-cost へ RUN_DEV.cmd 展開）

- `food-cost-calculation-system` にブランチ `claude/standardize-run-dev`、PR `#1`（base は `codex/bootstrap-invoice-reading` = このリポジトリの既定ブランチ、`main` は無い）。
- `RUN_DEV.cmd`（`import PySide6` チェック、`PYTHONPATH=src` で `python -m food_cost_app.main %*`）＋ `.gitattributes` を追加。`起動.bat` / `run_app.ps1` は変更せず併存。
- end-to-end 実機確認（一時 clone、`cmd.exe /c RUN_DEV.cmd --screenshot`）：venv 作成 → `pip install`（17パッケージ、PySide6 6.11.2 ほか）→ `python -m food_cost_app.main` 起動 → `QApplication` + DB 初期化 + `create_window()` + `window.show()` → **ウィンドウを PNG 取得（60,726 bytes）** → exit 0。
- 実運用データ隔離：`FOOD_COST_DATA_DIR` を一時ディレクトリへ向けて実行。実 DB（`%LOCALAPPDATA%\FoodCostCalculation\food_cost.db`）は **SHA-256 完全一致・mtime 不変**（`765def13…` / 3,268,608 bytes）。正式ソース未変更。一時ディレクトリ削除済み。
- `check_standards.py`：food-cost の RUN_DEV 警告が解消（WARN 6 → 5）。
- 判明した追加知見：`main.py` の既定 DB は `%LOCALAPPDATA%\FoodCostCalculation\food_cost.db`（`FOOD_COST_DATA_DIR` / `--data-dir` で上書き可）。GUI 検証では `--screenshot` フラグが event loop なしで描画→保存→exit する。fresh venv の PySide6 一式導入は約250MB・数分かかる。

### 追記（food-cost 依存チェック拡張＋merge）

- 依存チェックを直接依存すべてへ拡張（`import PySide6; import cv2; import PIL; import pytesseract; import flask; import qrcode`、`;` 区切り、`9894190`）。
- 再検証（一時 clone、`cmd.exe /c RUN_DEV.cmd --screenshot`）：(B) cold で venv 作成→`pip install`(18)→screenshot 60,726B→exit 0。(A) PySide6 等はあるが qrcode だけ欠落 → **依存不足を検知して `pip install` に入り** qrcode のみ導入→screenshot→exit 0。実 DB は両シナリオ SHA-256／mtime_ns 不変。
- PR `food-cost-calculation-system#1` を squash merge（`8008fb7`、`codex/bootstrap-invoice-reading` へ）、ブランチ削除。正式ローカルを `codex/bootstrap-invoice-reading` へ戻して pull 済み。

### 追記（inventory-reconciliation へ RUN_DEV.cmd 展開）

- ブランチ `claude/standardize-run-dev`、PR `#1`（base `main`）。`RUN_DEV.cmd`（`import openpyxl` チェック、`python room_inventory_reconcile.py %*`）＋ `.gitattributes`。
- 副作用調査：`room_inventory_reconcile.py` は引数なしで `gui()`（Tk）を開く操作者主導ツール。`--auto-run` が夜間バッチ（手間いらず/JTB取得・突合・Excel・メール送信）。全パスが `BASE_DIR` 相対、資格情報は `%LOCALAPPDATA%\SalesInventoryCheckTool\credentials.json`。
- end-to-end 実機確認（一時 clone、`cmd.exe /c RUN_DEV.cmd`）：
  - `--help`：venv 作成 → `pip install`（openpyxl + et-xmlfile）→ 全 import 解決 → argparse usage → exit 0。
  - 引数なし → `gui()`：Tk ウィンドウ生成（`販売在庫チェックシステム …` / 620x500）→ socket 全ブロック下でネットワーク試行 NONE → 5秒自動クローズ → exit 0。`LOCALAPPDATA` を一時ディレクトリへ隔離、実 `credentials.json` は SHA-256／mtime_ns 不変。
- `check_standards.py`：WARN 5 → 4。

### 追記（inventory-reconciliation PR #1 merged）

- `inventory-reconciliation-system#1` を squash merge（`1ca3793` → `main`）、ブランチ削除。正式ローカルを `main` へ戻して pull 済み。RUN_DEV.cmd は「開発時の対話 GUI 起動経路」として扱い、`--auto-run` / 夜間バッチは既存 bat のまま（ユーザー確認済みの構成）。
- Windows 系3リポジトリ（NDS / food-cost / inventory-reconciliation）へ RUN_DEV.cmd 展開・merge 完了。

### 追記（qr-supply / 小掃除 / 最終 WARN）

- **qr-supply-ordering-system**：`origin/main` はスケルトン `3e800f8` のみで、実装大半は正式ローカルの**未コミット変更**（GitHub 未反映、約31エントリ）。ローカル作業を汚さないよう `origin/main` からの新規 clone で作業。
  - ブランチ `claude/standardize-run-dev`、PR `#1`（base `main`）。`RUN_DEV.cmd`（`import flask` → `python run.py %*`）＋ `DEPLOY.md`（社内 LAN 1ホスト構成の手順集約、新ランタイム追加なし）＋ `.gitattributes`。
  - end-to-end（新規 clone、`cmd.exe /c RUN_DEV.cmd`）：venv → `pip install`（Flask 3.1.1 + pytest + 依存11）→ `python run.py` → Flask 構築、全ルート解決、**GET / → 200 / GET /health → 200**、socket バインドせず接続試行 NONE、DB は clone 内へ隔離、exit 0（cold/warm）。
  - 正式ローカルの WIP は未変更（31エントリのまま）。
- **next-day-setup master_settings.json**：調査の結果、既に `.gitignore` 済み＋ `dinner_system/master_settings.example.json`（tracked）が存在 → 対応不要。`check_standards.py` の誤検知だったため、`check_secrets` を gitignore 済みファイルはスキップするよう修正。
- **development-management README**：`管理対象プロジェクト` 表に `menu-sheet-generator` を追記。
- **最終 `check_standards.py`：ERROR 0 / WARN 2**（どちらも qr-supply の RUN_DEV / DEPLOY。PR #1 merge ＋ ローカル pull で解消）。
  - 解消済み：NDS / food-cost / inventory-reconciliation の RUN_DEV、next-day-setup の master_settings（誤検知修正）、menu-sheet-generator 参照漏れ。

### 追記（qr-supply の GitHub/ローカルズレ解消）

- **原因**：`origin/main` はスケルトン `3e800f8` のみ。実アプリ（Phase 1 / 1.5 / 発注表取込）は正式ローカルの未コミット31エントリだった。
- **混入監査**（commit 前）：秘密情報・`config/settings.py`（実ファイル無し）・DB・認証情報・キャッシュ・実運用データ・自動生成物 いずれも**なし**。`config/settings.example.py` はダミー値のみ。`.venv` / `__pycache__` / `*.sqlite3` / `backups/` は `.gitignore` 済みで staging 対象外。
- **保存**：ブランチ `feature/phase1-implementation`（`a07ff49`）へ commit + push。GitHub から実アプリを再現可能に。
- **combined 検証**：`feature/phase1-implementation` を clone → `claude/standardize-run-dev` を merge（衝突なし、3ファイル追加）→ `cmd.exe /c RUN_DEV.cmd`：venv → `pip install`（Flask + pytest + qrcode + openpyxl）→ `python run.py` で **Flask 開発サーバ起動** → **GET / 200（3,989B）／GET /health 200（16B）** → DB は `ensure_database()` が clone 内へ自動作成 → サーバ停止・残プロセス0。
- **DEPLOY.md 修正**（`9f663c5`）：実装と不一致だった点を反映（`config/settings.py` 読込機構は未実装、設定はコード既定値＋`QR_BASE_URL` 環境変数、`settings.example.py` は将来想定、DB 初回自動作成、WSGI 未導入）。
- PR #1（`claude/standardize-run-dev`、base `main`）にコメントで全結果を記録。

### 追記（qr-supply merge 完了・開発環境整備 一巡完了）

- 案Aで実施。履歴上、アプリ実装と標準化を別変更として分離：
  - `qr-supply-ordering-system#2`：`feature/phase1-implementation` → `main`（squash `1b3879e`）。マージ前に clone で `compileall` OK ／ `pytest 18 passed` を確認。実アプリが正式 `main` に。
  - `qr-supply-ordering-system#1`：`claude/standardize-run-dev` → `main`（squash `eb2068a`）。マージ前に「差分は `RUN_DEV.cmd` / `DEPLOY.md` / `.gitattributes` の3ファイルのみ」「新 `main`（実アプリ入り）へローカル test-merge が衝突なし」を確認。
  - qr-supply `main` 履歴：`3e800f8`（skeleton）→ `1b3879e`（Phase 1/1.5 実装 #2）→ `eb2068a`（開発環境標準化 #1）。
- 正式ローカルを `main` に戻して pull。作業ブランチ（remote / local とも）削除。
- **最終 `check_standards.py`：`OK: 指摘なし`（ERROR 0 / WARN 0）**。9リポジトリすべて標準充足。

### 開発環境整備 一巡完了（2026-09-04）

- 同期規約・能力ベース担当判定（`CAPABILITIES.md`）
- `templates/windows-python-app/`（ASCII+CRLF+括弧なし+`;`区切りの `.cmd` 標準、`beverage/python_app/` 由来）
- `scripts/check_standards.py`（種別対応・サブディレクトリ対応・gitignore スキップ、`repo_types.toml` を種別の唯一の正）
- `RUN_DEV.cmd` 展開：NDS / food-cost / inventory-reconciliation（desktop）、qr-supply（web、`DEPLOY.md` も）。各リポジトリで一時 clone の `cmd.exe /c RUN_DEV.cmd` end-to-end 実機確認（venv→依存→起動→GUI/HTTP→正常終了、実データ不変）を実施。beverage は既存で充足、kitchen-calendar は archived。
- GitHub/正式ローカルのズレ解消：development-management（`4293c5e`）、qr-supply（`feature/phase1-implementation` 経由で実装を GitHub へ）。

### 追記（CI 化 — 共通アクション ＋ next-day-setup パイロット、2026-09-04）

- **前提**：`development-management` は public、アプリ9個は private。public リポジトリの composite action は private からも PAT なしで `uses:` 参照でき、GitHub がアクションリポジトリを自動チェックアウトする。→ ロジックを各アプリへ複製せず、`check_standards.py` / `repo_types.toml` は development-management 側のものだけを使える。
- **development-management 側**：`.github/actions/check-standards/action.yml`（composite、`--repo` で単一リポジトリを点検、既定 warning-only）、`.github/workflows/standards-self.yml`（dogfood、`OK: 指摘なし` 成功）、`templates/ci/standards.yml`（各アプリ用の最小 caller）。
- **パイロット（next-day-setup、PR #3 `30f85cb`、`.github/workflows/standards.yml` 1ファイルのみ）**：
  1. push / PR で起動：両方 `completed success`
  2. 標準準拠時は成功：`OK: 指摘なし`
  3. 意図的な違反を検出：RUN_DEV.cmd を一時削除した commit で `[WARN] next-day-setup: [desktop] RUN_DEV.cmd 相当 が無い / ERROR 0 / WARN 1` をログ出力（検証後 reset）
  4. warning-only：違反 run も `conclusion=success`、push/PR をブロックしない
  5. 長期トークン不要：workflow に `secrets.*` なし、`Download action repository '4m9ccm98gt-rgb/development-management@main'` が自動・認証エラーなし
- パイロット成功。

### 追記（CI 全展開完了、2026-09-04）

- パイロット成功後、残り6リポジトリへ同一 `standards.yml` を展開・merge：
  `inventory-reconciliation-system#2`(`0d3a00f`) / `qr-supply-ordering-system#3`(`02bfae4`) /
  `menu-sheet-generator#2`(`a5ec884`) / `call-reception-assistant#1`(`805243b`) /
  `food-cost-calculation-system#2`(`3f83fdc`、base `codex/bootstrap-invoice-reading`) /
  `beverage-inventory-ordering-system#3`（base `main`）。
- 全6リポジトリで push / pull_request の CI が `completed / success`。各ログで
  `Download action repository '4m9ccm98gt-rgb/development-management@main'` が自動・
  認証エラーなし。`OK: 指摘なし`（menu-sheet-generator は .NET アプリで Python の
  app root 無し → 点検項目なし、call-reception はアプリ未実装で同様）。
- `kitchen-calendar` は archived のため CI 対象外（`check_standards.py` も早期 return）。
- 正式ローカルは各々の作業ブランチへ復帰、作業用 `claude/ci-standards` は全削除。
- **CI 化完了**：development-management（public）の共通 composite action を、8アプリ
  （private）＋ dogfood が warning-only で参照。ロジック複製なし・長期トークンなし。

### 追記（退役前整備 H3: 共通 Action を @ci-v1 固定）

- 既存タグ `v1.0.0` は知識ベースの版。CI アクションは別系統 `ci-` 接頭辞にする。
- `docs/ci_action_versioning.md` 追加（@main 不可の理由、`ci-v1` / `ci-v1.0.0` の意味、更新手順：main → dogfood → パイロット → 成功確認 → `ci-v1` 移動）。`templates/ci/standards.yml` を `@ci-v1` に。
- `development-management` main `c42b423` に annotated タグ `ci-v1.0.0`（不変）と `ci-v1`（移動用）を作成・push。直前に dogfood CI `success` を確認。
- 全7アプリ + テンプレートの caller を `@main` → `@ci-v1` へ（user 指定の順：NDS でパイロット `#4` → CI が `Download action repository '...@ci-v1' (SHA:c42b423)` で緑を確認 → 残り6を展開・merge）。全 CI `completed/success`。
- 最終確認：全7 repo + template が `check-standards@ci-v1`。`@main` 参照はゼロ。dogfood はローカルパス参照のまま。
- 効果：`development-management` main への push が全リポジトリ CI へ即波及する事故半径を解消。

### 追記（退役前整備 H1 完全完了 + H3 済）

- **H1**：Git 管理外データ16項目を棚卸し（`docs/git_external_data_inventory.md`、値は非記録）。従来 俺伝DB・認証情報・NDS DB にバックアップ無し、既存は同一ディスク。
  - `scripts/BACKUP_DEV_DATA.ps1` + `_CLICK_ME.cmd`（読み取り専用、SQLite Backup API、MANIFEST/RESTORE 付き）+ `docs/backup_restore.md` 作成。
  - **実バックアップ初回作成**：`%USERPROFILE%\DevDataBackups\` と `E:\DevDataBackups\`（別物理ディスクの外付けUSB HDD）。
  - 全検証合格：SQLite 3件 integrity_check ok・行数一致、JSON 229件 valid・破損0、逐次コピー分は SHA-256 一致、**元データ12件は前後で SHA/サイズ/mtime 不変**、E: コピーはファイルリスト+MANIFEST 一致。
  - 機密確認：Git 管理外・OneDrive 外・ACL は SYSTEM/Administrators/本人のみ。E: は常時マウントのため真のオフラインは物理取り外しが必要と明記。
- **H3**：共通 Action を `@ci-v1` タグ固定（別途記載）。

### 追記（H4 完了・H2 #1-#4 完了・ci-v1.0.1）

- **H4 DEV_DOCTOR**：`scripts/DEV_DOCTOR.ps1` + `_CLICK_ME.cmd`（読み取り専用、ASCII/CRLF）。toolchain / 正規 repo の branch・sync・dirty・venv・入口 / バックアップ鮮度・E: / ディスク / 正規パス外 clone の発見。OK/WARN/ERROR + Summary。全文を `%USERPROFILE%\DEV_DOCTOR_report.txt` へ UTF-8(BOM) 保存（ChatGPT へ貼れる）。実機実行済み（OK 7/WARN 11/ERROR 0）。`docs/dev_doctor.md`。
- **H2 #1**：`開発環境整備プロジェクト` の未 push 编集15件を分類・救出。`recovery/from-old-clone-docs`（Draft PR `development-management#1`）に BUSINESS_MODEL.md・projects 2件・フェーズ規律・未反映5設計判断を追記。canonical 上書きなし。`docs/recovery_from_old_clone.md`。
- **H2 #2**：`kichen-calendar` は NDS `dinner_system/kitchen_calendar/` へ統合済み・superseded。固有差分なし（旧固有モジュールは統合時に置換されたスタンドアロン配線）。保管。
- **H2 #3**：`ChatGPT\food-cost-calculation-system` は初期作業コピー・obsolete。公式 `src/` に全ファイル存在・全て小さいか一致。固有差分なし。保管。
- **H2 #4**：`hospitality-review-reply` を管理対象へ。`knowledge` 種別を新設（`repo_types.toml` + `check_standards.py`）＝実行・ビルド標準は課さず秘密チェックのみ。正規パスへ clone、CI 追加（PR `#1` merge `f6e1e74`）、README 明記、DEV_DOCTOR 対象へ追加。
- **ci-v1 → ci-v1.0.1**：`knowledge` 種別を CI へ反映。dogfood green → hospitality CI で `@ci-v1` が新 SHA を解決し `OK` 確認 → `ci-v1` 移動。`docs/ci_action_versioning.md` 更新。
- 旧 clone はいずれも**削除せず保管**（`docs/pc_repo_audit.md` に結果記録）。

### 退役前整備の残り（H6, H7, H5, M1〜M3）

- H2 PC 全体 clone/repo 監査と GitHub 突合（削除しない・未 push 作業は要確認）
- H1 Git 管理外データのバックアップ・復元検証（隔離環境、値は記録しない）
- H4 DEV_DOCTOR（ダブルクリック実行、結果を ChatGPT に貼れる）
- H6 オペレーター用ランブック
- H7 BUILD / DEPLOY の非本番実地検証
- H5 引き継ぎドライラン（このチャットの記憶なしで development-management だけから再開できるか）
- M1 新 PC ブートストラップ script / M2 gh 認証寿命 / M3 food-cost の既定ブランチ依存監査

### Git状態（2026-09-04 時点）

- `development-management` `main`：能力契約・テンプレート・checker・CI アクションまで push 済み（`4dcd757` 他）。`check_standards.py` は 9 リポジトリで ERROR 0 / WARN 0。
- 各アプリ：NDS / food-cost / inventory-reconciliation / qr-supply に RUN_DEV.cmd merge 済み。NDS に CI workflow merge 済み（PR #3）。

## 2026-07-20

### 今日の目的

- `next-day-setup` のケーキ発注書を休館前に欠落なく前倒し印刷できるようにする。

### 実施したこと

- 対象プロジェクト: `next-day-setup`
- 作業内容: 休館日取得・キャッシュ、休館前日／連続休館の対象業務日列挙、受取日別バッチ印刷、4日固定、異常時の通常分限定実行、README・テスト更新。
- 追加作業: 受取日を直接指定するケーキ手動印刷ボタン、業務日／受取日の確認表示、既存単日処理の再利用、注文なし表示を追加。
- 変更ファイル: `shift_holidays.py`、ケーキ生成／印刷／画面連携、設定例、README、関連テスト・文書。
- 対象プロジェクト: `beverage-inventory-ordering-system`
- 作業内容: 単体タスクで開発していた飲料発注システムを `apps/ordering/` へ移管し、飲料在庫管理システムから起動するサブシステムとして登録。
- 変更ファイル: `apps/ordering/`、`README.md`、`docs/inventory-system.md`、`docs/ordering-system.md`、`docs/inventory-ai-handoff.md`、`index.html`、`.gitignore`、development-management の管理文書。

### 確認結果

- 構文確認: 成功
- テスト: 38件成功
- 公開CSV: 取得・解析成功（35日、2026-07-07～2027-03-31）
- 飲料発注システム移管: JavaScript構文確認、静的ファイル存在確認、Git差分確認済み。発注システムは開発中。
- 手動起動: 未実施
- 実運用確認: 未実施（実Excel／プリンターへの出力なし）

### 決定事項

- [ケーキ発注書は業務日範囲で休館日前倒しする](docs/decisions.md#ケーキ発注書は業務日範囲で休館日前倒しする)
- [飲料発注システムは在庫管理リポジトリ内のサブシステムにする](docs/decisions.md#飲料発注システムは在庫管理リポジトリ内のサブシステムにする)

### 未確認・問題

- 実プリンターの連続印刷順、画面警告、EXE・共有版での動作は未確認。
- 飲料発注システムは開発中。在庫管理側の商品マスタ・発注履歴とは未統合。
- 対象リポジトリには今回以前から多数の未コミット変更がある。

### 次にやること

1. ユーザー確認後、実運用相当データと実Excel／プリンターで確認する。

### Git状態

- ブランチ: `main`
- コミット: なし
- push: なし
- タグ: なし

## YYYY-MM-DD

### 今日の目的

-

### 実施したこと

- 対象プロジェクト:
- 作業内容:
- 変更ファイル:

### 確認結果

- 構文確認:
- テスト:
- 手動起動:
- 実運用確認:

### 決定事項

- なし／`docs/decisions.md` の該当項目へのリンク

### 未確認・問題

-

### 次にやること

1.

### Git状態

- ブランチ:
- コミット:
- push:
- タグ:

## 2026-09-04（続き2）退役前整備 H4修正 / recovery補正 / H6

### H4 DEV_DOCTOR 修正（ChatGPT レビュー #4）

- 指摘を4段階に：`[ERROR]`（要修正）/`[ACTION]`（要対応）/`[INTENTIONAL]`（現在意図的）/`[INFO]`（許容・参考）。
- `$ActiveBranch`（beverage=python-desktop-migration）と `$Archived` を導入。意図的な作業ブランチは ACTION でなく INTENTIONAL。
- 未コミットを「追跡変更あり=ACTION／未追跡のみ=INFO」に分離。venv 未作成・E: 未接続・archived の状態=INFO。
- Summary は ERROR→ACTION の順。実行例: ERROR 0 / ACTION 2 / INTENTIONAL 1 / INFO 28。`docs/dev_doctor.md` 反映。

### recovery/from-old-clone-docs 補正（ChatGPT レビュー #1-#3、PR は Draft 維持）

- #1 フェーズ規律：旧 clone 版は「各フェーズ移行に明示依頼が必要」と厳しすぎた。canonical L251/L308 に合わせ「フェーズを限定された場合は境界厳守／最終成果まで依頼された場合は依頼範囲内で調査→設計→実装→検証を連続」へ書き換え。`AI_OPERATING_MANUAL.md` / `AI_CHECKLIST.md` / `PROMPT_PRINCIPLES.md`。仮説を事実にしない・安全な作業を戻さない原則は維持。`DEVELOPMENT_RULES` / `AI_MEMORY` と整合確認。
- #2 `projects/food-cost` / `qr-supply`：古い状態のまま取り込まず、現在の既定ブランチ・実装状態・commit/push・フェーズ・未確認事項へ書き直し。当時の記述は「経緯（参考）」節に分離。
- #3 `BUSINESS_MODEL.md`：冒頭に「共通のチェック観点・参考モデル。適合しなければ個別要件優先。共通化を目的化しない」位置づけを明記。
- `recovery/from-old-clone-docs` を origin/main へ rebase 済み（recovery 追加分のみを含む）。**Draft のまま維持、merge しない。**

### H6 オペレーター用ランブック

- `docs/operator_runbook.md`：非コーダー向け。毎週やること（バックアップ / DEV_DOCTOR）、各システムのダブルクリック操作一覧、困ったとき ChatGPT に貼るもの、やってはいけないこと、用語ミニ辞典。README にリンク集追加。

### H1 実バックアップ（既実施の再確認）

- `C:\Users\suisy\DevDataBackups\devdata-20260904-180931` と `E:\...` 実在。MANIFEST 57KB・integrity_check 3件。commit `0a1a514` で記録済み。**H1 は実施・検証済み。**

### 退役前整備の残り

- ~~H7 BUILD / DEPLOY の非本番実地検証~~ → 続き3で完了
- ~~H5 引き継ぎドライラン~~ → 続き3で完了
- M1 新 PC ブートストラップ script / M2 gh 認証寿命 / M3 food-cost の既定ブランチ依存監査

## 2026-09-04（続き3）退役前整備 H7 / beverage ACTION 解消

### H7 BUILD / DEPLOY / UPDATE の非本番実地検証 → 完了

- 記録: `docs/build_deploy_paths.md`（一目表 + 実行ログ + fail-safe まとめ + 既知ギャップ）。
- 実共有フォルダ・実 HDD・本番タスクスケジューラは不変更。実 `E:\FoodCostCalculation\`（512 ファイル）は
  size+mtime を検証前後で照合し完全一致。ネットワーク共有は `-TargetPath` に一時パスを渡したため未参照。
- 経路が実際に通ったもの（成果物 SHA-256 が一時配布先で一致）:
  - **俺伝** `1940db0`：`build_release.ps1 -DryRun -OutputRoot <一時>` → `BUILD_INFO.txt` に HEAD SHA + EXE SHA-256、
    検証ゲート（pytest 253 passed）通過 → `update_hdd.ps1 -DryRun -HddRoot <一時>` で `Assert-TreesEqual` 通過。
  - **NDS** `1b048f4`：`build_exe.py` 実ビルド（6,383,041 bytes / `0da441a2…`）→
    `update_shared_folder.ps1 -TargetPath <一時>`。運用 5 ファイル SHA 前後一致、target-only `_internal` ファイル保持。
  - **beverage** `04c3797`：`BUILD_EXE_CLICK_ME.cmd` 実ビルド（1,957,425 bytes / `ec30a6ae…`）→
    `update_shared_folder.ps1 -TargetPath <一時>`。`data\` 2 ファイル SHA 前後一致。
  - **menu-sheet** `fa4fdf7`：`BUILD_RELEASE.cmd`（dotnet publish、0 warn/0 error）→ `UPDATE.cmd "<一時>"`。
    4 ファイル SHA 一致、`menu-config.json` 等の運用ファイルは不変更。
- 静的確認のみ（要件どおり破壊的異常系・システム変更は強制しない）:
  - **inv-recon** `fd2de21`：`room_inventory_reconcile.py --help` 生存確認。`schtasks` 登録形を記録（登録はしない）。
  - **qr-supply** `790fff5`：`import run` 生存確認、`migrate-db` は加算型（`DROP`/`DELETE`/`TRUNCATE` なし）。
- 検証中の観測: cwd を repo ルート以外にして `build_release.ps1` を直接実行すると `pytest -q` が exit 5
  （no tests ran）→ 検証ゲートで停止。正式入口 `.cmd` は `cd /d "%~dp0"` するため問題なし。
- 既知ギャップ: NDS / menu-sheet は成果物に HEAD 情報を埋め込まない（俺伝の `BUILD_INFO.txt` 相当がない）。
  NDS はクリーンツリーも要求しない。→ `docs/decisions.md` に記録、次サイクルで検討。

### beverage ACTION（DEV_DOCTOR: behind 5）解消

- `origin/python-desktop-migration` へ **pure fast-forward**（`04c3797 → e458476`、5 コミット）。
  ローカル固有コミット 0・未コミット追跡変更 0・`git merge-base --is-ancestor` YES を確認してから実行。
- 現在 upstream と 0/0。ブランチは `python-desktop-migration` のまま（`$ActiveBranch` 変更不要）。
- H7 のビルド検証は `04c3797` 時点。FF 後の再ビルドで EXE SHA は変わるが経路の妥当性は不変。

### H5 引き継ぎドライラン → 完了

- development-management の入口（AI_STARTUP → PROJECT_STATUS → VERSION_MATRIX → REPOSITORIES →
  SYSTEM_OVERVIEW → docs/ai_handoff）をコールドスタート視点で読み直し、残ギャップを修正。
- 判明していた問題: 状態系文書が「2プロジェクト時代（2026-07）」のまま。新規セッションが
  (a) 俺伝・menu-sheet・qr-supply・kitchen-calendar・hospitality の存在を認識できない、
  (b) development-management が GitHub 未反映と誤認（VERSION_MATRIX の dev-mgmt 行が「初回コミット前」・
  作業場所が旧 clone パス）、(c) beverage の完了済み next-steps（HEAD 4f09fd9f / PR #2）を追いかける、
  (d) 退役前整備 H1〜H7 と DEV_DOCTOR / バックアップ / ランブックの存在に気づけない。
- 修正:
  - `PROJECT_STATUS.md`: 全面更新。管理対象10リポジトリ表（種別・既定ブランチ・現在地）、
    Current Focus、退役前整備 H1〜H7 の成果表、Claude Code 退役の背景、次タスク（H5/M1/M2/M3）。
  - `AI_STARTUP.md`: 確認順序に CAPABILITIES を第5へ、退役前整備の運用文書リンク集を追加。
    管理対象表を10行（種別・既定ブランチ・タグ）へ。俺伝の既定ブランチが `codex/bootstrap-invoice-reading`
    である旨を明記。`projects/` に文書が無いリポジトリの参照先を明記。
  - `VERSION_MATRIX.md`: 最終調査日 2026-09-04。dev-mgmt 行を実態（main `d45c0c9`・GitHub 同期済み）へ。
    next-day-setup / inventory-reconciliation / beverage / menu-sheet / call-reception の main コミットを現在値へ。
    food-cost（俺伝）/ qr-supply / kitchen-calendar / hospitality の行を新設。実運用版は全リポジトリ「未確認」で統一。
  - `REPOSITORIES.md`: 全面更新。10リポジトリ表（種別・既定ブランチ・HEAD・タグ）+ 旧 clone の扱い。
  - `SYSTEM_OVERVIEW.md`: 構成図と役割分担表を全アクティブリポジトリへ拡張。
  - `docs/ai_handoff.md`: 「管理対象は2つ」を10リポジトリへ。安定版・進行中作業を現在値へ。
  - `CHANGELOG.md`: v1.3.0（退役前整備 H1〜H7、beverage FF）を追加。
- 内部リンクの解決を確認。`docs/recovery_from_old_clone.md` は recovery ブランチのみに存在するため
  main 上の文書からは pc_repo_audit.md 経由で参照。

### 退役前整備の到達点

- H1〜H7 完了。残り M1（新PCブートストラップ）/ M2（gh 認証寿命）/ M3（俺伝の既定ブランチ依存監査）。

## 2026-09-04（続き4）M2 GitHub 認証の監査・再認証手順

### 実機確認（トークン値は記録しない）

- **`gh` CLI**: OAuth トークン `gho_`（`gh auth login` のブラウザフロー）。保存 = keyring
  （Windows 資格情報マネージャー `gh:github.com:4m9ccm98gt-rgb`）。scope = `gist, read:org, repo, workflow`。gh 2.97.0。
- **`git` push/pull**: `credential.helper=manager` = Git Credential Manager 2.9.0（system gitconfig）。
  保存 = 資格情報マネージャー `git:https://github.com`。GCM が自前で GitHub OAuth（アクセス+リフレッシュ）。
  全リモート HTTPS。`gh auth setup-git` は未実行 → **2系統は独立**。
- 期限日を表示する仕組みは両方に無い。失効条件は「OAuth アプリ連携取り消し / パスワード変更 /
  GitHub による無効化 / SSO 再認証要求」。
- 失効時の影響: gh 側 → `gh pr`/`gh run`/`gh api`/`gh workflow` が停止（`git push` と GitHub 上の CI は無事）。
  git(GCM) 側 → `git push`/`pull`/`fetch` が停止（ローカル commit と `gh` は無事）。

### 成果物

- `docs/github_auth.md` 新規: 構成・関係・失効条件・影響範囲・DEV_DOCTOR 検知・推奨。
- `docs/operator_runbook.md` §6 追加: 2系統の表 + `gh auth login` の4ステップ（開くもの/入力/ブラウザ/確認）
  + GCM 再ログイン（`git credential-manager github logout` → `git fetch` → `git ls-remote origin`）+
  資格情報マネージャーからの手動削除。§5 用語辞典に `gh` / GCM 追加。§3 の相談表に導線。
- `scripts/DEV_DOCTOR.ps1`: gh チェックを **終了コード + `X Failed`/invalid 行**で判定へ変更（従来は
  "Logged in" 文字列一致のみ＝失効を取りこぼす恐れ）。失効 = `[ERROR]`。
  さらに `git ls-remote`（private repo、プロンプト無効）で **git(GCM) 認証を実テスト**、失敗 = `[ACTION]`、
  オフライン等は `[INFO]`。ASCII のみ（メッセージは `operator_runbook.md section 6` を参照）。
- 検証: 通常実行で両方 `[OK]`。`GH_TOKEN` にダミー値を入れた実行で `[ERROR] gh auth failed` を確認。
- `docs/backup_restore.md` / `docs/dev_doctor.md` / `README.md` に相互リンク。

### 次にやること

- M3 俺伝の既定ブランチ依存監査。

## 2026-09-04（続き5）M3 俺伝の既定ブランチ依存監査

### 監査結果 → 判断 A（`main` へ移行）

- `docs/food_cost_default_branch.md` に全数監査（16 項目）+ 判断 + 非破壊・可逆の移行手順を記録。
- **機能依存は 1 件だけ**: `development-management/scripts/DEV_DOCTOR.ps1` の `$Canon`
  （`food-cost` → `branch = "codex/bootstrap-invoice-reading"`）。不一致なら誤 ACTION を出す。
- 影響なしを確認: food-cost の `standards.yml`（ブランチフィルタ無し）、`build_release.ps1`
  （`git branch --show-current` で動的取得、BUILD_INFO へ情報記録のみ）、`update_hdd.ps1`
  （BUILD_INFO の「Git branch」キーの存在のみ確認、値は不問）、他リポジトリの workflow（参照なし）、
  ブランチ保護（private + Pro 無しで機能自体が無効）、Open PR（0 件）。
- 文書参照: food-cost `AI_HANDOFF.md`、development-management の AI_STARTUP / PROJECT_STATUS /
  REPOSITORIES / VERSION_MATRIX / docs/ai_handoff / docs/build_deploy_paths。DAILY_LOG の過去分は据え置き。
- 外部参照は旧 clone（`ChatGPT\food-cost...`、`開発環境整備プロジェクト\...`）の文言のみ。機能依存なし。
- 判断 A の根拠: GitHub のブランチ改名はネイティブ・非破壊（履歴/SHA 保持、force push なし、
  リダイレクト自動、Open PR 自動張替え）で**可逆**。依存面積が小さく全把握済み。退役直前に
  「この repo だけ既定ブランチが違う」恒久リスクを消せる。

### 状態

- 監査・手順設計・検証は完了。GitHub 改名 API の自動実行はブロックされたため**ユーザー実行/承認待ち**。
  実行コマンドと後続手順は `docs/food_cost_default_branch.md`。実行後に DEV_DOCTOR `$Canon` と
  各文書を `main` へ更新し、DEV_DOCTOR / check_standards / `gh repo view` で検証する。

## 2026-09-04（続き6）M1 新 PC ブートストラップ

### 成果物

- `scripts/BOOTSTRAP_DEV_PC.ps1` + `scripts/BOOTSTRAP_DEV_PC_CLICK_ME.cmd`。
- 流れ: (1) git/Python/gh 存在確認（winget 案内、`-InstallMissing` で自動導入）→
  (2) GitHub 認証2系統確認（M2 のロジック流用）→ (3) canonical repos root 作成 →
  (4) `development-management` を clone し `repo_types.toml` から一覧取得（読めなければ組込みフォールバック）→
  (5) 不足リポジトリを clone。**既定ブランチは `git ls-remote --symref origin HEAD` で live 検出**
  （俺伝が `codex/...` でも M3 後の `main` でも正しい）→ (6) RUN_DEV 入口（beverage は `python_app\`、
  menu-sheet/.NET と call-reception は対象外）と `.venv` を報告（`-PrepareVenvs` で `requirements.txt` が
  あるものだけ venv 作成、アプリ起動しない）→ (7) Git 管理外データは復元せず `backup_restore.md` / `DEV_DOCTOR` へ誘導。
- **idempotent**: 既存 repo は `fetch --prune` のみで reset/merge しない。`-NoFetch` で完全に触れない。
- **fail-safe**: clone 先に非 git ディレクトリがあれば `[ERROR]` で拒否（上書きしない）。native git の
  stderr が PS の停止エラーにならないよう `Invoke-Git` ヘルパーで吸収。ASCII のみ / `.cmd` は CRLF。
- 検証（一時ディレクトリ `-ReposRoot <temp>` + `-Only`）: 実 clone 成功 / 再実行で「exists / fetched only,
  not merged / ahead 0 behind 0」/ 非 git 衝突で `stray.txt` を保持したまま `[ERROR]` / 俺伝の既定ブランチ
  `codex/bootstrap-invoice-reading` を検出 / type 別 RUN_DEV 期待も正しく分類。予備 PC が無いため
  完全な新品 Windows E2E（winget 導入・認証フロー）は未検証、それ以外の経路は実証済み。

### 退役前整備 まとめ

- H1〜H7 + M1〜M3 完了。**残るユーザー作業のみ**:
  1. ~~M3 の GitHub ブランチ改名~~ → **ユーザーが実行し完了**（下記「続き7」参照）。
  2. beverage PR #2: Draft のまま維持（触れていない）。別 Python 移行プロジェクトとして扱い、
     実プリンター・共有サーバー・2PC ゲート完了まで merge しない。
  3. recovery PR #1: 最新 main（`71fdc21`）へ rebase 済み（conflict は `docs/decisions.md` の末尾追記のみ、
     両者を残して解消）。`projects/food-cost` に M3 判断 A 反映、recovery 文書の #3 を取り消し線化。
     内部リンク解決・秘密情報なしを再確認。**Draft 解除 → Ready for review**。mergeable CLEAN。merge はユーザー。

## 2026-09-05（続き7）M3 実行完了 / recovery PR #1 merge / 退役前整備 完了

### M3: GitHub ブランチ改名の実行とローカル追従

- ユーザーが `gh api ... branches/codex/bootstrap-invoice-reading/rename -f new_name=main` を実行。
  `gh api repos/.../food-cost-calculation-system --jq .default_branch` で `main` を確認。
  GitHub 側の branches 一覧は `main` のみ（旧名は GitHub がリダイレクト）。
- 正式ローカル food-cost-calculation-system を追従:
  `git branch -m codex/bootstrap-invoice-reading main` → `git fetch origin --prune`
  （`origin/codex/bootstrap-invoice-reading` 追跡枝を自動削除、`origin/main` を新規取得）→
  `git branch -u origin/main main` → `git remote set-head origin -a`。
  検証: HEAD SHA `1940db031df7214f8ad087c6fd6c83492427a32b` は改名前後で**不変**（履歴の書き換えなし）、
  `git status` クリーン、ahead/behind `0/0`、`origin/HEAD` symref = `refs/heads/main`。
  `.git/config` に重複していた `[branch "main"]`（旧 `main` の残骸 + rename 後の追記による多重値）を
  `git config --unset-all` で統合。
- 機能依存の更新: `scripts/DEV_DOCTOR.ps1` の `$Canon` を `food-cost-calculation-system = "main"` へ。
- 文書更新（現状 = `main`、旧名は改名済みと分かる形で記載）: `AI_STARTUP.md` / `PROJECT_STATUS.md` /
  `REPOSITORIES.md` / `VERSION_MATRIX.md` / `docs/ai_handoff.md` / `README.md` / `food-cost/AI_HANDOFF.md`。
  `docs/build_deploy_paths.md` は H7 実施当時（改名前）の記録として旧名を残し、脚注で現状を明記
  （歴史的記録を書き換えない方針）。`scripts/BOOTSTRAP_DEV_PC.ps1` のコメントも更新。
  `DAILY_LOG.md` の当日以前のエントリは歴史的事実としてそのまま。
- `docs/food_cost_default_branch.md`: 監査本文（改名前の状況分析）はそのまま保持し、末尾の「状態」節を
  「完了（2026-09-04）」として全手順の実施結果を記録。
- 検証: `scripts/BOOTSTRAP_DEV_PC.ps1` の live 既定ブランチ検出（`git ls-remote --symref`、短パス
  `C:\tmp\m3verify` で実 clone）が `main` を正しく取得することを確認（ハードコードではなく検出のため
  ブランチ改名後もスクリプト変更不要だったことを実証）。
  `DEV_DOCTOR_CLICK_ME.cmd` → food-cost が `main`／`up-to-date`／`[OK]`（`[ACTION] unexpected branch` なし）。
  `scripts/check_standards.py`（全10リポジトリ）→ `OK: 指摘なし`。
  コミット `e0b73a0` で push 後、DEV_DOCTOR は **ERROR 0 / ACTION 0**。

### recovery PR #1: 再rebase・最終確認・merge

- main が `71fdc21` → `e0b73a0` へ進んだため、recovery/from-old-clone-docs を再度 `git rebase origin/main`
  （3 commits、**conflict なし**でクリーンに rebase）。
- `projects/food-cost-calculation-system.md` を「main 移行完了」の現状へ更新（既定ブランチ行・未確認事項）。
- 最終確認: (1) conflict なし（`mergeable: MERGEABLE`）、(2) 分岐9ファイルの内部リンクすべて解決、
  (3) 追加行に秘密情報・認証情報・実FAX番号・実業者名なし（設計文言としての言及のみ）、
  (4) 古い状態文書の混入なし（VERSION_MATRIX/REPOSITORIES旧テキストとCHANGELOG/DAILY_LOG/PROJECT_STATUSの
  ログ追記は最初から未収録）、(5) CI（`Dev standards (self, warning-only)`）が pull_request と push の
  両方で pass、(6) DEV_DOCTOR ERROR 0 / ACTION 0（俺伝 main 化後の状態で確認済み）。
- `gh pr merge 1 --squash --delete-branch` で merge（コミット `dd44366`）。リモートブランチ削除を確認。
  正式ローカルを `main` へ switch → ローカル `recovery/from-old-clone-docs` を削除 → `fetch --prune` →
  `pull --ff-only` で `dd44366` へ fast-forward。
- merge 後の最終確認: `check_standards.py` 全10リポジトリ `OK: 指摘なし`、`DEV_DOCTOR` **ERROR 0 / ACTION 0**。

### Claude Code 退役前整備 完了

**H1〜H7、M1〜M3 のすべてが完了。** 内訳は `PROJECT_STATUS.md` の「退役前整備 完了記録」表を正とする。

- H1 バックアップ・復元／H2 PC 全体監査／H3 CI 安定タグ／H4 DEV_DOCTOR／H5 引き継ぎドライラン／
  H6 オペレーターランブック／H7 BUILD・DEPLOY 実地検証／M1 新PCブートストラップ／
  M2 GitHub 認証監査・再設定手順／M3 俺伝の既定ブランチ main 化。
- 最終状態: `check_standards.py` 全10リポジトリ `OK: 指摘なし`。`DEV_DOCTOR` `ERROR 0 / ACTION 0`。
  development-management は `main` = `dd44366`。
- **残課題（退役前整備とは別の通常プロジェクト課題、`PROJECT_STATUS.md` の「次にやること」参照）**:
  beverage Draft PR #2 / #5（別プロジェクト、Draft のまま未着手）、俺伝の実データ精度・実HDD最終確認、
  qr-supply 既存発注表の業務確認、NDS/menu-sheet への `BUILD_INFO.txt` 追加検討（次サイクル）。
- 本セッションで development-management のコード・実運用データ・実共有フォルダ・実HDD・本番タスクは
  一切変更していない（H7 はすべて非本番の一時ターゲットで検証、M3 の GitHub 改名のみ本番設定変更だが
  非破壊・可逆でユーザー自身が実行）。
