# 変更履歴

新しい記録を上に追加します。「確認状況」は、未確認／開発環境確認済み／実運用確認済みを明記します。

## v1.1.2 - 2026-09-01

### Changed

- `beverage-inventory-ordering-system` のPython移行で、旧PySide6タブUIが現行ブラウザUIと大きく異なることをWindows実機で確認。
- Python/PySide6移行自体は継続し、現行 `index.html` / `styles.css` / `app.js` の最終UIをUI仕様正本として全面再構築する方針を正式化。
- WebView等へ切り替えず、PySide6ネイティブUIとして現行の色、余白、寸法、配置、情報密度、操作順を再現する。
- 共有サーバー試験はUI一致確認まで停止する。
- ユーザー手動EXEビルドは成功済みだが、EXE起動成功とUI同等性確認を別ゲートとして管理する。
- PySide6 UI全面再構築第一弾を `python-desktop-migration` に実装。旧 `QTabWidget` を撤去し、業務順1画面ダッシュボード、商品調整・個別発注・棚卸し管理画面を再構成。
- ブラウザCSSの主要色・寸法をPySide6側へ反映し、UIソース検査を追加。

### Result

データ・業務計算互換性は66/66商品一致のまま維持。UI全面再構築第一弾HEAD `d5d3e65c` はWindows-latestのPython compile / migration tests成功。次工程はWindows `RUN_DEV.cmd` でブラウザ版との横並び見比べと微調整。

確認状況: GitHub実装・Actions確認済み。Windows実機での新UI見比べは未確認。

## v1.1.1 - 2026-09-01

### Changed

- Python/Windowsアプリの開発標準を「ソース起動・手動EXEビルド・手動配布更新」の3経路へ統一。
- 日常の開発・確認では `.venv` のPythonソース版を起動し、EXE化を毎回の工程から外した。
- EXE配布するアプリには `BUILD_EXE_CLICK_ME.cmd` または同等のワンクリックビルドを必須化。
- 配布対象アプリには `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須化。
- 通常のEXEビルドをCodex担当から外し、手動ビルド失敗やEXE固有不具合の原因調査時だけCodexを使用する方針へ変更。
- `AGENTS.md`、`AI_OPERATING_MANUAL.md`、`AI_CHECKLIST.md`、`AI_STARTUP.md`、`DEVELOPMENT_RULES.md`、`PROJECT_BOOTSTRAP.md`、`REUSE_MAP.md`、`docs/decisions.md`、`PROJECT_STATUS.md`、飲料在庫プロジェクト文書を更新。

### Result

定型的なEXEビルド・配布更新でCodexクレジットを消費せず、ユーザーが必要なときだけワンクリックで実行できる構成を全Windowsアプリの標準とした。CodexはWindows実機でしか確認できない問題の調査へ優先配分する。

確認状況: GitHub管理文書更新済み。各既存アプリへの標準スクリプト実装状況はプロジェクトごとに別途確認する。

## v1.1.0 - 2026-09-01

### Changed

- ChatGPT / Codexの役割分担を更新。
- GitHubへ直接アクセスできるChatGPTは、調査・設計だけでなくGitHub上の実装、テスト追加、branch、commit、push、PR、レビューまで第一担当とする。
- CodexはWindows実機、正式ローカル、EXEビルド、実プリンター、共有サーバー、複数PC試験など、ChatGPTから直接扱えない作業へ優先して使用する。
- GitHub上のテスト成功とWindows実機確認を別の確認レベルとして扱う。
- Codexへの引き継ぎ時は、対象branch/commit、実装済み範囲、テスト結果、残作業、本番反映可否を明記する。
- `AI_OPERATING_MANUAL.md`、`AGENTS.md`、`DEVELOPMENT_RULES.md`、`AI_STARTUP.md`、`docs/decisions.md`、`PROJECT_STATUS.md` を新運用へ更新。
- `projects/beverage-inventory-ordering-system.md` をPython移行の現在地へ更新。

### Result

GitHub上だけで完結する作業をChatGPTとCodexで重複せず、CodexクレジットをWindows実機・ローカル依存作業へ優先配分する運用を正式化。

### First application

- `beverage-inventory-ordering-system` で `python-desktop-migration` / Draft PR #2をChatGPT側で実装。
- 現行実運用JSONによる互換確認とローカルpytest 11件成功までChatGPT側で実施。
- Windows実機、EXEビルド、実プリンター、共有サーバー複数PC試験はCodex側の後工程として分離。

確認状況: v1.1.1でEXEビルド担当を再整理。通常のEXEビルドはCodex担当から除外した。

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
| 2026-09-01 | beverage-inventory-ordering-system | 旧PySide6タブUIのUI差異を実機で確認し、現行ブラウザUIを正本としたPySide6全面再構築へ移行。データ互換は維持し、UI同等性を独立本番ゲート化 | GitHub第一弾実装・Actions成功。Windows実機見比べ未完了。共有サーバー試験停止 |
| 2026-09-01 | development-management | Python/Windowsアプリをソース起動・手動EXEビルド・手動配布更新の3経路へ統一。Codexの通常担当からEXEビルドを外し、`BUILD_EXE_CLICK_ME.cmd` と `UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` を標準化 | 管理文書をGitHub `main`で更新。既存各アプリへのスクリプト適用状況は別途確認 |
| 2026-09-01 | development-management | ChatGPTをGitHub側の第一実装担当、CodexをWindows実機・ローカル環境作業の第一担当とする分業へ変更。GitHub上の実装・テスト・branch・commit・push・PR・レビューをChatGPT側で進め、Codexクレジットを実機作業へ優先配分する運用を正式化 | `AGENTS.md`、`AI_OPERATING_MANUAL.md`、`AI_STARTUP.md`、`DEVELOPMENT_RULES.md`、`docs/decisions.md`、`PROJECT_STATUS.md`、飲料在庫プロジェクト文書をGitHub `main`で更新。コード・本番環境変更なし |
| 2026-09-01 | beverage-inventory-ordering-system | 現行ブラウザ版を仕様正本としてPython/PySide6移行を開始。`python-desktop-migration` / Draft PR #2に候補版を隔離し、旧JSON互換、共有JSON、在庫計算、棚卸、売上CSV、レシピ、定期消費、発注、商品マスタ、PySide6 UI等を実装 | 現行実運用JSONでローカルpytest 11件成功、主要コレクション保存・再読込一致。Windows実機、EXE、実プリンター、共有サーバー試験は未確認。`main`・本番未変更 |
| 2026-07-23 | menu-sheet-generator | `v1.0.0`初回正式リリース。WPFお品書き印刷、日本語・英語・従業員用、PMS CSV自動集計、宿泊日指定、泊目別・部屋数集計、従業員確認用自動印刷、共有フォルダ配布、実運用データ保持を正式版として登録 | タグ`v1.0.0`とGitHub Releaseをコミット`2376c216`へ公開。ビルド・全自動テスト成功、実機動作確認済み |
| 2026-07-21 | menu-sheet-generator | GitHub管理開始と正式ソース確定。自己完結型`win-x64`配布、ワンクリック共有フォルダ配布、PMS CSV自動集計印刷、対象日絞り込み、泊目別集計、泊目別従業員確認用自動印刷を登録 | GitHub `main`・正式ローカル`6e97ccea`同期、ビルド・全自動テスト成功、実プリンター確認完了 |
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