# プロジェクト状況

最終更新: 2026-09-04（JST）

## この時期の背景

- 開発補助ツール **Claude Code の提供終了が近い**。終了後も、ChatGPT（GitHub 側）と
  Codex／その他セッション（Windows 実機側）だけで各アプリの開発・ビルド・配布・復旧が
  回るように、退役前整備（H1〜H7）を実施した。→ 下記「退役前整備（H1〜H7、2026-09-04 完了）」節を参照。
- 担当判定は「ChatGPT / Codex / Claude Code」というエージェント名ではなく、そのセッションが
  実際に持つ**能力**で判定する（[CAPABILITIES.md](CAPABILITIES.md) が正本）。
- 非コーダーのユーザーが単独で日常運用できるよう、[docs/operator_runbook.md](docs/operator_runbook.md) を用意した。

## 管理対象リポジトリ（10）

種別の唯一の正は [scripts/repo_types.toml](scripts/repo_types.toml)。正式ソースは
すべて `C:\Users\suisy\Documents\Development\repos\<name>` 配下。

| リポジトリ | 種別 | 既定ブランチ | 現在地 |
|---|---|---|---|
| next-day-setup（翌日準備） | desktop | `main` | 実運用中。tag `v1.2.1`、main `1b048f4`。RUN_DEV / BUILD_EXE_CLICK_ME / UPDATE_SHARED_FOLDER 完備。 |
| inventory-reconciliation-system（在庫突合） | service | `main` | 実運用中。tag `v2.0.0`、main `fd2de21`。夜間自動実行（`install_daily_inventory_task.bat` でタスク登録）。 |
| beverage-inventory-ordering-system（飲料在庫） | desktop | `main`（移行作業は `python-desktop-migration`） | Python/PySide6 版へ移行中。作業ブランチ `python-desktop-migration` は upstream と同期（`e458476`）。能力ベース運用の起点・3経路の実績元。 |
| food-cost-calculation-system（俺伝） | desktop | **`codex/bootstrap-invoice-reading`**（`main` は無い） | 実運用中。HEAD `1940db0`。Nuitka ビルド + 外付け HDD 配布（`BUILD_俺伝_CLICK_ME.cmd` → `UPDATE_HDD_CLICK_ME.cmd`）。既定ブランチの `main` 化は M3 で依存監査後に判断。 |
| menu-sheet-generator（料理説明書、.NET） | desktop | `main` | 実運用中。tag `v1.0.0`、main `fa4fdf7`。`BUILD_RELEASE.cmd`（dotnet publish）→ `UPDATE.cmd`。 |
| qr-supply-ordering-system（QR 物品発注） | web | `main` | 社内 LAN の 1 ホストで Flask 常駐。main `790fff5`。`RUN_DEV.cmd` + 対象リポジトリの `DEPLOY.md`。 |
| call-reception-assistant（電話受付） | desktop | `main` | 初期管理文書のみ。**アプリ本体は未実装**。main `ae78cf5`。 |
| kitchen-calendar（調理場カレンダー） | archived | `main` | next-day-setup へ統合済み。**今後開発しない**（[docs/pc_repo_audit.md](docs/pc_repo_audit.md) #2）。 |
| hospitality-review-reply（口コミ返信） | knowledge | `main` | 旅館口コミ返信のテンプレート／知識 repo。アプリではない。main `f6e1e74`。CI は warning-only、実行・ビルド標準は課さない。 |
| development-management | （管理repo自身） | `main` | 本知識ベース。main `d45c0c9`、moving tag `ci-v1`。 |

## Current Focus

| リポジトリ | 現在の作業 |
|---|---|
| （全体） | 退役前整備 H1〜H7 + M1（新PCブートストラップ）+ M2（GitHub 認証監査）+ M3（俺伝の既定ブランチ監査）完了。残るユーザー作業: **M3 の GitHub ブランチ改名の実行/承認**（`docs/food_cost_default_branch.md` のコマンド）、beverage Draft PR #2、recovery PR #1。 |
| beverage-inventory-ordering-system | `python-desktop-migration` を upstream `e458476` へ FF 済み（DEV_DOCTOR の behind 5 解消）。Python ソース版の Windows 実機確認を継続。EXE は必要時のみユーザーが手動ビルド、本番共有版は確認完了まで更新しない。Draft PR #2 の merge 可否は未判断。 |
| next-day-setup / inventory-reconciliation / menu-sheet-generator / 俺伝 / qr-supply | 実運用中。標準3経路（または相当）と CI（warning-only、`@ci-v1`）を整備済み。個別の機能追加は各 `projects/*.md` と対象リポジトリの状態で判断。 |
| call-reception-assistant | 設計前。無課金・ローカル完結・外部非接続の初期試作方針（[docs/decisions.md](docs/decisions.md)）。 |

## 退役前整備（H1〜H7、2026-09-04 完了）

| 記号 | 内容 | 主な成果物 |
|---|---|---|
| H1 | Git 管理外データのバックアップ・復元 | `scripts/BACKUP_DEV_DATA.ps1` + `_CLICK_ME.cmd`、[docs/git_external_data_inventory.md](docs/git_external_data_inventory.md)、[docs/backup_restore.md](docs/backup_restore.md)。実バックアップ初回作成・全項目検証済み（`%USERPROFILE%\DevDataBackups\` と `E:\DevDataBackups\`）。 |
| H2 | PC 全体の repo／clone 監査、旧 clone 比較 | [docs/pc_repo_audit.md](docs/pc_repo_audit.md)。旧 clone #1〜#4 の分類。hospitality-review-reply を knowledge 種別で管理対象へ追加。 |
| H3 | 共通 CI アクションの安定タグ運用 | `ci-v1`（moving）/ `ci-v1.0.x`（固定）。[docs/ci_action_versioning.md](docs/ci_action_versioning.md)。各 repo の CI は `@ci-v1` を参照。 |
| H4 | 実機ヘルスチェック | `scripts/DEV_DOCTOR.ps1` + `_CLICK_ME.cmd`、[docs/dev_doctor.md](docs/dev_doctor.md)。4段階（ERROR / ACTION / INTENTIONAL / INFO）。 |
| H5 | 引き継ぎドライラン | development-management だけから作業再開できるかの検証。本文書・[AI_STARTUP.md](AI_STARTUP.md)・[VERSION_MATRIX.md](VERSION_MATRIX.md)・[REPOSITORIES.md](REPOSITORIES.md)・[SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)・[docs/ai_handoff.md](docs/ai_handoff.md) を現状へ更新。 |
| H6 | 非コーダー向けランブック | [docs/operator_runbook.md](docs/operator_runbook.md)。毎週やること／各システムのダブルクリック操作／困ったときの相談のしかた／禁止事項／用語辞典。 |
| H7 | BUILD / DEPLOY / UPDATE 経路の非本番実地検証 | [docs/build_deploy_paths.md](docs/build_deploy_paths.md)。一時ターゲットで各アプリの経路を実走破。fail-safe 一覧。 |

## Windows アプリ共通標準

- 開発起動: `RUN_DEV.cmd`（`.venv` の Python ソースを起動。無ければ自動作成）。
- EXE ビルド: `BUILD_EXE_CLICK_ME.cmd` 等をユーザーが必要時だけ手動実行。未コミットだと止まる設計（俺伝・beverage）。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1`（俺伝は `UPDATE_HDD_CLICK_ME.cmd`、menu-sheet は `UPDATE.cmd`）。業務データを消さない設計。
- 通常の EXE ビルドだけのために実機セッション（Codex 等）のクレジットを消費しない。
- 種別・経路・fail-safe の一覧は [docs/build_deploy_paths.md](docs/build_deploy_paths.md)。

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。GitHub 反映済み（`main` = `d45c0c9`）。
- `github-rw` を持つセッション（ChatGPT 等）は GitHub 上で完結する調査・実装・テスト・PR まで担当。
- `windows-real` を持つセッション（Codex 等）は Windows 実機・正式ローカル・実プリンター・共有サーバー・
  手動ビルド失敗時の原因調査へ優先配分。正式ソースに触れる前に `git fetch`（必要なら `pull --ff-only`）、
  作業後に `commit` + `push`。「編集したが push していない」は未完了工程。
- PR merge、安定版タグ、本番共有版・実 HDD 更新は、必要な確認と明示的な判断後にのみ行う。

## 次にやること

1. **H5**: この更新で本文書群を現状化した。新規セッションが development-management だけで
   現在地・正式ソース・未完了作業を把握できるか、実際に読み直して残ギャップを潰す。
2. ~~**M2**: GitHub 認証の監査・再認証手順~~ → 完了（[docs/github_auth.md](docs/github_auth.md)、
   [docs/operator_runbook.md](docs/operator_runbook.md) §6、DEV_DOCTOR に gh 失効=ERROR / git(GCM) 失敗=ACTION を追加）。
3. ~~**M3**: 俺伝の既定ブランチ依存監査~~ → 完了。判断 **A（`main` へ移行）**。
   全数監査（機能依存は DEV_DOCTOR `$Canon` 1行のみ）と非破壊・可逆の移行手順は
   [docs/food_cost_default_branch.md](docs/food_cost_default_branch.md)。
   **GitHub ブランチ改名 API の実行は自動化がブロックされたためユーザー実行/承認待ち。**
   実行後、DEV_DOCTOR `$Canon` と各文書の `codex/bootstrap-invoice-reading` を `main` へ更新し検証する。
4. ~~**M1**: 新 PC ブートストラップ~~ → 完了。`scripts/BOOTSTRAP_DEV_PC.ps1` + `_CLICK_ME.cmd`。
   idempotent（既存 repo は fetch のみ・reset しない）/ fail-safe（非 git ディレクトリは上書き拒否）。
   各 repo の既定ブランチは `git ls-remote --symref` で live 検出（俺伝が `codex/...` でも `main` でも正しく追従）。
   Git 管理外データは自動復元せず [docs/backup_restore.md](docs/backup_restore.md) へ誘導。
   一時ディレクトリへの実 clone + 再実行（idempotency）+ 非 git 衝突拒否を検証済み。
5. **beverage**: Draft PR #2 の merge 可否判断、GAS スマホ棚卸・発注システム統合。
6. `recovery/from-old-clone-docs`（Draft PR）の取り込み範囲決定。分類表はそのブランチの
   `docs/recovery_from_old_clone.md`、概要は [docs/pc_repo_audit.md](docs/pc_repo_audit.md) の「比較・救出の結果」#1。
