# プロジェクト状況

最終更新: 2026-09-01（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | データ互換は66/66一致で確認済み。手動EXEビルド・起動も成功。現行ブラウザUIを正本としてPySide6 UIを全面再構築し、第1回Windows横並び比較まで完了。本文幅、ヘッダー、共有バー、日曜始まりカレンダー、商品調整、棚卸し大画面、表入力欄を修正した最新HEADは`6bdee339`。GitHub Actions成功。次は同条件の第2回Windows比較。共有サーバー試験はUI一致まで停止。 |
| call-reception-assistant | 初期管理文書を整備済み。アプリ本体は未実装。 |
| menu-sheet-generator | 実運用中。PMS CSVからの帳票生成と共有フォルダ配布を継続運用。 |
| development-management | 正式ローカルcloneを `C:\Users\suisy\Documents\Development\repos\development-management` に復旧済み。ChatGPTをGitHub側の第一実装担当、Codexを実機問題確認の第一担当とする現行ルールをローカルから参照可能。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- GitHub上で完結する調査・設計・実装・テスト・branch・commit・push・PR・レビューはChatGPTが原則担当する。
- CodexはWindows実機、正式ローカル、実プリンター、共有サーバー、ローカル専用ファイル、手動ビルド失敗時の原因調査などへ優先して使用する。
- 通常のEXEビルドはCodex担当から外す。Python/Windowsアプリは正式ソースから直接起動できる状態を維持し、EXEは必要時だけユーザーがワンクリックで手動ビルドする。
- 配布対象のWindowsアプリは、配布先更新用 `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須とする。
- GitHub上の自動テスト、Pythonソース版Windows実機確認、EXE確認、UI同等性確認、共有版・実プリンター確認を別の確認レベルとして扱う。
- PR merge、安定版タグ、本番共有版更新は、必要な確認と明示的な判断後に行う。
- `beverage-inventory-ordering-system` は最新実運用JSONについてデータ・業務計算互換性を全件確認済み。現在の本番ブロッカーはUI同等性・共有サーバー・実プリンター。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護している。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## 進行中の作業

- `beverage-inventory-ordering-system`: `python-desktop-migration` / Draft PR #2。最新66商品版JSONでpytest 12 passed、`app.js`との66商品全件比較は66/66一致・不一致0件。Windows正式ローカルでPythonソース版、共有保存lock/backup/atomic replace、同時更新を確認済み。ユーザー手動 `BUILD_EXE_CLICK_ME.cmd` も成功し、EXE生成・起動まで確認した。現行ブラウザ版UIを正本として旧`QTabWidget`を撤去しPySide6 UIを全面再構築。第1回Windows比較は100%表示倍率 / 96 DPI、1380×940と1100×720で実施し、総合判定「微調整必要」。差として本文幅約180px、ヘッダー約28px、共有バー約28px、月曜始まりカレンダー、商品調整と棚卸し大画面の黒背景・サイズ差、表行高・入力欄差を特定。ChatGPT側で本文1180pxレイアウト、16px本文、44px通常行、ヘッダー幅、共有バー、日曜始まり、常時棚卸入力欄、14px inset白ページ、商品調整62px行・横スクロール・常時入力欄等を修正。最新HEAD `6bdee339` のGitHub Actionsは成功。第2回Windows比較待ち。
- `next-day-setup`: 実運用を維持しながら継続開発。
- `inventory-reconciliation-system`: 自動実行と運用設定の継続管理。
- `call-reception-assistant`: アプリ本体の設計・実装待ち。

## 完了済み作業

- `development-management` のGitHub運用開始とAI共同開発基盤の整備。
- 正式ソースを `Development\repos` 配下へ統一。
- ChatGPT / Codexの役割分担を2026-09-01に更新。
- WindowsアプリをPythonソース起動・ユーザー手動EXEビルド・ユーザー手動配布更新の3経路へ統一。
- `development-management` の正式ローカルcloneをGitHub正本から復旧。
- `beverage-inventory-ordering-system` の旧GAS共有保存案 Draft PR #1を未mergeでclose。
- `beverage-inventory-ordering-system` のPython移行 branch `python-desktop-migration` とDraft PR #2を作成。
- Windows Pythonソース版・共有保存模擬・UPD導線を確認。
- 最新66商品版実運用JSONについて、Windows Python版への保存・再読込、66商品全件のブラウザ計算比較、売上90日、発注履歴130件、レシピ34件、定期消費3件の互換性を確認。不一致0件。
- ユーザー手動EXEビルド成功。PyInstaller 6.22.2 / Python 3.13.14でEXE生成し、ローカルで起動まで確認。
- 現行ブラウザUIを正本とするPySide6 UI全面再構築の第一弾をGitHubへ実装。
- 第1回Windows UI比較を実施し、具体的なpx差・構造差を取得。
- 第1回比較で判明した主要差をChatGPT側で修正し、GitHub Actions成功を確認。

## 未確認項目

- 修正版PySide6 UIと現行ブラウザ版UIの第2回Windows実機見比べ・追加調整完了。
- Python版棚卸表の実プリンター確認。
- 共有サーバーのテスト領域への手動配布と共有サーバー上からの直接起動。
- 共有サーバー上で2台以上のPCによる同時更新試験。
- ブラウザ通知のデスクトップ向け置換。
- `apps/ordering/` の業者/FAX機能とPython在庫側の統合。
- GASスマホ棚卸連携。
- 旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneの未コミット変更の扱い判断。

## 次にやること

1. 正式ローカル `beverage-inventory-ordering-system` で `python-desktop-migration` の最新HEAD `6bdee339` へfast-forwardする。
2. `RUN_DEV.cmd` からPythonソース版を起動し、第1回と同じ100%表示倍率 / 96 DPI、1380×940と1100×720で現行ブラウザ版と第2回横並び比較を行う。
3. 本文幅、ヘッダー高さ/折返し、共有バー、カレンダー曜日順、通常表行高、商品調整、棚卸し大画面、個別発注を再計測する。
4. 残差があればChatGPT側で修正し、UI差分ゼロを目指す。
5. UI一致後にユーザーが `BUILD_EXE_CLICK_ME.cmd` を再度手動実行する。
6. EXE UIが正常なら共有サーバーのテスト領域へ `UPDATE_SHARED_FOLDER.cmd` で手動配布する。
7. 共有サーバー上から直接起動し、2台以上のPCで共有JSON同時更新を確認する。
8. 棚卸表を実プリンターで確認する。
9. 問題がなければDraft PR #2の本番切替・merge可否を判断する。
10. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
