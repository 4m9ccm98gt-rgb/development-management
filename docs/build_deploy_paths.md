# BUILD / DEPLOY / UPDATE 経路の実地検証（H7、2026-09-04）

各アプリの「GitHub/ソース HEAD → BUILD 入口 → 成果物 → DEPLOY/UPDATE 入口 → 配布先」を
**非本番環境（一時ターゲット）で実際に通した**記録。実共有フォルダ・実 HDD・本番環境は
一切変更していない（実 HDD `E:\FoodCostCalculation\` は 512 ファイルのサイズ+更新時刻を
検証前後で照合し完全一致を確認。ネットワーク共有は `-TargetPath` に一時パスを渡したため
スクリプトから参照もされていない）。

完了条件は「ファイルが存在する」ではなく「経路が実際に通った」。下表の 5 アプリすべてで
BUILD 入口→成果物→DEPLOY 入口→一時配布先まで到達し、成果物 SHA-256 が配布先で一致した。

---

## 一覧（一目表）

| アプリ | 種別 | ソース HEAD（検証時） | BUILD 入口 | 成果物（size / SHA-256 先頭） | DEPLOY/UPDATE 入口 | 実際の配布先（本番・今回は不変更） |
|---|---|---|---|---|---|---|
| food-cost（俺伝） | desktop | `codex/bootstrap-invoice-reading`† @ `1940db0` | `BUILD_俺伝_CLICK_ME.cmd` → `tools/release/build_release.ps1` | `releases/俺伝-<ts>/俺伝.exe` + `BUILD_INFO.txt`（HEAD SHA と EXE SHA-256 を記録）<br>※DryRun 実行。stub 3 bytes / `039058C6…` | `UPDATE_HDD_CLICK_ME.cmd` → `tools/release/update_hdd.ps1` | `E:\FoodCostCalculation\俺伝-<ts>\`（外付け HDD `WE-Elements`） |
| next-day-setup（翌日準備） | desktop | `main` @ `1b048f4` | `BUILD_EXE_CLICK_ME.cmd` → `build_exe.py`（PyInstaller onedir） | `dist/DinnerSystem/DinnerSystem.exe`<br>6,383,041 bytes / `0da441a2…`（BUILD_INFO なし） | `UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` | `\\<サーバ>\share\DinnerSystem`（社内共有フォルダ、`Z:` 等） |
| beverage（飲料在庫） | desktop | `python-desktop-migration` @ `04c3797`※検証後 `e458476` に FF | `python_app\BUILD_EXE_CLICK_ME.cmd`（PyInstaller onedir、pytest 同梱） | `python_app/dist/BeverageInventory/BeverageInventory.exe`<br>1,957,425 bytes / `ec30a6ae…`（コンソールに size+SHA 表示、BUILD_INFO ファイルなし） | `python_app\UPDATE_SHARED_FOLDER.cmd` → `update_shared_folder.ps1` | `\\<共有>\BeverageInventory`（社内共有フォルダ） |
| menu-sheet-generator（料理説明書 / .NET） | desktop | `main` @ `fa4fdf7` | `BUILD_RELEASE.cmd` → `dotnet build` + `dotnet publish -r win-x64 --self-contained -o publish\` | `publish\MenuPrinterWpf.exe`(162,304) / `.dll`(206,848) / logo png / stamp png（BUILD_INFO なし） | `UPDATE.cmd [ターゲット]` | `\\192.168.10.101\Shared\共有\…\お品書き印刷アプリ` |
| inventory-reconciliation（在庫突合） | service | `main` @ `fd2de21` | ―（ビルド成果物なし） | ―（`.venv` の Python で直接実行） | 登録: `install_daily_inventory_task.bat` → `schtasks /Create /TN 販売在庫チェック_定時実行 /SC DAILY …`<br>実行: `run_inventory_reconcile_auto.bat <CSVフォルダ>` → `room_inventory_reconcile.py --auto-run` | `outputs/`（突合結果 xlsx / `scheduled_auto_run*.log`）+ メール送信 |
| qr-supply（QR 物品発注） | web | `main` @ `790fff5` | ―（ビルド成果物なし） | `DEPLOY.md`：社内 LAN の 1 ホストに repo 配置 → `RUN_DEV.cmd` を 1 回。DB は初回 `ensure_database()` で自動生成。スキーマ更新は `flask --app run:app migrate-db`（加算型・非破壊） | 同ホストの `RUN_DEV.cmd`（`run.py` が `0.0.0.0:5000`） | `database\qr_supply.sqlite3`（同ホスト内、Git 管理外） |

`<ts>` = `build_release.ps1` の `-Timestamp`（`yyyy-MM-dd-HHmm` 形式、未指定なら実行時刻）。

† 俺伝の既定ブランチ名。**この検証（2026-09-04 H7）実施時点の名称であり、当時の実状を示す歴史的記録**。
同日 M3 の監査・判断を経て、この H7 検証の後に `main` へ改名済み（HEAD `1940db0` は改名前後で同一。
詳細は [docs/food_cost_default_branch.md](food_cost_default_branch.md)、現在の状態は
[REPOSITORIES.md](../REPOSITORIES.md) / [PROJECT_STATUS.md](../PROJECT_STATUS.md)）。

---

## H7 で実際に実行したこと（2026-09-04）

作業領域: `…\scratchpad\h7\`（一時）。実 HDD / ネットワーク共有 / 本番は不変更。

### 1. food-cost（俺伝）— DryRun で全経路

`build_release.ps1` は `-DryRun -OutputRoot <一時> -Timestamp 2026-09-04-0001` で実行
（Nuitka 本ビルド 15〜20 分は省略。DryRun でも `Assert-Repository` / `Assert-CleanWorkingTree` /
検証ゲート（pytest 253 passed・compileall・`git diff --check`）/ 同名リリース拒否 /
`Assert-Distribution`（配布禁止ファイル走査）/ `Write-BuildInfo` は本番同様に走る）。

- 成果物: `<一時>/fc_releases/俺伝-2026-09-04-0001/{俺伝.exe, _internal/runtime.dll, BUILD_INFO.txt}` と Updater 一式。
- `BUILD_INFO.txt` の `Git commit SHA` = `1940db0…` = repo HEAD（**成果物→HEAD の追跡可能**）。
  `EXE SHA-256` = 成果物の実 SHA と一致（自己整合）。
- ソース: tracked-tree ダイジェスト `d05815b2…` がビルド前後で不変、`git status` クリーンのまま。
- `update_hdd.ps1 -DryRun -SourceRoot <一時> -HddRoot <一時>` 実行 → `<一時>/fake_hdd/FoodCostCalculation/` へコピー。
  `Assert-BuildInfo`（EXE SHA-256 再計算照合）と `Assert-TreesEqual`（全ファイル数+size+SHA 照合）通過。
  出力の `俺伝.exe SHA-256 = 039058C6…` が BUILD_INFO・成果物と一致（**ソース↔配布先 主成果物 SHA 一致**）。
- 実 `E:\FoodCostCalculation\`（512 ファイル）: size+mtime を前後照合し **完全一致**。

> 注意: 検証時、cwd を repo ルート以外にして `build_release.ps1` を直接叩くと `pytest -q` が
> 「no tests ran」で exit 5 → 検証ゲートで停止した（fail-safe が正しく作動）。正式入口
> `BUILD_俺伝_CLICK_ME.cmd` は先頭で `cd /d "%~dp0"` するため repo ルートで pytest が走り正常。

### 2. next-day-setup（翌日準備）— 実ビルド + 一時共有フォルダ

- `build_exe.py`（`.venv` の Python、公式入口）実行 → 51 秒、`dist/DinnerSystem/DinnerSystem.exe`
  6,383,041 bytes / `0da441a2…`。`_internal/` あり、`保存データ/` は**空**（運用データは同梱しない設計どおり）。
- ソース: tracked-tree `8f8c6c11…` 不変。`dinner_system/config/print_preparation.json` は
  Git 追跡外のためビルドの書き込みでも tracked ツリーは動かない。
- 一時共有フォルダ `<一時>/nds_share`（`master_settings.json` / `ui_prefs.json` / `closing_tasks.json` /
  `保存データ/business.json` / `logs/app.log` / `_internal/legacy_only.dat` を配置）へ
  `update_shared_folder.ps1 -TargetPath <一時> -SourcePath dist\DinnerSystem -BackupRootPath <一時>` 実行。
  - `Planned deletion files: 0`（`Assert-NoPlannedDeletions` 作動）
  - フル事前バックアップ 7 ファイル/182 bytes を作成・件数+バイト照合で検証
  - `Target-only _internal files retained: 1`（`legacy_only.dat` は `/E` で削除されず保持 → **意図しない削除なし**）
  - スクリプト自身の検証: `Operational data SHA256 verified: 5 files`、closing task master SHA 前後一致
  - 独立再検証: 運用 5 ファイルの SHA-256 が前後で一致、配布先 EXE SHA = ソース `0da441a2…`
- 実ネットワーク共有: `-TargetPath` を渡したので InputBox もネットワークアクセスも発生せず。

### 3. beverage（飲料在庫）— 実ビルド + 一時共有フォルダ

- `python_app\BUILD_EXE_CLICK_ME.cmd`（公式入口。pip 更新 → `pytest -q` → PyInstaller → ordering 資産コピー）実行 →
  `dist/BeverageInventory/BeverageInventory.exe` 1,957,425 bytes / `ec30a6ae…`。`apps/ordering/index.html` あり、`data/` 空。
  `.cmd` 自体がコンソールに size+SHA-256 を出力。
- ソース: tracked-tree `ce638e2f…` 不変（変化は未追跡の `dist/` `build/` `BeverageInventory.spec` のみ）。
- 一時共有フォルダ `<一時>/bev_share`（`data/inventory-data.json` + `.backup.json`、`_internal/old_runtime_x.dll`、
  旧 `apps/ordering/index.html` を配置）へ `update_shared_folder.ps1 -TargetPath <一時> -SourcePath dist\BeverageInventory` 実行。
  - `protected data files before update: 2`（データ保護ガード作動）
  - `_internal` と `apps\ordering` を `/MIR` で同期（設計どおりミラー。`data\` のみ保護対象なので
    `_internal/old_runtime_x.dll` は削除された — これは意図された挙動）
  - スクリプト自身の検証: `operational data SHA-256 verified: 2 files`
  - 独立再検証: `data/` 2 ファイル SHA 前後一致、配布先 EXE SHA = ソース `ec30a6ae…`、`_internal` 202=202 ミラー一致
  - EXE は一時ファイル + `Move-Item` の原子的差し替え
- 検証後、`origin/python-desktop-migration` へ **pure fast-forward**（`04c3797 → e458476`、5 コミット、
  ローカル固有コミット 0・未コミット追跡変更 0 を確認済み。DEV_DOCTOR の ACTION「behind 5」を解消）。
  ※ビルド検証は `04c3797` 時点。FF 後に再ビルドすれば EXE SHA は変わるが、**経路の妥当性は不変**。

### 4. menu-sheet-generator（.NET）— 実ビルド + 一時ターゲット

- `BUILD_RELEASE.cmd`（`dotnet build` 0 warn/0 error → `dotnet publish -r win-x64 --self-contained -o publish\`）実行 →
  `publish\MenuPrinterWpf.exe`(162,304) / `.dll`(206,848) / `official_vertical_logo_trimmed.png`(88,464) / `tenyu_stamp.png`(1,027,221)。
  `.cmd` 内の 4 ファイル存在チェックを通過。
- ソース: tracked-tree `976261b0…` 不変（`bin/` `obj/` `publish/` は gitignore 済み）。
- 一時ターゲット `<一時>/menu_share`（旧 4 ファイル + `menu-config.json` + `last_sheet.json` を配置）へ
  `UPDATE.cmd "<一時>"` 実行（第 1 引数で本番ネットワークターゲットを上書き）。
  - 4 ファイルをコピー・各 `if not exist … exit /b 1` で存在確認
  - 独立再検証: 4 ファイルすべて SHA が publish 側と一致、`menu-config.json` / `last_sheet.json` は
    前後 SHA 一致（`UPDATE.cmd` は 4 個の指名ファイルのみ扱い、削除は一切しない）
- 実ネットワークターゲット `\\192.168.10.101\…` は参照されず。

### 5. inventory-reconciliation（service）— 経路の静的確認のみ

ビルド成果物のないサービス型。`schtasks` 登録は**システム変更 + 対話入力（CSV フォルダ・時刻）**を
伴うため実行しない（要件どおり破壊的異常系は強制しない）。

- 実行入口の生存確認: `room_inventory_reconcile.py --help` が正常終了（argparse ロード OK）。
- 登録コマンド形（登録はしない）:
  `schtasks /Create /TN "販売在庫チェック_定時実行" /SC DAILY /ST <HH:MM> /TR "\"<repo>\run_inventory_reconcile_auto.bat\" \"<CSVフォルダ>\"" /F`
- fail-safe（既存ロジック）: 引数なし → 両 `.bat` とも `exit /b 2`。`run_inventory_reconcile_auto.bat` は
  `outputs/scheduled_auto_run_history.log` に `START` / `END … RESULT=<code>` を追記。`schtasks /F` は
  同名タスクの冪等上書き。インストーラは `%ERRORLEVEL%` を判定し結果表示。

### 6. qr-supply（web）— 経路の静的確認のみ

ビルド成果物なし。`RUN_DEV.cmd` は先行フェーズ（パイロット）で開発版 GUI 起動まで確認済み。

- アプリ生存確認: `import run` で Flask app オブジェクト生成 OK、`DATABASE` パス解決 OK。
- CLI コマンド `init-db` / `migrate-db` / `seed-sample` 登録を確認。
- 非破壊性: `app/` `scripts/` に `DROP TABLE` / `DELETE FROM` / `TRUNCATE` / DB ファイル削除は無し
  （`migrate-db` は加算型）。
- DEPLOY = 成果物配布ではなく「ホストで source を動かす」。`DEPLOY.md` の手順（repo 配置 → `RUN_DEV.cmd` →
  初回 `ensure_database()` 自動生成 → 必要時 `migrate-db`）。

---

## fail-safe（安全停止）まとめ — 既存ロジックから

破壊的な異常系は既存テスト（例: 俺伝 `tests/test_release_scripts.py`、beverage `tests/test_desktop_safety.py`、
NDS のテスト群）で担保済みのため強制発火しない。以下はスクリプトを読んで/一部は自然に観測して確認した分岐。

### BUILD 側

| アプリ | 0 個の成果物 | 複数/曖昧な成果物 | 未コミット | 参照ファイル欠落 | その他 |
|---|---|---|---|---|---|
| 俺伝 `build_release.ps1` | `Assert-Distribution` → `throw "成果物EXEがありません"` | `Get-UniqueNuitkaDist`: `$dists.Count -ne 1` → `throw "…一意に特定できません。件数: N"`（0 でも複数でも停止） | `Assert-CleanWorkingTree` → `throw "未コミットの変更があります"`（`-AllowDirty` 明示時のみ許可） | `Assert-Repository`（`.git`/`pyproject.toml`/`src\food_cost_app`/`src\oreden_updater`）欠落 → throw。`git rev-parse --show-toplevel` ≠ repo ルート → throw | 検証ゲート（pytest/compileall/`git diff --check`）いずれか失敗 → 停止（**H7 で自然観測**）。`Timestamp` 形式不正 → throw。`同名リリースが既に存在します` → throw。配布禁止パターン（`*.db *.sqlite3 *.csv *.log *.pem *.key credential* *token* settings.json google_capture.json`）検出 → throw。`.git` 混入 → throw |
| NDS `build_exe.py` | PyInstaller 失敗で `SystemExit(returncode)` | ― | クリーンツリー要求なし（未コミットでもビルド可） | `tkinter` / `openpyxl` / `PIL` / `PyInstaller` import チェックを事前 `run()`。print config 読めない → `SystemExit` | 例外時 `FAILED` + `repr(exc)` を `build_exe_result.txt` に記録して再送 |
| beverage `BUILD_EXE_CLICK_ME.cmd` | `:missing_exe`（`if not exist "%EXE_PATH%"`）→ exit 1 | ― | クリーンツリー要求なし | `where py` 失敗 → `:no_python`。`pytest -q` 失敗 → `:failed`（exit 1）。ordering 資産 `apps\ordering\index.html` 欠落 → `:missing_ordering_assets` | `pip install` 失敗も `:failed` |
| menu-sheet `BUILD_RELEASE.cmd` | `if not exist ".\publish\MenuPrinterWpf.exe" goto :failed`（`.dll` / logo png / stamp png も個別） | ― | ― | `dotnet build` / `dotnet publish` の `errorlevel` → `:failed`（exit 1） | ― |

### DEPLOY/UPDATE 側

| アプリ | 一時ターゲット不正 | 成果物ファイル欠落 | 意図しない削除の防止 | 実データ保護 |
|---|---|---|---|---|
| 俺伝 `update_hdd.ps1` | `Get-HddRoot`: `WE-Elements` 無し → throw / 複数 → `throw "…コピーを中止します"`。`-DryRun` かつ `-HddRoot` 未指定 → throw。コピー元=コピー先 → throw。`同名releaseが既にHDDにあります。上書きしません` → throw | `Get-Latest` 空 → `throw "正式なreleaseが見つかりません"`。`Assert-BuildInfo`: BUILD_INFO / EXE / `_internal` 欠落 → throw、必須キー欠落 → throw、**EXE SHA-256 不一致 → throw** | 追加コピーのみ。失敗時 `catch` で `$destination` を `Remove-Item`（部分コピーを残さない）。Updater は stage→backup→move の原子的差し替え、失敗時ロールバック | `updater_settings.json` を退避・復元し、変更されていたら `throw "updater_settings.jsonが変更されました"` |
| NDS `update_shared_folder.ps1` | `Test-Path $Target` 失敗 → `throw "Target folder not found"`。EXE/`_internal` 無ければ「子フォルダ or 新規インストール」に分岐 | `if (-not (Test-Path "$Source\DinnerSystem.exe")) throw "Source EXE not found. Run BUILD_EXE_CLICK_ME.cmd first."` | `Assert-NoPlannedDeletions`（削除マニフェスト該当ファイルがあれば `throw`）。`/E`（`/MIR` ではない）で target-only ファイル保持、`KEEP _internal\…` をログ。事前にフル robocopy バックアップ（件数+バイト照合、失敗で throw） | `closing_tasks.json` / `master_settings.json` / `ui_prefs.json` / `*.log` / `保存データ` / `print_work` / `logs` を `/XF` `/XD` 除外。更新後、保護ファイルの SHA-256 前後照合 → 変化/消失で `throw`。closing task master は別途 SHA 前後照合 |
| beverage `update_shared_folder.ps1` | `Test-Path $Target` 失敗 → throw。`Source` = `Target` → `throw "Source and target must be different folders"` | `BeverageInventory.exe` / `_internal` / `apps\ordering\index.html` 欠落 → それぞれ `throw "… No target was changed."` | `_internal` と `apps\ordering` のみ `/MIR`。EXE は `.update` 一時ファイル + `Move-Item` の原子的差し替え。更新後 `apps\ordering\index.html` 消失 → throw | `data\inventory-data.json` 無し → `throw "… No application files were changed."`。`.inventory-data.json.lock` あり → `throw "… locked …"`。更新後 `Assert-DataUnchanged`（`data\` 全ファイル SHA-256 前後照合 + 件数照合）→ 変化/消失/件数差で throw |
| menu-sheet `UPDATE.cmd` | `if not exist "%UPDATE_TARGET%\" goto :target_missing`。`if exist "%UPDATE_TARGET%\menu-edit.lock" goto :locked`（編集中ロック） | source 4 ファイルいずれか欠落 → `:source_missing`（"Run BUILD_RELEASE.cmd first."） | 指名 4 ファイルの `copy /Y` のみ。削除・ミラー・再帰コピーなし。各コピー後 `if not exist … exit /b 1` | 4 ファイル以外（設定・保存データ）には触れない設計 |
| inv-recon `install_daily_inventory_task.bat` / `run_inventory_reconcile_auto.bat` | CSV フォルダ空 → `exit /b 2` | ― | `schtasks /F` は冪等上書き（重複タスクを作らない） | 実行結果を `outputs/scheduled_auto_run_history.log` に `RESULT=<code>` 付きで追記 |
| qr-supply `migrate-db` | ― | ― | 加算型スキーマ更新（既存 DB を削除しない）。`DROP`/`DELETE`/`TRUNCATE` なし | `backup_db.ps1`（SQLite Backup API）で日付付きコピー。DB は Git 管理外 |

---

## 既知のギャップ（H7 で判明・別途対応候補）

1. **成果物→HEAD の追跡可能性がアプリで不揃い。**
   - 俺伝: `BUILD_INFO.txt` に Git branch / commit SHA / EXE SHA-256 を記録（配布先でも SHA 照合）。◎
   - beverage: ビルド `.cmd` がコンソールに EXE size + SHA-256 を表示するがファイルに残さない。
   - NDS / menu-sheet: 成果物に HEAD 情報を一切埋め込まない（`dist/` / `publish/` 単体では
     どのコミットから作られたか不明）。→ NDS `build_exe.py` と menu-sheet `BUILD_RELEASE.cmd` に
     俺伝相当の `BUILD_INFO.txt`（HEAD SHA + EXE SHA-256 + ビルド日時）出力を足すと横並びになる。
2. **NDS はクリーンツリーを要求しない。** 未コミットのままビルドでき、上記 1 と相まって
   「配布した EXE の出所」が曖昧になりうる。俺伝の `Assert-CleanWorkingTree` 相当があると安全。
3. beverage のビルド `.cmd` は `pip install --upgrade pip` + `requirements-dev.txt` を毎回流すため
   `.venv` が更新される（追跡外だが再現性の観点で `--dry-run` 事前確認や lock 運用の余地）。

いずれも「今すぐ壊れる」問題ではない。CI/標準の次サイクルで検討。

---

## 検証しなかったこと（意図的）

- Nuitka / PyInstaller / dotnet の**実行時間のかかる本ビルドを俺伝で実施**（DryRun で経路確認。
  俺伝の本ビルド成果物は `releases/俺伝-2026-09-02-1128` 等に実績あり）。
- 破壊的な異常系（壊れた成果物での配布、途中失敗時のロールバック実挙動など）の強制発火
  （既存テストで担保済み。要件でも「無理に実行しなくて構わない」）。
- 実ネットワーク共有・実 HDD・本番タスクスケジューラへの書き込み（要件どおり全面回避）。
