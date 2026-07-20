# プロジェクト状況

最終更新: 2026-07-20（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。ケーキ発注書の休館日前倒しと緊急用の受取日指定手動印刷を実装し、開発環境テスト済み。実運用確認・GitHub反映は未実施。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、メール送信時間など細かな調整を行う。 |
| beverage-inventory-ordering-system | 飲料在庫管理＋飲料発注システムとして管理。発注システムを `apps/ordering/` へ移管済み。発注システムは開発中。 |
| development-management | GitHub初回push済み、main運用中。AI共同開発の司令塔として継続更新する。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 各システムは独立リポジトリで管理し、設計・運用・履歴・AI引き継ぎは本リポジトリへ記録する。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- `next-day-setup` はケーキ発注書自動印刷まで実装・実運用・GitHub反映済み。
- `inventory-reconciliation-system` は実運用中で、自動実行も概ね安定している。
- `beverage-inventory-ordering-system` は飲料在庫管理＋飲料発注システムとして管理する。飲料発注システムは独立プロジェクトにせず、同一リポジトリ内の `apps/ordering/` サブシステムとして継続開発する。

## 進行中の作業

- `next-day-setup`: ケーキ発注書の休館日前倒し印刷を実装済み。実Excel／プリンター、画面警告、EXE・共有版での確認待ち。
- `beverage-inventory-ordering-system`: `apps/ordering/` へ移管した飲料発注システムを開発中として、在庫管理側との共通商品マスタ・発注履歴統合を段階的に進める。
- `inventory-reconciliation-system`: メール送信時間など細かな運用調整。

## 完了済み作業

- `development-management` の初回pushとmain運用開始。
- `AI_STARTUP.md`、`AI_MEMORY.md`、`VERSION_MATRIX.md`、`SYSTEM_OVERVIEW.md`等の管理文書整備。
- `next-day-setup` のケーキ発注書自動印刷を実装し、Excel自動印刷へ統合。
- `next-day-setup` の確認画面を廃止し、夕食印刷後の自動判定・自動印刷へ移行。
- `next-day-setup` の変更をGitHubへ反映。
- `inventory-reconciliation-system` の実運用と自動実行を概ね安定化。
- `beverage-inventory-ordering-system` の正式ソースを確定し、アプリ本体、初期マスタ、運用文書をGitHubへ反映。
- `beverage-inventory-ordering-system` のローカル`main`をGitHub `main`（`8d2ab9c`）へfast-forwardし、同期後の起動・JavaScript構文・クリーンなGit状態を確認。
- `beverage-inventory-ordering-system` へ開発途中の飲料発注システムを `apps/ordering/` サブシステムとして移管。README、docs、AI引き継ぎを在庫管理＋発注システム構成へ更新。
- 飲料在庫管理の現行版でブラウザ保存と発注中数量を加味した要発注判定を実装し、運用開始。
- 新規フォルダ作成失敗の原因をWindows ACLと特定。
- `projects/beverage-inventory-ordering-system.md` を作成。

## 未確認項目

- ブラウザ保存データの移行時保持方法と正式な保存仕様。
- 飲料発注システムと在庫管理側の商品マスタ・発注履歴の統合仕様。
- `inventory-reconciliation-system` のメール送信時間の最終設定。

## 次にやること

1. `apps/ordering/` の発注システムを、在庫管理側の商品マスタ・発注履歴とどう統合するか設計する。
2. 実業者名、実FAX番号、実発注履歴をGit管理しない前提で、実運用データの安全な投入・移行手順を決める。
3. 複数PC共有を前提とした保存方式と、既存在庫データを保護する段階的な統合手順を設計する。
