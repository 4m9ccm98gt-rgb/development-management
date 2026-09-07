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
| FAX | 業者別集約、個別 `FAX送信`、`未送信を一斉FAX`、Windows FAX COM送信、成功履歴、永続診断ログまで実装済み。開発PCではCOMジョブ投入とNO_LINE安全挙動まで実機確認済み。次は実運用PCでの実送信確認 |
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
- 一斉送信は業者単位で成功 / 失敗 / 結果不明を独立管理
- 成功した業者だけSQLiteを発注済みに進める
- 失敗 / 結果不明は未送信として残す
- 結果不明時は無条件再送しない

## 自動FAX送信実装（2026-09-07）

Draft PR #7では最初の自動送信エンジンとしてWindows Fax Service COM APIを実装した。

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

### 成功履歴

FAX送信成功時点を「実際の発注」とみなし、SQLiteへ保存する。

- 送信日時
- 発注先ID / 名スナップショット
- FAX番号スナップショット
- transport
- transport job ID
- 元発注依頼ID
- 商品ID / 名スナップショット
- 数量 / 発注単位

`fax_line_requests` により、集約後も元QR発注依頼との対応を保持する。
物品側schemaはadditive migration version 4で `vendor_name_snapshot`, `fax_number_snapshot`, `transport`, `transport_job_id` を追加済み。
既存DBは削除・再作成しない。

## FAX診断ログ（2026-09-07）

実運用PCでCodexを使えないため、送信失敗時も持ち帰って解析できる永続診断を実装済み。

既定保存先:

`%USERPROFILE%\Documents\ShizenTenyou\FaxDiagnostics`

環境変数 `SUPPLY_FAX_LOG_DIR` で上書き可能。

保存物:

- 1試行ごとの `fax_attempt_*.log` JSON Lines
- `fax_attempts.sqlite3`
  - `fax_attempts`: 1試行1行の要約
  - `fax_attempt_events`: COM接続、宛先設定、submit、job状態、Archive確認、結果の時系列

主な記録:

- PC名
- transport
- 宛先名 / FAX番号
- 帳票パス
- job ID
- COM初期化 / FaxServer接続
- Recipients.Add
- ConnectedSubmit
- job status / status code / ExtendedStatus
- Archive確認
- success / failed / unknown / cancelled
- 例外内容

診断ログの書込み失敗はFAX処理そのものを止めない。
診断SQLiteは業務SQLiteと独立し、診断結果だけで発注状態を変更しない。

## 実機確認済み

### UI / QR

2026-09-06〜07:

- `飲料在庫・発注` / `物品発注依頼処理` の2タブ
- 正式兄弟repoの物品SQLite自動検出
- 状態絞り込み / 検索 / 再読込
- Apps Script独立デプロイ
- PCから商品マスタ3件をGoogleへ同期
- iPhone 4G/5GでQR読取・発注
- PC取込
- 同一 `request_token` 再取込で重複なし

QR受付ゲートは完了。

### 開発PC FAX

2026-09-07、開発PCで以下を実機確認済み。

- Windows標準 `Fax` / `Microsoft Shared Fax Driver` / FaxComEx COM存在
- COM生成 / `Connect("")`
- OutgoingQueue / OutgoingArchiveアクセス
- アプリから `0558-52-1234` を渡して実ジョブ投入
- job ID `201dd3e6e74f54a`
- 状態 `pending + NO_LINE`（status code 33）
- 回線未確保のため手動キャンセル
- キュー0件
- `fax_attempt_*.log` 永続保存成功
- 診断DB `fax_attempts.sqlite3` 永続保存成功
- attempt ID 1
- `started → COM初期化 → server接続 → document設定 → recipient追加 → submitted → pending/no_line → unknown → COM終了` を記録
- キャンセル後にジョブが消えたため最終診断は安全側の `unknown`
- `fax_documents` 成功履歴は0件
- 対象依頼ID 2は `requested` / 1ケースのまま

この結果により、**送信経路が成立しないPCでも成功誤判定せず、発注済みに進めず、原因解析ログを持ち帰れることを実機確認済み。**

## 自動テスト

GitHub Actions Windows runnerで最新版成功。

- Python 3.13.15
- pywin32 311
- compileall success
- pytest **61 passed / 1 skipped**
- FAX番号受け渡し
- success / failed判定
- `no_line → timeout → unknown`
- 診断log生成
- 診断SQLite / イベント履歴
- 成功履歴 / job ID / スマホ最終発注日時
- QR冪等性

重い全面テストを同じ条件で繰り返さない。

## 次の実機ゲート

次は、**日常的にFAX送信を行っている実運用PCでの個別実送信確認**。

開発PCでテスト版EXEを作成し、実運用PCの既存環境やデータを汚さない専用テストbundleとして持ち込む。

推奨bundle:

- PyInstaller onedir `BeverageInventory` 一式
- 開発用物品DBからSQLite backup APIで作成した専用 `qr_supply_fax_test.sqlite3`
- `QR_SUPPLY_DB_PATH` をそのテストDBへ向ける専用起動CMD
- `SUPPLY_FAX_LOG_DIR` をbundle内 `FaxDiagnostics` へ向ける
- source HEAD / EXE SHA-256 / 操作手順を記したテキスト

実運用PCではインストールや既存DB置換をせずbundleから起動する。

1. サンプル商店 / `0558-52-1234` / トイレットペーパー1ケースを確認
2. 個別 `FAX送信` を1回だけ押す
3. 一斉FAXは使わない
4. 実際の着信を確認
5. 成功なら `COMPLETED` / Archive、job ID、成功履歴、対象依頼 `ordered` を確認
6. 失敗 / unknownなら再送せずbundle内 `FaxDiagnostics` を開発PCへ持ち帰る
7. 個別成功後にのみ一斉FAX検証へ進む

Windows FAX COMが実運用PCの実送信経路につながらない場合はtransportだけ差し替える。

PR #7はDraftのまま維持する。merge / 本番配布 / tagは別判断。

## 経緯

2026-09-04時点では飲料システムとの統合境界を「相互URLリンクのみ」としていた。
2026-09-06、別アプリ間遷移ではなく「飲料PySide6を母艦に、物品発注依頼処理を同じウィンドウ内へ再構成する」方針へ変更した。
同日、館内Wi-Fiを利用できない運用条件を再確認し、QRスマホ受付はローカルFlask直結ではなくGoogle Apps Script / Sheetsを一時HUBとする方式に確定した。
2026-09-07、Apps Script独立デプロイからiPhone 4G/5G発注、PC取込、`request_token` 再取込まで実機確認し、QR受付ゲートを完了した。
同日、FAXは業者別自動集約 + 個別送信 / 一斉送信 + 成功履歴とし、納品管理は行わない方針を決定。スマホにはFAX送信成功時点の `最終発注日時` を表示する方針とした。
同日、自動送信ベースのWindows FAX COM transportを実装し、開発PCで実job投入まで確認。開発PCはNO_LINEだったが、永続診断ログと安全側のunknown判定、業務DB非更新まで実機確認した。次の本命ゲートは実運用PCの実FAX送信。
