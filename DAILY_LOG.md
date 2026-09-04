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

### 次にやること

1. `qr-supply-ordering-system`（web）を Web 用 RUN_DEV パターンとして対応。
2. `next-day-setup` の `master_settings.json` を example 化（実ファイルは触らず、サニタイズした `*.example.json` を追加）。
3. `development-management` README へ `menu-sheet-generator` 追記。
4. `check_standards.py` 再実行で最終 WARN を確認。
2. 確定後、`food-cost-calculation-system` / `inventory-reconciliation-system` / `qr-supply-ordering-system` へ同様に展開（qr-supply は web なので RUN_DEV は `run.py` 起動形＋デプロイ手順も別途）。
3. `next-day-setup` の実 `master_settings.json` を `*.example.*` 化。
4. `development-management` の README 等へ `menu-sheet-generator` を追記（`projects/menu-sheet-generator.md` 参照漏れ）。
5. `check_standards.py` を warning-only の CI チェックとして各リポジトリへ追加（CI から `development-management` を参照）。

### Git状態

- ブランチ: `main`
- コミット: `4293c5e`（ローカル同期）、`95ac83d`（Phase 0 契約レイヤー）、`d1805d7`（テンプレート再作成・checker サブディレクトリ対応）、本日さらに種別導入分を追加予定
- push: 実施
- タグ: なし

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
