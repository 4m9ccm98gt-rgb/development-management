# プロジェクト状況

最終更新: 2026-09-02（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | Python/PySide6ソース版はUI・主要業務機能・実運用データ互換までWindows実機確認完了。最新HEAD `0d72d012`、pytest 21 passed / 1 skipped。最新EXEはユーザー手動ビルドとローカル起動に成功したが、各ボタンの機能・表示とデータ読込がソース版と一致せず、EXE機能ゲートは未通過。次は同一複製JSONをRUN_DEV版とEXE版へ与えるA/B比較で、データパス差かPyInstaller固有差かを切り分ける。 |
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
- `beverage-inventory-ordering-system` は最新実運用JSONのデータ・業務計算互換性、現行UI再現、主要業務機能のWindows Pythonソース実機確認まで完了。最新EXEは起動するがソース版との機能・表示・データ読込一致が未確認で、現在の本番ゲートはEXEパリティ、実プリンター、共有サーバー、2PC同時更新。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護している。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## beverage-inventory-ordering-system 最新状態

- branch: `python-desktop-migration`
- latest HEAD: `0d72d012706863abce134049e5324d36f1742e1e`
- Draft PR: #2
- Pythonソース版: UI、主要機能、実運用JSON互換まで確認完了。
- 実運用JSON: 66商品、売上90日、レシピ34、定期消費3、発注履歴130件。ブラウザ/Python計算66/66一致。
- Windows Pythonソース版: pytest 21 passed / 1 skipped。売上CSV、発注、納品、配送休み、通知、商品調整、レシピ、定期消費、dailyRoundUp、商品マスタ、棚卸、アラートCSV、外部URL、Excel実オープンまで確認済み。
- アラートCSV空行問題は修正・Windows再確認済み。
- 最新EXE: ユーザー手動ビルドはエラー表示なく完了し、`BeverageInventory.exe` のローカル起動成功。ただし各ボタンの機能・表示とデータ読込がPythonソース版と一致していないため、EXE確認は未完了。
- コード上、Pythonソース版の既定データは `python_app\data`、frozen EXEの既定データはEXE横の `data`。`BUILD_EXE_CLICK_ME.cmd` はビルド前に `dist` を削除し、ビルド後に空の `dist\BeverageInventory\data` を作るため、ローカルEXEがソース版と別データで起動することは確認済み。共有サーバー更新スクリプトは配布先の既存 `data` を保護し、EXEと `_internal` だけ更新する。

## 次にやること

1. EXEを再ビルドせず、正式ローカルの最新HEADを維持する。
2. 実運用JSONの複製を2つ作り、RUN_DEV版と最新EXE版を同一内容の別データディレクトリへ `BEVERAGE_DATA_DIR` で接続する。
3. 同一データ条件でUI表示、ヘッダーボタン、商品調整、個別発注、要発注、棚卸、通知、外部URL等をA/B比較する。
4. EXE既定の `dist\BeverageInventory\data\inventory-data.json` の有無・内容・ハッシュを確認し、データパス差が症状の原因か判定する。
5. 同一データでもEXE固有差が残る場合はPyInstaller同梱モジュール・ランタイム差を調査し、原因と必要修正をChatGPTへ返す。
6. EXEパリティが通った後に実プリンター、共有サーバーテスト領域、共有サーバー上直接起動、2PC同時更新へ進む。
7. 問題がなければDraft PR #2のmerge可否を判断する。
8. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
