# qr-supply-ordering-system

## 目的

一般物品を対象に、商品QRからの発注依頼と、発注先ごとのFAX送信・送信履歴を管理する物品発注ドメイン。**在庫管理システムではない。**

2026-09-06の方針変更により、日常のPC操作UIは `beverage-inventory-ordering-system` のPython/PySide6版へ統合する。
ただし、飲料と物品の商品マスター・DB・発注先マスター・履歴・業務ロジックは共有しない。
物品側SQLiteと既存実装は物品ドメインの正として維持し、飲料側統合デスクトップから専用アダプタ経由で参照・操作する。

## 現在の状態（2026-09-07）

| 項目 | 内容 |
|---|---|
| GitHub | `4m9ccm98gt-rgb/qr-supply-ordering-system`（private） |
| 正式ローカル | `C:\Users\suisy\Documents\Development\repos\qr-supply-ordering-system` |
| 既定ブランチ | `main` |
| 物品DB | `database/qr_supply.sqlite3`。物品ドメインの正として独立維持 |
| PC統合先 | `beverage-inventory-ordering-system` Draft PR #7 / `feature/unified-ordering-flow` |
| PC UI | `飲料在庫チェック` 直下に `飲料在庫・発注` / `物品発注依頼処理` |
| QR受付 | 館内LANを使わず、スマホの4G/5G → Google Apps Script → Google Sheets一時受付箱 → PC → 物品SQLite |
| FAX | 業者別集約、個別 `FAX送信`、`未送信を一斉FAX`、Windows FAX COM送信、成功履歴までGitHub側実装済み。実運用PCでの実送信確認待ち |
| 納品管理 | 行わない |

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
FAX送信
```

### スマホ操作

QRを読むと対象商品を1商品だけ表示する。
日常入力は以下だけとする。

- 商品名表示
- 最終発注日時表示
- 数量 `- / 数量 / +`
- `発注する`

依頼者名・備考・商品検索・在庫数などは日常QR画面へ置かない。
SQLite側の依頼者名は `QR発注` として記録する。

`最終発注日時` はスマホからQR依頼を送った日時ではなく、PC側で業者へ実際にFAX送信が成功した日時を基準とする。
納品管理を行わないため、スマホ側には `発注中` / `納品待ち` のような継続状態を表示しない。
これにより、スタッフは「最後にいつ実発注した商品か」を確認できるが、納品済みかどうかをシステムが推測しない。

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
- FAX送信成功後、各商品の最終発注日時をGoogle側商品ミラーへ再同期する

### 二重発注防止

各スマホ発注に一意の `request_token` を持たせる。
物品SQLiteの既存 `order_requests.request_token UNIQUE` を冪等キーとして利用する。

- 初回: SQLiteへ発注依頼を作成
- 同じ依頼の再取得: 既存依頼として扱い、二重作成しない
- SQLiteへ保存済み / 既存確認済みのトークンだけGoogleへACKする
- 不正・マスタ不整合の行はGoogle側へ残し、黙って捨てない

## beverage側のQR実装

Draft PR #7 `feature/unified-ordering-flow` で以下を実装済み。

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
- スマホQRへの最終発注日時表示

Apps Script実装はbeverage repoの `google_apps_script/supply_order/` に置く。
既存飲料スマホ棚卸と同じSpreadsheet ID / Bridge secretを使用可能だが、物品QR用Web App URLは独立デプロイとして扱える。

## FAX処理の運用設計（2026-09-07決定）

QR依頼を検知した瞬間に自動FAXする方式にはしない。
QR受付と実FAX送信の間に明示的な送信操作を残すが、その送信操作を押した後はアプリだけで完結する完全自動送信を本命とする。

基本フロー:

```text
QR発注依頼
  ↓
PCへ自動取込
  ↓
発注先ごとに未送信依頼を自動集約
  ↓
[ FAX送信 ] または [ 未送信を一斉FAX ]
  ↓
FAX帳票を自動生成
  ↓
登録済みFAX番号を自動指定
  ↓
FAX送信ジョブ投入
  ↓
送信結果を追跡
  ↓
成功確認分だけ発注済みとして履歴保存
  ↓
商品ごとの最終発注日時をGoogleへ再同期
```

### PC画面

`物品発注依頼処理` では、未送信依頼を業者ごとのカード / グループにまとめる。
各業者グループには、その業者へ今回送る商品名・数量・発注単位を表示する。

- 各業者カードに `FAX送信`
- 画面全体に `未送信を一斉FAX`
- FAX番号未登録の業者は送信不可として残す
- ボタン押下後にFAXソフト上でFAX番号入力や送信ボタン操作を求めない設計を本命とする

一斉送信は業者単位で成功 / 失敗 / 結果不明を独立管理する。
途中で1社失敗しても他社の送信は継続する。
成功した業者だけSQLiteを発注済みに進め、失敗 / 結果不明は未送信として残す。
結果不明時は無条件再送を促さず、FAXキュー確認を要求する。

## 自動FAX送信実装（2026-09-07）

Draft PR #7では最初の自動送信エンジンとしてWindows Fax Service COM APIを実装する。

### 送信エンジン

`WindowsFaxComSender`:

- `FaxComEx.FaxServer`
- `FaxComEx.FaxDocument`
- `Recipients.Add(fax_number, recipient_name)`
- `ConnectedSubmit()` でジョブ投入
- 戻り値のFAXジョブIDを保持
- `OutgoingQueue.GetJob(job_id)` で送信状態を追跡
- `COMPLETED` を確認した場合だけ `success`
- `FAILED` / `RETRIES_EXCEEDED` / `CANCELED` は `failed`
- タイムアウト等は `unknown`
- キューからジョブが消えた場合は `OutgoingArchive.GetMessage(job_id)` を確認し、送信済みアーカイブに存在した場合だけ成功と判定

ジョブ投入成功やWindowsスプーラー受付だけでは発注成功とみなさない。

### FAX帳票

業者ごとの集約内容から白黒TIFFを自動生成する。

- 発注先
- FAX番号
- 発注日時
- 発注元
- 商品名
- 数量
- 発注単位

1ページに収まらない場合は内容を黙って切らず、送信前にエラーとする。

### 履歴

FAX送信成功時点を「実際の発注」とみなし、SQLiteへ保存する。
履歴では以下を保持する。

- 送信日時
- 発注先ID
- 発注先名スナップショット
- 送信先FAX番号スナップショット
- FAX送信エンジン名
- FAXジョブID
- 対象となった元の発注依頼ID
- 商品ID
- 商品名スナップショット
- 数量
- 発注単位

商品名・発注先・FAX番号が後日変更されても、過去に実際に何をどこへ送ったかが変わらないよう送信時点の値を保存する。
`fax_line_requests` により、集約後も元のQR発注依頼との対応を保持する。

物品側正式schemaにもFAX履歴用として以下を追加した。

- `fax_documents.vendor_name_snapshot`
- `fax_documents.fax_number_snapshot`
- `fax_documents.transport`
- `fax_documents.transport_job_id`
- additive migration version 4

既存DBは削除・再作成しない。

### 納品管理

納品済み / 未納品の管理は今回の運用対象から外す。
そのため `発注中` や `納品待ち` をスマホへ表示しない。
旧schemaや旧Webに納品状態が存在していても、新しいPySide6日常運用では納品管理を必須工程にしない。

## FAX環境調査結果

2026-09-07、Codexを利用できる開発PCで読取調査を実施。

- Microsoft Shared Fax Driver / `Fax` キューあり
- Windows Fax and Scan / FaxComEx COM登録あり
- Kyocera TASKalfa 3554ci(J) KXは通常印刷ドライバとして存在
- 京セラFAX専用ドライバは開発PCでは検出されなかった
- Windows FAX COM自体はFAX番号指定・ジョブ投入・状態取得が可能
- 開発PCのWindows FAX経路が実運用の京セラ複合機へ実際に送信できることは未確認
- 実運用PCにはCodexがないため、実運用PCの詳細な読取調査は行えない

ユーザーが実運用PCで実送信テストを担当する。
その結果に基づき、Windows FAX COMをそのまま正式送信エンジンとするか、別送信アダプタへ差し替えるか決定する。

## 現行物品ドメイン設計 / 旧Web実装

`qr-supply-ordering-system` のFlask版は物品ドメイン・schema・既存仕様の参照として維持する。

- Flask / SQLite / HTML / CSS / JavaScript
- SQLiteはアプリ経由のみ（WAL、外部キー、トランザクション）
- 旧QRは `/order-item/<item_id>` URL
- 旧依頼状態: 発注依頼 / FAX準備済み / 発注済み / 納品済み / 取消
- `/admin/requests` は旧Web版の日常業務入口
- 商品 / 発注先 / 依頼詳細 / 取消 / 履歴 / QRラベル / 発注表取込を実装済み
- 旧WebのFAX画面はプレースホルダー

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

2026-09-07、物品QR発注のGoogle経路も実機確認済み。

- Apps Scriptを物品QR発注用Web Appとして独立デプロイ
- 既存飲料スマホ棚卸と同じSpreadsheet ID / Bridge secretを使用
- `setupSupplyOrderSheets()` 正常完了
- `supply_qr_items` / `supply_qr_requests` の2シート作成
- PCから商品マスタ3件をGoogleへ同期
- iPhoneを4G/5GでQR読取
- 商品名・数量・`発注する` のスマホ画面を確認
- スマホから1件発注し、PCの `今すぐ取込` で発注依頼一覧へ1件追加
- 再度 `今すぐ取込` を実行しても2件目は作成されず、`request_token` の冪等性を実機確認

途中でWeb App公開範囲不足による401が出たが、公開設定修正後は解消。
その後の一時的な `Google bridge returned an invalid response` は再現せず、Codexの最小通信調査で `/exec` POSTが302経由で `script.googleusercontent.com/macros/echo` に到達し、最終200 / `application/json; charset=utf-8` でdoPostのJSONが返ることを確認した。コード修正は不要だった。

## 自動テスト

beverage Draft PR #7 最新HEAD `8e6785426e091e29a05e4c929bf68624d121b3cf` でGitHub Actions `Python migration tests` run #166 成功。

- Windows Server 2025 runner
- Python 3.13.15
- pywin32 311導入成功
- compileall: success
- pytest: **60 passed / 1 skipped**
- Windows FAX COMへFAX番号を渡すテスト
- FAXジョブの成功 / 失敗判定テスト
- 業者別集約
- FAX成功履歴と元依頼紐付け
- FAX番号 / transport / job IDスナップショット
- FAX成功日時からスマホ最終発注日時を導出
- 既存QR発注の冪等性

## QR実機ゲート結果

QR受付の実機ゲートは完了。
GitHub CIの自動テストと合わせ、QR読取からSQLite登録までの主要経路と二重登録防止を確認済み。

- `RUN_DEV.cmd` 正常起動
- QR発注UIの5項目表示
- Apps Scriptデプロイ
- Web App URL設定
- 商品同期
- QRラベル生成
- iPhone 4G/5G読取
- 1件発注
- PC取込
- 同一依頼の再取込で重複なし

以後、Codexへ同じQR経路の重いpytestや全面再検証を繰り返し依頼しない。

## 次の実機ゲート

次はFAX実送信確認。
実運用PCにCodexはないため、ユーザーが操作確認を担当する。

1. `development-management`、`qr-supply-ordering-system`、`beverage-inventory-ordering-system` の正式ローカルを最新へfast-forward
2. beverage `feature/unified-ordering-flow` を最新HEADへ合わせる
3. Python依存関係へ `pywin32` を反映する
4. DEV起動し、物品タブに業者別FAXカードと `FAX送信` / `未送信を一斉FAX` が表示されることを確認
5. ユーザーが指定する安全なテスト送信先で、まず1社の `FAX送信` を実行
6. 実際にFAXが届くことを確認
7. アプリ側が成功として確定し、対象依頼だけ `発注済み` になることを確認
8. FAX送信履歴にFAX番号・ジョブID・送信日時が残ることを確認
9. スマホQRの `前回発注` が送信成功日時へ更新されることを確認
10. 個別送信が通った後にだけ、一斉FAXを複数業者で確認する

実FAX送信で失敗 / 結果不明になった場合は、再送を連打せず表示されたジョブIDとWindows FAXキューの状態を確認する。
Windows FAX COM経路が実運用複合機へ接続できない場合は、`FaxSender` 境界を維持したまま送信アダプタだけ差し替える。

## 経緯

2026-09-04時点では飲料システムとの統合境界を「相互URLリンクのみ」としていた。
2026-09-06、別アプリ間遷移ではなく「飲料PySide6を母艦に、物品発注依頼処理を同じウィンドウ内へ再構成する」方針へ変更した。
同日、館内Wi-Fiを利用できない運用条件を再確認し、QRスマホ受付はローカルFlask直結ではなくGoogle Apps Script / Sheetsを一時HUBとする方式に確定した。
2026-09-07、Apps Script独立デプロイからiPhone 4G/5G発注、PC取込、`request_token` 再取込まで実機確認し、QR受付ゲートを完了した。
同日、FAXは業者別自動集約 + 個別送信 / 一斉送信 + 送信履歴とし、納品管理は行わない方針を決定。スマホには継続状態ではなくFAX送信成功時点の `最終発注日時` を表示する方針とした。
同日、ユーザー方針によりFAX番号コピー方式を本命とせず、アプリ内ボタンだけで完結する自動送信ベースで実装する方針へ更新。Windows FAX COMを最初の送信エンジンとして実装し、GitHub CIを通過した。実運用PCでの実FAX送信だけを次の実機ゲートとする。
