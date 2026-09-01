# プロジェクト状況

最終更新: 2026-09-02（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | Python/PySide6ソース版はUI・主要業務機能・実運用データ互換までWindows実機確認完了。最新HEAD `0d72d012`、pytest 21 passed / 1 skipped。アラートCSV空行、発注先URL、Excel実オープンの残差も解消。次はユーザー手動の最新EXEビルドとEXE確認。 |
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
- `beverage-inventory-ordering-system` は最新実運用JSONのデータ・業務計算互換性、現行UI再現、主要業務機能のWindows Pythonソース実機確認まで完了。現在の本番ゲートは最新EXE、実プリンター、共有サーバー、2PC同時更新。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護している。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## 進行中の作業

- `beverage-inventory-ordering-system`: `python-desktop-migration` / Draft PR #2。最新HEAD `0d72d012706863abce134049e5324d36f1742e1e`。最新66商品版JSONでブラウザ計算66/66一致・不一致0件を確認。現行ブラウザ版をUI正本としてPySide6 UIを全面再構築し、ユーザー側で再現を確認済み。Windows実機でPython 3.13.14 / PySide6 6.8.3、`RUN_DEV.cmd` 起動、pytest 21 passed / 1 skipped。実運用JSON複製上で売上CSV、同日上書き、カレンダー、要発注、本/ケース発注、個別発注、実納品数変更、発注履歴、配送休み3週間前アラート、繁忙期候補、Windows通知、商品追加・編集・削除、`items` / `productMaster` / `orderSettings`同期、販売商品レシピ、材料側消費容量、定期消費、dailyRoundUp、商品マスタ、棚卸、保存・再読込を一周確認済み。アラートCSVのWindows空行問題は修正し、空行なし・13列・BOM付きUTF-8・CRCRLFなしを再確認。発注先URLは実UIから既定ブラウザで正常に開くことを確認し、注文確定は未実施。現行/空商品マスタ `.xls` はMicrosoft Excelで実際に開き、23列・日本語文字化けなし・破損警告なしを確認。元実運用JSONはSHA-256一致で未変更。Pythonソース版はUI・主要機能・実運用データ互換まで完了判定。次はユーザー手動の最新EXE再ビルド。
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
- ユーザー手動EXEビルド成功。PyInstaller 6.22.2 / Python 3.13.14で旧候補版EXE生成し、ローカルで起動まで確認。
- 現行ブラウザUIを正本とするPySide6 UI全面再構築を実施し、実機比較と修正を経てユーザー確認済み。
- Windows Pythonソース版で現行ブラウザの主要業務機能を実運用JSON複製上で一周確認。
- 材料側消費容量、定期消費、dailyRoundUp、実納品数、配送休み警告、繁忙期候補、Windows通知、商品マスタ互換同期を含む機能差分を解消。
- アラートCSVのWindows改行二重変換を修正し、実機で空行なし・13列・BOM付きUTF-8を確認。
- 発注先URLの既定ブラウザ起動と、商品マスタ `.xls` のMicrosoft Excel実オープンを確認。

## 未確認項目

- 最新HEAD `0d72d012` のユーザー手動EXE再ビルドとEXE固有起動・UI・主要機能スポット確認。
- Python版棚卸表の実プリンター確認。
- 共有サーバーのテスト領域への手動配布と共有サーバー上からの直接起動。
- 共有サーバー上で2台以上のPCによる同時更新試験。
- `apps/ordering/` の業者/FAX機能とPython在庫側の統合。
- GASスマホ棚卸連携。
- 旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneの未コミット変更の扱い判断。

## 次にやること

1. ユーザーが正式ローカル `beverage-inventory-ordering-system\python_app\BUILD_EXE_CLICK_ME.cmd` を手動実行し、最新HEAD `0d72d012` のEXEをビルドする。
2. ビルド成功後、最新EXEをローカル起動し、UI・起動・主要機能をスポット確認する。
3. 棚卸表を実プリンターで確認する。
4. EXEとプリンターが正常なら、ユーザーが `UPDATE_SHARED_FOLDER.cmd` で共有サーバーのテスト領域へ手動配布する。
5. 共有サーバー上から直接起動する。
6. 2台以上のPCで共有JSON同時更新を実機確認する。
7. 問題がなければDraft PR #2の本番切替・merge可否を判断する。
8. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
