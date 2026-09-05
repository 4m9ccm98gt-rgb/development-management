# Version Matrix

実運用中の版、GitHub上の版、ローカルの作業状態を混同しないための確認表です。

最終調査日: 2026-09-04（JST）。GitHub コミット値はこの日に `git log -1` で確認。

## 判定上の注意

- 「最新確認タグ」はローカル Git で確認できた最新タグであり、実運用中バージョンを保証しない。
- **実運用中バージョン・共有版・デモ機版は全リポジトリで「未確認」**。GitHub / 正式ローカルの
  一致は確認済みだが、現場で動いている版との突き合わせは未実施（オンサイトまたはユーザー確認が必要）。
- 「未確認」は推測で補わず、実機、共有版、本番環境または担当者への確認が必要な項目を示す。
- 2026-09-04 時点で全10リポジトリの GitHub と正式ローカルは同期（beverage は作業ブランチ
  `python-desktop-migration`、俺伝は同日 M3 で `codex/bootstrap-invoice-reading` から改名した `main` が基準）。
  詳細は [REPOSITORIES.md](REPOSITORIES.md) / [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## next-day-setup

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `next-day-setup` |
| 最新確認タグ | `v1.2.1` |
| mainの最新コミット | `1b048f4` — `CI: pin common action to @ci-v1 instead of @main (#4)`（2026-09-04） |
| 実運用中バージョン | 未確認 |
| デモ機版 | 未確認 |
| 共有版または本番版 | 未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\next-day-setup` |
| 使用Python | Python 3.13、リポジトリ直下の`.venv` |
| 主要依存関係 | `openpyxl 3.1.5`、`Pillow 12.2.0`、`PyInstaller 6.21.0` |
| 最終動作確認日 | 未確認 |
| 確認済み機能 | 未確認 |
| 未確認機能 | Google Sheetsシフト取得、席割・担当割、各種帳票、連続印刷、現場での追加印刷、EXE起動、共有版更新、業務データ保持、`_internal`完全同期 |
| GitHubと実運用版が一致しているか | 未確認 |
| 備考 | `main` に未コミット変更と未追跡ファイルがある。タグ以後の変更や未コミット変更が実運用版へ反映済みかは未確認。 |

## inventory-reconciliation-system

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `inventory-reconciliation-system` |
| 最新確認タグ | `v2.0.0` |
| mainの最新コミット | `fd2de21` — `CI: pin common action to @ci-v1 instead of @main (#3)`（2026-09-04） |
| 実運用中バージョン | 未確認 |
| デモ機版 | 未確認 |
| 共有版または本番版 | 未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\inventory-reconciliation-system` |
| 使用Python | Python 3.13、リポジトリ直下の`.venv` |
| 主要依存関係 | `openpyxl 3.1.5`。標準ライブラリや外部アプリケーションとの連携範囲は別途確認が必要。 |
| 最終動作確認日 | 未確認 |
| 確認済み機能 | 未確認 |
| 未確認機能 | Google Sheets休館日取得、キャッシュ正常系・異常系、在庫照合、手間いらず／JTB取得、PIN取得補助、夜間自動実行、Excel出力、警告メール |
| GitHubと実運用版が一致しているか | 未確認 |
| 備考 | `main` に未コミット変更と未追跡ファイルがある。タグ以後の変更や未コミット変更が実運用版へ反映済みかは未確認。 |

## beverage-inventory-ordering-system

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `beverage-inventory-ordering-system` |
| 最新確認タグ | なし |
| 既定ブランチ（移行作業） | `python-desktop-migration`（HEAD `e458476`、`origin/python-desktop-migration` と同期・behind/ahead 0） |
| `main` の最新コミット | `7af032d`（ブラウザ版仕様正本。Python 移行は作業ブランチ側で進行、Draft PR #2） |
| 実運用中バージョン | ブラウザローカル保存版が運用中。コミットによる版番号は未設定。配布先とのファイル一致は未確認 |
| デモ機版 | 未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system` |
| 使用環境 | ブラウザ版=`index.html`。移行版=Python 3.13 / PySide6、`python_app\.venv`、`python_app\RUN_DEV.cmd` |
| 確認済み機能（移行版） | 主要業務機能、実運用 JSON 互換、Windows ライト/ダーク、カレンダー履歴表示、操作フィードバック、発注中一覧の棚卸サイクル絞り込み、QDateEdit ホイール無効化まで Windows 実機確認。GitHub Actions 32 passed / 1 skipped（`e458476` 時点） |
| 未確認機能 | 最新 EXE の実機スポット確認、実プリンター、共有サーバーでの複数 PC 同時更新、飲料発注アプリ統合、実運用端末とのファイル一致 |
| GitHubと正式ローカルが一致しているか | 一致（作業ブランチ `python-desktop-migration` = `e458476`、Git status は未追跡のビルド生成物のみ） |
| 備考 | 3経路（RUN_DEV / BUILD_EXE_CLICK_ME / UPDATE_SHARED_FOLDER）の実績元。EXE は必要時のみユーザーが手動ビルド。本番共有版は確認完了まで更新しない。 |

## call-reception-assistant

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `call-reception-assistant` |
| 最新確認タグ | なし |
| mainの最新コミット | `ae78cf5` — `CI: pin common action to @ci-v1 instead of @main (#2)`（2026-09-04）。アプリ本体は未実装 |
| 実運用中バージョン | なし |
| デモ機版 | なし（無課金社内試作の設計前） |
| 共有版または本番版 | なし |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\call-reception-assistant` |
| 使用環境 | Windows PCを予定。技術構成は未決定 |
| 主要依存関係 | 未決定。外部AI API・有料APIは初期試作で使用しない |
| 最終動作確認日 | 未確認（アプリ本体なし） |
| 確認済み機能 | 対象なし。GitHub到達、空リポジトリclone、初期文書構成を確認 |
| 未確認機能 | 全機能。音声認識、音声合成、対話、外部連携はいずれも未実装 |
| GitHubと正式ローカルが一致しているか | 一致。`HEAD`、`main`、`origin/main`はいずれも`ae78cf5`、Git statusクリーン |
| 備考 | 電話回線、手間いらず・Hub実接続、実在庫変更、PMS自動入力は初期対象外。プロジェクト化完了、アプリ本体未実装 |

## menu-sheet-generator

| 区分 | バージョン / コミット | 状態 |
|---|---|---|
| GitHub版 | `v1.0.0` / `2376c216dfc6900a9e559da7f3804ae411d05f34` | Private、GitHub Release公開済み |
| 正式ローカル版 | `C:\Users\suisy\Documents\Development\repos\menu-sheet-generator` / 同上 | GitHub `main`・`v1.0.0`と同期、作業ツリーclean |
| 開発版 | 正式ローカル版の`main` / 同上 | v1.0.0正式版と同一 |
| `publish`配布版 | 自己完結型`win-x64` / 同上 | Releaseビルド・publish成功 |
| 共有フォルダ実運用版 | ワンクリック配布対応 | 実運用・実プリンター確認済み。タグ対象コミットとの配布一致は別途確認 |

- 正式リリース: `v1.0.0`（2026-07-23）。タグ対象コミット `2376c216dfc6900a9e559da7f3804ae411d05f34`。
- `main` の最新コミット（2026-09-04）: `fa4fdf7` — `CI: pin common action to @ci-v1 instead of @main (#3)`。
  タグ `v1.0.0` 以後の変更は CI 追加などの管理系。
- GitHub Release: `menu-sheet-generator v1.0.0`
- ビルド/配布: `BUILD_RELEASE.cmd`（`dotnet publish -r win-x64 --self-contained -o publish\`）→ `UPDATE.cmd [ターゲット]`。
- 確認済み機能: WPFお品書き印刷、日本語・英語・従業員用印刷、PMS CSV自動集計、宿泊日指定、泊目別印刷、部屋数自動集計、従業員確認用自動印刷、共有フォルダへのワンクリック配布、実運用データ保持。
- 実運用データと配布先実パスはGit管理外。

## development-management

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `development-management` |
| 最新確認タグ | `ci-v1`（moving）/ `ci-v1.0.0` / `ci-v1.0.1`（固定）。共通 CI アクション用であり文書版ではない |
| mainの最新コミット | `d45c0c9` — `退役前整備 H7: BUILD/DEPLOY/UPDATE 経路の非本番実地検証`（2026-09-04） |
| 実運用中バージョン | 対象外（開発知識を管理する文書＋スクリプトのリポジトリ） |
| デモ機版 | 対象外 |
| 共有版または本番版 | 対象外。GitHub `main` が正本 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\development-management`（git user `e2e`） |
| 使用言語 | Markdown 文書 + Python（stdlib、`scripts/check_standards.py`）+ PowerShell（`scripts/*.ps1`）|
| 主要依存関係 | なし（`check_standards.py` は stdlib のみ。PS スクリプトは Windows PowerShell 5.1 互換）|
| 確認済み機能 | 標準（CAPABILITIES / repo_types / templates / check_standards / DEV_DOCTOR / BACKUP_DEV_DATA）、CI 共通アクション（`@ci-v1`）、退役前整備 H1〜H7。別セッションからの引き継ぎは H5 で本文書群を現状化 |
| 未確認機能 | 新規セッションが本文書群だけで迷わず再開できるか（H5 の継続確認）、新 PC での初回 clone 後の利用性（M1）|
| GitHubと正式ローカルが一致しているか | 一致。`HEAD` = `main` = `origin/main` = `d45c0c9` |
| 備考 | 旧 clone `C:\Users\suisy\Documents\開発環境整備プロジェクト` は別物として保護（[pc_repo_audit.md](docs/pc_repo_audit.md)）。 |

## food-cost-calculation-system（俺伝）

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `food-cost-calculation-system` |
| 最新確認タグ | なし |
| 既定ブランチ | `main`。HEAD `1940db0`（2026-09-04）。同日 M3 の判断どおり `codex/bootstrap-invoice-reading` から GitHub ネイティブ改名（履歴・SHA 保持、旧名は GitHub 側でリダイレクト） |
| 実運用中バージョン | 実運用中。版番号未設定。`releases/俺伝-YYYY-MM-DD-HHMM/` に過去ビルド（`BUILD_INFO.txt` 付き）。最新は `俺伝-2026-09-02-1128`（Git SHA `cc476ca`） |
| 共有版または本番版 | 外付け HDD `E:\FoodCostCalculation\` 経由で配布（`WE-Elements` ボリューム）。配布先の版一致は未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\food-cost-calculation-system` |
| 使用環境 | Python 3.12（`.venv`）、PySide6、Nuitka standalone/onedir。ビルドは MSVC 必須 |
| ビルド/配布 | `BUILD_俺伝_CLICK_ME.cmd` → `tools/release/build_release.ps1`（未コミットで停止・`BUILD_INFO.txt` に HEAD SHA と EXE SHA-256）→ `UPDATE_HDD_CLICK_ME.cmd` → `tools/release/update_hdd.ps1` |
| 確認済み機能 | H7 で DryRun による BUILD→HDD 配布経路を非本番で実走破。検証ゲート（pytest 253 passed）通過。詳細 [docs/build_deploy_paths.md](docs/build_deploy_paths.md) |
| 未確認機能 | 実運用データとの突き合わせ、実 HDD 配布後の現場動作、請求書読み取りの実データ精度 |
| GitHubと正式ローカルが一致しているか | 一致（`main` = `1940db0`、Git status クリーン、正式ローカルは `codex/bootstrap-invoice-reading` から `git branch -m` で追従済み）|
| 備考 | 既定ブランチは 2026-09-04 に `codex/bootstrap-invoice-reading` → `main` へ改名済み（M3、[docs/food_cost_default_branch.md](docs/food_cost_default_branch.md)） |

## qr-supply-ordering-system

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `qr-supply-ordering-system` |
| 最新確認タグ | なし |
| mainの最新コミット | `790fff5` — `CI: pin common action to @ci-v1 instead of @main (#4)`（2026-09-04）|
| 実運用中バージョン | 未確認。社内 LAN の 1 ホストで Flask を常駐運用する構成（`DEPLOY.md`）|
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\qr-supply-ordering-system` |
| 使用環境 | Python 3.13（`.venv`）、Flask。`RUN_DEV.cmd` が `run.py` を `0.0.0.0:5000` で待受 |
| ビルド/配布 | ビルド成果物なし。ホストに repo を配置 → `RUN_DEV.cmd` を 1 回。DB は初回 `ensure_database()` で自動生成。スキーマ更新は `flask --app run:app migrate-db`（加算型・非破壊）|
| 確認済み機能 | `RUN_DEV.cmd` から開発サーバー起動をパイロットで確認。`import run` で app 生成・`migrate-db` 登録・非破壊性を H7 で確認 |
| 未確認機能 | 実ホストでの常時起動、複数端末からの発注、固定ホスト名運用、実印刷 QR |
| GitHubと正式ローカルが一致しているか | 一致（`main` = `790fff5`、Git status クリーン）|
| 備考 | DB とバックアップは Git 管理外。`scripts\backup_db.ps1`（SQLite Backup API）|

## kitchen-calendar

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `kitchen-calendar` |
| 種別 | **archived**（[scripts/repo_types.toml](scripts/repo_types.toml)）。next-day-setup へ統合済み。今後開発しない |
| `main` の最新コミット | `2362043`（2026-09-04）。正式ローカル clone は作業ブランチ `codex/a3-print-prototype` `4ac5955` にある |
| 備考 | 単体では使わない。機能は `next-day-setup/dinner_system/kitchen_calendar/` にあり NDS 側が上位互換（[docs/pc_repo_audit.md](docs/pc_repo_audit.md) #2）。`check_standards.py` / DEV_DOCTOR は点検対象外 |

## hospitality-review-reply

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `hospitality-review-reply` |
| 種別 | **knowledge**（テンプレート／知識 repo。アプリではない）|
| `main` の最新コミット | `f6e1e74` — `CI: add warning-only dev standards check (knowledge repo) (#1)`（2026-09-04）|
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\hospitality-review-reply`（旧 clone は `C:\Users\suisy\Documents\hospitality-review-reply`、behind のため正規パスへ新規 clone）|
| 確認済み機能 | `README.md` / `AI_HANDOFF.md` あり。tracked ファイルに秘密パターンなし。CI は warning-only |
| 備考 | `check_standards.py` は `knowledge` に実行・ビルド標準を課さず、秘密情報チェックのみ。[docs/pc_repo_audit.md](docs/pc_repo_audit.md) #4 |

## 更新手順

1. リリースまたは実運用確認時に、タグ、コミット、配布先の版を確認する。
2. 実機で確認した日付と機能だけを「確認済み」として記録する。
3. `PROJECT_STATUS.md`、対象の`projects/*.md`、`CHANGELOG.md`と同時に更新する。
4. 未コミット変更が配布されている場合は、タグではなくコミットまたは差分を特定してから記録する。
