# プロジェクト状況

最終更新: 2026-09-04（JST）

## Current Focus

| プロジェクト | 現在の作業 |
|---|---|
| next-day-setup | 実運用中。GitHub・正式ローカル・共有版の一致を確認しながら継続開発する。 |
| inventory-reconciliation-system | 実運用中。自動実行は概ね安定しており、運用設定を継続管理する。 |
| beverage-inventory-ordering-system | Python/PySide6ソース版は主要業務機能・実運用データ互換・Windowsライト/ダーク・カレンダー履歴表示・操作フィードバックまでWindows実機確認完了。最新EXE確認で、発注中一覧だけ過去の`ordered`履歴を全件表示する不整合と、QDateEditがマウスホイールで意図せず大きく日付変更される問題を確認。デスクトップ版は棚卸日以降の未納品だけ発注中表示へ絞り、全QDateEditのホイール変更を禁止。最新HEAD `4f09fd9f`、GitHub Actions 32 passed / 1 skipped。次はRUN_DEVで2点をWindows実機確認。 |
| call-reception-assistant | 初期管理文書を整備済み。アプリ本体は未実装。 |
| menu-sheet-generator | 実運用中。PMS CSVからの帳票生成と共有フォルダ配布を継続運用。 |
| development-management | 開発環境整備 一巡完了（2026-09-04）。能力ベース担当判定（[CAPABILITIES.md](CAPABILITIES.md)、pull前・push後を必須化）、`templates/windows-python-app/`、`scripts/check_standards.py`（種別対応、`repo_types.toml` が種別の唯一の正）。RUN_DEV.cmd を NDS / food-cost / inventory-reconciliation（desktop）、qr-supply（web、DEPLOY.md も）へ展開し各々一時 clone で end-to-end 実機確認。qr-supply の GitHub/ローカルズレも解消。`check_standards.py` は ERROR 0 / WARN 0。次は CI 化。 |

## 全体の現在地

- `development-management` を業務システム全体の司令塔として運用中。
- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下に統一する。
- GitHub上で完結する調査・設計・実装・テスト・branch・commit・push・PR・レビューはChatGPTが原則担当する。
- CodexはWindows実機、正式ローカル、実プリンター、共有サーバー、ローカル専用ファイル、手動ビルド失敗時の原因調査などへ優先して使用する。
- 通常のEXEビルドはCodex担当から外す。Python/Windowsアプリは正式ソースから直接起動できる状態を維持し、EXEは必要時だけユーザーがワンクリックで手動ビルドする。
- 配布対象のWindowsアプリは、配布先更新用 `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須とする。
- GitHub上の自動テスト、Pythonソース版Windows実機確認、EXE確認、UI同等性確認、共有版・実プリンター確認を別の確認レベルとして扱う。
- PR merge、安定版タグ、本番共有版更新は、必要な確認と明示的な判断後に行う。
- `beverage-inventory-ordering-system` は最新実運用JSONのデータ・業務計算互換性、現行UI再現、主要業務機能、Windowsライト/ダークテーマ、カレンダー履歴データ表示、クリック可能箇所の操作フィードバックまでPythonソース版Windows実機確認済み。
- 2026-09-02最新EXE確認で、在庫計算は棚卸日以降の発注だけを発注中数量として扱う一方、発注中一覧は`status == ordered`の全履歴を表示していたため、古い未完了履歴が大量表示され得る不整合を確認。データ自体は削除せず、デスクトップUIの発注中表示のみ現在棚卸サイクルへ絞る修正を追加。
- QDateEditはQt標準挙動でマウスホイールに反応し、カーソルが乗った状態のスクロールで日付が大きく変わるため、デスクトップ版では全QDateEditのWheelイベントを無効化。日付変更はクリック・カレンダー・キーボードに限定する。
- `development-management` の正式ローカルcloneはGitHub正本から復旧済み。旧 `C:\Users\suisy\Documents\開発環境整備プロジェクト` cloneは未コミット変更があるため別物として保護している。

## Windowsアプリ共通標準

- 開発起動: `RUN_DEV.cmd` または同等手段から `.venv` のPythonソースを起動。
- EXEビルド: `BUILD_EXE_CLICK_ME.cmd` または同等手段をユーザーが必要時だけ手動実行。
- 配布先更新: `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` をユーザーが必要時だけ手動実行。
- Codex: 通常のビルド作業ではなく、実機でしか確認できない問題や手動処理失敗時の原因調査に使う。

## beverage-inventory-ordering-system 最新状態

- branch: `python-desktop-migration`
- latest HEAD: `4f09fd9fdc4b63dd95f29a06453d2156b5a3c2ca`
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
- カレンダー履歴表示はブラウザ版と同じ優先順位へ修正済み。データ存在日は `imported`、データなし配送休みは `holiday`、対象期間内データなしは `missing`、それ以外は `outside`。2026-09-02 Windows再確認で8/1〜8/31の実データ日が緑、9/1のデータ有無による imported/missing、棚卸日前データなしのoutsideを確認済み。元JSON SHA-256不変。
- クリック可能コントロール用 `ui_interactions.py` を追加。全QPushButton/QToolButtonへ手カーソル、hover枠、押下時の沈み/色変化を共通適用。商品タブ・開閉ボタン等も対象。
- `個別発注`、`在庫データ読込`、`在庫データ保存`、`飲料発注システム`、`通知`、`商品調整`、`アラート出力`、売上CSV、棚卸、発注/納品、商品マスタ、定期消費など主要操作へ説明tooltipを追加。
- `要発注` と `未記入` のクリック可能メトリクスカードにもhover/押下反応と説明tooltipを追加。
- 2026-09-02 Windows実機操作フィードバック確認: 総合判定「操作フィードバックOK」。ヘッダー7ボタン、メイン主要操作、表示/閉じる、要発注/未記入、商品調整、個別発注、発注中、カレンダーを確認。hover・pressed・手カーソルは明確で、レイアウトのガタつきなし。tooltipは約250〜350msで表示し、内容は実機能と整合、表示位置や頻度も邪魔になりすぎない。動的に `クロスオーダーを開く` へ変わった後も反応維持。ライト/ダーク双方で可読性・識別性OK。元実運用JSON SHA-256不変。
- 最新EXE確認で発注中一覧が多すぎる問題を確認。`InventoryEngine.get_pending_from_order_history()`は棚卸日以降だけを在庫計算へ加える一方、旧UI側`pending_orders()`は全期間の`ordered`を返していた。デスクトップ専用 `DesktopInventoryService` を追加し、発注中一覧も棚卸日以降の有効日付・未納品に限定。過去履歴は`order_history()`へ残す。
- QDateEditのマウスホイール変更を`ButtonInteractionFilter`で全件無効化。カーソルを合わせたままページスクロールしても日付値を変更しない。
- 回帰テスト `test_desktop_safety.py` を追加。GitHub Actions: 32 passed / 1 skipped。

## 次にやること

1. 正式ローカル `beverage-inventory-ordering-system` を `python-desktop-migration` 最新HEAD `4f09fd9f` へfast-forwardする。
2. `RUN_DEV.cmd` で実運用JSON複製を読み込み、発注中一覧が棚卸日 `2026-08-30` 以降の未納品だけになることを確認する。
3. 発注履歴一覧には古い履歴も残っていること、在庫計算値が修正前と変わらないことを確認する。
4. カレンダー表示月、棚卸し日、配送休み開始/終了など各QDateEditへカーソルを置いた状態でホイールを回し、日付が変化しないことを確認する。ページ自体のスクロールは継続できることも確認する。
5. 通過後、ユーザーが `python_app\BUILD_EXE_CLICK_ME.cmd` を手動実行して最新EXEを再ビルドする。
6. 最新EXEへ実運用JSON複製を読み込み、66商品、カレンダー履歴表示、飲料発注システム起動、ダーク/ライト、操作フィードバック、発注中一覧、日付ホイール防止をスポット確認する。
7. ここまで通れば最新EXE機能ゲートを通過とし、棚卸表の実プリンター確認へ進む。
8. その後、共有サーバーのテスト領域へ `UPDATE_SHARED_FOLDER.cmd` でユーザー手動配布し、共有サーバー上から直接起動、2台以上のPCで共有JSON同時更新を確認する。
9. 問題がなければDraft PR #2のmerge可否を判断する。
10. 本体移行後にGASスマホ棚卸と発注システム統合へ進む。
