# food-cost-calculation-system（俺伝）

## 概要

料理長が月次で行う納品伝票の確認・集計・売上照合を段階的に効率化する料理原価計算システム。
Phase 1 は原価率計算より、伝票画像から業者名・合計金額を人が確認して保存する前工程を優先する。

## 現在の状態（2026-09-04 時点）

| 項目 | 内容 |
|---|---|
| GitHub | `https://github.com/4m9ccm98gt-rgb/food-cost-calculation-system`（private） |
| 正式ローカル | `C:\Users\suisy\Documents\Development\repos\food-cost-calculation-system` |
| **既定ブランチ** | `codex/bootstrap-invoice-reading`（`main` は無い。M3 で既定ブランチ名依存を監査予定） |
| 最新コミット | `1940db0`（CI を `@ci-v1` へ固定）。実装は push 済みで初回 commit 前ではない |
| 種別（repo_types.toml） | `desktop` |
| 開発フェーズ | Phase 1 実装済み。`cc476ca` で仕入税基準を原価計算へ追加。Phase 1.5（短期トークン QR / スマホ撮影 / LAN 送信）実装済み。Google Apps Script 経由の 4G/5G PoC 実装済み・実デプロイ未実施 |
| 標準化 | `RUN_DEV.cmd`（`import PySide6; import cv2; import PIL; import pytesseract; import flask; import qrcode` チェック）、`BUILD_俺伝_CLICK_ME.cmd`、`UPDATE_HDD_CLICK_ME.cmd`、CI（`standards.yml` warning-only）すべて有り |
| RUN_DEV 実機確認 | 一時 clone で `cmd.exe /c RUN_DEV.cmd --screenshot` を実行し、venv 作成 → `pip install`（PySide6 ほか）→ ウィンドウ描画 → exit 0 を確認（2026-09-04）。依存欠落検知も確認 |
| 実運用データ | `%LOCALAPPDATA%\FoodCostCalculation\food_cost.db`（9表 28,566行）ほか。`BACKUP_DEV_DATA.ps1` の対象。`config\google_capture.json` は `bridge_secret` を含む（Git 管理外） |
| 配布 | 外付け HDD（`E:`）経由。`UPDATE_HDD_CLICK_ME.cmd` はボリュームラベル検出・既存リリース非上書き・`updater_settings.json` 保持 |

## Phase 1 の境界

画像追加、複数伝票候補分割、業者名・合計金額の候補表示、人による修正、SQLite 確定保存、一覧・
ダッシュボード反映まで。原価率計算、PMS 売上 CSV、明細読取、Excel 出力、クラウド OCR 契約は対象外。

## 未確認事項

- 実伝票の撮影条件、業者名・合計金額の正解率、Tesseract 本体・日本語データを入れた実機 OCR
- 実運用担当者による画面・入力手順評価、iPhone/Android 実機のカメラ起動・HEIC 到達
- Apps Script の公開範囲・所有アカウント、Google Drive 一時フォルダ、4G/5G 実機
- `codex/bootstrap-invoice-reading` を既定にしたままでよいか（`main` 化の是非は M3 で判断）
- 俺伝 HDD 配布の業務データの復元検証（H7）

## 禁止事項

実伝票・OCR 実データ・実 DB・API キー・credential・実業者情報を Git 管理しない。
OCR 結果だけで自動確定せず、人が確認できる設計を維持する。

## 経緯（参考・旧 clone `開発環境整備プロジェクト` より、当時の記述）

- 2026-08-09 に空の GitHub リポジトリを正式ローカルパスへ clone。PySide6 / SQLite / OpenCV /
  交換可能な OCR interface を採用。伝票取込・複数伝票分割・候補編集保存・伝票一覧・月次ダッシュボードを実装。
- Phase 1.5 として短期トークン QR・スマホ撮影ページ・LAN 内画像送信・PC 即時反映を実装。
- Google Apps Script Web App ＋非公開 Drive 一時受信箱＋ PC ポーリングによる 4G/5G 対応 PoC を実装（Google 実デプロイ未実施）。
- PC SQLite を正本、Google を一時受け渡し、LAN 方式を補助経路とする境界を文書化。
- （当時）変更は未コミット・未 push、プロジェクト化進行中 — **現在は上記のとおり push 済み・CI 済み。**
