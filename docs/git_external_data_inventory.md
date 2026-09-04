# Git 管理外データ 棚卸しとバックアップ・復元検証（2026-09-04）

Git に入れていない開発データ（DB / 実設定 / 認証情報 / ローカル専用ファイル /
業務データ）の一覧と、バックアップの有無・復元検証の結果。

**この文書には値そのものを記録しない。** 場所・種別・件数・整合性判定のみ。
バックアップ出力（実際の値を含む）は Git 管理しない。

## 一覧

| # | データ | アプリ | 種別 | 場所（値は記載しない） | 規模 | 従来のバックアップ |
|---|---|---|---|---|---|---|
| 1 | `food_cost.db` | 俺伝(food-cost) | 業務DB | `%LOCALAPPDATA%\FoodCostCalculation\` | 3.2MB / 9表 / 28,566行 | **無し** |
| 2 | `config\google_capture.json` ほか | 俺伝 | 実設定・秘密 | `%LOCALAPPDATA%\FoodCostCalculation\config\` | 小 / JSON 18キー・4キー | 無し。`bridge_secret` を含む |
| 3 | `collected_originals` `crops` `google_inbox` `uploads` | 俺伝 | 業務データ（請求書画像等） | `%LOCALAPPDATA%\FoodCostCalculation\` | 日付別ディレクトリ | 無し |
| 4 | `credentials.json` | 在庫突合 | **認証情報** | `%LOCALAPPDATA%\SalesInventoryCheckTool\` | 2.9KB / JSON 7キー | **無し**。手間いらず／エージェント認証 |
| 5 | `print_config\print_preparation.json` | 在庫突合 | 実設定 | `%LOCALAPPDATA%\SalesInventoryCheckTool\print_config\` | 4.8KB / JSON 21キー | 無し |
| 6 | `ChromeAutomation\` | 在庫突合 | ブラウザプロファイル・キャッシュ | `%LOCALAPPDATA%\SalesInventoryCheckTool\` | ディレクトリ | 対象外（再生成可能） |
| 7 | `master_settings.json` | next-day-setup | 実設定 | `<repo>\next-day-setup\dinner_system\` | 9KB / JSON 28キー | `*.example.json` は Git 内。実ファイルの明示的バックアップは無し |
| 8 | `kitchen_data.sqlite3` | next-day-setup | 業務DB | `<repo>\next-day-setup\dinner_system\<日次データ>\` | 56.6MB / 3表 / 4,294行 | **無し**（アプリ内の日次 JSON 上書き前退避のみ、DB は対象外） |
| 9 | 日次スナップショット `YYYY-MM-DD.json`（23件）+ `_上書き前バックアップ\`（多数）+ `締め作業\` + `cake_order_snapshot.json` + 監査 JSONL | next-day-setup | 業務データ・ログ | `<repo>\next-day-setup\dinner_system\<日次データ>\` | 各 0.2–0.5MB | アプリ内退避（同一ディスク） |
| 10 | `ui_prefs.json` / `config\print_preparation.json` | next-day-setup | ローカル設定 | `<repo>\next-day-setup\dinner_system\` | 小 | 無し（再生成可） |
| 11 | `shared_folder_path.txt` | next-day-setup | 配布先パス | `<repo>\next-day-setup\` | 小 | 無し |
| 12 | `qr_supply.sqlite3` | qr-supply | DB（現状は開発データ） | `<repo>\qr-supply-ordering-system\database\` | 小 / 13表 | `scripts\backup_db.ps1` 有り。ただし最終実行 2026-07-21（55日前）・同一ディスク |
| 13 | `google_capture.json`（repo 内） | 俺伝(repo) | 実設定・秘密 | `<repo>\food-cost-calculation-system\` | 小 / JSON 3キー | 無し。`bridge_secret` を含む |
| 14 | 共有配布フォルダの業務データ | next-day-setup | 配布先業務データ | `\\server\...`（パスは記載しない） | — | 配布物とは分離運用。別途検証が必要 |
| 15 | 俺伝 HDD 配布の業務データ | 俺伝 | 配布先業務データ | `E:` 外付けHDD | — | 配布インスタンスのコピー。HDD 自体が単一障害点 |
| 16 | `gh` 認証トークン | 共通 | 認証 | Windows 資格情報マネージャー | — | エクスポート不可。復旧は `gh auth login` 再実行 |

## 従来の状態（問題点）

- **#1 俺伝DB、#4 認証情報、#8 NDS DB にバックアップが存在しなかった。**
- 既存のバックアップ（#9 アプリ内退避、#12 qr-supply）はすべて**同一ディスク**で、
  ディスク故障を生き残らない。オフマシン／オフラインの複製が無い。
- #12 は 55 日間実行されていなかった。

## 実施した復元検証（2026-09-04、隔離環境）

すべて一時ディレクトリへコピーして検証。実運用データには書き込んでいない。

| 対象 | 方法 | 結果 |
|---|---|---|
| #1 `food_cost.db` | temp へコピー → `PRAGMA integrity_check` | **ok**、9表 28,566行 読み取り可 |
| #8 `kitchen_data.sqlite3` | temp へコピー → integrity_check | **ok**、3表 4,294行 |
| #12 `qr_supply.sqlite3` | `backup_db.ps1` 実行（55日ぶり）→ 生成物を temp で開く | **ok**、13表 |
| #2 #4 #5 #7 #9 #10 #13 の JSON | temp へコピー → `json.load` | 全件 **valid**（構造のみ確認、値は記録せず） |

→ 現時点の全データストアは健全で、復元可能な状態。

## 新規に用意したバックアップ手段

- `scripts/BACKUP_DEV_DATA.ps1` … #1〜#13 と #16 の手順を1つにまとめた読み取り専用バックアップ。
  SQLite は Backup API（アプリ起動中でも安全）。出力は `devdata-<日時>\` に MANIFEST（SHA-256）と RESTORE（復元先対応）付き。
- `scripts/BACKUP_DEV_DATA_CLICK_ME.cmd` … ダブルクリック実行。`E:` があれば第2コピーも作成。
- **一時ターゲットで1回実行し、生成物の DB integrity と JSON 妥当性を再検証済み**（上表と同結果）。

## 残タスク（ユーザー作業・判断）

1. `BACKUP_DEV_DATA_CLICK_ME.cmd` を定期実行する（週次目安）。出力をオフライン媒体にも保管。
2. #14 共有配布フォルダ・#15 HDD の業務データについて、配布先の復元検証を別途行う（H7 と併せて）。
3. `#16` gh: 新PCでは `gh auth login` を実行し直す（[docs/backup_restore.md](backup_restore.md)）。
