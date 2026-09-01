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
- 配布先更新は専用ワンクリックスクリプトを整備し、ユーザーが手動実行できるようにする。

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

`RUN_DEV.cmd`、`BUILD_EXE_CLICK_ME.cmd`、`UPDATE_SHARED_FOLDER.cmd`、`update_shared_folder.ps1` は候補版に存在します。

### GitHub上の候補版

- branch: `python-desktop-migration`
- Draft PR: #2 `Start Python desktop migration`
- Windows実機確認後HEAD: `94f0b5fa48c473897a5e60989536865cea3e1279`
- commit: `Verify Windows Python workflow and shared updater`
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
- `BUILD_EXE_CLICK_ME.cmd`
- `UPDATE_SHARED_FOLDER.cmd`
- `update_shared_folder.ps1`
- GitHub Actions用Pythonテスト定義

## GitHub / 非Windows実データ互換確認

2026-09-01に現行ブラウザ版から書き出した実運用JSONでChatGPT側の検証済み。

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

この66件版JSONはWindows正式ローカルでは未発見のため、Windows実機で同一データを使った全件突合は未完了です。

## Windows Pythonソース版確認

2026-09-01、正式ローカル `python-desktop-migration` でCodexにより確認・整備。

- Python: 3.13.14
- PySide6: 6.8.3
- PySide6 6.11.2は既定Windowsパス長を超えて正式パスの`.venv`へ導入できなかったため、検証済み6.8系へ固定。
- pytest: 11 passed / 0 failed / 1 skipped
- skipは `BEVERAGE_REAL_EXPORT` 指定時のみ実行する任意実データテスト。
- `RUN_DEV.cmd` からPythonソース版を起動確認。
- `.venv` 初回作成・依存導入、2回目以降の不要なpip省略、エラー時画面保持を確認。
- Windows native Qtで起動時例外なし、日本語表示、主要タブ、表、ボタン、ファイルダイアログ、Windows/UNCパス変換を確認。
- 900x600 / 1600x1000 / 1100x720で致命的なレイアウト崩れなし。
- URL・共有ファイルは外部影響を避け、変換・呼出導線まで確認。

## Windowsで使用したJSON

PCのDownloads内で見つかった最新候補 `drink-inventory-data (2).json` をコピーして確認。

内容:

- items: 50
- recipes: 8
- orderSettings: 47
- periodicConsumptions: 1
- salesDates: 0
- productMaster: 0
- orderHistory: 0
- deletedItemKeys: 0

コピーの保存・再読込後は内容一致。Python計算は51商品 / 販売0 / 要発注0 / 未記入0。

このJSONはChatGPT側で確認した66件・売上履歴90日・発注履歴130件の2026-09-01版とは別物であり、最新実運用正本とは扱わない。現行ブラウザ版から最新JSONを再出力してWindows側で再確認する必要がある。

## ブラウザ版比較

Windows側で見つかった50件版JSONについて、`app.js` の正式式と同じ条件で51行を比較し、現在庫・判定在庫の不一致0行を確認。

ただし売上・発注履歴・商品マスタが空のJSONだったため、これらを含む実運用全件比較は未確認。

## 共有保存ローカル模擬

Windows一時フォルダで確認済み。

- 読込・保存・再読込: 成功
- backup生成: 成功
- lock取得・解放: 成功
- atomic replace: 成功、一時ファイル残留なし
- JSON破損: なし
- Qtウィンドウ2インスタンス間の変更検知: 成功
- 別Pythonプロセス2本の同時更新: 両方成功
- 更新消失: なし
- 同時保存後のJSON再解析: 成功

## 手動EXE / 配布更新

`BUILD_EXE_CLICK_ME.cmd` はユーザー手動実行用として整備済み。

- 環境・依存確認
- pytest
- build/dist整理
- PyInstaller onedir
- EXE存在確認
- パス、サイズ、SHA-256表示
- 成功/失敗時の画面保持

CodexはPyInstaller、Nuitka、ビルドCMDを実行していない。`build` / `dist` も未生成。手動EXEビルドは未確認。

追加済み:

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

Codex確認時、指定された `C:\Users\suisy\Documents\Development\repos\development-management` およびDocuments配下にローカルcloneが存在せず、必読文書をローカルで確認できなかった。

GitHub上の `4m9ccm98gt-rgb/development-management` は正本として存在するため、今後のCodex開始前に正式ローカルへclone / 同期する必要がある。ローカル不在を放置すると、新しい運用ルールをCodexが読めないため優先して修正する。

## 本番切替前の未確認事項

- 現行ブラウザ版から最新実運用JSONを再出力し、Windows Python版へ読み込む。
- 66件版相当の実運用データで在庫・要発注・発注履歴・商品マスタを全件突合。
- 必要時にユーザーが `BUILD_EXE_CLICK_ME.cmd` を手動実行し、EXE固有動作を確認。
- 棚卸表を実プリンターで確認。
- 共有サーバーのテスト領域へ手動配布し、直接起動。
- 2台以上のPCで共有JSONの同時更新を確認。
- 配送カレンダー表示そのものの移植・確認。
- ブラウザ通知のデスクトップ向け置換。
- `apps/ordering/` の業者マスタ / FAX発注機能統合。
- GASスマホ棚卸連携。

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

1. 現行ブラウザ版から最新の `drink-inventory-data.json` を新しく出力する。
2. 出力した最新JSONを原本保護したコピーでWindows Python版へ読み込み、66件版相当の実運用内容を全件突合する。
3. `development-management` を正式ローカル `C:\Users\suisy\Documents\Development\repos\development-management` にclone / 同期する。
4. 上記で問題がなければ、ユーザーが必要時に `BUILD_EXE_CLICK_ME.cmd` を手動実行してEXE固有確認へ進む。
5. 共有サーバーのテスト領域へ専用更新スクリプトで手動配布し、複数PC更新を試験する。
6. 問題がなければPython版の本番切替手順を確定する。
7. 本体移行後にGASスマホ棚卸、発注システム統合へ進む。

## 注意

- ブラウザ保存データを消失させない。
- 実運用JSONをGit管理しない。
- 認証情報、実運用設定、顧客データ、出力物をGit管理しない。
- 現行ブラウザ版を移行確認前に削除・上書きしない。
- GitHub上のテスト、Pythonソース版実機、EXE、共有版を分けて記録する。
- 通常のEXEビルドをCodexへ依頼しない。
- 本番共有フォルダへの反映は、実機確認完了後に専用更新スクリプトで行う。
