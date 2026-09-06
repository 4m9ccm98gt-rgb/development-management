# AI Startup

このファイルは、新しいチャットや別のCodex環境が安全に作業を開始するための入口です。

## このリポジトリの役割

`development-management` は、業務システム全体の設計判断、開発ルール、進行状況、AIとの共同開発知識を管理する正式な知識ベースです。コード本体は管理しません。

[AGENTS.md](AGENTS.md) はAIがこのリポジトリで作業する際の短い入口ガイドです。本ファイルは開始時の確認方法の正本です。単体タスクを正式プロジェクトへ昇格する場合は [PROJECT_BOOTSTRAP.md](PROJECT_BOOTSTRAP.md) を適用します。

開始時の文書読み込み、調査範囲、テスト範囲、反復上限は [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を最優先します。小変更で開始文書一式を機械的に全読みしません。

## 開始時の確認順序

### 0. 最初に変更ティアを決める

1. [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を読む。
2. 対象リポジトリ / ブランチ / HEAD SHA / dirty tree を確認する。
3. 今回の作業を `T0 / T1 / T2 / T3` に分類し、1行のblast-radiusを決める。
4. 以下のティア別ルートで必要な文書だけ読む。

### T0 / T1 の最小ルート

- 対象のREADMEまたは対象 `projects/*.md` のうち、今回に直接必要な部分
- 対象ファイルと直接の呼び出し元1ホップ
- 能力判定が必要な場合のみ [CAPABILITIES.md](CAPABILITIES.md)
- 今回に直接関係するルール・判断がある場合だけ、該当文書の関連箇所

T0 / T1では、`PROJECT_STATUS.md`、`VERSION_MATRIX.md`、`SYSTEM_OVERVIEW.md`、`docs/decisions.md`、`LESSONS_LEARNED.md` 等を一律に全読みしない。既存機構の局所修正ではREUSE_MAP横断調査も自動発火させない。

### T2 の標準ルート

1. [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md)
2. [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) の今回に関係する部分
3. [AI_CHECKLIST.md](AI_CHECKLIST.md)
4. [CAPABILITIES.md](CAPABILITIES.md)
5. [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) の今回に関係する部分
6. 対象の `projects/*.md` またはREADME
7. 金額・在庫・印刷・DB・共有フォルダ・build/deploy等に関係する場合だけ、該当する [docs/decisions.md](docs/decisions.md) / [LESSONS_LEARNED.md](LESSONS_LEARNED.md) / [REUSE_MAP.md](REUSE_MAP.md)

管理対象全プロジェクトの状態を一括で読み込む必要はない。

### T3 のフルルート

T3では、構造変更・repo横断・移行のため、次を順番に確認する。

1. [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md)
2. [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) — AIの役割、思考順序、役割分担
3. [AI_CHECKLIST.md](AI_CHECKLIST.md) — 新しいチャット開始時の確認項目
4. [PROMPT_PRINCIPLES.md](PROMPT_PRINCIPLES.md) — 回答・提案・思考品質の基準
5. [AI_MEMORY.md](AI_MEMORY.md) — プロジェクト固有のルール
6. [CAPABILITIES.md](CAPABILITIES.md) — 担当判定（エージェント名ではなく、そのセッションが持つ能力で判定）と正式ローカルリポジトリの同期規約（作業前 `git pull --ff-only`・作業後 `git push`）
7. [PROJECT_STATUS.md](PROJECT_STATUS.md) — 管理対象10リポジトリの現在地、退役前整備（H1〜H7）の成果、次の作業
8. [VERSION_MATRIX.md](VERSION_MATRIX.md) — GitHubと実運用版の確認状況
9. [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) — 管理対象と全体構成
10. [docs/decisions.md](docs/decisions.md) — 重要な設計判断
11. [LESSONS_LEARNED.md](LESSONS_LEARNED.md) — 再発防止に使う知見

退役前整備で追加した運用文書（必要時に参照）:

- [docs/operator_runbook.md](docs/operator_runbook.md) — 非コーダー向けの日常運用手順
- [docs/build_deploy_paths.md](docs/build_deploy_paths.md) — 各アプリの BUILD/DEPLOY/UPDATE 経路と fail-safe
- [docs/dev_doctor.md](docs/dev_doctor.md) — 実機ヘルスチェック（`scripts/DEV_DOCTOR.ps1`）
- [docs/backup_restore.md](docs/backup_restore.md) / [docs/git_external_data_inventory.md](docs/git_external_data_inventory.md) — Git 管理外データのバックアップ・復元
- [docs/pc_repo_audit.md](docs/pc_repo_audit.md) — PC 上の repo／旧 clone 監査
- [docs/ci_action_versioning.md](docs/ci_action_versioning.md) — 共通 CI アクションのタグ運用（`@ci-v1`）

対象プロジェクトがある場合は、ティアに応じて対象の `projects/*.md`、README、Git状態、関連コードを確認します。
`projects/` に対象の文書が無いリポジトリ（現状 `food-cost-calculation-system` / `qr-supply-ordering-system` /
`hospitality-review-reply` / `kitchen-calendar`）は、対象リポジトリの README と [VERSION_MATRIX.md](VERSION_MATRIX.md) /
[PROJECT_STATUS.md](PROJECT_STATUS.md) の該当行を正とします。ただしT0 / T1では今回の変更に不要な文書まで機械的に読み込みません。`food-cost` と `qr-supply` の詳細な
プロジェクト文書は `recovery/from-old-clone-docs`（Draft PR）に現状版があり、取り込みは保留中です。

同一セッション / 同一ブランチで一度確認した開始文書は、HEAD・文書・前提が変わらない限り回答ごとに再ロードしません。

## 管理対象と正式ソース

種別の唯一の正は [scripts/repo_types.toml](scripts/repo_types.toml)。正式ソースはすべて
`C:\Users\suisy\Documents\Development\repos\<name>` 配下。詳細な現在地は [PROJECT_STATUS.md](PROJECT_STATUS.md)。

| プロジェクト | 種別 | 既定ブランチ | 最新確認タグ |
|---|---|---|---|
| next-day-setup | desktop | `main` | `v1.2.1` |
| inventory-reconciliation-system | service | `main` | `v2.0.0` |
| menu-sheet-generator（.NET） | desktop | `main` | `v1.0.0` |
| food-cost-calculation-system（俺伝） | desktop | `main`（2026-09-04 M3 で `codex/bootstrap-invoice-reading` から改名） | なし |
| beverage-inventory-ordering-system | desktop | `main`（移行作業は `python-desktop-migration`） | なし |
| qr-supply-ordering-system | web | `main` | なし |
| call-reception-assistant | desktop | `main` | なし（アプリ本体未実装） |
| kitchen-calendar | archived | `main` | なし（next-day-setup へ統合済み。開発しない） |
| hospitality-review-reply | knowledge | `main` | なし（テンプレート集。実行・ビルド標準対象外） |
| development-management | — | `main` | `ci-v1`（共通CIアクション用） |

タグ欄は最後に管理文書へ反映した確認値であり、実運用中の版との一致は `VERSION_MATRIX.md` と各プロジェクト文書で確認します。

## 現在の重点作業

最新は [PROJECT_STATUS.md](PROJECT_STATUS.md) の Current Focus を正とする。要点:

- **背景**: 開発補助ツール Claude Code の提供終了が近い。終了後も ChatGPT（GitHub側）と実機セッション
  （Windows側）だけで各アプリの開発・ビルド・配布・復旧が回るよう、退役前整備 H1〜H7 を完了した
  （バックアップ／実機ヘルスチェック／CI 安定タグ／非コーダー向けランブック／BUILD・DEPLOY 経路検証）。
- `beverage-inventory-ordering-system`: 現行ブラウザ版を仕様正本として Python/PySide6 版へ段階移行中。
  作業ブランチ `python-desktop-migration`（upstream と同期、`e458476`）/ Draft PR #2。Python ソース版の
  Windows 実機確認を継続。EXE は必要時だけユーザーが手動ビルド、本番共有版は確認完了まで更新しない。
- `next-day-setup` / `inventory-reconciliation-system` / `menu-sheet-generator` / `food-cost-calculation-system`（俺伝）
  / `qr-supply-ordering-system`: 実運用中。標準3経路（または相当）と CI（warning-only、`@ci-v1`）を整備済み。
- `call-reception-assistant`: 設計前。無課金・ローカル完結・外部非接続の初期試作方針。
- 残タスク: H5 引き継ぎドライラン、M1 新PCブートストラップ、M2 gh 認証寿命、M3 俺伝の既定ブランチ依存監査。

## Windowsアプリ標準

Python等のWindowsアプリでは、次を標準確認する。

- 開発版は `RUN_DEV.cmd` 等から正式ソースを直接起動できる。
- EXEが必要な場合は `BUILD_EXE_CLICK_ME.cmd` 等をユーザーが手動実行できる。
- 配布対象では `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` で手動更新できる。
- Codexへ通常のEXEビルドを依頼しない。
- Codexは手動ビルド失敗、EXE固有不具合、実プリンター、共有サーバー、ローカル専用ファイル等の実機問題確認に使う。

T0 / T1で今回の変更にビルド・配布経路が関係しない場合、この標準確認を毎回の固定ゲートとして再実行しない。

## 作業前チェック

- [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) に従って変更ティアと調査・テスト予算を先に決める。
- 対象リポジトリのブランチ、HEAD SHA、未コミット変更を確認する。
- 自分のセッションが持つ能力（`github-rw` / `sandbox-exec` / `windows-real` 等）の確認が必要なら [CAPABILITIES.md](CAPABILITIES.md) を参照し、タスクの必要能力と照合する。
- `windows-real` を持つ場合、正式ソースに触れる前に `git fetch`（必要なら `git pull --ff-only`）、作業後に `git commit` + `git push` する。「編集したが push していない」は未完了工程として扱う。
- [VERSION_MATRIX.md](VERSION_MATRIX.md) は実運用版・デモ機版との一致が今回の作業に関係する場合に確認する。T0 / T1で無関係なら固定ゲートにしない。
- 旧フォルダ、共有版、業務データ、実運用設定を無断で変更対象にしない。
- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) と設計判断は、ティアと影響範囲に応じて必要箇所を読む。
- ChatGPTでGitHub側の作業が完結できるかを先に判断し、可能ならGitHub上で実装・テスト・PRまで進める。
- Windows実機、正式ローカル、プリンター、共有サーバー等が必要な確認だけCodexへ引き継ぐ。
- EXEビルドや配布更新は、原則としてユーザー向けワンクリックスクリプトを整備する。
- 不明点をチャットの記憶だけで補わず、文書・Git差分・動作確認で確かめる。
- 同じセッションで確認済みの開始文書・確立済み事実は、前提が変わらない限り再導出しない。

## 作業中・作業後の記録

- 重要な判断は [docs/decisions.md](docs/decisions.md) に記録する。
- 進行状況と次の作業は [PROJECT_STATUS.md](PROJECT_STATUS.md) と対象の `projects/*.md` に記録する。
- 日々の作業は [DAILY_LOG.md](DAILY_LOG.md) に簡潔に記録する。
- 再発防止に使える知見は [LESSONS_LEARNED.md](LESSONS_LEARNED.md) に記録する。
- 変更履歴は [CHANGELOG.md](CHANGELOG.md) に記録する。
- コードを変更した場合は、対象リポジトリのREADMEも更新する。

T0 / T1のために、変更と無関係な管理文書を形式的に更新しない。記録は「将来の判断に使う事実・運用変更・設計変更」がある場所へ絞る。

## 禁止事項

- チャットだけに重要な判断を残すこと。
- 正式ソース以外で開発すること。
- 秘密情報、認証情報、実運用設定、顧客データ、業務データをGit管理すること。
- GitHub上のテスト成功だけで、Windows実機・EXE・共有版・実プリンターまで確認済みと扱うこと。
- ChatGPTとCodexで同じGitHub実装を理由なく二重に行うこと。
- 単純なEXEビルドのためだけにCodexクレジットを消費すること。
- T0 / T1で開始文書一式、repo全体、他repoの類似実装を理由なく全読みすること。
- targeted failureの診断にfull suiteを使うこと。
- コード変更なしで同じfull suiteを安心のためだけに繰り返すこと。

## 新しいチャットへの標準指示文

> 新しいチャットでは、まず development-management の `AGENT_EFFICIENCY_POLICY.md` を確認し、対象repo / branch / HEAD SHA / dirty treeを確認して変更ティア T0〜T3 を決めてください。
>
> T0 / T1では開始文書一式を機械的に全読みせず、対象READMEまたはprojects文書、対象ファイル、直接の呼び出し元1ホップを基本にしてください。T2は関連する運用・安全文書を追加し、T3だけAI_STARTUPのフル開始チェーンを適用してください。同一セッションで確認済みの文書・確立した事実は前提が変わらない限り再読込・再導出しないでください。
>
> GitHubへ直接アクセスできる場合は、GitHub上で完結する調査・実装・targeted test・ブランチ・PRまでChatGPT側で進めてください。Python/Windowsアプリはソース起動を標準とし、EXEは必要時だけユーザーがワンクリックで手動ビルド、配布更新も専用スクリプトで手動実行できる状態にしてください。通常のEXEビルドはCodexへ依頼しないでください。
>
> T1はtargeted test、T2はtargeted + blast-radius regressionを基本とし、CIがfull suiteをカバーしている場合はCodexローカルでfull suiteを回さないでください。失敗1件の診断にfull suiteを使わず、同じ修正ループは原則2回までにしてください。
>
> Windows実機、正式ローカル、実プリンター、共有サーバー、手動ビルド失敗時の原因調査などが必要な作業だけCodexへ引き継いでください。引き継ぎには変更ティア、確立した事実、棄却した仮説、greenベースライン、回すテスト、回さないテスト、残作業を含めてください。
>
> 重要な判断や作業結果はチャットだけに残さずdevelopment-managementへ記録してください。
