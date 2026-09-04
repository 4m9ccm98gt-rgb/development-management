# 旧 clone からの救出（`Documents\開発環境整備プロジェクト`）

`Documents\開発環境整備プロジェクト` は development-management の旧 clone。
コミット履歴は canonical の祖先（失われたコミットは無し）だが、**15件の未 push 编集**があった。
各ファイルを canonical の現状と1件ずつ比較し分類した。**canonical を旧 clone で上書きはしていない。**
取り込み候補はこのブランチ（`recovery/from-old-clone-docs`）に**追記**の形でまとめてある。
このブランチはレビュー用。内容確認のうえ、必要な部分だけ正本へ取り込むこと。

## 分類

| ファイル | 旧 clone の追加内容 | 判定 | このブランチでの扱い |
|---|---|---|---|
| `BUSINESS_MODEL.md`（新規 187行） | 全システム共通の業務モデル／タスクモデル | **救出**（canonical に無い基盤文書。秘密・顧客情報・認証情報なし） | 追加 |
| `projects/food-cost-calculation-system.md`（新規） | プロジェクト文書 | **救出**（canonical `projects/` に欠落。秘密なし） | 追加。冒頭に「日付・commit・件数は古い」注記 |
| `projects/qr-supply-ordering-system.md`（新規） | プロジェクト文書 | **救出**（同上。現在は実アプリが main に merge 済みなので「現状」節は古い） | 追加。同注記 |
| `AI_OPERATING_MANUAL.md`（+86） | フェーズ規律フレームワーク（調査／設計／実装の境界、仮説の扱い、回答前セルフチェック） | **救出**（canonical に無い AI 運用知識。秘密なし） | 末尾に追記（配置は要見直し） |
| `AI_CHECKLIST.md`（+5） | フェーズ確認項目 | **救出**（上と一体） | 末尾に追記 |
| `PROMPT_PRINCIPLES.md`（+2） | フェーズ優先原則 | **救出**（上と一体） | 末尾に追記 |
| `LESSONS_LEARNED.md`（+1） | 業務分類の教訓 | **救出** | 末尾に追記 |
| `docs/decisions.md`（+43） | 5つの設計判断（期間限定タスクエンジン／台帳カレンダー休館日表示／発注書は手配先だけ管理／QR物品発注は独立Web／既存発注表はプレビュー後トランザクション取込） | **救出**（canonical に未反映の設計判断。実 FAX 番号・実業者名などの値は含まない） | 末尾に追記 |
| `AI_STARTUP.md`（±19） | 読む順に `BUSINESS_MODEL.md` を挿入、標準プロンプト更新 | **条件付き救出**：`BUSINESS_MODEL.md` を正本化する場合のみ意味を持つ | このブランチでは未適用。正本化判断後に反映 |
| `projects/next-day-setup.md`（+26） | NDS の機能更新記録（期間限定タスクエンジン実装、料理名補完廃止、263テスト成功、commit `14eb0c0`） | **要判断**：機能記述は実在だが commit / tag 参照が古い。canonical の該当文書と突き合わせて必要分のみ | 未適用 |
| `VERSION_MATRIX.md`（+38） | food-cost / qr-supply の行 | **旧・要最新化**：表に両プロジェクトを足すのは有用だが、内容が古い（2026-08-09、空リポジトリ表記、PySide6 6.11.1） | 未適用。canonical で新規に書き起こす |
| `REPOSITORIES.md`（+17） | food-cost / qr-supply の行 | **旧・要最新化**：同上（`3e800f8` 同期表記など） | 未適用。canonical で新規に書き起こす |
| `CHANGELOG.md`（+18）/ `DAILY_LOG.md`（+68）/ `PROJECT_STATUS.md`（+24） | ログ・状況の追記（2026-09-01 以前） | **旧・不要**：canonical に自前の新しい記録がある | 未適用 |

## 次の対応

1. このブランチをレビューし、`BUSINESS_MODEL.md`・`projects/*.md`・フェーズ規律・5設計判断を正本へ取り込むか判断する。
2. 取り込む場合、`AI_STARTUP.md` の読む順も更新する。
3. `VERSION_MATRIX.md` / `REPOSITORIES.md` に food-cost / qr-supply を**現在の実態で**追記する（旧 clone のテキストは使わない）。
4. `projects/next-day-setup.md` は canonical 版と突き合わせ、未反映の機能記述だけ足す。
5. 判断が済むまで `Documents\開発環境整備プロジェクト` は削除しない。
