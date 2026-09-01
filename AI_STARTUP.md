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
- `beverage-inventory-ordering-system`: 現行ブラウザ版を仕様正本としてPython/PySide6版へ段階移行中。GitHubの `python-desktop-migration` / Draft PR #2 で候補版を隔離し、Windows実機・EXE・共有サーバー確認前は本番へマージしない。
- `call-reception-assistant`: 初期管理文書を整備済み。アプリ本体は未実装。
- `development-management`: ChatGPTがGitHub側の実装まで担当し、CodexをWindows実機・ローカル環境作業へ優先配分する新しい分業を正式運用とする。

## 作業前チェック

- 対象が `Development\repos` 配下の正式ソースであることを確認する。
- 対象リポジトリのブランチ、最新タグ、未コミット変更を確認する。
- [VERSION_MATRIX.md](VERSION_MATRIX.md)でGitHub、実運用版、デモ機版の一致状況を確認する。
- 旧フォルダ、共有版、業務データ、実運用設定を無断で変更対象にしない。
- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) と関連する設計判断を読む。
- ChatGPTでGitHub側の作業が完結できるかを先に判断し、可能ならGitHub上で実装・テスト・PRまで進める。
- Windows実機、正式ローカル、EXE、プリンター、共有サーバーが必要な作業だけCodexへ引き継ぐ。
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
- GitHub上のテスト成功だけで、Windows実機・共有版・実プリンターまで確認済みと扱うこと。
- ChatGPTとCodexで同じGitHub実装を理由なく二重に行うこと。

## 新しいチャットへの標準指示文

> 新しいチャットでは、まず development-management リポジトリを確認してください。
>
> AI_OPERATING_MANUAL.md、AI_CHECKLIST.md、PROMPT_PRINCIPLES.md、AI_MEMORY.md、PROJECT_STATUS.md、VERSION_MATRIX.md、SYSTEM_OVERVIEW.md、docs/decisions.md、LESSONS_LEARNED.md を順番に読み、必要に応じて対象の projects/*.md と対象リポジトリを確認してください。
>
> GitHubへ直接アクセスできる場合は、GitHub上で完結する調査・実装・テスト・ブランチ・PRまでChatGPT側で進めてください。Windows実機、正式ローカル、EXEビルド、実プリンター、共有サーバーなどが必要な作業だけCodexへ引き継いでください。
>
> 現在の進行状況、正式ソース、未完了作業、未コミット変更を把握してから作業を開始し、重要な判断や作業結果はチャットだけに残さずdevelopment-managementへ記録してください。
