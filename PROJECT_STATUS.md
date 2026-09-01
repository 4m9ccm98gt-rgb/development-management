# プロジェクト状況

最終更新: 2026-09-01（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | 現行ブラウザ版を仕様正本としてPython/PySide6版へ段階移行中。`python-desktop-migration` / Draft PR #2で候補版を隔離。次はPythonソース版のWindows実機確認。EXEは必要時だけユーザーが手動ビルドし、共有配布更新も専用スクリプトで手動実行する。 |
| call-reception-assistant | 初期管理文書を整備済み。アプリ本体は未実装。 |
| menu-sheet-generator | 実運用中。PMS CSVからの帳票生成と共有フォルダ配布を継続運用。 |
| development-management | ChatGPTをGitHub側の第一実装担当、Codexを実機問題確認の第一担当とする。Python/Windowsアプリはソース起動・手動EXEビルド・手動配布更新の3経路を共通標準化。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- GitHub上で完結する調査・設計・実装・テスト・branch・commit・push・PR・レビューは、GitHubへ直接アクセスできるChatGPTが原則担当する。
- CodexはWindows実機、正式ローカル、実プリンター、共有サーバー、ローカル専用ファイル、手動ビルド失敗時の原因調査などへ優先して使用する。
- 通常のEXEビルドはCodex担当から外す。Python/Windowsアプリは正式ソースから直接起動できる状態を維持し、EXEは必要時だけユーザーがワンクリックで手動ビルドする。
- 配布対象のWindowsアプリは、配布先更新用 `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須とする。
- GitHub上の自動テスト、Pythonソース版Windows実機確認、EXE確認、共有版・実プリンター確認を別の確認レベルとして扱う。
- PR merge、安定版タグ、本番共有版更新は、必要な確認と明示的な判断後に行う。
- `beverage-inventory-ordering-system` はブラウザ版からPython/PySide6版への移行を開始。現行JSON互換を維持し、共有サーバー上の1つのJSONを全PCで利用する構成を候補として実装中。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## 進行中の作業

- `beverage-inventory-ordering-system`: GitHub `python-desktop-migration` / Draft PR #2でPython候補版を実装。旧JSON互換、在庫計算、売上CSV、棚卸、レシピ、定期消費、発注、商品マスタ、共有JSONロック・backup・atomic replace、PySide6 UI等を実装済み。2026-09-01の実運用JSONでローカルpytest 11件成功、主要コレクションの保存・再読込一致を確認済み。次はWindows実機でPythonソース版を起動し、GUI・実データ・共有保存を確認する。EXEはその後、必要時にユーザーが手動ビルドする。
- `next-day-setup`: 実運用を維持しながら継続開発。
- `inventory-reconciliation-system`: 自動実行と運用設定の継続管理。
- `call-reception-assistant`: アプリ本体の設計・実装待ち。

## 完了済み作業

- `development-management` のGitHub運用開始とAI共同開発基盤の整備。
- 正式ソースを `Development\repos` 配下へ統一。
- ChatGPT / Codexの役割分担を2026-09-01に更新。ChatGPTがGitHub側実装まで担当し、Codexを実機作業へ優先配分する運用を正式化。
- 2026-09-01にWindowsアプリの標準を追加。日常開発はPythonソース起動、EXEはユーザーの手動ワンクリックビルド、配布先更新も専用ワンクリックスクリプトとし、通常のEXEビルドをCodex担当から外した。
- `beverage-inventory-ordering-system` の旧GAS共有保存案 Draft PR #1を未mergeでclose。
- `beverage-inventory-ordering-system` のPython移行 branch `python-desktop-migration` とDraft PR #2を作成。
- menu-sheet-generator、next-day-setup、inventory-reconciliation-system等の既存業務システムを継続管理。

## 未確認項目

- `beverage-inventory-ordering-system` Python版のWindows実機PySide6表示。
- 現行ブラウザ版とPython版の在庫・要発注・発注履歴の全件突合。
- Python版棚卸表の実プリンター確認。
- 共有サーバー上からの直接起動と2台以上のPCによる同時更新試験。
- Python版の手動EXEビルド経路のWindows確認。
- Python版の配布先更新スクリプト整備・安全確認。
- `apps/ordering/` の業者/FAX機能とPython在庫側の統合。
- GASスマホ棚卸連携。

## 次にやること

1. `beverage-inventory-ordering-system` の `python-desktop-migration` を正式ローカルへ取得する。
2. CodexまたはWindows実機でPythonソース版を起動し、テスト・GUI・実運用JSON互換を確認する。Codexには通常のEXEビルドをさせない。
3. 共有保存をローカル模擬環境で確認する。
4. 必要な修正をChatGPT側でGitHubへ反映する。
5. Python版に `UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` を整備する。
6. EXE固有確認が必要な段階で、ユーザーが `BUILD_EXE_CLICK_ME.cmd` を手動実行する。
7. 共有サーバーのテスト領域へユーザーが専用更新スクリプトで配布し、複数PC更新を確認する。
8. 問題がなければPython版の本番切替判断を行う。
9. その後、GASスマホ棚卸と発注システム統合へ進む。
