# qr-supply-ordering-system

## 目的

一般物品を対象に、商品QRからの発注依頼と、発注先ごとのFAX準備・送信完了・納品を管理する物品発注ドメイン。**在庫管理システムではない。**

2026-09-06の方針変更により、日常のPC操作UIは `beverage-inventory-ordering-system` のPython/PySide6版へ統合する。
ただし、飲料と物品の商品マスター・DB・発注先マスター・履歴・業務ロジックは共有しない。
物品側SQLiteと既存実装は物品ドメインの正として維持し、飲料側統合デスクトップから専用アダプタ経由で参照・操作する。

## 現在の状態（2026-09-06）

| 項目 | 内容 |
|---|---|
| GitHub | `4m9ccm98gt-rgb/qr-supply-ordering-system`（private） |
| 正式ローカル | `C:\Users\suisy\Documents\Development\repos\qr-supply-ordering-system` |
| 既定ブランチ | `main` |
| 物品DB | `database/qr_supply.sqlite3`。物品ドメインの正として独立維持 |
| PC統合先 | `beverage-inventory-ordering-system` Draft PR #7 / `feature/unified-ordering-flow` |
| PC UI | `飲料在庫チェック` 直下に `飲料在庫・発注` / `物品発注依頼処理` |
| QR受付 | 館内LANを使わず、スマホの4G/5G → Google Apps Script → Google Sheets一時受付箱 → PC → 物品SQLite |
| FAX | 既存物品Webでは第2期プレースホルダー。統合PySide6側でもまだ未実装 |

## 統合境界

### 同じアプリにするもの

- Windows上の起動アプリ / メインウィンドウ
- トップレベルナビゲーション
- 見た目・操作体験
- 日常業務フロー

完成形の基本UI:

```text
飲料在庫チェック

[ 飲料在庫・発注 ] [ 物品発注依頼処理 ]
```

`飲料在庫・発注` には既存の飲料PySide6 UIを維持する。
`物品発注依頼処理` には物品側業務機能をPySide6ネイティブUIとして段階的に再構成する。
WebViewや旧Flask管理画面への単純遷移を統合完成形とはしない。

### 共有しないもの

- 飲料商品マスター ↔ 物品商品マスター
- 飲料発注履歴 ↔ 物品発注依頼履歴
- 飲料JSON ↔ 物品SQLite
- 物品の発注先マスター
- 物品固有の依頼状態・取消・FAX処理ロジック

統合は「データ統合」ではなく「デスクトップUIと業務導線の統合」とする。

## 物品データへの接続

- 物品側の正は `qr-supply-ordering-system/database/qr_supply.sqlite3`
- beverage側では `SupplyRequestStore` 等の専用境界層を通す
- DEVでは正式ローカル兄弟repoを自動検出
- 必要時は `QR_SUPPLY_DB_PATH` で明示
- 将来配布構成を変更してもDB境界を維持し、飲料マスターへ吸収しない

## QR発注の運用設計（2026-09-06決定）

館内Wi-Fi / 館内LANから発注PCへ直接アクセスする方式は採用しない。
スマホは4G/5G等のインターネット接続でGoogle Apps ScriptのWeb Appへアクセスする。

```text
商品棚のQR
  ↓
スマホ（4G / 5G）
  ↓
Apps Scriptの商品発注ページ
  ↓
Google Sheets 一時受付箱
  ↓
PCが定期取得
  ↓
qr_supply.sqlite3
  ↓
物品発注依頼処理
  ↓
FAX送信（次段階）
```

### スマホ操作

QRを読むと対象商品を1商品だけ表示する。
日常入力は以下だけとする。

- 商品名表示
- 数量 `- / 数量 / +`
- `発注する`

依頼者名・備考・商品検索・在庫数などは日常QR画面へ置かない。
SQLite側の依頼者名は `QR発注` として記録する。

### 商品マスターとQR

- 物品SQLiteの商品マスターが正
- Google側 `supply_qr_items` は現在の有効商品を表示するためのミラーのみ
- PCから明示的に「商品をQRへ同期」する
- QRには商品名・発注先・FAX番号を埋め込まない
- QR URLには商品IDからBridge secretで決定的に生成したトークンを含める
- 商品名・発注先・発注単位・場所を変更しても、Bridge secretを変更しない限りQRは刷り直さない
- 商品変更履歴そのものは管理しない
- 発注時点の商品名・発注先・単位・部署・場所を依頼スナップショットとして保存する

### Google受付箱

Googleは正式DBではない。

- `supply_qr_items`: QR表示用の現在商品ミラー
- `supply_qr_requests`: スマホから届いた未取込発注の一時キュー
- PC取込成功後だけGoogle側を `imported` にする
- 正式履歴は物品SQLite

### 二重発注防止

各スマホ発注に一意の `request_token` を持たせる。
物品SQLiteの既存 `order_requests.request_token UNIQUE` を冪等キーとして利用する。

- 初回: SQLiteへ発注依頼を作成
- 同じ依頼の再取得: 既存依頼として扱い、二重作成しない
- SQLiteへ保存済み / 既存確認済みのトークンだけGoogleへACKする
- 不正・マスタ不整合の行はGoogle側へ残し、黙って捨てない

## beverage側のQR実装

Draft PR #7 `feature/unified-ordering-flow` で以下を実装する。

- `SupplyOrderBridgeClient`
- Apps Script Web App URL / Bridge secretによる接続
- 物品SQLiteから有効商品を取得してGoogleへ同期
- QRラベルHTML生成
- Google未取込依頼の取得
- 約60秒ごとのバックグラウンド自動取込
- `今すぐ取込`
- `request_token` による冪等SQLite登録
- 成功済み依頼のGoogle ACK
- 取込後の `物品発注依頼処理` 一覧更新

Apps Script実装はbeverage repoの `google_apps_script/supply_order/` に置く。
既存飲料スマホ棚卸と同じSpreadsheet ID / Bridge secretを使用可能だが、物品QR用Web App URLは独立デプロイとして扱える。

## 現行物品ドメイン設計 / 旧Web実装

`qr-supply-ordering-system` のFlask版は物品ドメイン・schema・既存仕様の参照として維持する。

- Flask / SQLite / HTML / CSS / JavaScript
- SQLiteはアプリ経由のみ（WAL、外部キー、トランザクション）
- 旧QRは `/order-item/<item_id>` URL
- 依頼状態: 発注依頼 / FAX準備済み / 発注済み / 納品済み / 取消
- `/admin/requests` は旧Web版の日常業務入口
- 商品 / 発注先 / 依頼詳細 / 取消 / 履歴 / QRラベル / 発注表取込を実装済み
- FAX工程はプレースホルダー

旧Flaskをスマホ向け本番ホストとして常時公開する方針にはしない。

## 実機確認済み

2026-09-06、beverage PR #7のWindows確認で以下を確認済み。

- `飲料在庫・発注` / `物品発注依頼処理` の2タブ
- ライト / ダークテーマ
- 既存飲料UIのレイアウト
- 正式兄弟repoの `qr_supply.sqlite3` 自動検出
- 取消データの実読込
- 状態絞り込み / 検索 / 再読込
- DB未接続でもアプリ起動継続

QRのGoogle経路はまだ実機未確認。

## 次の実機ゲート

GitHub CIを先に通し、自動テストはGitHub側で完結させる。
Codexへ重いpytest・全面UI監査・ビルドを繰り返し依頼しない。

GitHub側実装完了後に必要な実機作業だけ行う。

1. development-management と beverage 正式ローカルを最新へfast-forward
2. `RUN_DEV.cmd` で起動できることだけ確認
3. Apps Script `google_apps_script/supply_order/` をデプロイ
4. Web App URLを物品タブのQR発注設定へ保存
5. 商品同期を1回実行
6. QRラベルを1枚だけ出力
7. iPhoneで4G/5GからQRを読む
8. 数量を指定して1件発注
9. PCへ自動または `今すぐ取込` で1件だけ入ることを確認
10. 同じGoogle依頼を再取得してもSQLiteへ二重登録されないことを確認

この実機ゲートでは、ユーザーが操作確認を担当する。Codexはローカル取得・起動補助・必要最小限の設定確認に限定する。

## 次段階

QR受付が実機で通った後、PC側のFAX処理を設計・実装する。
FAX実装前に架空の状態遷移や帳票仕様を作らない。

## 経緯

2026-09-04時点では飲料システムとの統合境界を「相互URLリンクのみ」としていた。
2026-09-06、別アプリ間遷移ではなく「飲料PySide6を母艦に、物品発注依頼処理を同じウィンドウ内へ再構成する」方針へ変更した。
同日、館内Wi-Fiを利用できない運用条件を再確認し、QRスマホ受付はローカルFlask直結ではなくGoogle Apps Script / Sheetsを一時HUBとする方式に確定した。
