# プロジェクト状況

最終更新: 2026-09-05（JST）

## この時期の背景

- 開発補助ツール **Claude Code の提供終了が近い**。終了後も、ChatGPT（GitHub 側）と
  Codex／その他セッション（Windows 実機側）だけで各アプリの開発・ビルド・配布・復旧が
  回るように、**退役前整備（H1〜H7、M1〜M3）を実施し、2026-09-05 に完了した。**
  → 下記「退役前整備 完了記録（H1〜H7、M1〜M3）」節を参照。
- 担当判定は「ChatGPT / Codex / Claude Code」というエージェント名ではなく、そのセッションが
  実際に持つ**能力**で判定する（[CAPABILITIES.md](CAPABILITIES.md) が正本）。
- 非コーダーのユーザーが単独で日常運用できるよう、[docs/operator_runbook.md](docs/operator_runbook.md) を用意した。

## 管理対象リポジトリ（10）

種別の唯一の正は [scripts/repo_types.toml](scripts/repo_types.toml)。正式ソースは
すべて `C:\Users\suisy\Documents\Development\repos\<name>` 配下。

| リポジトリ | 種別 | 既定ブランチ | 現在地 |
|---|---|---|---|
| next-day-setup（翌日準備） | desktop | `main` | 実運用中。tag `v1.2.1`、main `614c985`。RUN_DEV / BUILD_EXE_CLICK_ME / UPDATE_SHARED_FOLDER 完備。2026-09-05 に pytest CI（windows-latest）・帳票ビルダー回帰テスト40件・`BUILD_INFO.txt` を追加（PR #5、[projects/next-day-setup.md](projects/next-day-setup.md)）。 |
| inventory-reconciliation-system（在庫突合） | service | `main` | 実運用中。tag `v2.0.0`、main `fd2de21`。夜間自動実行（`install_daily_inventory_task.bat` でタスク登録）。 |
| beverage-inventory-ordering-system（飲料在庫） | desktop | `main`（移行作業は `python-desktop-migration`） | Python/PySide6 版へ移行中。作業ブランチ `python-desktop-migration` は upstream と同期（`e458476`）。能力ベース運用の起点・3経路の実績元。 |
| food-cost-calculation-system（俺伝） | desktop | `main`（2026-09-04 M3 で `codex/bootstrap-invoice-reading` から改名済み。旧名は履歴として GitHub がリダイレクト） | 実運用中。HEAD `1940db0`（改名前後で同一 SHA、履歴の書き換えなし）。Nuitka ビルド + 外付け HDD 配布（`BUILD_俺伝_CLICK_ME.cmd` → `UPDATE_HDD_CLICK_ME.cmd`）。 |
| menu-sheet-generator（料理説明書、.NET） | desktop | `main` | 実運用中。tag `v1.0.0`、main `fa4fdf7`。`BUILD_RELEASE.cmd`（dotnet publish）→ `UPDATE.cmd`。 |
| qr-supply-ordering-system（QR 物品発注） | web | `main` | 社内 LAN の 1 ホストで Flask 常駐。main `790fff5`。`RUN_DEV.cmd` + 対象リポジトリの `DEPLOY.md`。 |
| call-reception-assistant（電話受付） | desktop | `main` | 初期管理文書のみ。**アプリ本体は未実装**。main `ae78cf5`。 |
| kitchen-calendar（調理場カレンダー） | archived | `main` | next-day-setup へ統合済み。**今後開発しない**（[docs/pc_repo_audit.md](docs/pc_repo_audit.md) #2）。 |
| hospitality-review-reply（口コミ返信） | knowledge | `main` | 旅館口コミ返信のテンプレート／知識 repo。アプリではない。main `f6e1e74`。CI は warning-only、実行・ビルド標準は課さない。 |
| development-management | （管理repo自身） | `main` | 本知識ベース。main `dd44366`、moving tag `ci-v1`。 |

## Current Focus

| リポジトリ | 現在の作業 |
|---|---|
| （全体） | **退役前整備 H1〜H7 + M1〜M3 完了（2026-09-05）。** development-management は開発補助ツール無しでも
  運用を再開できる状態。今後は各アプリの通常開発（beverage 移行、俺伝の実データ精度向上等）に戻る。 |
| beverage-inventory-ordering-system | `python-desktop-migration` は upstream と同期。並行して `feature/mobile-stocktake-sheets`（PR #5）で
  Google Sheets モバイル棚卸を開発中。**Draft PR #2 と #5 は今回の退役前整備とは別プロジェクトのため未着手・未マージ**
  （実プリンター・共有サーバー・2PC ゲート完了まで merge しない）。 |
| next-day-setup / inventory-reconciliation / menu-sheet-generator / 俺伝 / qr-supply | 実運用中。標準3経路（または相当）と CI（warning-only、`@ci-v1`）を整備済み。個別の機能追加は各 `projects/*.md` と対象リポジトリの状態で判断。 |
| call-reception-assistant | 設計前。無課金・ローカル完結・外部非接続の初期試作方針（[docs/decisions.md](docs/decisions.md)）。 |

## 退役前整備 完了記録（H1〜H7、M1〜M3、2026-09-04〜05）

Claude Code 退役前に、ChatGPT（GitHub 側）と Codex／その他セッション（Windows 実機側）だけで
開発・ビルド・配布・復旧・認証再設定・新PC構築が回る状態を整備した。**全項目完了。**

| 記号 | 内容 | 主な成果物 |
|---|---|---|
| H1 | Git 管理外データのバックアップ・復元 | `scripts/BACKUP_DEV_DATA.ps1` + `_CLICK_ME.cmd`、[docs/git_external_data_inventory.md](docs/git_external_data_inventory.md)、[docs/backup_restore.md](docs/backup_restore.md)。実バックアップ初回作成・全項目検証済み（`%USERPROFILE%\DevDataBackups\` と別物理ディスク `E:\DevDataBackups\`）。 |
| H2 | PC 全体の repo／clone 監査、旧 clone 比較 | [docs/pc_repo_audit.md](docs/pc_repo_audit.md)。旧 clone #1〜#4 の分類（救出済み／superseded／obsolete、いずれも削除せず保管）。hospitality-review-reply を knowledge 種別で管理対象へ追加（10リポジトリ体制）。 |
| H3 | 共通 CI アクションの安定タグ運用 | `ci-v1`（moving）/ `ci-v1.0.x`（固定）。[docs/ci_action_versioning.md](docs/ci_action_versioning.md)。各 repo の CI は `@ci-v1` を参照、warning-only。 |
| H4 | 実機ヘルスチェック | `scripts/DEV_DOCTOR.ps1` + `_CLICK_ME.cmd`、[docs/dev_doctor.md](docs/dev_doctor.md)。ERROR / ACTION / INTENTIONAL / INFO の4段階。 |
| H5 | 引き継ぎドライラン | development-management だけから作業再開できるかを検証し、「2プロジェクト時代」のまま停止していた
  状態系文書を現状化。[AI_STARTUP.md](AI_STARTUP.md)・[VERSION_MATRIX.md](VERSION_MATRIX.md)・
  [REPOSITORIES.md](REPOSITORIES.md)・[SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)・
  [docs/ai_handoff.md](docs/ai_handoff.md)・本文書。 |
| H6 | 非コーダー向けランブック | [docs/operator_runbook.md](docs/operator_runbook.md)。毎週やること／各システムのダブルクリック操作／
  困ったときの相談のしかた／禁止事項／用語辞典／GitHub 認証の再設定（H6 §6 は M2 で追加）。 |
| H7 | BUILD / DEPLOY / UPDATE 経路の非本番実地検証 | [docs/build_deploy_paths.md](docs/build_deploy_paths.md)。一時ターゲットで5アプリの経路を実走破
  （成果物 SHA-256 が配布先で一致、実 HDD・実共有・本番は不変更）。fail-safe 一覧。 |
| M1 | 新 PC ブートストラップ | `scripts/BOOTSTRAP_DEV_PC.ps1` + `_CLICK_ME.cmd`。git/Python/gh 確認 → GitHub 認証確認 →
  canonical 10 リポジトリを clone（既定ブランチは live 検出）→ RUN_DEV/venv 報告。idempotent・fail-safe。
  一時ディレクトリでの実 clone・再実行・衝突拒否を検証済み。 |
| M2 | GitHub 認証の監査・再認証手順 | [docs/github_auth.md](docs/github_auth.md)。`gh`（OAuth）と `git` push/pull（GCM）の
  2系統・独立の構成、失効条件、失効時の影響範囲を記録。[docs/operator_runbook.md](docs/operator_runbook.md) §6 に
  4ステップの再ログイン手順。DEV_DOCTOR が両系統の失効を検出（gh=ERROR、git(GCM)=ACTION）。 |
| M3 | 俺伝の既定ブランチ監査・main 化 | [docs/food_cost_default_branch.md](docs/food_cost_default_branch.md)。16項目の依存監査 → 判断 A →
  **実施完了**: `codex/bootstrap-invoice-reading` → `main`（GitHub ネイティブ改名、HEAD `1940db0` は
  改名前後で同一 SHA、履歴の書き換えなし）。正式ローカル追従・DEV_DOCTOR `$Canon`・全文書を更新済み。 |

## Windows アプリ共通標準

- 開発起動: `RUN_DEV.cmd`（`.venv` の Python ソースを起動。無ければ自動作成）。
- EXE ビルド: `BUILD_EXE_CLICK_ME.cmd` 等をユーザーが必要時だけ手動実行。未コミットだと止まる設計（俺伝・beverage）。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1`（俺伝は `UPDATE_HDD_CLICK_ME.cmd`、menu-sheet は `UPDATE.cmd`）。業務データを消さない設計。
- 通常の EXE ビルドだけのために実機セッション（Codex 等）のクレジットを消費しない。
- 種別・経路・fail-safe の一覧は [docs/build_deploy_paths.md](docs/build_deploy_paths.md)。

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。GitHub 反映済み（`main` = `dd44366`）。
- `github-rw` を持つセッション（ChatGPT 等）は GitHub 上で完結する調査・実装・テスト・PR まで担当。
- `windows-real` を持つセッション（Codex 等）は Windows 実機・正式ローカル・実プリンター・共有サーバー・
  手動ビルド失敗時の原因調査へ優先配分。正式ソースに触れる前に `git fetch`（必要なら `pull --ff-only`）、
  作業後に `commit` + `push`。「編集したが push していない」は未完了工程。
- PR merge、安定版タグ、本番共有版・実 HDD 更新は、必要な確認と明示的な判断後にのみ行う。

## 次にやること（退役前整備は完了。ここからは通常の開発課題）

退役前整備（H1〜H7、M1〜M3）の各項目と recovery PR #1 は上記のとおりすべて完了・merge 済み。
以下は退役前整備とは別の、通常のプロジェクト残課題。

1. **beverage**: Draft PR #2（Python 移行本体）と PR #5（`feature/mobile-stocktake-sheets`、Google Sheets
   モバイル棚卸）は継続開発中。実プリンター・共有サーバー・2PC 同時更新のゲートを満たすまで merge しない。
2. **俺伝**: 実伝票・実 OCR データでの精度確認、HDD 配布の実地（本番 `E:\FoodCostCalculation\`）での
   最終確認（H7 は非本番の一時ターゲットで経路のみ検証済み）。
3. **qr-supply**: 既存発注表の候補ファイルが現行運用の正式発注表であることの業務確認、正式 DB への確定取込。
4. 次サイクルで検討: menu-sheet-generator のビルド成果物へ俺伝相当の `BUILD_INFO.txt`
   （HEAD SHA + 成果物 SHA-256）を追加する方針（[docs/decisions.md](docs/decisions.md)）。
   next-day-setup は 2026-09-05 に対応済み（PR #5、[projects/next-day-setup.md](projects/next-day-setup.md)）。
5. **next-day-setup の残課題**（2026-09-05 の安全網追加（pytest CI・帳票ビルダー回帰テスト・`BUILD_INFO.txt`）で
   確認、優先度は次サイクルで判断。大規模リファクタリングや印刷方式統合は対象外）:
   - clean-tree gate（俺伝の `Assert-CleanWorkingTree` 相当。今回は `BUILD_INFO.txt` 追加のみで見送り）
   - JSON保存のアトミック化（一時ファイル + rename。現状は直接上書きのためクラッシュ時に破損しうる）
   - 配布EXEのアトミック差し替え（`update_shared_folder.ps1` は現状 `Copy-Item -Force` の直接上書き）
   - 実プリンターでの全帳票確認（GDI直叩き／Excel COM×2系統／reportlab+SumatraPDF／Edgeキオスク印刷の
     4方式が併存しており、実機でしか検証できない）
