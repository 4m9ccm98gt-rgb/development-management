# AI向け引き継ぎ

## 最重要事項

- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下のみ。
- 管理対象は10リポジトリ（[REPOSITORIES.md](../REPOSITORIES.md) / [PROJECT_STATUS.md](../PROJECT_STATUS.md)）。
  種別の唯一の正は [scripts/repo_types.toml](../scripts/repo_types.toml)。
- 旧フォルダは参照専用。変更禁止（[pc_repo_audit.md](pc_repo_audit.md)）。
- コード本体は各業務リポジトリにあり、本リポジトリには置かない。
- 担当はエージェント名ではなく能力で判定（[CAPABILITIES.md](../CAPABILITIES.md)）。
- 開発補助ツール Claude Code の提供終了が近いため、退役前整備 H1〜H7 を完了済み
  （[PROJECT_STATUS.md](../PROJECT_STATUS.md) の該当節）。

## 現在の安定版（2026-09-04 時点）

- `next-day-setup`: tag `v1.2.1`、main `1b048f4`
- `inventory-reconciliation-system`: tag `v2.0.0`、main `fd2de21`
- `menu-sheet-generator`: tag `v1.0.0`、main `fa4fdf7`
- `food-cost-calculation-system`（俺伝）: タグなし、既定ブランチ `main` `1940db0`（2026-09-04 M3 で `codex/bootstrap-invoice-reading` から改名）
- `beverage-inventory-ordering-system`: タグなし、作業ブランチ `python-desktop-migration` `e458476`（upstream と同期）
- `qr-supply-ordering-system`: タグなし、main `790fff5`

実運用中の版との一致、タグ以後の変更の安定性は [VERSION_MATRIX.md](../VERSION_MATRIX.md) と
各 `projects/*.md` で確認する（未確認は「未確認」と明記）。

## 進行中作業

- 退役前整備の残り: H5 引き継ぎドライラン、M1 新PCブートストラップ、M2 gh 認証寿命、M3 俺伝の既定ブランチ依存監査。
- `beverage-inventory-ordering-system`: Python/PySide6 版の Windows 実機確認、Draft PR #2 の merge 可否判断。
- `recovery/from-old-clone-docs`（Draft PR）: 正本への取り込み範囲決定。
- 実運用5アプリは標準3経路（または相当）と CI（warning-only、`@ci-v1`）を整備済み。

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
