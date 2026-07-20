# プロジェクト状況

最終更新: 2026-07-20（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。ケーキ発注書自動印刷をExcel自動印刷へ統合済み。確認画面は廃止し、夕食印刷後に自動判定・自動印刷する。GitHub反映済み。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、メール送信時間など細かな調整を行う。 |
| beverage-inventory-ordering-system | 正式ソースとGitHubの同期完了。次は飲料発注アプリの取り込み調査を行う。 |
| development-management | GitHub初回push済み、main運用中。AI共同開発の司令塔として継続更新する。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 各システムは独立リポジトリで管理し、設計・運用・履歴・AI引き継ぎは本リポジトリへ記録する。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- `next-day-setup` はケーキ発注書自動印刷まで実装・実運用・GitHub反映済み。
- `inventory-reconciliation-system` は実運用中で、自動実行も概ね安定している。
- `beverage-inventory-ordering-system` は正式ソースを確定し、アプリ本体と文書をGitHubへ反映済み。ローカル`main`もGitHub `main`（`8d2ab9c`）へ同期済み。

## 進行中の作業

- `beverage-inventory-ordering-system`: 飲料発注アプリの正式ソース、機能、データ構造、保存方式、運用フローを読み取り専用で調査する。
- `beverage-inventory-ordering-system`: 在庫管理側との共通商品マスタと段階的な統合手順を設計する。
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
- 飲料在庫管理の現行版でブラウザ保存と発注中数量を加味した要発注判定を実装し、運用開始。
- 新規フォルダ作成失敗の原因をWindows ACLと特定。
- `projects/beverage-inventory-ordering-system.md` を作成。

## 未確認項目

- ブラウザ保存データの移行時保持方法と正式な保存仕様。
- 飲料発注システム統合の対象機能、データ構造、運用フロー。
- `inventory-reconciliation-system` のメール送信時間の最終設定。

## 次にやること

1. 飲料発注アプリの正式ソースと現行運用版を特定する。
2. 機能、商品データ、発注設定、履歴、保存方式、運用フローを読み取り専用で調査する。
3. 在庫管理側との商品識別子、名称、単位、入数を比較し、共通商品マスタの移行対応表を作成する。
4. 複数PC共有を前提とした保存方式と、既存在庫データを保護する段階的な統合手順を設計する。
