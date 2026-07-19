# AI向け引き継ぎ

## 最重要事項

- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下のみ。
- 管理対象は `next-day-setup` と `inventory-reconciliation-system`。
- 旧フォルダは参照専用。変更禁止。
- コード本体は各業務リポジトリにあり、本リポジトリには置かない。

## 現在の安定版

- `next-day-setup`: 最新確認タグ `v1.1.0`
- `inventory-reconciliation-system`: 最新確認タグ `v2.0.0`

これは2026-07-16にローカルGitで確認した最新タグです。実運用中の版との一致、タグ以後の未コミット変更の安定性は未確認です。

## 進行中作業

- `next-day-setup`: Google Sheetsシフト取得、印刷、ビルド、共有版更新。
- `inventory-reconciliation-system`: Google Sheets休館日取得、キャッシュ、夜間自動実行、警告メール。
- 両方に未コミット変更あり。変更内容の確定、テスト、実運用確認が必要。

## 変更禁止領域

- 旧フォルダ、共有版上での直接開発、業務データ、顧客データ、実運用設定、認証情報。
- 本リポジトリでの業務コード・業務ロジック管理。

## 配布方法

`next-day-setup` の正式ソースから `dist\DinnerSystem` をビルドし、専用スクリプトで共有版を更新します。`_internal` は完全同期し、共有フォルダ全体への単純な `/MIR` は使いません。詳細は [deployment.md](deployment.md) を参照してください。

## Git管理外の情報

秘密情報、Google等の認証情報、実運用設定、共有先パス、顧客データ、業務データ、実行ログ、出力物、キャッシュはGit管理しません。必要な値は現地環境で安全に確認します。

## 新規チャット開始時の確認手順

1. `README.md`、`PROJECT_STATUS.md`、`AI_STARTUP.md`を読む。
2. `AI_MEMORY.md`でユーザー固有の開発方針と報告ルールを確認する。
3. 本ファイルと対象の`projects/*.md`を読む。
4. `VERSION_MATRIX.md`でタグ、最新コミット、実運用版の確認状況を確認する。
5. `REPOSITORIES.md`と正式ソースのREADME、現在のブランチ、最新タグ、未コミット変更を確認する。
6. `DEVELOPMENT_RULES.md`と関連する設計判断・配布・障害対応文書を読む。
7. 未確認事項を推測で確定せず、検証してから作業する。

## 標準指示文

> この development-management リポジトリの README.md、PROJECT_STATUS.md、AI_STARTUP.md、AI_MEMORY.md、docs/ai_handoff.md、VERSION_MATRIX.md を最初に確認してください。
>
> その後、今回対象となるプロジェクトの projects/*.md と対象リポジトリ本体を確認し、現在の進行状況・正式ソース・未完了作業を把握してから作業してください。
