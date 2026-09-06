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
