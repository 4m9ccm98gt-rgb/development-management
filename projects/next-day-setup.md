# next-day-setup

最終確認: 2026-07-18（JST）

## 正式ソース

`C:\Users\suisy\Documents\Development\repos\next-day-setup`

## 役割

翌日準備業務を支援し、PMS等の取込、席割、担当割、帳票作成、印刷を行います。印刷プラットフォームと共有版配布も本プロジェクトの責務です。

## 現在の状態

- 最新確認タグ: `v1.1.0`
- Google Sheetsの公開CSVからスタッフシフトを取得する変更が進行中。取得失敗時は現在表示中または前回取得データを保持する設計。
- 帳票・印刷処理を本プロジェクトへ集約済み。inventory側は印刷を担当しない。
- 正式ソースから `dist\DinnerSystem` をビルドし、`DinnerSystem.exe` と `_internal` を配布する。
- 共有版更新は `update_shared_folder.ps1`／`UPDATE_SHARED_FOLDER.cmd` を使い、`_internal` を完全同期する。
- PMS CSVの番号付き手配枠を構造化し、実行日＋設定日数（初期値3日）のケーキを検出する確認機能を追加。CSV範囲警告と確認画面まで実装し、自動転記・印刷は未実装。

## 現在の未コミット変更

2026-07-18確認時点で、従来からのビルド、印刷、スタッフ取得、共有版更新等の変更に加え、ケーキ手配解析・画面・設定・文書・テストの未コミット変更があります。`requirements.txt`、`tests/`、`dinner_system/cake_orders.py`、`docs/CAKE_ORDER_AUTOMATION.md`は未追跡です。変更一覧は作業開始時に`git status`と差分で再確認してください。

## 実運用で未確認の項目

- Google Sheetsから実データを安定取得でき、失敗時表示が適切か。
- 席割・担当割と各帳票の内容、連続印刷、現場での追加印刷。
- クリーンビルドしたEXEが対象PCで起動するか。
- 共有版更新で`_internal`が完全同期され、業務データが保持されるか。
- 最新タグと実運用中の版が一致するか。
- 実際の翌日準備画面でCSV期間警告、続行／キャンセル、ケーキ確認画面が期待どおり表示されるか。
- PMSの手配済みフラグ`0`／`1`の正式な意味。
- ケーキ発注マクロへの転記・印刷、同一予約の複数ケーキを一枚へまとめる運用。

## 次の作業

1. 実運用相当CSVでケーキ検出結果と警告画面を手動確認する。
2. PMSの手配済みフラグ定義と、複数ケーキの発注書単位を確定する。
3. 検出確認後、`FAX!B9`と`FAX!A11:D48`候補への転記・印刷を実装する。
4. 既存の未コミット差分全体をレビューし、Python版・ビルド・共有版を検証する。
5. 内容確認後にコミット可否を判断する。

## 2026-09-05 追記: Claude Code 総合評価 + 安全網追加（PR #5, `614c985`）

Claude Code 退役前整備の完了後、NDSの実装・テスト・ビルド配布経路を実際に確認して総合評価を実施。
「今すぐ直す価値が高い」とされた3項目を、既存の業務ロジック・`update_shared_folder.ps1`・本番共有フォルダ・
実業務データ・実プリンターを一切変更しない安全網として、作業ブランチ `claude/nds-safety-net` で実装した。

- **NDS pytest CI追加**: `.github/workflows/tests.yml` を新設。既存の `standards.yml`（warning-only）とは
  別ジョブとして、`tests/` の pytest スイートを windows-latest 上で push / pull_request ごとに実行し、
  失敗時は CI を red にする（従来は 446〜447 件のテストが存在するのにローカルでしか実行されておらず、
  CI では何も守っていなかった）。
- **print_jobs 帳票ビルダー40件の回帰テスト追加**（`tests/test_print_jobs_builders.py`）: 直接テストが
  0件だった `build_bill_slips`（会計伝票）/ `build_assignment_sheet`（担当割表）/
  `build_service_sheet_v2`（食事提供表）/ `build_today_status_room_order`（本日の状況）に、
  予約情報・部屋・人数・空値・複数予約・境界値を中心とした回帰テストを追加。現在の仕様を変更するものではない。
- **BUILD_INFO.txt追加**（`build_exe.py`）: ビルド成功後に `dist/DinnerSystem/BUILD_INFO.txt`
  （Git branch / commit SHA / working tree clean-dirty 状態 / ビルド日時 / アプリバージョン /
  EXE 名・サイズ・SHA-256）を出力。失敗してもビルド自体は失敗させない。俺伝の `BUILD_INFO.txt` と
  同じ考え方（[decisions.md](../docs/decisions.md) の「ビルド成果物に出所を残す」判断を参照）。
  clean-tree 強制（俺伝の `Assert-CleanWorkingTree` 相当）は今回追加していない。
- CIを実際にwindows-latestで走らせて判明した、コード起因ではない環境依存の失敗（Tcl/Tk破損、
  `Get-FileHash` 未ロード、パス短縮名(8.3)不一致）は該当テストのみを対象に対処。アプリ本体・
  `update_shared_folder.ps1` は無変更。
- 未追跡の `artifacts/` と `docs/checkin_card_previews/` は、`checkin_cards.save_checkin_card_previews()`
  が出力するQAプレビュー画像（git追跡履歴なし、自動テストからの参照なし）と判明。BUILD_INFOのdirty/clean
  両パターン検証のため一時退避して確認後、削除せず元の場所へ復元済み。安全に削除または `.gitignore` 追加が
  できそうだが、ユーザー作成物の可能性を排除できないため今回は現状維持（要ユーザー判断）。
- 検証: ローカル pytest 487件中486 passed / 1 skipped（ローカル機のTcl/Tk破損起因）。GitHub Actions
  （`next-day-setup#5`）は `NDS pytest (Windows)` / `Dev standards` とも success。非本番ビルド（dist/local、
  共有フォルダ未使用）で dirty tree / clean tree 両方の `BUILD_INFO.txt` を検証し、Git HEAD SHA・EXE SHA-256
  とも独立再計算値と完全一致。PR #5 を squash merge（`614c985`）、作業ブランチ削除、正式ローカルを
  `main` へ同期、`check_standards.py` 全10リポジトリ OK、`DEV_DOCTOR` next-day-setup は `up-to-date`。

### 残課題（次サイクル、大規模リファクタリング・印刷方式統合は対象外）

- clean-tree gate（俺伝の `Assert-CleanWorkingTree` 相当）→ **2026-09-05 Phase 1 で対応済み（下記）**
- JSON保存のアトミック化（一時ファイル + rename。現状は直接上書きでクラッシュ時に破損しうる）→
  **Phase 2 で着手（下記）**
- 配布EXEのアトミック差し替え（`update_shared_folder.ps1` は現状 `Copy-Item -Force` の直接上書き）→
  **2026-09-05 Phase 1 で対応済み（下記）**
- 実プリンターでの全帳票確認（GDI直叩き／Excel COM×2系統／reportlab+SumatraPDF／Edgeキオスク印刷の
  4方式が併存。実機でしか検証できない）→ 未着手

## 2026-09-05 追記2: NDS hardening Phase 1（PR #6, `0d134be`）— BUILD/配布経路の事故耐性

安全網（Phase 0）を土台に、「間違ったソース・古いEXE・壊れたコピーを本番へ配布しにくい」状態への
強化を実施。業務ロジック・`hotel_app.py`分割・新機能追加は対象外。

- **clean-tree gate**（`build_exe.py`）: `git status --porcelain` でtracked/untrackedを問わず検出し、
  正式ビルドは既定でclean treeを要求。差分一覧を理由として提示して安全停止。`--allow-dirty` は非常用
  override（`BUILD_EXE_CLICK_ME.cmd` は無変更、通常経路では使われない）。QA生成物2フォルダ
  （`artifacts/checkin_card_stayover_previews/`、`docs/checkin_card_previews/`、前回追記1で安全と確認済み）
  は `.gitignore` へ追加し、ゲートを常時邪魔しないようにした。
- **BUILD_INFOによる配布元検証・stale/dirty成果物の拒否**（`update_shared_folder.ps1` の
  `Assert-SourceBuildInfo`）: ターゲットへ触れる前に、BUILD_INFO.txtの存在・必須項目・EXE SHA-256の一致・
  working treeがclean（`-AllowDirtySource`で上書き可）・記載HEADが現在の正式HEADと一致
  （`-AllowStaleSource`で上書き可）を検証。
- **EXEのsame-directory staged swap**（`Invoke-AtomicExeSwap`）: 一時名コピー→SHA-256再照合→既存EXEを
  `.previous`へrename→新EXEを最終名にrename。コピー破損時は既存EXEに触れず停止、rename失敗時は
  `.previous`から復元を試みる。
- **rollback経路**: 新スクリプトは作らず、既存の `Backup-UpdateTarget` の完全バックアップを
  `-SourcePath` に指定し `-AllowStaleSource` 付きで再実行するだけで復元できるよう整理。
- **Get-FileHash依存の除去**: GitHub Actions windows-latestで `Get-FileHash` が解決できないと判明
  （`Import-Module`でも直らず）、俺伝の `build_release.ps1` と同じ.NET直呼びのハッシュ関数に置換。
- 追加テスト25件（`tests/test_build_exe_clean_tree.py` 13件、`tests/test_update_shared_folder_hardening.py`
  12件）。既存4件にもBUILD_INFO.txtを付与し新ゲートの下で意味のあるテストを維持。

### 確認結果

- ローカルpytest 512件中511 passed / 1 skipped（Tcl/Tk環境フレーキー、コード起因ではない）。
- GitHub Actions（PR #6、push/pull_request両方）: `NDS pytest (Windows)` / `Dev standards` とも success、
  Get-FileHash関連のskipはゼロ。
- 非本番ビルド: dirty tree拒否 → `--allow-dirty`でDIRTY記録確認 → commit後clean treeで成功、
  Git HEAD・EXE SHA-256とも独立計算値と完全一致。
- 非本番デプロイ（H7方式、一時ターゲット）: 実ビルド成果物でBUILD_INFO検証・アトミックswap・
  target-only/保護ファイルの不変性を確認。stale版の配布ブロック→`-AllowStaleSource`で配布→
  ロールバックで旧版復元、までEXE SHA-256一致を含め実証。
- PR #6 を squash merge（`0d134be`）、作業ブランチ削除、正式ローカルを `main` へ同期、
  `check_standards.py` 全10リポジトリOK、`DEV_DOCTOR` next-day-setup は `up-to-date`・未追跡0件
  （`.gitignore`追加が効いていることを確認）、ERROR 0 / ACTION 0。

### 残課題（次サイクル）

- `_internal` のrobocopy同期自体は非アトミック（EXE単体のみアトミック化、既存設計のまま）
- 実共有フォルダでの最終確認は未実施（今回もH7同様、非本番の一時ターゲットのみで検証）
- clean-tree gateのallowlist方式（`.gitignore`追加）の運用上の妥当性は、実際の開発で使いながら再評価が必要

## 2026-09-06 追記: NDS hardening Phase 2 第一段階（PR #7, `754d214`）— JSON保存・破損耐性

Phase 0/1（リリース安全性）に続き、データ・設定消失を防ぐJSON保存・読込の安全化に着手。
大規模リファクタリングではなく、重要度の高いJSONから段階的に適用。

- **JSON I/O 棚卸し**（`next-day-setup/docs/JSON_SAFETY_PHASE2.md`）: `dinner_system/`配下の全JSON/JSONL
  ファイルを、読み書き箇所・重要度・正本orキャッシュ・SQLite重複・書き込み方式・読み込み失敗時の挙動・
  バックアップ有無で一覧化。SQLiteとの整合（`seats`/`staff_assignments`/`closing_task_snapshot`は
  `kitchen_data.sqlite3`に存在しない日次JSON唯一のコピーであること、保存順序に共有トランザクションが
  ないこと）も調査・文書化（コード変更はせず、統一は次サイクル課題として記録）。
- **共通の安全なJSON書き込み**（新規`dinner_system/json_safety.py`）: `atomic_write_json`（同一ディレクトリ
  一時ファイル→flush→fsync→再パース検証→任意でバックアップ→`os.replace`）、`backup_existing_file`
  （世代数制限付き、既定20世代）、`quarantine_corrupted_file`（破損ファイルの隔離保存）。
- **master_settings.json（最優先）**: 「不存在（初回起動）」「正常」「壊れたJSON」「型不正」を区別し、
  壊れている場合は隔離保存（元ファイル無変更）＋起動時警告ダイアログ。黙って初期化・上書きしない。
  レビューで指摘された`__init__`内の旧キー移行処理（`cake_order_lead_days`等削除）の直接書き込みも
  `atomic_write_json`へ統一し、最終grepで対象3ファイル（本ファイル・日次保存データ・closing_tasks.json）
  への直接write_text残存がないことを確認済み。
- **日次保存データ**: `load_work_data`が生のトレースバックではなく`WorkDataLoadError`（ファイル名・
  何が壊れているか・バックアップからの復元手順を明記）を出す設計に変更。空データを異常扱いしない。
- **closing_tasks.json**: `save_master`を`atomic_write_json`+バックアップへ統一（`load_master`は
  既に良好な実装のため変更なし）。

### 確認結果

- ローカルpytest 558 passed / 2 skipped（Tcl/Tk環境フレーキー）。GitHub Actions（PR #7、push/PR両方）
  `NDS pytest (Windows)` / `Dev standards` とも success。
- CIでのみタイムスタンプ衝突（Windowsのクロック分解能起因）による2件のflakeを発見しUUID付与で修正。
- 実物の`master_settings.json`（28キー）・`closing_tasks.json`（18タスク）のコピーで警告ゼロの読み込みと
  アトミック書き込みの往復一致を確認 — 既存データ形式との後方互換を実機で確認済み。
- PR #7 を squash merge（`754d214`）、作業ブランチ削除、正式ローカルを`main`へ同期、
  `check_standards.py`全10リポジトリOK、`DEV_DOCTOR` next-day-setupは`up-to-date`・未追跡0件、
  ERROR 0 / ACTION 0。

### 残課題（次サイクル）

- `ui_prefs.json`・`print_preparation.json`等の低優先度JSONは未対応（意図的、影響軽微のため）
- SQLite/日次JSONの整合性統一は未着手（調査・文書化のみ、Phase 2では意図的に見送り）
- `monthly_tasks.json`の「破損時に空状態へ静かにリセット」は今回未対応（棚卸しで発見、対応は次サイクル）

## 2026-09-06 追記: NDS hardening Phase 3（PR #8, `9606da9`）— 日次データ整合性・復旧力の強化

Phase 2で棚卸しのみで持ち越した2課題（`monthly_tasks.json`の破損時サイレントリセット、SQLite/日次JSON
の整合性未統一）に対応。**SQLiteへの全面移行は目的ではなく**、「食い違いを検出できる」「唯一データを
失っても復旧しやすい」状態を作ることが目的。作業ブランチ `claude/nds-hardening-phase3`。

- **3A（最優先）**: `closing_tasks.py`の`load_scheduled_task_state`（`monthly_tasks.json`、旧形式含む）
  と`load_daily`（締め作業当日スナップショット`保存データ/締め作業/{date}.json`）が、破損時に空状態へ
  静かにリセットしていた挙動を、`ScheduledTaskStateLoadError`/`ClosingTaskDailyLoadError`を送出する
  設計へ変更。ファイル不存在（＝正常な「未保存」）と実際の破損を明確に区別。破損ファイルは
  `quarantine_corrupted_file`で複製隔離し、元ファイルは変更しない。保存は`atomic_write_json(backup=True)`
  へ統一。
- **3B**: 実際の保存フロー（PMS CSV取込→SQLite保存→日次JSON保存→席割/担当割/締め作業変更→再CSV取込
  →アプリ終了→次回起動）をコードから追跡し、`docs/PHASE3_DATA_CONSISTENCY.md`として文書化。
  `seats`/`staff_assignments`/`closing_task_snapshot`はSQLiteに一切存在しない日次JSON唯一のコピーで
  あることを確認。
- **3C**: 日次JSON保存時に`kitchen_import_id`/`kitchen_imported_at`を埋め込み、起動時にSQLite側の
  現在の取込IDと比較する`compare_kitchen_snapshot_provenance`（`hotel_app.py`）を追加。
  `match`/`json_stale`/`sqlite_stale`/`no_snapshot`/`unknown`の5分類。**いずれの判定でも自動上書き・
  自動修復は一切行わず**、不一致は`messagebox.showwarning`で通知するのみ。
- **3D**: SQLiteに新テーブル`operator_state_backup`（`kitchen_snapshot_store.py`、`CREATE TABLE
  IF NOT EXISTS`で既存DB非破壊）を追加。`save_work_data`成功後にベストエフォートで`seats`/
  `staff_assignments`/`closing_task_snapshot`を複写（失敗しても保存自体は成功のまま、
  `HotelApp.backup_operator_state_to_sqlite`が`audit_event`にのみ記録）。**日次JSON＝正本、SQLite側
  ＝復旧用の冗長コピーという位置づけは変更せず**、自動復元は行わない（`load_operator_state_backup`は
  読み出し関数のみ）。
- **3E**: 一致/日次JSON古い/SQLite古い/破損JSON/対応スナップショットなし/JSON成功SQLite失敗/SQLite成功
  JSON失敗/再取込直後クラッシュ、を一時環境で再現するリカバリーシナリオテスト（`test_phase3_recovery_
  scenarios.py`）を追加。実業務データ・実共有フォルダ・実プリンターは無変更。

### 最終監査（PR作成前、追加コミット）

Phase 3Aの2例外の全呼び出し元をリポジトリ全体でgrepベースに追跡し、未保護の2箇所を新規発見・修正:

- `closing_task_ui.print_closing_task_sheet`（単体印刷ボタン経由）: 例外処理が一切なかった。
- `hotel_app.HotelApp.prepare_dinner_print_queue`の`CLOSING_TASK_BULK_PRINT_ENTRY`分岐（一括印刷
  ボタン経由）: 呼び出し元`print_dinner_jobs`/`print_all_jobs`が`traceback.format_exc()`を
  そのままダイアログに埋め込む実装だったため、生のトレースバックがユーザーに表示される経路だった。

両者とも、既存の`kitchen_calendar`ジョブ分岐と同じパターン（例外捕捉→単一ダイアログ or
印刷キューへ「スキップ・理由記録」エントリ）で修正。純粋関数側への個別try/except追加は避け、
UI境界でまとめて処理する既存方針を踏襲。呼び出し元回帰テスト8件を追加
（`tests/test_closing_task_ui_call_site_protection.py`）。`docs/PHASE3_DATA_CONSISTENCY.md`に、
`operator_state_backup.work_data_saved_at`はSQLite側保存が失敗すると古い値のまま残るため、将来の
復旧UIで必ず日次JSON側の保存日時と突き合わせ、最新であるという前提を置いてはならない旨を明記。

### 確認結果

- ローカルpytest 617 passed / 1 skipped（Tcl/Tk環境フレーキー、既存の環境依存事象）。GitHub Actions
  （PR #8、push/pull_request両方）`NDS pytest (Windows)` / `Dev standards` とも success。
- 差分は想定通り11ファイル（Phase 3の10ファイル＋最終監査の追加）のみ。`origin/main`からbehind 0。
  自動復元・自動上書きロジックが存在しないことをgrepで再確認、日次JSONが正本のままであることを確認。
- PR #8 を squash merge（`9606da9`）、作業ブランチ削除、正式ローカルを`main`へ同期、
  `check_standards.py`全10リポジトリOK、`DEV_DOCTOR` next-day-setupは`up-to-date`・未追跡0件、
  ERROR 0 / ACTION 0。

### 残る「復元不能ケース」・次サイクル候補

- 日次JSONと`operator_state_backup`の**両方**が失われた場合、`seats`/`staff_assignments`/
  `closing_task_snapshot`は復元不能。
- 締め作業の第3ファイル（`保存データ/締め作業/{date}.json`）は`operator_state_backup`の対象外。
- `compare_kitchen_snapshot_provenance`はSQLiteの`import_id`比較のみで、日次JSON内の`reservations`
  本体の実差分までは比較しない。
- `ui_prefs.json`等の低優先度JSONの安全化は引き続き未着手（Phase 2から継続、意図的）。

## 2026-09-06 追記: NDS hardening Phase 4（PR #9, `5955bf9`）— 印刷経路・Windows実機監査

印刷方式の統合や`hotel_app.py`の分割ではなく、GDI直接印刷／Excel COM／reportlab+SumatraPDF／
Edge HTMLが併存する印刷サブシステムを可視化し、安全な範囲（読み取り専用診断・pure logicテスト）
で検証することが目的。作業ブランチ `claude/nds-print-audit-phase4`。

- **全印刷経路の棚卸し**（`docs/PHASE4_PRINT_AUDIT.md`）: `PRINT_JOBS`登録11帳票＋レジストリ外の
  独立2系統（ケーキ帳票Excel COM、設定可能なExcel自動印刷アイテム）を、job key・呼び出しUI・
  builder・preview経路・実印刷経路・印刷エンジン・用紙サイズ・DPI・外部依存・実プリンター必須か・
  テスト有無・重要度で一覧化。
- **print/preview分岐の不一致**: `render_direct_preview()`は未知job keyを暗黙`else`で「伝票」として
  誤描画、`print_job()`は逆に汎用Edge/HTML経路へ静かにfallbackする真逆の失敗モードを発見。
  `kitchen_calendar`は一括印刷（reportlab PDF+SumatraPDF）と単体印刷/プレビュー（PIL画像+GDI）が
  同一job keyで完全に別実装であることも判明。レジストリの全面統合は今回は実施せず。
- **死んだ印刷経路**（削除せず記録のみ）: `seating_chart`、`print_all`/`render_all`/
  `BULK_PRINT_KEYS`、未使用HTMLビルダー群、`print_one`とその呼び出し元一式
  （`select_print_job`/`select_breakfast_print_job`/`print_all_jobs`/`preview_assignment_print`）
  ——いずれも呼び出し元ゼロを確認済み。
- **Add-Printer副作用の実地確認**: `print_preparation.py`の`Ensure-DuplexPrinter`
  （Excel印刷の両面設定用に複製プリンターを`Add-Printer`で作成、対になる`Remove-Printer`は
  存在せず恒久的に残る）について読み取り専用の`Get-Printer`診断を実施した結果、**この開発機に
  既に`Codex_Duplex_Short_Kyocera_TASKalfa_3554ci(J)_KX`/`Codex_Duplex_Long_Kyocera_TASKalfa_3554ci(J)_KX`
  が実在する**ことを確認——理論上ではなく実際に発火済み。リポジトリ追跡の
  `config/print_preparation.json`にも`duplex_mode: duplex_long`が1件設定済み。
  **今回はAdd-Printer/Remove-Printer実行、プリンター設定変更は一切行っていない**。
- **回帰テスト46件を追加**（実プリンター・PowerShell実行・Excel COM不要）:
  - `tests/test_direct_print_render_coverage.py`(32件): 未テストだった8帳票描画関数の
    寸法固定・空データ耐性・固定グリッド超過時の切り詰め耐性。
  - `tests/test_excel_duplex_mode_safety.py`(8件): `normalize_excel_print_items`の
    duplex_mode正規化フォールバック境界（Add-Printer発火条件）と、正規化後の値が
    PowerShellスクリプトへ正しく渡ることの確認。
  - `tests/test_print_job_registry_consistency.py`(6件): `PRINT_JOBS`/`render_job()`/
    `render_direct_preview()`/`print_job()`のjob key集合一致をソース検査で固定。

### 確認結果

- ローカルpytest 664 passed。GitHub Actions（PR #9、push/pull_request両方）
  `NDS pytest (Windows)` / `Dev standards` とも success。
- 差分4ファイル（監査ドキュメント＋テスト3本）のみ確認、`origin/main`からbehind 0。
  プリンター状態・印刷エンジン実装・`hotel_app.py`挙動はいずれも無変更。
- PR #9 を squash merge（`5955bf9`）、作業ブランチ削除、正式ローカルを`main`へ同期、
  `check_standards.py`全10リポジトリOK、`DEV_DOCTOR` next-day-setupは`up-to-date`・未追跡0件、
  ERROR 0。

### 残課題（次サイクル候補）

- `Codex_Duplex_Short/Long_*`合成プリンターの削除処理（`Remove-Printer`）が存在しない。
  改善案（対応するクリーンアップ処理、作成前の確認ダイアログ、失敗時ロールバック、
  診断用UI）を`docs/PHASE4_PRINT_AUDIT.md`に記録のみ、今回は実装せず。
- `render_direct_preview()`の`bill`向け暗黙`else`分岐の明示化、印刷レジストリ3分岐の一本化。
- 実プリンターでの最終確認は未実施——Phase 4で最小チェックリスト10項目を作成済み
  （GDI A4/A3/B5代表帳票、両面印刷、Excel自動印刷のduplex clone実機確認、
  ケーキ帳票、調理場カレンダーPDF/画像経路の見比べ、一括印刷、プレビューとの一致）、実施は次回。
