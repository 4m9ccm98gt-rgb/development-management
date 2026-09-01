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
- UI全面再構築第一弾HEAD: `d5d3e65ce8fd90f823e0e591f46fad8e13a7432b`
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

旧構成:

- `QTabWidget` による「在庫 / 棚卸 / 売上CSV / 発注 / 商品設定 / 定期消費 / 配送休み」分割

新構成:

- `QTabWidget` を撤去
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
- 個別発注ダイアログ

ブラウザCSSの主要値もPySide6側へ反映。

- bg `#f6f7f4`
- ink `#1c2522`
- muted `#64716d`
- line `#d9dfd9`
- accent `#0f766e`
- accent-dark `#0d5f58`
- danger `#b91c1c`
- header `#20352f`
- eyebrow `#9fd6cd`
- main max width 1180px相当
- header padding 28px / 48px相当
- title 42px相当
- button min-height 42px / radius 6px / padding 0 16px
- input min-height 38px
- metric min-height 92px / padding 18px
- panel radius 8px
- calendar day min-height 38px
- 配送休み・画面棚卸しのpill形状

UIコードは保守性のため以下へ分割。

- `ui.py`
- `ui_components.py`
- `ui_build.py`
- `ui_reload.py`
- `ui_actions.py`
- `ui_dialogs.py`

`test_ui_parity_source.py` で旧 `QTabWidget` 非使用、主要UIラベル、ブラウザ配色値をソースレベル検査する。

UI全面再構築第一弾HEAD `d5d3e65c` のGitHub Actions `Python migration tests` はWindows-latestで成功。Python compileとmigration testsを通過済み。

## 本番切替前の未確認事項

- 再構築PySide6 UIをWindows `RUN_DEV.cmd` で起動し、現行ブラウザ版と横並びで実機見比べ
- UI差分の追加調整
- UI確定後の手動EXE再ビルドとEXE UI確認
- 棚卸表の実プリンター確認
- 共有サーバーのテスト領域への手動配布
- 共有サーバー上から直接起動
- 2台以上のPCで共有JSONの同時更新を実機確認
- ブラウザ通知のデスクトップ向け置換
- `apps/ordering/` の業者マスタ / FAX発注機能統合
- GASスマホ棚卸連携

UI一致確認が終わるまでは共有サーバー試験・Draft PR #2のmergeへ進みません。

## 発注システム

開発途中の飲料発注システムは `apps/ordering/` にあります。

- 独立リポジトリにはしない。
- Python移行後は同一商品マスタ・発注履歴を使う方向で統合する。
- 実業者名、実FAX番号、実発注履歴はGit管理しない。
- QR発注を追加する場合も、在庫自動判定の代替ではなく補助入力機能として統合する。

## スマホ棚卸

QR方式は棚卸用途には使用しない。スマホ棚卸は棚順に商品を表示して数量だけ高速入力できる操作感を優先する。GASはスマホ側UI / 一時通信経路として使い、PC共有JSONを正本とする。
