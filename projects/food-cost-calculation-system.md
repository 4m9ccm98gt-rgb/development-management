<!-- 旧cloneから救出。「現在の状態」「確認結果」等の日付・commit・件数は古い。正本化時に最新へ更新すること。 -->

# food-cost-calculation-system

## 概要

料理長が月次で行う納品伝票の確認、電卓集計、売上との照合を段階的に効率化する料理原価計算システムです。Phase 1では原価率計算より、伝票画像から業者名・合計金額を人が確認して保存する前工程を優先します。

## 正式ソース

- GitHub: `https://github.com/4m9ccm98gt-rgb/food-cost-calculation-system.git`
- 正式ローカルパス: `C:\Users\suisy\Documents\Development\repos\food-cost-calculation-system`
- 作業ブランチ: `codex/bootstrap-invoice-reading`

## 現在の状態

- 2026-08-09に空のGitHubリポジトリを正式ローカルパスへclone
- PySide6、SQLite、OpenCV、交換可能なOCR interfaceを採用
- 伝票取込、複数伝票分割、候補編集・保存、伝票一覧、月次ダッシュボードを実装
- Phase 1.5として短期トークン付きQR、スマホ撮影ページ、LAN内画像送信、PC即時反映を実装
- Google Apps Script Web App＋非公開Drive一時受信箱＋PCポーリングによる4G／5G対応PoCを実装。Google実デプロイは未実施
- PC SQLiteを正本、Googleを一時受け渡し、LAN方式を補助経路とする境界を文書化
- PCブラウザを390×844に設定し、LAN URL表示、画像プレビュー、削除、multipart送信、送信完了表示を代替検証
- ローカルTesseractは任意。未導入でも手入力で保存可能
- 架空画像による複数伝票分割、自動テスト、compileall、UI起動、スクリーンショットを確認
- 変更は未コミット・未push。プロジェクト化進行中

## Phase 1境界

画像追加、複数伝票候補分割、業者名・合計金額の候補表示、人による修正、SQLite確定保存、一覧・ダッシュボード反映までです。原価率計算、PMS売上CSV、明細読取、Excel出力、クラウドOCR契約は対象外です。

## 次の作業

1. ユーザー操作でApps Script、非公開Driveフォルダ、Script Properties、Web App、cleanup triggerを設定する
2. Google実環境でセッション、アップロード、PC回収、ack後ゴミ箱移動を確認する
3. Wi-Fiを切ったスマホの4G／5Gで背面カメラ、複数撮影、PC即時反映を確認する
4. LAN版実機、実伝票分割、OCR精度を継続評価する

## 未確認事項

- 実伝票の撮影条件、業者名・合計金額の正解率
- Tesseract本体・日本語言語データを入れた実機OCR
- 実運用担当者による画面・入力手順評価
- iPhone／Android実機のカメラ起動、HEIC到達有無、同一LAN接続
- Apps Script公開範囲・所有アカウント、Google Drive一時フォルダ、実割当、4G／5G実機
- GitHub公開範囲、既定ブランチ、ブランチ保護
- 初回commit、push、GitHub同期

## 禁止事項

実伝票、OCR実データ、実DB、APIキー、credential、実業者情報をGit管理しません。OCR結果だけで自動確定せず、人が確認できる設計を維持します。
