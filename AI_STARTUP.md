# AI Startup

このファイルは、新しいチャットや別のCodex環境が安全に作業を開始するための入口です。

## このリポジトリの役割

`development-management` は、業務システム全体の設計判断、開発ルール、進行状況、AIとの共同開発知識を管理する正式な知識ベースです。コード本体は管理しません。

[AGENTS.md](AGENTS.md) はAIがこのリポジトリで作業する際の短い入口ガイドです。本ファイルは開始時に読む文書と確認順序の正本です。単体タスクを正式プロジェクトへ昇格する場合は [PROJECT_BOOTSTRAP.md](PROJECT_BOOTSTRAP.md) を適用します。

## 開始時の確認順序

1. [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) — AIの役割、思考順序、ChatGPT/Codexの役割分担
2. [AI_CHECKLIST.md](AI_CHECKLIST.md) — 新しいチャット開始時の確認項目
3. [PROMPT_PRINCIPLES.md](PROMPT_PRINCIPLES.md) — 回答・提案・思考品質の基準
4. [AI_MEMORY.md](AI_MEMORY.md) — プロジェクト固有のルール
5. [PROJECT_STATUS.md](PROJECT_STATUS.md) — Current Focus、未確認事項、次の作業
6. [VERSION_MATRIX.md](VERSION_MATRIX.md) — GitHubと実運用版の確認状況
7. [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) — 管理対象と全体構成
8. [docs/decisions.md](docs/decisions.md) — 重要な設計判断
9. [LESSONS_LEARNED.md](LESSONS_LEARNED.md) — 再発防止に使う知見

担当判定と正式ローカルリポジトリの同期規約は [CAPABILITIES.md](CAPABILITIES.md) を参照します（エージェント名ではなく、そのセッションが持つ能力で判定する）。

対象プロジェクトがある場合は、上記に続けて対象の `projects/*.md`、README、Git状態、関連コードを確認します。

## 管理対象と正式ソース

| プロジェクト | 正式ソース | 最新確認タグ |
|---|---|---|
| next-day-setup | `C:\Users\suisy\Documents\Development\repos\next-day-setup` | `v1.1.0` |
| inventory-reconciliation-system | `C:\Users\suisy\Documents\Development\repos\inventory-reconciliation-system` | `v2.0.0` |
| beverage-inventory-ordering-system | `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system` | なし |
| call-reception-assistant | `C:\Users\suisy\Documents\Development\repos\call-reception-assistant` | なし |

タグ欄は最後に管理文書へ反映した確認値であり、実運用中の版との一致は `VERSION_MATRIX.md` と各プロジェクト文書で確認します。

## 現在の重点作業

- `next-day-setup`: 実運用中。GitHubと正式ローカル、共有版の一致を確認しながら継続開発する。
- `inventory-reconciliation-system`: 実運用中。自動実行と運用設定を継続管理する。
- `beverage-inventory-ordering-system`: 現行ブラウザ版を仕様正本としてPython/PySide6版へ段階移行中。GitHubの `python-desktop-migration` / Draft PR #2 で候補版を隔離し、CodexではまずPythonソース版のWindows実機確認を行う。EXEは必要時だけユーザーが手動ビルドし、本番共有版は確認完了まで更新しない。
- `call-reception-assistant`: 初期管理文書を整備済み。アプリ本体は未実装。
- `development-management`: ChatGPTがGitHub側の実装まで担当し、CodexをWindows実機・ローカル環境の問題確認へ優先配分する。Windowsアプリはソース起動、手動EXEビルド、手動配布更新の3経路を標準とする。

## Windowsアプリ標準

Python等のWindowsアプリでは、次を標準確認する。

- 開発版は `RUN_DEV.cmd` 等から正式ソースを直接起動できる。
- EXEが必要な場合は `BUILD_EXE_CLICK_ME.cmd` 等をユーザーが手動実行できる。
- 配布対象では `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` で手動更新できる。
- Codexへ通常のEXEビルドを依頼しない。
- Codexは手動ビルド失敗、EXE固有不具合、実プリンター、共有サーバー、ローカル専用ファイル等の実機問題確認に使う。

## 作業前チェック

- 自分のセッションが持つ能力（`github-rw` / `sandbox-exec` / `windows-real` 等）を [CAPABILITIES.md](CAPABILITIES.md) で確認し、タスクの必要能力と照合する。
- 対象が `Development\repos` 配下の正式ソースであることを確認する。
- 対象リポジトリのブランチ、最新タグ、未コミット変更を確認する。
- `windows-real` を持つ場合、正式ソースに触れる前に `git fetch`（必要なら `git pull --ff-only`）、作業後に `git commit` + `git push` する。「編集したが push していない」は未完了工程として扱う。
- [VERSION_MATRIX.md](VERSION_MATRIX.md)でGitHub、実運用版、デモ機版の一致状況を確認する。
- 旧フォルダ、共有版、業務データ、実運用設定を無断で変更対象にしない。
- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) と関連する設計判断を読む。
- ChatGPTでGitHub側の作業が完結できるかを先に判断し、可能ならGitHub上で実装・テスト・PRまで進める。
- Windows実機、正式ローカル、プリンター、共有サーバー等が必要な確認だけCodexへ引き継ぐ。
- EXEビルドや配布更新は、原則としてユーザー向けワンクリックスクリプトを整備する。
- 不明点をチャットの記憶だけで補わず、文書・Git差分・動作確認で確かめる。

## 作業中・作業後の記録

- 重要な判断は [docs/decisions.md](docs/decisions.md) に記録する。
- 進行状況と次の作業は [PROJECT_STATUS.md](PROJECT_STATUS.md) と対象の `projects/*.md` に記録する。
- 日々の作業は [DAILY_LOG.md](DAILY_LOG.md) に簡潔に記録する。
- 再発防止に使える知見は [LESSONS_LEARNED.md](LESSONS_LEARNED.md) に記録する。
- 変更履歴は [CHANGELOG.md](CHANGELOG.md) に記録する。
- コードを変更した場合は、対象リポジトリのREADMEも更新する。

## 禁止事項

- チャットだけに重要な判断を残すこと。
- 正式ソース以外で開発すること。
- 秘密情報、認証情報、実運用設定、顧客データ、業務データをGit管理すること。
- GitHub上のテスト成功だけで、Windows実機・EXE・共有版・実プリンターまで確認済みと扱うこと。
- ChatGPTとCodexで同じGitHub実装を理由なく二重に行うこと。
- 単純なEXEビルドのためだけにCodexクレジットを消費すること。

## 新しいチャットへの標準指示文

> 新しいチャットでは、まず development-management リポジトリを確認してください。
>
> AI_OPERATING_MANUAL.md、AI_CHECKLIST.md、PROMPT_PRINCIPLES.md、AI_MEMORY.md、PROJECT_STATUS.md、VERSION_MATRIX.md、SYSTEM_OVERVIEW.md、docs/decisions.md、LESSONS_LEARNED.md を順番に読み、必要に応じて対象の projects/*.md と対象リポジトリを確認してください。
>
> GitHubへ直接アクセスできる場合は、GitHub上で完結する調査・実装・テスト・ブランチ・PRまでChatGPT側で進めてください。Python/Windowsアプリはソース起動を標準とし、EXEは必要時だけユーザーがワンクリックで手動ビルド、配布更新も専用スクリプトで手動実行できる状態にしてください。通常のEXEビルドはCodexへ依頼しないでください。
>
> Windows実機、正式ローカル、実プリンター、共有サーバー、手動ビルド失敗時の原因調査などが必要な作業だけCodexへ引き継いでください。
>
> 現在の進行状況、正式ソース、未完了作業、未コミット変更を把握してから作業を開始し、重要な判断や作業結果はチャットだけに残さずdevelopment-managementへ記録してください。
