# プロジェクト状況

最終更新: 2026-07-20（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。ケーキ発注書自動印刷をExcel自動印刷へ統合済み。確認画面は廃止し、夕食印刷後に自動判定・自動印刷する。GitHub反映済み。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、メール送信時間など細かな調整を行う。 |
| beverage-inventory-ordering-system | 現行運用版を正式リポジトリ化する。Windows ACLを解消後、正式ソースへ移行し、初回push、その後に飲料発注システムを統合する。 |
| development-management | GitHub初回push済み、main運用中。AI共同開発の司令塔として継続更新する。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 各システムは独立リポジトリで管理し、設計・運用・履歴・AI引き継ぎは本リポジトリへ記録する。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- `next-day-setup` はケーキ発注書自動印刷まで実装・実運用・GitHub反映済み。
- `inventory-reconciliation-system` は実運用中で、自動実行も概ね安定している。
- `beverage-inventory-ordering-system` のGitHubリポジトリは作成済みだが空。現行運用版はCodex配下にあり、正式ソース移行前。

## 進行中の作業

- `beverage-inventory-ordering-system`: Windows ACLの解消。
- `beverage-inventory-ordering-system`: 現行運用版を正式ソースへ移行し、構成・データ・Git管理対象を整理する。
- `beverage-inventory-ordering-system`: README、`.gitignore`、初回コミット・pushを実施する。
- `beverage-inventory-ordering-system`: 正式化後に飲料発注システム統合へ進む。
- `inventory-reconciliation-system`: メール送信時間など細かな運用調整。

## 完了済み作業

- `development-management` の初回pushとmain運用開始。
- `AI_STARTUP.md`、`AI_MEMORY.md`、`VERSION_MATRIX.md`、`SYSTEM_OVERVIEW.md`等の管理文書整備。
- `next-day-setup` のケーキ発注書自動印刷を実装し、Excel自動印刷へ統合。
- `next-day-setup` の確認画面を廃止し、夕食印刷後の自動判定・自動印刷へ移行。
- `next-day-setup` の変更をGitHubへ反映。
- `inventory-reconciliation-system` の実運用と自動実行を概ね安定化。
- `beverage-inventory-ordering-system` のGitHub空リポジトリを作成。
- 飲料在庫管理の現行版でブラウザ保存と発注中数量を加味した要発注判定を実装し、運用開始。
- 新規フォルダ作成失敗の原因をWindows ACLと特定。
- `projects/beverage-inventory-ordering-system.md` を作成。

## 未確認項目

- `Development\repos` または新規プロジェクトフォルダへの `CodexSandboxUsers` の `Modify` 権限付与。
- 現行飲料在庫管理システムの正確なファイル構成とGit管理対象。
- ブラウザ保存データの移行時保持方法と正式な保存仕様。
- 正式ソース移行後の起動・保存・要発注判定の動作確認。
- 飲料発注システム統合の対象機能、データ構造、運用フロー。
- `inventory-reconciliation-system` のメール送信時間の最終設定。

## 次にやること

1. Windows側で `Development\repos` または `beverage-inventory-ordering-system` フォルダに `CodexSandboxUsers` の `Modify` 権限を付与する。
2. 現行運用版を `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system` へ移行する。
3. ファイル構成、保存データ、秘密情報、生成物を確認し、READMEと`.gitignore`を整備する。
4. 正式ソースで動作確認後、GitHubへ初回コミット・pushする。
5. 結果を本ファイル、対象プロジェクト文書、`CHANGELOG.md`、必要に応じて`VERSION_MATRIX.md`へ反映する。
6. 飲料発注システム統合の設計に進む。
