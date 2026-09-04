# 変更履歴

新しい記録を上に追加します。「確認状況」は、未確認／開発環境確認済み／実運用確認済みを明記します。

## v1.3.0 - 2026-09-04

### Added（退役前整備 H1〜H7 + M1〜M3）

- Claude Code の提供終了に備え、終了後も ChatGPT（GitHub 側）＋実機セッション（Windows 側）だけで
  開発・ビルド・配布・復旧が回るよう、以下を整備。
- **H1** Git 管理外データのバックアップ・復元: `scripts/BACKUP_DEV_DATA.ps1` + `_CLICK_ME.cmd`、
  [docs/git_external_data_inventory.md](docs/git_external_data_inventory.md) / [docs/backup_restore.md](docs/backup_restore.md)。
  実バックアップ初回作成・全項目検証（`%USERPROFILE%\DevDataBackups\` と 別物理ディスク `E:\DevDataBackups\`）。
- **H2** PC 全体の repo／旧 clone 監査: [docs/pc_repo_audit.md](docs/pc_repo_audit.md)。旧 clone #1〜#4 を
  救出済み／superseded／obsolete に分類（削除しない）。`hospitality-review-reply` を `knowledge` 種別で管理対象へ追加（計10）。
- **H3** 共通 CI アクションの安定タグ: `ci-v1`（moving）/ `ci-v1.0.0` / `ci-v1.0.1`（固定）。
  [docs/ci_action_versioning.md](docs/ci_action_versioning.md)。全 caller を `@main` → `@ci-v1` へ。
- **H4** 実機ヘルスチェック: `scripts/DEV_DOCTOR.ps1` + `_CLICK_ME.cmd`、[docs/dev_doctor.md](docs/dev_doctor.md)。
  指摘を ERROR / ACTION / INTENTIONAL / INFO の4段階に分離。
- **H5** 引き継ぎドライラン: 新規セッションが development-management だけで再開できるよう、
  [AI_STARTUP.md](AI_STARTUP.md) / [PROJECT_STATUS.md](PROJECT_STATUS.md) / [VERSION_MATRIX.md](VERSION_MATRIX.md) /
  [REPOSITORIES.md](REPOSITORIES.md) / [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) / [docs/ai_handoff.md](docs/ai_handoff.md)
  を10リポジトリ・現在の HEAD／タグ・退役前整備の文脈へ更新（2プロジェクト時代の記述を一掃）。
- **H6** 非コーダー向けランブック: [docs/operator_runbook.md](docs/operator_runbook.md)。
- **H7** BUILD / DEPLOY / UPDATE 経路の非本番実地検証: [docs/build_deploy_paths.md](docs/build_deploy_paths.md)。
  一時ターゲットで各アプリの経路を実走破し、成果物 SHA-256 の配布先一致を確認。実 HDD・実共有・本番は不変更。
- 「ビルド成果物に出所（HEAD SHA + 成果物 SHA-256）を残す」方針を [docs/decisions.md](docs/decisions.md) に追加。
- **M1** 新 PC ブートストラップ: `scripts/BOOTSTRAP_DEV_PC.ps1` + `_CLICK_ME.cmd`。
  git/Python/gh 確認（winget 案内）→ GitHub 認証2系統確認 → `development-management` を clone して
  `repo_types.toml` から一覧取得 → 不足 repo を clone（既定ブランチは `git ls-remote --symref` で live 検出）→
  RUN_DEV 入口と `.venv` の有無を報告 → Git 管理外データは復元せず `backup_restore.md` へ誘導。
  idempotent（既存 repo は fetch のみ）/ fail-safe（非 git ディレクトリは上書き拒否）。一時 clone・再実行・衝突拒否を検証済み。
- **M2** GitHub 認証の監査: [docs/github_auth.md](docs/github_auth.md)。この PC は `gh`（OAuth `gho_`、keyring 保存、
  scope `gist read:org repo workflow`）と `git` push/pull（Git Credential Manager 2.9.0、`git:https://github.com`）の
  **2系統・独立**。期限日表示なし・失効条件・失効時に何が止まるかを記録（トークン値は非記録）。
  [docs/operator_runbook.md](docs/operator_runbook.md) §6 に『開くもの／入力するもの／ブラウザで／成功後に確認』の
  4ステップで `gh auth login` と GCM 再ログインを明文化。
- **M3** 俺伝の既定ブランチ監査: [docs/food_cost_default_branch.md](docs/food_cost_default_branch.md)。
  `codex/bootstrap-invoice-reading` の依存を16項目で全数監査 → 判断 A（`main` へ移行）。機能依存は
  DEV_DOCTOR `$Canon` の1行のみ。GitHub ネイティブ改名（非破壊・可逆）の移行/ロールバック手順を明記。
  改名 API の実行はユーザー待ち。

### Changed

- `beverage-inventory-ordering-system` の作業ブランチ `python-desktop-migration` を upstream `e458476` へ
  pure fast-forward（DEV_DOCTOR の ACTION「behind 5」を解消。ローカル固有コミット 0 を確認済み）。
- `scripts/DEV_DOCTOR.ps1`（M2）: `gh` 認証チェックを「"Logged in" 文字列一致」から
  **`gh auth status` の終了コード + 失効行の検出**へ変更（失効を取りこぼさない）。失効 = `[ERROR]`。
  private repo への `git ls-remote`（プロンプト無効）で **git(GCM) 認証を実テスト**する行を追加。失敗 = `[ACTION]`。

### 確認状況

開発環境確認済み（非本番）。実運用環境・実 HDD・実共有フォルダ・実プリンター・本番タスクスケジューラは未変更・未確認。
GitHub 認証は現在有効（`gh auth status` exit 0、private repo `git ls-remote` exit 0）。

## v1.2.0 - 2026-09-04

### Changed

- 開発環境整備を一巡完了。担当判定をエージェント名から能力ベースへ切り替え（[CAPABILITIES.md](CAPABILITIES.md)）。正式ローカルリポジトリの「作業前 pull・作業後 push」を必須規約化。
- `templates/windows-python-app/` を追加（`beverage-inventory-ordering-system/python_app/` の実績3スクリプトを汎用化）。Windows `.cmd` の必須事項（ASCII のみ / CRLF / `if(...)` 内に括弧を書かない / `python -c` の複数 import は `;` 区切り）を確立し `LESSONS_LEARNED.md` へ記録。
- `scripts/check_standards.py` を追加。アプリ種別（desktop / web / service / lib / archived）ごとに必要経路を点検。種別は `scripts/repo_types.toml` を唯一の正とし、アプリ側にマーカーを置かない。gitignore 済みファイルは秘密チェック対象外。
- `RUN_DEV.cmd` を `next-day-setup` / `food-cost-calculation-system` / `inventory-reconciliation-system`（desktop）、`qr-supply-ordering-system`（web、`DEPLOY.md` も）へ展開。各リポジトリで一時 clone の `cmd.exe /c RUN_DEV.cmd` により venv 作成 → 依存導入 → 起動 → GUI/HTTP 応答 → 正常終了までを実機確認。`beverage-inventory-ordering-system` は既存で 3 経路充足、`kitchen-calendar` は archived。
- `qr-supply-ordering-system` の GitHub/正式ローカルのズレを解消。スケルトンのみだった `origin/main` に対し、正式ローカルの未コミット実装（Phase 1 / 1.5 / 発注表取込）を混入監査のうえ GitHub へ保存し、アプリ実装（PR #2）と開発環境標準化（PR #1）を別履歴として `main` へ反映。
- CI 用の共通 composite action `.github/actions/check-standards` と、各アプリ用の最小 caller workflow テンプレート `templates/ci/standards.yml` を追加。
- CI 化を実施。`development-management`（public）の composite action を、8アプリリポジトリ（private）＋ dogfood が `.github/workflows/standards.yml` から `uses:` 参照。ロジックは各アプリへ複製せず、`check_standards.py` / `repo_types.toml` は `development-management` 側のものだけを使用。`strict` なし＝warning-only で push / PR をブロックしない。public→private のため PAT 等の長期秘密情報は不要。`kitchen-calendar` は archived のため対象外。

### Result

`scripts/check_standards.py` は9リポジトリすべてで `OK: 指摘なし`（ERROR 0 / WARN 0）。RUN_DEV.cmd 展開時、各アプリの実運用データ（DB / 資格情報 / master_settings）は SHA-256 不変を確認。CI は `next-day-setup` でパイロット（push/PR 起動・準拠時成功・意図的違反の WARN 検出・warning-only 非ブロック・長期トークン不要 の5条件確認）後、全8アプリへ展開し全 CI が success。アプリ本体・正式EXE・共有版・実運用環境・配布経路は変更なし。

確認状況: 開発環境確認済み（一時 clone での end-to-end 実機確認）＋ CI 全展開・全 success。

## v1.1.2 - 2026-09-01

### Changed

- `beverage-inventory-ordering-system` のPython移行で、旧PySide6タブUIが現行ブラウザUIと大きく異なることをWindows実機で確認。
- Python/PySide6移行自体は継続し、現行 `index.html` / `styles.css` / `app.js` の最終UIをUI仕様正本として全面再構築する方針を正式化。
- WebView等へ切り替えず、PySide6ネイティブUIとして現行の色、余白、寸法、配置、情報密度、操作順を再現する。
- 共有サーバー試験はUI一致確認まで停止する。
- ユーザー手動EXEビルドは成功済みだが、EXE起動成功とUI同等性確認を別ゲートとして管理する。
- PySide6 UI全面再構築第一弾を `python-desktop-migration` HEAD `d5d3e65c` まで実装。旧 `QTabWidget` を撤去し、業務順1画面ダッシュボード、商品調整・個別発注・棚卸し管理画面を再構成。
- ブラウザCSSの主要色・寸法をPySide6側へ反映し、UIソース検査を追加。

### Result

データ・業務計算互換性は66/66商品一致のまま維持。UI全面再構築第一弾HEAD `d5d3e65c` はWindows-latestのPython compile / migration tests成功。次工程はWindows `RUN_DEV.cmd` でブラウザ版との横並び見比べと微調整。

確認状況: GitHub実装・Actions確認済み。Windows実機での新UI見比べは未確認。

## v1.1.1 - 2026-09-01

### Changed

- Python/Windowsアプリの開発標準を「ソース起動・手動EXEビルド・手動配布更新」の3経路へ統一。
- 日常の開発・確認では `.venv` のPythonソース版を起動し、EXE化を毎回の工程から外した。
- EXE配布するアプリには `BUILD_EXE_CLICK_ME.cmd` または同等のワンクリックビルドを必須化。
- 配布対象アプリには `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須化。
- 通常のEXEビルドをCodex担当から外し、手動ビルド失敗やEXE固有不具合の原因調査時だけCodexを使用する方針へ変更。
- `AGENTS.md`、`AI_OPERATING_MANUAL.md`、`AI_CHECKLIST.md`、`AI_STARTUP.md`、`DEVELOPMENT_RULES.md`、`PROJECT_BOOTSTRAP.md`、`REUSE_MAP.md`、`docs/decisions.md`、`PROJECT_STATUS.md`、飲料在庫プロジェクト文書を更新。

### Result

定型的なEXEビルド・配布更新でCodexクレジットを消費せず、ユーザーが必要なときだけワンクリックで実行できる構成を全Windowsアプリの標準とした。CodexはWindows実機でしか確認できない問題の調査へ優先配分する。

確認状況: GitHub管理文書更新済み。各既存アプリへの標準スクリプト実装状況はプロジェクトごとに別途確認する。

## v1.1.0 - 2026-09-01

### Changed

- ChatGPT / Codexの役割分担を更新。
- GitHubへ直接アクセスできるChatGPTは、調査・設計だけでなくGitHub上の実装、テスト追加、branch、commit、push、PR、レビューまで第一担当とする。
- CodexはWindows実機、正式ローカル、EXEビルド、実プリンター、共有サーバー、複数PC試験など、ChatGPTから直接扱えない作業へ優先して使用する。
- GitHub上のテスト成功とWindows実機確認を別の確認レベルとして扱う。
- Codexへの引き継ぎ時は、対象branch/commit、実装済み範囲、テスト結果、残作業、本番反映可否を明記する。
- `AI_OPERATING_MANUAL.md`、`AGENTS.md`、`DEVELOPMENT_RULES.md`、`AI_STARTUP.md`、`docs/decisions.md`、`PROJECT_STATUS.md` を新運用へ更新。
- `projects/beverage-inventory-ordering-system.md` をPython移行の現在地へ更新。

### Result

GitHub上だけで完結する作業をChatGPTとCodexで重複せず、CodexクレジットをWindows実機・ローカル依存作業へ優先配分する運用を正式化。

### First application

- `beverage-inventory-ordering-system` で `python-desktop-migration` / Draft PR #2をChatGPT側で実装。
- 現行実運用JSONによる互換確認とローカルpytest 11件成功までChatGPT側で実施。
- Windows実機、EXEビルド、実プリンター、共有サーバー複数PC試験はCodex側の後工程として分離。

確認状況: v1.1.1でEXEビルド担当を再整理。通常のEXEビルドはCodex担当から除外した。

## v1.0.0 - 2026-07-20

Initial stable release.

### Added

- `AI_OPERATING_MANUAL.md`
- `AI_CHECKLIST.md`
- `PROMPT_PRINCIPLES.md`
- `PROJECT_BOOTSTRAP.md`
- `AGENTS.md`
- AI引き継ぎとAI共同開発フロー
- プロジェクト化完了の定義

### Changed

- `AI_STARTUP.md` の開始手順
- ChatGPTとCodexの役割分担
- `development-management` の位置付け
- 新規プロジェクト立ち上げ手順

### Result

`development-management` を「AI共同開発基盤」v1.0.0として正式化。

| 日付 | 変更対象プロジェクト | 変更内容 | 確認状況 |
|---|---|---|---|
| 2026-09-01 | beverage-inventory-ordering-system | 旧PySide6タブUIのUI差異を実機で確認し、現行ブラウザUIを正本としたPySide6全面再構築へ移行。データ互換は維持し、UI同等性を独立本番ゲート化 | GitHub第一弾実装・Actions成功。Windows実機見比べ未完了。共有サーバー試験停止 |
| 2026-09-01 | development-management | Python/Windowsアプリをソース起動・手動EXEビルド・手動配布更新の3経路へ統一。Codexの通常担当からEXEビルドを外し、`BUILD_EXE_CLICK_ME.cmd` と `UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` を標準化 | 管理文書をGitHub `main`で更新。既存各アプリへのスクリプト適用状況は別途確認 |
| 2026-09-01 | development-management | ChatGPTをGitHub側の第一実装担当、CodexをWindows実機・ローカル環境作業の第一担当とする分業へ変更。GitHub上の実装・テスト・branch・commit・push・PR・レビューをChatGPT側で進め、Codexクレジットを実機作業へ優先配分する運用を正式化 | `AGENTS.md`、`AI_OPERATING_MANUAL.md`、`AI_STARTUP.md`、`DEVELOPMENT_RULES.md`、`docs/decisions.md`、`PROJECT_STATUS.md`、飲料在庫プロジェクト文書をGitHub `main`で更新。コード・本番環境変更なし |
| 2026-09-01 | beverage-inventory-ordering-system | 現行ブラウザ版を仕様正本としてPython/PySide6移行を開始。`python-desktop-migration` / Draft PR #2に候補版を隔離し、旧JSON互換、共有JSON、在庫計算、棚卸、売上CSV、レシピ、定期消費、発注、商品マスタ、PySide6 UI等を実装 | 現行実運用JSONでローカルpytest 11件成功、主要コレクション保存・再読込一致。Windows実機、EXE、実プリンター、共有サーバー試験は未確認。`main`・本番未変更 |
| 2026-07-23 | menu-sheet-generator | `v1.0.0`初回正式リリース。WPFお品書き印刷、日本語・英語・従業員用、PMS CSV自動集計、宿泊日指定、泊目別・部屋数集計、従業員確認用自動印刷、共有フォルダ配布、実運用データ保持を正式版として登録 | タグ`v1.0.0`とGitHub Releaseをコミット`2376c216`へ公開。ビルド・全自動テスト成功、実機動作確認済み |
| 2026-07-21 | menu-sheet-generator | GitHub管理開始と正式ソース確定。自己完結型`win-x64`配布、ワンクリック共有フォルダ配布、PMS CSV自動集計印刷、対象日絞り込み、泊目別集計、泊目別従業員確認用自動印刷を登録 | GitHub `main`・正式ローカル`6e97ccea`同期、ビルド・全自動テスト成功、実プリンター確認完了 |
| 2026-07-21 | call-reception-assistant | 空の正式GitHubリポジトリを `Development\repos` 配下へcloneし、README、`docs/`、AI引き継ぎ、AI作業ガイド、`.gitignore`を作成。初回commit・pushと管理文書への登録を実施 | `main`と`origin/main`が`95bd3ca`で一致、Git状態クリーン、文書リンク・秘密情報を確認。アプリ本体は未実装。`PROJECT_BOOTSTRAP v1.0.0`に基づくプロジェクト化完了 |
| 2026-07-20 | beverage-inventory-ordering-system | 単体タスクで開発していた飲料発注システムを正式プロジェクトの `apps/ordering/` へ移管。在庫管理画面から起動するサブシステムとして位置付け、README、docs、AI引き継ぎ、development-managementを「飲料在庫管理＋飲料発注システム」へ更新 | JavaScript構文確認、静的ファイル存在確認、Git差分確認済み。発注システムは開発中。実業者名・実FAX番号・実発注履歴はGit管理対象外 |
| 2026-07-20 | next-day-setup | ケーキ発注書の緊急用手動印刷を追加。受取日を直接指定し、業務日＝受取日－4日を確認表示して、自動印刷と同じ単日生成・Excel印刷処理を1回だけ実行 | 構文確認・自動テスト38件成功。テスト用出力ファイル生成と注文なし時の未出力を確認。実画面・実Excel・実プリンターは未確認。コミット／pushなし |
| 2026-07-20 | next-day-setup | ケーキ受取日を対象業務日＋4日に固定。Google Sheets休館日を在庫照合と同じ取得・解析・3日キャッシュ方式で参照し、休館前日・連続休館日の未実行分を受取日別に前倒し連続印刷する処理とテストを追加 | 構文確認・自動テスト36件・公開CSV実取得成功。実Excel／実プリンター、画面表示、EXE、共有版は未確認。コミット／pushなし |
| 2026-07-20 | development-management | `AGENTS.md`をAI向け入口ガイドとして整備し、ChatGPT／Codexの役割分担、指示書優先、知識記録、Git運用を要約。`PROJECT_BOOTSTRAP.md`を追加し、単体タスクの正式プロジェクト化手順と完了定義を標準化 | 文書差分・リンク・役割分担を確認済み。コード・業務システム変更なし |
| 2026-07-20 | beverage-inventory-ordering-system | 正式ソースのローカル`main`をGitHub `main`（`8d2ab9c`）へfast-forward。アプリ本体と文書のGitHub反映、ローカル同期完了を管理文書へ反映し、次工程を飲料発注アプリの取り込み調査へ更新 | HEAD・main・origin/main一致、Git statusクリーン、JavaScript構文、ブラウザ起動、コンソールエラーなしを確認。機能・UI・保存方式の変更なし |
| 2026-07-20 | development-management | AI回答品質・提案品質を標準化する`PROMPT_PRINCIPLES.md`を追加。回答方針、提案方針、開発方針、Codex連携、回答スタイル、継続開発の原則を定義し、AI開始順序とREADMEへ組み込み | 文書差分・リンク・読む順番を確認済み。コード・業務システム変更なし |
| 2026-07-20 | development-management | AI運用を標準化。`AI_OPERATING_MANUAL.md`と`AI_CHECKLIST.md`を追加し、AIの役割、Codexとの役割分担、思考順序、指示書優先、開始時の確認順序を整理。README、AI_STARTUP、AI_MEMORYを更新 | 文書差分・リンク・責務分離を確認済み。コード・業務システム変更なし |
| 2026-07-18 | next-day-setup | PMS番号付き手配枠の構造化、3日後ケーキ検出、CSV期間警告、確認画面、マクロ転記仕様メモ、テストを追加 | 構文確認・自動テスト14件・実CSV解析済み。画面・転記・印刷は実運用未確認。コミット／pushなし |
| 2026-07-16 | development-management | `VERSION_MATRIX.md`と`AI_MEMORY.md`を追加し、README、AI開始手順、AI引き継ぎ、現在地へ組み込み | ローカル文書作成・必須項目確認済み。コミット／push前 |
| 2026-07-16 | development-management | AI開始手順、Current Focus、知識管理ルール、判断・依頼テンプレート、日次ログ、全体構成図を追加 | ローカル文書作成済み。コミット／push前 |
| 2026-07-16 | development-management | 司令塔リポジトリの文書構成を新規作成 | ローカル文書作成済み。コミット／push前 |
| 2026-07-16 | next-day-setup | Google Sheetsシフト取得、印刷、ビルド、共有版更新に関する作業を進行中として記録 | 未コミット差分を確認。動作・実運用は未確認 |
| 2026-07-16 | inventory-reconciliation-system | Google Sheets休館日取得、キャッシュ、夜間実行、警告メールに関する作業を進行中として記録 | 未コミット差分を確認。動作・実運用は未確認 |