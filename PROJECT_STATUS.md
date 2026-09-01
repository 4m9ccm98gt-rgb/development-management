# プロジェクト状況

最終更新: 2026-09-01（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | データ互換は66/66一致で確認済み。手動EXEビルド・起動も成功したが、旧PySide6タブUIが現行ブラウザUIと大きく異なることを実機で確認。現行`index.html` / `styles.css` / `app.js`をUI正本としてPySide6 UIを全面再構築中。共有サーバー試験はUI一致確認まで停止。 |
| call-reception-assistant | 初期管理文書を整備済み。アプリ本体は未実装。 |
| menu-sheet-generator | 実運用中。PMS CSVからの帳票生成と共有フォルダ配布を継続運用。 |
| development-management | 正式ローカルcloneを `C:\Users\suisy\Documents\Development\repos\development-management` に復旧済み。ChatGPTをGitHub側の第一実装担当、Codexを実機問題確認の第一担当とする現行ルールを次回以降ローカルから参照可能。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- GitHub上で完結する調査・設計・実装・テスト・branch・commit・push・PR・レビューは、GitHubへ直接アクセスできるChatGPTが原則担当する。
- CodexはWindows実機、正式ローカル、実プリンター、共有サーバー、ローカル専用ファイル、手動ビルド失敗時の原因調査などへ優先して使用する。
- 通常のEXEビルドはCodex担当から外す。Python/Windowsアプリは正式ソースから直接起動できる状態を維持し、EXEは必要時だけユーザーがワンクリックで手動ビルドする。
- 配布対象のWindowsアプリは、配布先更新用 `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須とする。
- GitHub上の自動テスト、Pythonソース版Windows実機確認、EXE確認、UI同等性確認、共有版・実プリンター確認を別の確認レベルとして扱う。
- PR merge、安定版タグ、本番共有版更新は、必要な確認と明示的な判断後に行う。
- `beverage-inventory-ordering-system` は最新実運用JSONについて、現行ブラウザ版からWindows Pythonソース版へのデータ移行互換性を全件確認済み。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護している。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## 進行中の作業

- `beverage-inventory-ordering-system`: `python-desktop-migration` / Draft PR #2。最新66商品版JSONでpytest 12 passed、`app.js`との66商品全件比較は66/66一致・不一致0件。Windows正式ローカルでPythonソース版、共有保存lock/backup/atomic replace、同時更新を確認済み。ユーザー手動 `BUILD_EXE_CLICK_ME.cmd` も成功し、EXE生成・起動まで確認した。一方、旧PySide6 UIが現行ブラウザ版と大きく異なることが実機で判明。現行ブラウザ版のUIを正本として、PySide6のタブ構成を撤去し、業務順1画面ダッシュボード、ヘッダー、CSV取込、売上カレンダー、4メトリクス、折りたたみ一覧、要注文、現在庫、月次棚卸し、個別発注、商品調整を再構築中。UI一致確認が終わるまで共有サーバー配布へ進まない。
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

## 未確認項目

- 再構築したPySide6 UIと現行ブラウザ版UIの実機見比べ・微調整完了。
- Python版棚卸表の実プリンター確認。
- 共有サーバーのテスト領域への手動配布と共有サーバー上からの直接起動。
- 共有サーバー上で2台以上のPCによる同時更新試験。
- ブラウザ通知のデスクトップ向け置換。
- `apps/ordering/` の業者/FAX機能とPython在庫側の統合。
- GASスマホ棚卸連携。
- 旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneの未コミット変更の扱い判断。

## 次にやること

1. `python-desktop-migration` の最新PySide6 UIを正式ローカルへpullする。
2. `RUN_DEV.cmd` からPythonソース版を起動し、現行ブラウザ版を横に並べてUI差分を確認する。
3. 色、余白、寸法、並び順、テーブル、カレンダー、商品調整、個別発注、棚卸しを差分ゼロへ向けて調整する。
4. UI一致後にユーザーが `BUILD_EXE_CLICK_ME.cmd` を再度手動実行する。
5. EXE UIが正常なら共有サーバーのテスト領域へ `UPDATE_SHARED_FOLDER.cmd` で手動配布する。
6. 共有サーバー上から直接起動し、2台以上のPCで共有JSON同時更新を確認する。
7. 棚卸表を実プリンターで確認する。
8. 問題がなければDraft PR #2の本番切替・merge可否を判断する。
9. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
