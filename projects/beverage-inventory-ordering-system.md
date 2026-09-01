# beverage-inventory-ordering-system

## 概要

飲料在庫の入力、保存、要発注判定、発注管理を行う業務システムです。

現行ブラウザ版を仕様正本として維持しつつ、共有サーバー上のアプリとデータを全PCで直接利用できるPython/PySide6版へ段階移行しています。将来はGASによるスマホ棚卸入力と、発注システムの統合を追加する方針です。

## 正式ソース

`C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`

GitHub: `4m9ccm98gt-rgb/beverage-inventory-ordering-system`

## 現行運用版

現行の在庫管理はブラウザアプリです。

- `index.html`
- `app.js`
- `styles.css`
- `default-drink-items.js`
- `default-recipes.js`
- `default-order-settings.js`

主保存はブラウザ `localStorage` の `drinkInventorySettings`、バックアップは `drinkInventorySettingsBackup`。JSONの保存・読込として `drink-inventory-data.json` を使用します。

正式な在庫・要発注式:

```text
現在庫 = 棚卸在庫 + 納品済み - 売上消費
判定在庫 = 現在庫 + 発注中
```

売上は棚卸日の翌日以降、納品済みと発注中は棚卸日以降を対象にします。

## Python移行方針

- Python/PySide6移行を継続する。
- 現行ブラウザ版を削除・上書きせず、移行完了まで仕様正本・比較対象として残す。
- データ構造・業務計算だけでなく、UIも現行 `index.html` / `styles.css` / `app.js` の最終表示状態を正本としてPySide6へ移行する。
- UI移行は「似たデスクトップUI」ではなく、現行の色、余白、寸法、配置、情報密度、操作順、カレンダー、折りたたみ、商品調整、個別発注、棚卸し画面を差分ゼロへ向けて再現する。
- WebView化やブラウザUI埋め込みには切り替えない。PySide6ネイティブUIとして再構築する。
- 共有サーバー上の `BeverageInventory.exe` を各PCから直接起動する。
- 正本データは共有配布フォルダ内の `data/inventory-data.json` とする。
- 更新時はロック → 最新JSON再読込 → 変更 → backup → atomic replace とし、複数PC更新による破損・単純上書きを防ぐ。
- 日常開発はPythonソース版で行い、EXEは必要時だけユーザーが手動ビルドする。
- Codexには通常のEXEビルドを依頼しない。

## 標準操作経路

```text
開発起動
python_app\RUN_DEV.cmd

必要時だけEXE化
python_app\BUILD_EXE_CLICK_ME.cmd

配布先更新
python_app\UPDATE_SHARED_FOLDER.cmd
  ↓
python_app\update_shared_folder.ps1
```

## GitHub候補版

- branch: `python-desktop-migration`
- 最新UI調整HEAD: `6bdee339e3432de11389f97b633dd053377f3660`
- Draft PR: #2 `Start Python desktop migration`
- `main` には未マージ。本番運用版は変更していない。
- 旧GAS共有保存案Draft PR #1はclose済み、未merge。

## データ・計算互換性

2026-09-01に現行ブラウザ版から新規書き出した最新実運用JSONで確認済み。

- items: 66
- salesDates: 90
- recipes: 34
- orderSettings: 47
- periodicConsumptions: 3
- productMaster: 66
- orderHistory: 130
- deletedItemKeys: 4
- stocktakeDate: `2026-08-30`
- `BEVERAGE_REAL_EXPORT` 指定pytest: 12 passed / 0 failed / 0 skipped
- 保存・再読込後も主要10コレクション一致
- 現行 `app.js` と66商品を本番条件で全件比較し、66/66一致・不一致0件
- 売上90日、発注履歴130件、レシピ34件、定期消費3件を確認

**データ・業務計算互換性は確認済み。**

## Windows確認

正式Windowsローカルで以下を確認済み。

- Python 3.13.14
- PySide6 6.8.3
- `RUN_DEV.cmd` 起動
- 共有保存lock / backup / atomic replace
- 2ウィンドウ変更検知
- 2プロセス同時更新
- `UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` のPowerShell 5.1模擬確認

ユーザー手動ビルドも実施済み。

- PyInstaller 6.22.2
- ビルド前テスト: 11 passed / 1 skipped
- `dist/BeverageInventory/BeverageInventory.exe` 生成成功
- EXEローカル起動成功

ただし旧PySide6 UIは、実機確認時に現行ブラウザUIと大きく異なることが判明した。このためEXE起動成功だけでは本番ゲート通過としない。

## UI全面再構築

現行ブラウザ版の最終UIを正本として `python-desktop-migration` でPySide6 UIを再構築。

旧 `QTabWidget` 構成を撤去し、以下をブラウザ版と同じ業務順1画面へ再配置した。

- 濃緑ヘッダー `#20352f`
- `Inventory Control` / `飲料在庫チェック`
- 個別発注 / 在庫データ読込 / 在庫データ保存 / 飲料発注システム / 通知 / 商品調整 / アラート出力
- 共有状態バー
- 売上CSV取込
- 売上伝票取り込みカレンダー + 配送休み
- 飲料商品 / 販売数 / 要発注 / 未記入の4メトリクス
- 登録売上一覧
- 発注履歴一覧
- 要注文飲料
- 現在庫一覧
- 月次棚卸し
- 棚卸CSV取込
- 画面棚卸し + 大きく開く
- 棚卸し登録一覧
- 棚卸表印刷
- 商品調整の専用管理画面
- 商品一覧 / 商品マスタ出力 / 定期消費
- レシピ編集
- 個別発注

UIコードは保守性のため以下へ分割。

- `ui.py`
- `ui_components.py`
- `ui_build.py`
- `ui_reload.py`
- `ui_actions.py`
- `ui_dialogs.py`

## 第1回 Windows UI比較

2026-09-01、Codexで現行ブラウザ版とPySide6版をWindows 100% DPI / 96 DPIで実機比較した。

比較サイズ:

- 1380 × 940
- 1100 × 720

テスト:

- 正式 `python_app` からpytest: 14 passed / 1 skipped
- `RUN_DEV.cmd` 起動成功
- EXE再ビルドは未実施

第1回比較結果:

- 全体: 明確な差。Python本文幅が約180px狭く、フォントが概ね2〜3px小さい。
- ヘッダー: 明確な差。Python約152px / ブラウザ約124px。Pythonのみ1380pxでボタン2段。
- 共有状態: 明確な差。Python約70px / ブラウザ約42px。Pythonだけパス・状態・再読込を表示。
- 売上CSV: 軽微差。
- カレンダー: 明確な差。Pythonは月曜始まり、ブラウザは日曜始まり。
- 4メトリクス: 軽微差。本文幅の影響でカードが狭い。
- 折りたたみ一覧: 軽微差。Python tableが過密。
- 要注文飲料: 軽微差。
- 現在庫: 3列構成は一致。
- 月次棚卸し: 軽微差。入力欄の見え方が異なる。
- 商品調整: 明確な差。Pythonが黒背景の独立ダイアログで、行高約30px。ブラウザは14px insetの白い全画面パネル、行高約62px。
- 個別発注: 軽微差。ブラウザは右上オーバーレイ、Pythonは独立ダイアログ。
- 棚卸し大画面: 明確な差。Pythonが黒背景1100×720ダイアログで日付欄なし。ブラウザは14px insetの白い全画面パネル。

総合判定は「微調整必要」。共有サーバー試験は継続停止。

## 第1回比較後の修正

ChatGPT側で第1回比較結果を基にPySide6 UIを修正。最新HEAD `6bdee339...`。

主な修正:

- 本文レイアウトをsizeHint縮小から、最大1180pxまで実幅を使う中央レイアウトへ変更。
- ブラウザの基本本文サイズに合わせ、通常UIを16px、helper/field labelを13pxへ整理。
- 通常テーブル行高を44pxへ拡大。
- ヘッダーのアクション領域を残り幅へ伸ばし、1380px時の1段配置を狙う構造へ変更。
- タイトルをword-wrap可能にし、1100px時の折返しに対応。
- 共有状態バーからPython独自のパス・状態・再読込表示を除き、ブラウザ版文言へ統一。
- カレンダーを日曜始まりへ変更。
- 通常棚卸し表の棚卸本数・メモを常時見える `QLineEdit` へ変更。
- 棚卸し大画面を独立黒ダイアログから、14px insetの白い全画面作業パネルへ変更。
- 棚卸し大画面内へ棚卸し日を追加。
- 商品調整を固定1500pxダイアログから、親画面内14px insetの全画面作業パネルへ変更。
- 商品調整テーブルをブラウザ同様に横スクロール前提へ変更。
- 商品調整行高を62pxへ変更。
- 商品調整の編集項目を常時見える入力欄・選択欄へ変更。
- 個別発注を親画面右上配置のオーバーレイ構造へ変更。
- 発注先ボタン文言を発注先名に追従させる。

GitHub Actions `Python migration tests` は最新修正系列で成功。Python compile / migration testsを通過している。

## 本番切替前の未確認事項

- 修正版PySide6 UIをWindows `RUN_DEV.cmd` で再起動し、第2回ブラウザ横並び比較を行う。
- 第2回比較で残ったpx差・操作差を追加修正し、UI差分ゼロを目指す。
- UI確定後の手動EXE再ビルドとEXE UI確認。
- 棚卸表の実プリンター確認。
- 共有サーバーのテスト領域への手動配布。
- 共有サーバー上から直接起動。
- 2台以上のPCで共有JSONの同時更新を実機確認。
- ブラウザ通知のデスクトップ向け置換。
- `apps/ordering/` の業者マスタ / FAX発注機能統合。
- GASスマホ棚卸連携。

UI一致確認が終わるまでは共有サーバー試験・Draft PR #2のmergeへ進みません。

## 発注システム

開発途中の飲料発注システムは `apps/ordering/` にあります。

- 独立リポジトリにはしない。
- Python移行後は同一商品マスタ・発注履歴を使う方向で統合する。
- 実業者名、実FAX番号、実発注履歴はGit管理しない。
- QR発注を追加する場合も、在庫自動判定の代替ではなく補助入力機能として統合する。

## スマホ棚卸

QR方式は棚卸用途には使用しない。スマホ棚卸は棚順に商品を表示して数量だけ高速入力できる操作感を優先する。GASはスマホ側UI / 一時通信経路として使い、PC共有JSONを正本とする。
