# 変更履歴

新しい記録を上に追加します。「確認状況」は、未確認／開発環境確認済み／実運用確認済みを明記します。

## v1.0.0 - 2026-07-20

Initial stable release.

### Added

- `AI_OPERATING_MANUAL.md`
- `AI_CHECKLIST.md`
- `PROMPT_PRINCIPLES.md`
- `PROJECT_BOOTSTRAP.md`
- `AGENTS.md`
- AI引き継ぎとAI共同開発フロー
- プロジェクト化完了の定義

### Changed

- `AI_STARTUP.md` の開始手順
- ChatGPTとCodexの役割分担
- `development-management` の位置付け
- 新規プロジェクト立ち上げ手順

### Result

`development-management` を「AI共同開発基盤」v1.0.0として正式化。

| 日付 | 変更対象プロジェクト | 変更内容 | 確認状況 |
|---|---|---|---|
| 2026-07-21 | call-reception-assistant | 空の正式GitHubリポジトリを `Development\repos` 配下へcloneし、README、`docs/`、AI引き継ぎ、AI作業ガイド、`.gitignore`を作成。初回commit・pushと管理文書への登録を実施 | `main`と`origin/main`が`95bd3ca`で一致、Git状態クリーン、文書リンク・秘密情報を確認。アプリ本体は未実装。`PROJECT_BOOTSTRAP v1.0.0`に基づくプロジェクト化完了 |
| 2026-07-20 | beverage-inventory-ordering-system | 単体タスクで開発していた飲料発注システムを正式プロジェクトの `apps/ordering/` へ移管。在庫管理画面から起動するサブシステムとして位置付け、README、docs、AI引き継ぎ、development-managementを「飲料在庫管理＋飲料発注システム」へ更新 | JavaScript構文確認、静的ファイル存在確認、Git差分確認済み。発注システムは開発中。実業者名・実FAX番号・実発注履歴はGit管理対象外 |
| 2026-07-20 | next-day-setup | ケーキ発注書の緊急用手動印刷を追加。受取日を直接指定し、業務日＝受取日－4日を確認表示して、自動印刷と同じ単日生成・Excel印刷処理を1回だけ実行 | 構文確認・自動テスト38件成功。テスト用出力ファイル生成と注文なし時の未出力を確認。実画面・実Excel・実プリンターは未確認。コミット／pushなし |
| 2026-07-20 | next-day-setup | ケーキ受取日を対象業務日＋4日に固定。Google Sheets休館日を在庫照合と同じ取得・解析・3日キャッシュ方式で参照し、休館前日・連続休館日の未実行分を受取日別に前倒し連続印刷する処理とテストを追加 | 構文確認・自動テスト36件・公開CSV実取得成功。実Excel／実プリンター、画面表示、EXE、共有版は未確認。コミット／pushなし |
| 2026-07-20 | development-management | `AGENTS.md`をAI向け入口ガイドとして整備し、ChatGPT／Codexの役割分担、指示書優先、知識記録、Git運用を要約。`PROJECT_BOOTSTRAP.md`を追加し、単体タスクの正式プロジェクト化手順と完了定義を標準化 | 文書差分・リンク・役割分担を確認済み。コード・業務システム変更なし |
| 2026-07-20 | beverage-inventory-ordering-system | 正式ソースのローカル`main`をGitHub `main`（`8d2ab9c`）へfast-forward。アプリ本体と文書のGitHub反映、ローカル同期完了を管理文書へ反映し、次工程を飲料発注アプリの取り込み調査へ更新 | HEAD・main・origin/main一致、Git statusクリーン、JavaScript構文、ブラウザ起動、コンソールエラーなしを確認。機能・UI・保存方式の変更なし |
| 2026-07-20 | development-management | AI回答品質・提案品質を標準化する`PROMPT_PRINCIPLES.md`を追加。回答方針、提案方針、開発方針、Codex連携、回答スタイル、継続開発の原則を定義し、AI開始順序とREADMEへ組み込み | 文書差分・リンク・読む順番を確認済み。コード・業務システム変更なし |
| 2026-07-20 | development-management | AI運用を標準化。`AI_OPERATING_MANUAL.md`と`AI_CHECKLIST.md`を追加し、AIの役割、Codexとの役割分担、思考順序、指示書優先、開始時の確認順序を整理。README、AI_STARTUP、AI_MEMORYを更新 | 文書差分・リンク・責務分離を確認済み。コード・業務システム変更なし |
| 2026-07-18 | next-day-setup | PMS番号付き手配枠の構造化、3日後ケーキ検出、CSV期間警告、確認画面、マクロ転記仕様メモ、テストを追加 | 構文確認・自動テスト14件・実CSV解析済み。画面・転記・印刷は実運用未確認。コミット／pushなし |
| 2026-07-16 | development-management | `VERSION_MATRIX.md`と`AI_MEMORY.md`を追加し、README、AI開始手順、AI引き継ぎ、現在地へ組み込み | ローカル文書作成・必須項目確認済み。コミット／push前 |
| 2026-07-16 | development-management | AI開始手順、Current Focus、知識管理ルール、判断・依頼テンプレート、日次ログ、全体構成図を追加 | ローカル文書作成済み。コミット／push前 |
| 2026-07-16 | development-management | 司令塔リポジトリの文書構成を新規作成 | ローカル文書作成済み。コミット／push前 |
| 2026-07-16 | next-day-setup | Google Sheetsシフト取得、印刷、ビルド、共有版更新に関する作業を進行中として記録 | 未コミット差分を確認。動作・実運用は未確認 |
| 2026-07-16 | inventory-reconciliation-system | Google Sheets休館日取得、キャッシュ、夜間実行、警告メールに関する作業を進行中として記録 | 未コミット差分を確認。動作・実運用は未確認 |
