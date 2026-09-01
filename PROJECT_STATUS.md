# プロジェクト状況

最終更新: 2026-09-01（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | Pythonソース版のWindows実機確認・共有保存模擬・UPD導線整備まで完了。`python-desktop-migration` HEADは`94f0b5f`。次は現行ブラウザ版から最新実運用JSONを再出力して全件突合し、`development-management` の正式ローカルcloneを復旧する。EXEは必要時だけユーザーが手動ビルドする。 |
| call-reception-assistant | 初期管理文書を整備済み。アプリ本体は未実装。 |
| menu-sheet-generator | 実運用中。PMS CSVからの帳票生成と共有フォルダ配布を継続運用。 |
| development-management | ChatGPTをGitHub側の第一実装担当、Codexを実機問題確認の第一担当とする。Python/Windowsアプリはソース起動・手動EXEビルド・手動配布更新の3経路を共通標準化。正式ローカルclone不在が判明したため復旧対象。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- GitHub上で完結する調査・設計・実装・テスト・branch・commit・push・PR・レビューは、GitHubへ直接アクセスできるChatGPTが原則担当する。
- CodexはWindows実機、正式ローカル、実プリンター、共有サーバー、ローカル専用ファイル、手動ビルド失敗時の原因調査などへ優先して使用する。
- 通常のEXEビルドはCodex担当から外す。Python/Windowsアプリは正式ソースから直接起動できる状態を維持し、EXEは必要時だけユーザーがワンクリックで手動ビルドする。
- 配布対象のWindowsアプリは、配布先更新用 `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須とする。
- GitHub上の自動テスト、Pythonソース版Windows実機確認、EXE確認、共有版・実プリンター確認を別の確認レベルとして扱う。
- PR merge、安定版タグ、本番共有版更新は、必要な確認と明示的な判断後に行う。
- `beverage-inventory-ordering-system` はブラウザ版からPython/PySide6版への移行を開始し、Windows Pythonソース版確認まで到達。現行JSON互換を維持し、共有サーバー上の1つのJSONを全PCで利用する構成を候補としている。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## 進行中の作業

- `beverage-inventory-ordering-system`: `python-desktop-migration` / Draft PR #2。Windows正式ローカルでPython 3.13.14 / PySide6 6.8.3、pytest 11 passed / 1 skipped、RUN_DEV起動、主要GUI、ファイルダイアログ、Windows/UNCパス、共有保存のlock/backup/atomic replace、2インスタンス変更検知、2プロセス同時更新を確認済み。`UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` も追加しPowerShell 5.1模擬確認済み。CodexはEXEをビルドしていない。PC内で見つかったJSONは50件版で、ChatGPT側の66件・発注履歴130件版とは別物のため最新実運用全件比較は未完了。
- `development-management`: GitHub正本は更新済みだが、Codex確認時に `C:\Users\suisy\Documents\Development\repos\development-management` のローカルcloneが存在しなかった。Codexが最新運用ルールを開始時に読めるよう正式ローカルcloneを復旧する。
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
- `beverage-inventory-ordering-system` のWindows Pythonソース版・共有保存模擬・UPD導線整備をcommit `94f0b5f`で確認。
- menu-sheet-generator、next-day-setup、inventory-reconciliation-system等の既存業務システムを継続管理。

## 未確認項目

- 現行ブラウザ版から再出力した最新実運用JSONを使ったPython版全件突合。
- 66件版相当の実運用データで売上履歴・発注履歴・商品マスタを含む比較。
- Python版棚卸表の実プリンター確認。
- 共有サーバー上からの直接起動と2台以上のPCによる同時更新試験。
- Python版の手動EXEビルド経路のWindows確認。
- `development-management` 正式ローカルcloneの復旧。
- `apps/ordering/` の業者/FAX機能とPython在庫側の統合。
- GASスマホ棚卸連携。

## 次にやること

1. 現行ブラウザ版で最新 `drink-inventory-data.json` を新規出力する。
2. そのコピーをWindows Python版へ読み込み、商品・売上・発注履歴・商品マスタ・現在庫・判定在庫を全件突合する。
3. `development-management` を `C:\Users\suisy\Documents\Development\repos\development-management` へclone / 同期する。
4. 全件突合に問題がなければ、必要な段階でユーザーが `BUILD_EXE_CLICK_ME.cmd` を手動実行する。
5. 共有サーバーのテスト領域へユーザーが専用更新スクリプトで配布し、複数PC更新を確認する。
6. 問題がなければPython版の本番切替判断を行う。
7. その後、GASスマホ棚卸と発注システム統合へ進む。
