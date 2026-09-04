# qr-supply-ordering-system

## 目的

一般物品を対象に、商品 QR からの発注依頼と、発注先ごとの FAX 準備・送信完了・納品を管理する
社内 LAN Web アプリ。**在庫管理システムではない。**飲料システムとは相互 URL リンクだけを許可し、
コード・DB・マスタ・履歴は共有しない。

## 現在の状態（2026-09-04 時点）

| 項目 | 内容 |
|---|---|
| GitHub | `https://github.com/4m9ccm98gt-rgb/qr-supply-ordering-system`（private） |
| 正式ローカル | `C:\Users\suisy\Documents\Development\repos\qr-supply-ordering-system` |
| 既定ブランチ | `main` |
| 最新コミット | `790fff5`（CI を `@ci-v1` へ固定） |
| 種別（repo_types.toml） | `web` |
| 実装状態 | **Phase 1 / 1.5 と既存発注表取込を含む実装が `main` に反映済み**。以前は `origin/main` がスケルトン（`3e800f8`）のみで、実装は正式ローカルの未 push 分だった。混入監査のうえ `feature/phase1-implementation`（`a07ff49`）へ保存し、`qr-supply#2`（`1b3879e`）で `main` へ merge。標準化 `qr-supply#1`（`eb2068a`）は別履歴 |
| commit / push | 済み。正式ローカル `main` と `origin/main` 一致 |
| 標準化 | `RUN_DEV.cmd`（`import flask` チェック → `python run.py`）、`DEPLOY.md`（社内 LAN 1 ホスト構成）、CI（`standards.yml` warning-only）有り |
| RUN_DEV 実機確認 | 実装入り clone で `cmd.exe /c RUN_DEV.cmd` を実行し、venv 作成 → `pip install`（Flask 3.1.1 / qrcode / openpyxl ほか）→ `python run.py` で開発サーバ起動 → **GET / 200 / GET /health 200** → exit 0 を確認（2026-09-04） |
| 設定 | `config/settings.py` の読み込み機構は**未実装**。設定はコード既定値＋環境変数 `QR_BASE_URL`（既定 `http://127.0.0.1:5000`）。`config/settings.example.py` は将来の想定値で現行コードは未読込。詳細は repo の `DEPLOY.md` |
| DB | `database/qr_supply.sqlite3`（現状は開発データ。13表）。初回起動時に `ensure_database()` が自動作成。`BACKUP_DEV_DATA.ps1` の対象。`scripts/backup_db.ps1` も有り |
| 開発フェーズ | Phase 1（発注依頼・管理・QR ラベル・依頼詳細・取消）＋ Phase 1.5（ホーム 3 区分・共通ナビ・パンくず）＋既存発注表取込（xlsx/xlsm/CSV のプレビュー→確定、`import_batches` schema）実装済み。本番運用は未開始 |

## 設計

- Flask / SQLite / HTML / CSS / JavaScript
- SQLite はアプリ経由のみ（WAL、外部キー、トランザクション）
- QR は `/order-item/<item_id>` を含む URL のみ。商品名・FAX 番号は埋め込まない
- 依頼状態: 発注依頼 / FAX 準備済み / 発注済み / 納品済み / 取消
- `/` を管理コンソール、`/admin/requests` を発注担当者の日常業務入口

## 未確認事項

- 実スマートフォン、実 QR カメラ読取、社内 LAN 端末間通信、固定ホスト名 / 固定 IP、HTTPS 要否
- 印刷実機、実 FAX、管理者認証方式、常時起動方式（Flask 開発サーバは本番非推奨。WSGI 未導入）
- 既存発注表の候補ファイルが現行運用の正式発注表であることの業務確認、正式 DB への確定取込
- `config/settings.py` 読み込み層を追加するか（`SECRET_KEY` / `DATABASE` の外部化）

## 経緯（参考・旧 clone `開発環境整備プロジェクト` より、当時の記述、2026-07-23 時点）

- 第1期と既存 FAX 発注表取込に加え、Phase 1.5 の管理コンソール・役割別入口・共通レイアウト・
  現在位置付きナビ・パンくず・QR ラベル業務 UI を実装。既存 URL・FAX 機能・DB 構造は不変。
- （当時）差分は未コミット・未 push、GitHub `main` はスケルトン `3e800f8` — **現在は上記のとおり `main` に merge 済み。**
- pytest 18件成功、実候補 xlsm から発注先17件・商品104件を検出（正式 DB へは未取込）。
