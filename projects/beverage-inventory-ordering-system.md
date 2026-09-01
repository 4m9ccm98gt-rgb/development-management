# beverage-inventory-ordering-system

## 概要

飲料在庫の入力、保存、要発注判定、発注管理を行う業務システムです。

現行ブラウザ版を仕様正本として維持しつつ、共有サーバー上のアプリとデータを全PCで直接利用できるPython/PySide6版へ段階移行しています。将来はGASによるスマホ棚卸入力と、発注システムの統合を追加する方針です。

## 正式ソース

`C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`

GitHub: `4m9ccm98gt-rgb/beverage-inventory-ordering-system`

旧フォルダや単体タスク側は参照専用とし、正式開発はこのリポジトリのみで行います。

## 現行運用版

現行の在庫管理はブラウザアプリです。

- `index.html`
- `app.js`
- `styles.css`
- `default-drink-items.js`
- `default-recipes.js`
- `default-order-settings.js`

主保存はブラウザ `localStorage` の `drinkInventorySettings`、バックアップは `drinkInventorySettingsBackup`。JSONの保存・読込として `drink-inventory-data.json` を使用します。

現行の正式な在庫・要発注式:

```text
現在庫 = 棚卸在庫 + 納品済み - 売上消費
判定在庫 = 現在庫 + 発注中
```

売上は棚卸日の翌日以降、納品済みと発注中は棚卸日以降を対象にします。

## Python移行

### 方針

- ブラウザ版を削除・上書きせず、移行完了まで仕様正本・比較対象として残す。
- 現行 `drink-inventory-data.json` の構造を維持し、商品マスタ、在庫、売上履歴、レシピ、定期消費、発注履歴を落とさない。
- 共有サーバー上の `BeverageInventory.exe` を各PCから直接起動する。
- 正本データは共有配布フォルダ内の `data/inventory-data.json` とする。
- 更新時はロック → 最新JSON再読込 → 変更 → backup → atomic replace とし、複数PC更新による破損・単純上書きを防ぐ。
- 共有JSONの変更を定期検知し、別PCの更新へ追従する。
- 日常開発はPythonソース版で行い、EXEは必要時だけユーザーが手動ビルドする。
- Codexには通常のEXEビルドを依頼しない。
- 配布先更新は専用ワンクリックスクリプトを使用し、ユーザーが手動実行する。

想定配置:

```text
\\server\share\BeverageInventory\
  BeverageInventory.exe
  _internal\
  data\
    inventory-data.json
    inventory-data.backup.json
```

### 標準操作経路

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

### GitHub上の候補版

- branch: `python-desktop-migration`
- HEAD: `94f0b5fa48c473897a5e60989536865cea3e1279`
- Draft PR: #2 `Start Python desktop migration`
- `main` には未マージ。本番運用版は変更していない。
- 旧GAS共有保存案のDraft PR #1は方針変更によりclose済み、未merge。

### Python版で実装済み

- 旧JSON互換読込
- 在庫 / 商品マスタ / 売上履歴 / 発注履歴の保持
- 売上CSV取込
- レシピ消費 / レシピ編集
- 材料の日ごと切り上げ
- 定期消費 / 定期消費編集
- 画面棚卸
- 棚卸CSV入出力
- 棚卸表印刷プレビュー
- 発注中 / 納品済み / 発注履歴
- 注文URL・共有ファイルを開く処理
- 要発注判定 / 要発注CSV
- 商品追加 / 削除 / 基本設定
- 商品マスタHTML-XLS / CSV / TSV入出力
- 配送休み登録 / 削除
- 共有JSONのロック、backup、atomic replace
- 共有データ変更検知
- PySide6 UI
- `RUN_DEV.cmd`
- ユーザー手動用 `BUILD_EXE_CLICK_ME.cmd`
- `UPDATE_SHARED_FOLDER.cmd`
- `update_shared_folder.ps1`
- GitHub Actions用Pythonテスト定義

## Windows Pythonソース版確認

2026-09-01、正式Windowsローカルで確認済み。

- Python 3.13.14
- PySide6 6.8.3
- `RUN_DEV.cmd` から起動成功
- 主要画面、ファイルダイアログ、Windows/UNCパス導線を確認
- PySide6 6.11.2は正式パスでWindows既定MAX_PATHを超えて導入失敗したため、検証済み6.8系へ固定
- ローカル模擬共有保存で読込・保存・backup・lock・atomic replaceを確認
- 2つのQtウィンドウ間で変更検知成功
- 別Pythonプロセス2本の同時更新に成功し、更新消失・JSON破損なし
- `UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` はWindows PowerShell 5.1で模擬確認済み
- 本番共有フォルダは未変更
- CodexによるEXEビルドは未実施

## 最新実運用JSONのデータ移行互換確認

2026-09-01 11:59:52に現行ブラウザ版から新規書き出しした最新実運用JSONを、原本を変更せず一時コピーで検証した。

主要件数:

- items: 66
- salesDates: 90
- recipes: 34
- orderSettings: 47
- periodicConsumptions: 3
- productMaster: 66
- orderHistory: 130
- deliveryHolidays: 0
- deletedItemKeys: 4
- stocktakeMissingItemKeys: 0
- stocktakeDate: `2026-08-30`
- stocktakeMonth: `2026-08`

テスト:

- `BEVERAGE_REAL_EXPORT` に最新JSONコピーを指定
- pytest: **12 passed / 0 failed / 0 skipped**
- Python版へ保存・再読込後、主要10コレクションが件数・内容とも一致
- JSON再解析成功、lock残留なし、原本SHA-256不変

現行ブラウザ版 `app.js` との本番条件全件比較:

- 比較商品数: 66
- 完全一致: 66
- 不一致: 0
- 比較項目: key、コード、名称、type、棚卸在庫、棚卸日、売上消費、レシピ消費、定期消費、納品済み、発注中、現在庫、判定在庫、発注ライン、orderQuantity、caseQuantity、orderQuantityMode、要発注状態
- レシピ消費対象12商品も内訳一致
- dailyRoundUp対象の炭酸水・ハイサワーも一致
- 定期消費3件は棚卸日と比較日の条件上今回の反映0で両実装一致

発注履歴:

- orderHistory: 130件
- delivered: 75
- ordered: 18
- legacy blank: 37
- 日付範囲: 2026-05-27〜2026-09-01
- 棚卸日以降の発注中: 16件
- pending在庫換算合計: 124
- case発注5件の `発注数量 × caseQuantity` を含め商品別pending/receivedがブラウザ版とPython版で一致

売上履歴:

- salesDates: 90日
- 日付範囲: 2026-05-21〜2026-08-31
- 保存数量合計: 2,273
- 明細行数: 1,223
- 棚卸日翌日以降: 14行 / 数量17
- 未解決商品コード・名称: 0
- alias解決後不一致: 0
- `stocktakeDate` より後の売上だけが在庫計算へ反映されることを確認

GUI:

- `RUN_DEV.cmd` から最新JSON指定で起動成功
- 在庫66行
- 棚卸対象43行
- 売上日90行
- 発注中履歴18行
- 発注履歴130行
- 商品設定66商品
- 定期消費3行
- ボタン24個すべて有効
- 複数サイズで致命的崩れなし

### 判定

**最新実運用JSONについて、現行ブラウザ版からWindows Pythonソース版への本番データ移行互換性は確認済み。データ・業務計算上の不一致は0件。**

これはEXE・共有サーバー・実プリンターの確認とは別レイヤーであり、最終本番切替判定はまだ行わない。

## 手動EXE / 配布更新

`BUILD_EXE_CLICK_ME.cmd` はユーザー手動実行用として整備済み。

- 環境・依存確認
- pytest
- build/dist整理
- PyInstaller onedir
- EXE存在確認
- パス、サイズ、SHA-256表示
- 成功/失敗時の画面保持

CodexはPyInstaller、Nuitka、ビルドCMDを実行していない。手動EXEビルドは未確認。

配布更新:

- `python_app/UPDATE_SHARED_FOLDER.cmd`
- `python_app/update_shared_folder.ps1`

Windows PowerShell 5.1の模擬確認済み。

- 配布先は入力または `-TargetPath` で明示指定。推測・ハードコードなし。
- 更新対象は `BeverageInventory.exe` と `_internal` のみ。
- `_internal` 内だけを同期して古いランタイムを除去。
- `data` 全ファイルを更新前後にSHA-256検証。
- `inventory-data.json` が存在しない配布先は拒否。
- lock存在時は更新拒否。
- 更新元欠落時は配布先無変更。
- 模擬試験でdata / backup / 設定のハッシュ不変を確認。
- 本番共有フォルダへの実行は未実施。

## development-management ローカル状態

Codex確認時、`C:\Users\suisy\Documents\Development\repos\development-management` にローカルcloneが存在せず、必読文書をローカルで確認できなかった。

GitHub上の `4m9ccm98gt-rgb/development-management` は正本として存在するため、今後のCodex開始前に正式ローカルへclone / 同期する必要がある。ローカル不在を放置すると、新しい運用ルールをCodexが読めないため優先して修正する。

## 本番切替前の未確認事項

- ユーザーが `BUILD_EXE_CLICK_ME.cmd` を手動実行し、EXE生成・EXE固有起動を確認
- 棚卸表を実プリンターで確認
- 共有サーバーのテスト領域へ手動配布し、共有サーバー上から直接起動
- 2台以上のPCで共有JSONの同時更新を実機確認
- 配送カレンダー表示そのものの移植・確認
- ブラウザ通知のデスクトップ向け置換
- `apps/ordering/` の業者マスタ / FAX発注機能統合
- GASスマホ棚卸連携

上記を確認するまではDraft PR #2を `main` へマージせず、現行ブラウザ版を本番正本として残します。

## 発注システム

開発途中の飲料発注システムは `apps/ordering/` にあります。

- 独立リポジトリにはしない。
- Python移行後は同一商品マスタ・発注履歴を使う方向で統合する。
- 実業者名、実FAX番号、実発注履歴はGit管理しない。
- QR発注を追加する場合も、在庫自動判定の代替ではなく補助入力機能として統合する。

## スマホ棚卸

QR方式は棚卸用途には使用しない。スマホ棚卸は棚順に商品を表示して数量だけ入力する方式とし、GASをスマホ側の入口として使用する予定です。

PC側の正本データをGoogleへ全面移行するのではなく、PC本体・正本データは共有サーバー、スマホ棚卸だけGAS経由で連携する構成を基本とします。

## 開発担当の新運用

2026-09-01以降、このプロジェクトを含むGitHub開発は次の分業を基本とします。

- ChatGPT: GitHub調査、設計、実装、テスト、branch、commit、push、PR、レビュー、標準スクリプト整備
- Codex: Windows実機でのPythonソース版確認、実プリンター、共有サーバー、複数PC試験、手動ビルド失敗時の原因調査
- ユーザー: 必要時だけ `BUILD_EXE_CLICK_ME.cmd` で手動ビルド、専用更新スクリプトで手動配布

GitHub上だけで完結する作業や単純EXEビルドをCodexへ重複依頼せず、Codexクレジットを実機問題調査へ優先配分します。

## 次にやること

1. `development-management` の正式ローカルcloneを `C:\Users\suisy\Documents\Development\repos\development-management` に復旧し、今後Codexが開始時に最新ルールを読める状態にする。
2. EXE固有確認が必要になった時点で、ユーザーが `python_app\BUILD_EXE_CLICK_ME.cmd` を手動実行する。
3. EXEが正常なら、共有サーバーのテスト領域へ `UPDATE_SHARED_FOLDER.cmd` で手動配布する。
4. 共有サーバー上から直接起動し、2台以上のPCで同時更新を試験する。
5. 棚卸表を実プリンターで確認する。
6. 上記に問題がなければDraft PR #2の本番切替・merge可否を判断する。
7. 本体移行後にGASスマホ棚卸、発注システム統合へ進む。

## 注意

- ブラウザ保存データを消失させない。
- 実運用JSONをGit管理しない。
- 認証情報、実運用設定、顧客データ、出力物をGit管理しない。
- 現行ブラウザ版を移行確認前に削除・上書きしない。
- GitHub上のテスト、Pythonソース版実機、EXE、共有版を分けて記録する。
- 通常のEXEビルドをCodexへ依頼しない。
- 本番共有フォルダへの反映は、実機確認完了後に専用更新スクリプトで行う。
