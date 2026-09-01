# プロジェクト状況

最終更新: 2026-09-01（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | Pythonソース版のWindows実機確認、最新66商品版JSONの全件互換確認、ユーザー手動EXEビルド・起動まで完了。ただし現行ブラウザ版とPython版のUI構成が大きく異なることを実機で確認。本番ゲートをUI互換・操作感の再構築へ戻し、共有サーバー配布は保留。 |
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
- GitHub上の自動テスト、Pythonソース版Windows実機確認、EXE確認、UI互換確認、共有版・実プリンター確認を別の確認レベルとして扱う。
- PR merge、安定版タグ、本番共有版更新は、必要な確認と明示的な判断後に行う。
- `beverage-inventory-ordering-system` は最新実運用JSONについて、現行ブラウザ版からWindows Pythonソース版へのデータ移行互換性を全件確認済み。
- 2026-09-01にユーザーが `BUILD_EXE_CLICK_ME.cmd` を手動実行し、PyInstaller 6.22.2 / Python 3.13.14でEXE生成成功。生成EXEは起動することを確認した。
- ただし生成EXEのUIが現行ブラウザ版と大きく異なるため、UIは本番移行要件を満たしていない。共有サーバー試験へ進まず、ブラウザ版の画面構成・操作感を正本としてPython UIを再構築する。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護し、変更・削除していない。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## 進行中の作業

- `beverage-inventory-ordering-system`: `python-desktop-migration` / Draft PR #2。Windows正式ローカルでPython 3.13.14 / PySide6 6.8.3、`RUN_DEV.cmd` 起動、共有保存のlock/backup/atomic replace、2インスタンス変更検知、2プロセス同時更新を確認済み。2026-09-01 11:59:52にブラウザ版から新規書き出しした最新JSONでpytest 12 passed / 0 failed / 0 skipped。items 66、salesDates 90、recipes 34、orderHistory 130等を移行し、現行`app.js`と66商品を全件比較して66/66一致・不一致0件。データ移行互換性は確認済み。ユーザー手動EXEビルドも成功し起動確認したが、現行ブラウザ版の濃緑ヘッダー、操作パネル、集計カード、カレンダー、アラート、在庫表を中心とする画面構成に対し、Python候補版は素のQtタブ構成で大きく異なる。次工程は業務ロジックを維持したままUIのみブラウザ版準拠へ再構築すること。
- `next-day-setup`: 実運用を維持しながら継続開発。
- `inventory-reconciliation-system`: 自動実行と運用設定の継続管理。
- `call-reception-assistant`: アプリ本体の設計・実装待ち。

## 完了済み作業

- `development-management` のGitHub運用開始とAI共同開発基盤の整備。
- 正式ソースを `Development\repos` 配下へ統一。
- ChatGPT / Codexの役割分担を2026-09-01に更新。ChatGPTがGitHub側実装まで担当し、Codexを実機作業へ優先配分する運用を正式化。
- 2026-09-01にWindowsアプリの標準を追加。日常開発はPythonソース起動、EXEはユーザーの手動ワンクリックビルド、配布先更新も専用ワンクリックスクリプトとし、通常のEXEビルドをCodex担当から外した。
- `development-management` の正式ローカルcloneを `C:\Users\suisy\Documents\Development\repos\development-management` にGitHub正本から復旧。
- `beverage-inventory-ordering-system` の旧GAS共有保存案 Draft PR #1を未mergeでclose。
- `beverage-inventory-ordering-system` のPython移行 branch `python-desktop-migration` とDraft PR #2を作成。
- `beverage-inventory-ordering-system` のWindows Pythonソース版・共有保存模擬・UPD導線整備をcommit `94f0b5f`で確認。
- 最新66商品版実運用JSONについて、Windows Python版への保存・再読込、66商品全件のブラウザ計算比較、売上90日、発注履歴130件、レシピ34件、定期消費3件の互換性を確認。不一致0件。
- ユーザー手動ビルドで `BeverageInventory.exe` の生成成功。EXEサイズ1,886,396 bytes、SHA-256 `BD296017F16DCA457D274E61DF604572B0A6934BD6C5CF38A66BCD64B306850A`。ローカル起動も確認済み。

## 未確認・未完了項目

- 現行ブラウザ版と同等のUI構成・視認性・操作感へのPython UI再構築と実機確認。
- Python版棚卸表の実プリンター確認。
- 共有サーバーのテスト領域への手動配布と共有サーバー上からの直接起動。
- 共有サーバー上で2台以上のPCによる同時更新試験。
- 配送カレンダー表示そのものの移植・確認。
- ブラウザ通知のデスクトップ向け置換。
- `apps/ordering/` の業者/FAX機能とPython在庫側の統合。
- GASスマホ棚卸連携。
- 旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneの未コミット変更の扱い判断。

## 次にやること

1. 現行ブラウザ版 `index.html` / `styles.css` をUI正本として、Python版のメイン画面を再構築する。業務ロジック・JSON形式・計算式は変更しない。
2. `RUN_DEV.cmd` でWindows Pythonソース版を確認し、現行ブラウザ版と操作感を比較する。
3. UIが承認できる状態になった後、ユーザーが `BUILD_EXE_CLICK_ME.cmd` を再度手動実行して新UI版EXEを確認する。
4. EXEが正常なら、共有サーバーのテスト領域へ `UPDATE_SHARED_FOLDER.cmd` で手動配布する。
5. 共有サーバー上から直接起動し、2台以上のPCで共有JSON同時更新を確認する。
6. 棚卸表を実プリンターで確認する。
7. 問題がなければDraft PR #2の本番切替・merge可否を判断する。
8. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
