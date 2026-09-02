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

### 次にやること

1. NDS パイロットをブランチで実施：`RUN_DEV.cmd` のみ追加（種別マーカーは置かない）、実機で `RUN_DEV.cmd` 起動確認、点検再実行。本番EXE・共有フォルダ・実運用には触れない。
2. パイロット結果を受けて `food-cost` / `inventory-reconciliation` / `qr-supply` へ展開する。
3. `check_standards.py` を warning-only の CI チェックとして各リポジトリへ追加する（CI から `development-management` を参照）。

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
