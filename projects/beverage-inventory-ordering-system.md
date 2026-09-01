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

想定配置:

```text
\\server\share\BeverageInventory\
  BeverageInventory.exe
  _internal\
  data\
    inventory-data.json
    inventory-data.backup.json
```

### GitHub上の候補版

- branch: `python-desktop-migration`
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
- PyInstaller onedirビルド手順
- GitHub Actions用Pythonテスト定義

## 実データ互換確認

2026-09-01に現行ブラウザ版から書き出した実運用JSONでローカル検証済み。

- pytest: 11 passed
- 共有JSONへ保存して再読込後、主要コレクションが内容ごと一致
  - items: 66
  - salesDates: 90
  - recipes: 34
  - orderSettings: 47
  - periodicConsumptions: 3
  - productMaster: 66
  - orderHistory: 130
  - deletedItemKeys: 4
- 2026-09-01時点のPython計算確認: 66商品 / 販売16 / 要発注0 / 未記入0

この検証はデータ互換とPythonロジックの確認であり、Windows実機・共有サーバー・実プリンター確認済みを意味しません。

## 本番切替前の未確認事項

- Windows実機でPySide6画面を確認
- WindowsでPyInstaller onedirビルド
- 現行ブラウザ版と在庫・要発注・発注履歴を全件突合
- 棚卸表を実プリンターで確認
- 共有サーバー上から直接起動
- 2台以上のPCで共有JSONの同時更新を確認
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

- ChatGPT: GitHub調査、設計、実装、テスト、branch、commit、push、PR、レビュー
- Codex: Windows実機、正式ローカル、EXEビルド、実プリンター、共有サーバー、複数PC試験

GitHub上だけで完結する作業をCodexへ重複依頼せず、Codexクレジットを実機作業へ優先配分します。

## 次にやること

1. Codex / Windows実機で `python-desktop-migration` を取得する。
2. `python_app/BUILD_EXE_CLICK_ME.cmd` でテストとPyInstallerビルドを確認する。
3. 現行実運用JSONをPython版へ初回移行し、現行ブラウザ版と全件突合する。
4. 共有サーバーのテスト領域で直接起動し、複数PC更新を試験する。
5. 問題がなければPython版の本番切替手順を確定する。
6. 本体移行後にGASスマホ棚卸、発注システム統合へ進む。

## 注意

- ブラウザ保存データを消失させない。
- 実運用JSONをGit管理しない。
- 認証情報、実運用設定、顧客データ、出力物をGit管理しない。
- 現行ブラウザ版を移行確認前に削除・上書きしない。
- GitHub上のテスト成功とWindows実機・共有版確認を分けて記録する。
- 本番共有フォルダへの反映は、実機確認完了後に行う。
