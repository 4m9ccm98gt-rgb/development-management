# qr-supply-ordering-system

## 目的

一般物品を対象に、商品 QR からの発注依頼と、発注先ごとの FAX 準備・送信完了・納品を管理する
物品発注ドメイン。**在庫管理システムではない。**

2026-09-06 の方針変更により、日常操作UIは beverage-inventory-ordering-system の Python/PySide6 版へ統合する。
ただし、飲料と物品の商品マスター・DB・発注先マスター・履歴・業務ロジックは共有しない。
物品側 SQLite と既存実装は物品ドメインの正として維持し、飲料側の統合デスクトップから専用アダプタ経由で参照・操作する。

## 現在の状態（2026-09-06 時点）

| 項目 | 内容 |
|---|---|
| GitHub | `https://github.com/4m9ccm98gt-rgb/qr-supply-ordering-system`（private） |
| 正式ローカル | `C:\Users\suisy\Documents\Development\repos\qr-supply-ordering-system` |
| 既定ブランチ | `main` |
| 最新 main | `790fff5`（CI を `@ci-v1` へ固定） |
| 種別（repo_types.toml） | `web` |
| 実装状態 | **Phase 1 / 1.5 と既存発注表取込を含む実装が `main` に反映済み**。発注依頼・管理・QR ラベル・依頼詳細・取消・履歴・商品/発注先マスターを実装済み。FAX工程は現時点では第2期プレースホルダー。 |
| commit / push | main は正式ローカルと origin が一致する運用。旧 UI 連携 Draft PR #5 は方針変更により未mergeでclose。 |
| 標準化 | `RUN_DEV.cmd`（`import flask` チェック → `python run.py`）、`DEPLOY.md`、CI（`standards.yml` warning-only）有り |
| RUN_DEV 実機確認 | 実装入り clone で `cmd.exe /c RUN_DEV.cmd` を実行し、venv 作成 → `python run.py` で開発サーバ起動 → **GET / 200 / GET /health 200** を確認（2026-09-04） |
| 設定 | `config/settings.py` の読み込み機構は未実装。設定はコード既定値＋環境変数 `QR_BASE_URL`（既定 `http://127.0.0.1:5000`）。 |
| DB | `database/qr_supply.sqlite3`。物品ドメインの正として独立維持する。飲料側の `inventory-data.json` とは統合しない。 |
| 統合先UI | beverage-inventory-ordering-system Draft PR #7 `feature/unified-ordering-flow`。`飲料在庫チェック` 直下に `飲料在庫・発注` / `物品発注依頼処理` のトップレベルタブを置く。 |

## 統合境界（2026-09-06 決定）

### 同じ建物にするもの

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
`物品発注依頼処理` には物品側の実装済み業務機能をPySide6ネイティブUIとして段階的に再構成する。
WebViewや外部ブラウザへの単純遷移を統合の完成形とはしない。

### 共有しないもの

- 飲料商品マスター ↔ 物品商品マスター
- 飲料発注履歴 ↔ 物品発注依頼履歴
- 飲料JSON ↔ 物品SQLite
- 物品の発注先マスター
- 物品固有の依頼状態・取消・将来のFAX処理ロジック

統合は「データ統合」ではなく「デスクトップUIと業務導線の統合」とする。

### 物品データへの接続

- 物品側の正は `qr-supply-ordering-system/database/qr_supply.sqlite3`
- beverage側では専用の `SupplyRequestStore` 等の境界層を通して参照する
- DEVでは正式ローカルの兄弟repoを自動検出可能にする
- 必要時は `QR_SUPPLY_DB_PATH` で明示する
- 将来、配布構成を変更する場合もDB境界を維持し、飲料マスターへ吸収しない

## 現行物品ドメイン設計

- Flask / SQLite / HTML / CSS / JavaScript
- SQLite はアプリ経由のみ（WAL、外部キー、トランザクション）
- QR は `/order-item/<item_id>` を含む URL のみ。商品名・FAX 番号は埋め込まない
- 依頼状態: 発注依頼 / FAX 準備済み / 発注済み / 納品済み / 取消
- `/admin/requests` は現行Web版における発注担当者の日常業務入口
- UI統合後も、物品側DB・マスター・履歴の責務はこのドメインに残す

## 現在の統合実装範囲

beverage-inventory-ordering-system PR #7 で、まず以下を同一PySide6ウィンドウへ移す。

- `物品発注依頼処理` トップレベルタブ
- 発注依頼一覧
- 状態フィルター
- 文字検索
- 件数サマリー
- 物品SQLiteからの読込

現行物品WebアプリでもFAX工程は第2期プレースホルダーのため、PR #7 では架空のFAX処理を追加しない。
次段階で現行実装済みの詳細・取消・履歴・マスター管理を必要な順にPySide6へ再構成する。

## 未確認事項

2026-09-06 Windows確認追記: beverage PR #7の候補 `94dcd29` を正式ローカルへ取得し、
2タブ・ライト/ダーク・正式物品SQLiteの自動検出・取消1件の実読込・状態/検索/再読込・
DB未接続時の起動継続を確認した。物品repoは `main` / `790fff5` とoriginが一致。
物品コード・DB schema・マスター・FAX処理は変更していない。
詳細と検証の限界は `projects/beverage-inventory-ordering-system.md` の2026-09-06追記を参照。
以下の実機UI関連項目は同追記の範囲で確認済み。スマートフォン・本番運用関連は引き続き未確認。

- PR #7 を正式Windowsローカルへ取得した際の2タブ実描画
- ライト / ダークテーマ
- 既存飲料UIへのレイアウト影響
- 実 `qr_supply.sqlite3` の読込
- 状態絞り込み・検索・更新時再読込
- 実スマートフォン、実 QR カメラ読取、社内 LAN 端末間通信、固定ホスト名 / 固定 IP、HTTPS 要否
- 印刷実機、実 FAX、管理者認証方式、常時起動方式
- 既存発注表の候補ファイルが現行運用の正式発注表であることの業務確認、正式 DB への確定取込

## Windows-real 次工程

Development の能力分担に従い、GitHub側実装後は Codex 等の `windows-real` セッションで以下を確認する。

1. `development-management` を先に fetch して最新方針を読む
2. beverage 正式ローカルを安全確認し `feature/unified-ordering-flow` へ追従
3. `python_app\RUN_DEV.cmd` で起動
4. 2タブ表示と既存飲料UIを実機確認
5. `物品発注依頼処理` が正式ローカルの物品SQLiteを読めることを確認
6. 検索・状態絞り込み・リロード・ライト/ダークを確認
7. pytest と `git diff --check` を実行
8. 実機依存の軽微修正が必要ならcommit + push
9. merge / EXEビルド / 本番配布は行わない

## 経緯

2026-09-04 時点では飲料システムとの統合境界を「相互 URL リンクのみ」としていた。
2026-09-06、ユーザーの業務イメージを再確認し、別アプリ間遷移ではなく「飲料PySide6を母艦に、物品発注依頼処理を同じウィンドウ内へ再構成する」方針へ変更した。
ただし、マスター・DB・履歴の非共有原則は維持する。
