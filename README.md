# development-management

Current stable version: **v1.0.0**

## AI Startup

新しいチャットでは、作業を始める前に次の順番で確認します。

1. [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md)
2. [AI_CHECKLIST.md](AI_CHECKLIST.md)
3. [PROMPT_PRINCIPLES.md](PROMPT_PRINCIPLES.md)
4. [AI_MEMORY.md](AI_MEMORY.md)
5. [PROJECT_STATUS.md](PROJECT_STATUS.md)
6. [VERSION_MATRIX.md](VERSION_MATRIX.md)
7. [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)
8. [docs/decisions.md](docs/decisions.md)
9. [LESSONS_LEARNED.md](LESSONS_LEARNED.md)

短い開始手順と確認事項は [AI_STARTUP.md](AI_STARTUP.md) にまとめています。

## AI関連ドキュメント

- [AGENTS.md](AGENTS.md) — このリポジトリで作業するAI向けの入口ガイド
- [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) — AIの役割、思考順序、Codexとの役割分担
- [AI_CHECKLIST.md](AI_CHECKLIST.md) — 新しいチャット開始時の確認チェックリスト
- [PROMPT_PRINCIPLES.md](PROMPT_PRINCIPLES.md) — ユーザーが期待する回答・提案・思考品質の基準
- [AI_STARTUP.md](AI_STARTUP.md) — 新規チャットの開始手順と読む順番
- [AI_MEMORY.md](AI_MEMORY.md) — プロジェクト固有のルール
- [docs/ai_handoff.md](docs/ai_handoff.md) — AI／新規担当者向けの短い引き継ぎ

## 開発運用文書一覧
- [docs/operator_runbook.md](docs/operator_runbook.md) — 非コーダー向け。日常操作と困ったときの相談のしかた
- [docs/dev_doctor.md](docs/dev_doctor.md) / [docs/backup_restore.md](docs/backup_restore.md) — 実機ヘルスチェックとバックアップ・復元
- [docs/github_auth.md](docs/github_auth.md) — GitHub 認証（`gh` と `git`/GCM の2系統）の構成・失効条件・再設定
- [docs/food_cost_default_branch.md](docs/food_cost_default_branch.md) — 俺伝の既定ブランチ（`codex/bootstrap-invoice-reading` → `main`）監査と移行手順
- [docs/pc_repo_audit.md](docs/pc_repo_audit.md) / [docs/git_external_data_inventory.md](docs/git_external_data_inventory.md) — PC 上の repo 監査と Git 管理外データ棚卸し
- [docs/ci_action_versioning.md](docs/ci_action_versioning.md) — 共通 CI アクションのタグ運用
- [docs/build_deploy_paths.md](docs/build_deploy_paths.md) — 各アプリの BUILD/DEPLOY/UPDATE 経路と非本番実地検証（H7）・fail-safe 一覧

- [PROJECT_BOOTSTRAP.md](PROJECT_BOOTSTRAP.md) — 単体タスクを正式プロジェクトへ昇格する標準手順
- [VERSIONING.md](VERSIONING.md) — バージョン番号とリリース運用の基準
- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) — 開発時に守る共通ルール
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — リリース前の確認項目
- [DECISION_TEMPLATE.md](DECISION_TEMPLATE.md) — 重要な設計判断の記録テンプレート
- [ISSUE_TEMPLATE.md](ISSUE_TEMPLATE.md) — 調査・実装依頼の整理テンプレート

## 目的

`development-management` は、AIと人が継続的に共同開発するための「AI共同開発基盤」（AI Collaborative Development Framework）です。

このリポジトリは、業務システム全体の設計判断・開発ルール・進行状況・AIとの共同開発知識を管理する正式な知識ベースです。

コードではなく「開発知識」を管理することを目的とします。コード本体、業務ロジック、秘密情報、実運用設定、顧客データ、業務データは置きません。

## 最初に読むファイル

開始時は [AI_STARTUP.md](AI_STARTUP.md) を入口とし、次の順序で読みます。

1. [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) — AIの役割と運用基準
2. [AI_CHECKLIST.md](AI_CHECKLIST.md) — 開始時の確認項目
3. [PROMPT_PRINCIPLES.md](PROMPT_PRINCIPLES.md) — 回答・提案・思考品質の基準
4. [AI_MEMORY.md](AI_MEMORY.md) — プロジェクト固有のルール
5. [PROJECT_STATUS.md](PROJECT_STATUS.md) — 全体の現在地と次の作業
6. [VERSION_MATRIX.md](VERSION_MATRIX.md) — GitHub、実運用版、デモ機版の対応
7. [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) — 管理対象と全体構成
8. [docs/decisions.md](docs/decisions.md) — 重要な設計判断
9. [LESSONS_LEARNED.md](LESSONS_LEARNED.md) — 再発防止に使う知見

対象プロジェクトがある場合は、続けて対象の `projects/*.md`、README、Git状態、関連する管理文書を確認します。

## 管理対象プロジェクト

| プロジェクト | 役割 | 状況ファイル |
|---|---|---|
| next-day-setup | 翌日準備、席割・担当割、帳票・印刷 | [projects/next-day-setup.md](projects/next-day-setup.md) |
| inventory-reconciliation-system | PMS・手間いらず・JTBの販売在庫照合 | [projects/inventory-reconciliation-system.md](projects/inventory-reconciliation-system.md) |
| beverage-inventory-ordering-system | 飲料在庫管理＋飲料発注システム | [projects/beverage-inventory-ordering-system.md](projects/beverage-inventory-ordering-system.md) |
| call-reception-assistant | 旅館の電話受付支援・将来自動化 | [projects/call-reception-assistant.md](projects/call-reception-assistant.md) |
| menu-sheet-generator | PMS CSV から料理説明書（帳票）を生成・印刷する対話型アプリ | [projects/menu-sheet-generator.md](projects/menu-sheet-generator.md) |
| hospitality-review-reply | 旅館口コミ返信のテンプレート／知識リポジトリ。**アプリではない（knowledge repository / runtime 標準対象外）**。CI は秘密情報チェックのみ | — |

正式なローカルパスは [REPOSITORIES.md](REPOSITORIES.md) を参照してください。

## 更新ルール

- コード変更と同じ作業単位で、対象プロジェクトの README、`projects/*.md`、必要に応じて `PROJECT_STATUS.md` と `CHANGELOG.md` を更新する。
- `PROJECT_STATUS.md` の最終更新日時と「次にやること」を古いまま残さない。
- 設計上の重要判断は `docs/decisions.md` に理由と影響を残す。
- 安定版タグ、配布状況、実運用確認は、確認できた事実だけを記載する。
- 秘密情報、実運用設定、顧客データ、業務データは記載・コミットしない。

## 新しいチャットでの使い方

次の標準開始手順を新しいチャットの冒頭に貼り付けます。

> 新しいチャットでは、まず development-management リポジトリを確認してください。
>
> 確認順序
>
> 1. AI_OPERATING_MANUAL.md
> 2. AI_CHECKLIST.md
> 3. PROMPT_PRINCIPLES.md
> 4. AI_MEMORY.md
> 5. PROJECT_STATUS.md
> 6. VERSION_MATRIX.md
> 7. SYSTEM_OVERVIEW.md
> 8. docs/decisions.md
> 9. LESSONS_LEARNED.md
>
> その後、必要に応じて対象の projects/*.md と対象リポジトリを確認し、現在の進行状況・正式ソース・未完了作業を把握してから作業を開始してください。正式ソース以外は変更せず、重要な判断は development-management に記録してください。
