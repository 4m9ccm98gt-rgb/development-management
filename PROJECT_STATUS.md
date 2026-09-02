# プロジェクト状況

最終更新: 2026-09-02（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | Python/PySide6ソース版は主要業務機能・実運用データ互換・Windowsライト/ダーク実機確認まで完了。EXE確認で「8月は8/31しか取込済み緑にならない」移植差を発見し、ブラウザ版と同じく既存売上データを対象期間より優先して `imported` 表示するよう修正。最新HEAD `caebeac3`、GitHub Actions 28 passed / 1 skipped。次はRUN_DEVで履歴日表示を確認後、ユーザー手動で最新EXEを再ビルドする。 |
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
- `beverage-inventory-ordering-system` は最新実運用JSONのデータ・業務計算互換性、現行UI再現、主要業務機能のWindows Pythonソース実機確認、Windowsライト/ダークテーマ確認まで完了。EXE確認でカレンダーの履歴データ表示差を発見し、ブラウザ版仕様へ修正済み。現在はこの1点をRUN_DEVで再確認後、ordering同梱修正版EXE、実プリンター、共有サーバー、2PC同時更新へ進む。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護している。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## beverage-inventory-ordering-system 最新状態

- branch: `python-desktop-migration`
- latest HEAD: `caebeac3f9a283069cfce482c7058970bc6b1367`
- Draft PR: #2
- Pythonソース版: UI、主要機能、実運用JSON互換まで確認完了。
- 実運用JSON: 66商品、売上90日、レシピ34、定期消費3、発注履歴130件。ブラウザ/Python計算66/66一致。
- Windows Pythonソース版: 売上CSV、発注、納品、配送休み、通知、商品調整、レシピ、定期消費、dailyRoundUp、商品マスタ、棚卸、アラートCSV、外部URL、Excel実オープンまで確認済み。
- アラートCSV空行問題は修正・Windows再確認済み。
- 2026-09-02 EXE A/B診断: 同一JSONを `BEVERAGE_DATA_DIR` で与えると飲料商品66、販売数16、要発注0、未記入0、棚卸日2026-08-30、売上90日、発注履歴130、recipes34、periodicConsumptions3、productMaster66が全一致。メイン・商品調整・個別発注はピクセル差分0。
- PyInstallerの必要Pythonモジュール欠落はなし。
- fresh build直後の `dist\BeverageInventory\data` が空なのは仕様。実運用データをビルド成果物へ自動混入させず、共有更新時は配布先 `data` をSHA-256で保護する。
- EXE固有差として `apps\ordering\index.html` と関連静的資産が旧ビルド成果物に含まれず、「飲料発注システム」だけ開けない問題を確認済み。`BUILD_EXE_CLICK_ME.cmd` と `update_shared_folder.ps1` の両方に `apps\ordering` コピー/同期を追加済み。
- Windowsダークモード対応を追加。Qt/Windowsのシステム配色へ起動時・実行中とも追従し、メイン、パネル、入力欄、テーブル、商品調整、個別発注、棚卸オーバーレイ、警告/発注中カード、QDateEditカレンダー、tooltip、scrollbarをライト/ダーク双方でテーマ化。
- 売上取込カレンダーは imported / missing / outside / holiday の4状態をライト/ダーク双方で明示色にし、対象外日をdisabled文字色へ依存させないよう修正。hover時の枠/背景反応と即時詳細tooltip表示を追加。
- 2026-09-02 Windows実機テーマ確認: 総合判定「テーマ対応OK」。ダーク時に全対象画面の可読性を確認。カレンダー4状態は明確に判別でき、日付数字欠落なし。tooltipはマウス侵入後約39msで出現。QDateEdit、商品調整、個別発注、棚卸大画面、レシピ、材料消費容量、発注中、配送休みもOK。
- Windowsダーク→ライト→ダークをアプリ起動中に切替し、`ColorScheme.Dark` → `ColorScheme.Light` → `ColorScheme.Dark` のライブ追従成功。ライト側も従来UIから大きな崩れなし。
- 2026-09-02 EXEカレンダー確認: 実運用JSONには `salesDates` 90日分が存在する一方、8月表示で8/31のみ緑になっていた。原因はPython版が棚卸日 `2026-08-30` より前を先に `outside` と判定していたためで、データ欠落ではない。
- 現行ブラウザ版 `app.js` は `hasData` を対象期間 `inTarget` より先に評価し、売上データが存在する日は棚卸日前の履歴でも `imported` 表示する。対象期間は未取込判定と対象期間内件数集計にのみ使用する。
- Python版も同じ優先順位へ修正。データ存在日は `imported`、データなし配送休みは `holiday`、対象期間内データなしは `missing`、それ以外は `outside`。対象期間内の取込/未取込集計は維持。
- 回帰テストを追加し、GitHub Actions: 28 passed / 1 skipped。

## 次にやること

1. 正式ローカル `beverage-inventory-ordering-system` を `python-desktop-migration` 最新HEAD `caebeac3` へfast-forwardする。
2. `RUN_DEV.cmd` で実運用JSON複製を読み込み、8月カレンダーで売上データが存在する棚卸日前の日付も緑の `imported` になることを確認する。
3. 9月側では棚卸日翌日以降の未取込判定が従来どおり機能することも確認する。
4. 通過後、ユーザーが `python_app\BUILD_EXE_CLICK_ME.cmd` を手動実行して最新EXEを再ビルドする。
5. `dist\BeverageInventory\apps\ordering\index.html` が存在することを確認する。
6. 最新EXEへ実運用JSON複製を読み込み、66商品、カレンダー履歴表示、飲料発注システム起動、ダーク/ライト表示をスポット確認する。
7. ここまで通れば最新EXE機能ゲートを通過とし、棚卸表の実プリンター確認へ進む。
8. その後、共有サーバーのテスト領域へ `UPDATE_SHARED_FOLDER.cmd` でユーザー手動配布し、共有サーバー上から直接起動、2台以上のPCで共有JSON同時更新を確認する。
9. 問題がなければDraft PR #2のmerge可否を判断する。
10. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
