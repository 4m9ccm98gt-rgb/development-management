# development-management

## AI Startup

新しいチャットでは、作業を始める前に次の順番で確認します。

1. [PROJECT_STATUS.md](PROJECT_STATUS.md)
2. [AI_STARTUP.md](AI_STARTUP.md)
3. [AI_MEMORY.md](AI_MEMORY.md)
4. [docs/ai_handoff.md](docs/ai_handoff.md)
5. 対象プロジェクトの `projects/*.md`
6. [VERSION_MATRIX.md](VERSION_MATRIX.md)
7. 必要に応じて対象リポジトリ本体

短い開始手順と確認事項は [AI_STARTUP.md](AI_STARTUP.md) にまとめています。

## 目的

このリポジトリは、業務システム全体の設計判断・開発ルール・進行状況・AIとの共同開発知識を管理する正式な知識ベースです。

コードではなく「開発知識」を管理することを目的とします。コード本体、業務ロジック、秘密情報、実運用設定、顧客データ、業務データは置きません。

## 最初に読むファイル

1. [PROJECT_STATUS.md](PROJECT_STATUS.md) — 全体の現在地と次の作業
2. [AI_STARTUP.md](AI_STARTUP.md) — 新規チャットの開始手順
3. [AI_MEMORY.md](AI_MEMORY.md) — ユーザー固有の開発方針と報告ルール
4. [docs/ai_handoff.md](docs/ai_handoff.md) — AI／新規担当者向けの短い引き継ぎ
5. 対象プロジェクトの `projects/*.md` — 個別状況
6. [VERSION_MATRIX.md](VERSION_MATRIX.md) — GitHub、実運用版、デモ機版の対応
7. [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) — 作業前に守るルール
8. 必要に応じて対象リポジトリ本体のREADMEとGit状態

## 管理対象プロジェクト

| プロジェクト | 役割 | 状況ファイル |
|---|---|---|
| next-day-setup | 翌日準備、席割・担当割、帳票・印刷 | [projects/next-day-setup.md](projects/next-day-setup.md) |
| inventory-reconciliation-system | PMS・手間いらず・JTBの販売在庫照合 | [projects/inventory-reconciliation-system.md](projects/inventory-reconciliation-system.md) |

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
> 1. README.md
> 2. PROJECT_STATUS.md
> 3. AI_STARTUP.md
> 4. AI_MEMORY.md
> 5. docs/ai_handoff.md
> 6. 対象プロジェクト（projects/*.md）
> 7. VERSION_MATRIX.md
> 8. 必要に応じて対象リポジトリ
>
> その後、現在の進行状況・正式ソース・未完了作業を把握してから作業を開始してください。正式ソース以外は変更せず、重要な判断は development-management に記録してください。
