# Development Control Center — Phase 1

正本は [OPERATING_CONTRACT.md](../OPERATING_CONTRACT.md)。`RUN_DEV.cmd` / `DEV_CONTROL_CENTER.pyw` が起動入口です。

## 画面

メインはrepo選択、RUN / BUILD / UPDATE、AI Orchestrator入口を上部へ配置します。最小1080×720。AI依頼、Main / Reviewer選択、Claude / Codex残量、run状態・ログ、candidate、AI安全停止はOrchestrator別画面に置きます。別画面は実行中runの一覧・再接続を持ち、DCCメインの表示領域を圧迫しません。repo登録指示はコピー可能な別画面で生成し、Claude / Codex直接実装へ渡せます。

## 操作と成果物

RUN / BUILDはcandidate、tracked clean、GitHub取得成功を要求しません。起動直前に正式repo / origin / entrypointを再検査します。Orchestrator内部のclean条件は別です。

BUILDは非対話adapterから既存の処理本体を実行し、`%LOCALAPPDATA%/ShizenDev/DCC/builds/<repo-key>/` にlatest.jsonとbuild ID別記録を保存します。repo、base HEAD、dirty、開始・終了日時、build ID、入力fingerprint、成果物パス・全ファイルの集約SHA-256、結果を保持します。前回成功は新しいBUILD開始時に無効化します。

BUILDの成功（`status: ready`）は次の**すべて**が成立した場合だけです。不成立の条件は記録の `reject_reasons` に列挙し、UPDATE対象にしません。

- BUILD本体のreturncode == 0（失敗コードはそのまま記録。成功後の補助処理の失敗も非0で検出）
- BUILD前後で入力が不変（`inputs_stable`）、HEADが不変（`head_unchanged`）
- **このBUILDで**成果物が生成・更新された（`artifact_refreshed`: BUILD前と内容が異なり、かつBUILD開始後に書かれたファイルがある。repoがbuild-infoファイルを書く場合はそのファイル自身がBUILD開始後に書かれていること）。古い成果物が残っただけ・一部が消えただけは不可
- repoがbuild-infoを宣言している場合（`[build.<repo>].build_info`、next-day-setupは `BUILD_INFO.txt` の `Git commit SHA`）、そのSHAがBUILDしたHEAD（candidate時はcandidate SHA）と一致し、candidate時は作業ツリーclean
- 成果物hash（`artifact_hash`）が取得できる
- candidate時は、BUILD worker自身が起動直前に承認SHA == push SHA == local HEAD == origin（ls-remote）とcleanを再確認

DCCは手動用CMD（`BUILD_EXE_CLICK_ME.cmd` 等）を実行しません。CMDは正式入口の存在確認だけに使い、処理本体（next-day-setupは `.venv\Scripts\python.exe build_exe.py`、`[build.<repo>]` で管理）をstdinを閉じた非対話プロセスで直接実行するため、CMD末尾の `pause` には到達しません。本体が無ければ起動前に停止します。

入力監視はtrackedファイルとGitで無視されない新規ファイルを対象とし、成果物ディレクトリは除外します。Gitで無視するローカルbuild設定は `.dcc-build-inputs.json` に相対ファイルパスの配列を指定して監視に含めます（内容は記録しない）。依存関係・外部ツールの全変更や瞬間的な変更を完全追跡する再現ビルド保証ではありません。入力不安定・失敗・成果物欠落はUPDATE不可です。

UPDATEの成果物hash計算はUI外のworkerで行います。UPDATEはBUILD記録、入力fingerprint、成果物hash、配布先、更新スクリプトを確認画面へ渡し、ユーザー承認後に再検査します。実行workerでも出力先ロック取得後に同じ条件を検証します。DCC経由の同じ出力先のBUILD / UPDATEはprocess間で排他します。外部ツールによる直接変更はこのロックには従わないため、配布中に外部BUILDや編集を重ねないでください。

## Orchestrator candidateフロー

`scripts/dev_control_center/candidate.py`。Orchestratorの最新 `completed / OK` runの `run.json` がcandidate（SHA / branch / base）の唯一の正です。DCCは `%LOCALAPPDATA%/ShizenDev/DCC/candidates/<repo-key>/<run-id>.json` にそのcandidateのRUN_DEV結果・承認・push・終了状態（`deployed` / `rolled_back` / `discarded`）だけを保存し（run id単位なので新しいrunは古い承認を引き継がない）、BUILDの事実はBUILD記録（`candidate_sha` / `candidate_run_id` / `build_info_sha`）から、本番の事実は下記「本番状態・rollback・失効SHA」の記録から導きます。

| 段階 | 対象SHAと条件 |
|---|---|
| Orchestrator candidate | run.jsonのcandidate_sha。commit消失・candidate branch移動・baseの子孫でない場合は停止 |
| RUN_DEV | `%LOCALAPPDATA%/ShizenDev/DCC/run-worktrees/<run-id>/<repo名>`（candidate SHAのdetached worktree。Orchestratorのworktreeが残っていればそれ）。source repoの `.venv` のPython、cwdはworktree。開始前・終了後のHEADを確認し、run id・repo・SHA・branch・target・entrypoint・command・開始 / 終了・終了コードをログと状態へ記録。candidate RUNはvenv作成・pip installをせず、不足なら停止。`[run.<repo>].seed` のランタイムデータを起動前にコピー（下記） |
| Human approval | 最新RUN_DEVがPASSの同一SHAだけ。PASS = rc 0、HEAD不変、Git管理ファイルが開始前・終了後ともclean。RUN開始前に試行を `RUNNING` として記録し承認を無効化するため、停止・異常終了したRUNは承認できない。再RUNで承認は無効。確認ダイアログでSHAを表示 |
| push | 承認済みSHAだけ。管理branch・clean・進行中操作なし、local / originがbaseまたはcandidate。`merge --ff-only` と `git push origin <sha>:refs/heads/<branch>`（forceなし）後、`ls-remote` とfetchでorigin == SHAを確認 |
| BUILD | 承認 == push == local HEAD == origin（ls-remote）かつclean。BUILD workerも起動直前と終了後にHEAD == SHAを再確認 |
| UPDATE / DEPLOY | BUILD記録の `base_head` / `candidate_sha` / `build_info_sha` == 承認・push済みSHA、dirtyでない、local HEAD == origin == SHA。candidateの束縛（run id・SHA・承認とRUNの識別・ルート）を確認時とUPDATE worker内の実行直前の両方で算出し、変化があれば停止。成功時はcandidateを `deployed` にする |

メイン画面のRUNは、有効なcandidateがあれば「RUN_DEV <SHA>」になり、そのSHAを実行します。candidateが無い、または終了状態（`deployed` / `rolled_back` / `discarded`）のcandidateは従来どおり作業ツリーの通常ルートです。終了状態はcandidateの検証（commit・branch）より先に読まれ、branchが後から動いても終了済みcandidateが再びactiveになることはありません。GitHubのbranch HEAD / open PR表示とSYNC基準SHAは観測・手動SYNC用で、Orchestrator candidateの代わりにはなりません。

RUNの処理本体は `dev_control_center_repos.toml` の `[run.<repo>]`（cwd / entry または module / probe / env）で管理します（repo側の `dcc_entrypoints.json` が優先）。entryはRUN対象（source repoまたはcandidate worktree）基準で解決し、存在しなければ起動前に停止します。next-day-setupはv1.4.1以降、`RUN_DEV.cmd` と同じ `.venv\Scripts\python.exe dinner_system\hotel_app_entry.py`（`hotel_app.HotelApp` を拡張する正式entry。`build_exe.py` のBUILD対象も同じ）です。

### RUN_DEVのランタイムデータ（seed）

next-day-setupのように設定・保存データをコード横のgit管理外ファイルに置くrepoは、candidate worktreeにそれが無いため、`[run.<repo>]` の `seed`（repo相対パスの配列）で指定したものだけを**RUN_DEVのたびにsource → candidate worktreeへ一方向コピー**します。

- コピー先の同名パスは毎回sourceの内容で置き換えます（前回RUNでの変更は持ち越さない）。RUNが書き込むのはworktree内のコピーだけで、RUN中・終了後ともsourceへは何も書き戻しません。RUN前後でsource側seedのサイズ・更新時刻を比較し、変化があれば警告として記録します（DCCの書き込みではない＝別のアプリ等）。
- 各パスはsourceでgit ignored、かつcandidateでGit管理されていないことが必須です（candidateのコードを上書きしない）。repo外・絶対パス・`..`・リンク（symlink / junction）を含むものは起動前に停止。sourceに無いパスはskipしてログに残します。
- 対象は作業ツリーの通常RUNには関係しません（通常RUNはsourceのデータをそのまま使う）。
- next-day-setup: `master_settings.json` / `ui_prefs.json` / `closing_tasks.json` / `monthly_tasks.json` / `config/print_preparation.json` / `保存データ/`（いずれも `dinner_system/` 配下）。`print_work` / `outputs` / ログ / `shared_folder_path.txt` は対象外。コピーされた設定のままアプリが動くため、印刷等の外部動作は通常RUNと同様に実環境へ出ます。

## 本番状態・rollback・失効SHA

**本番（production）とmainは別の状態です。** mainは「次に配布できるコード」、productionは「DCCが配布を確認済みの配布物」です。rollback直後のように両者が異なっていてもDCCはどちらかで他方を推測しません。記録はすべて `%LOCALAPPDATA%/ShizenDev/DCC/builds/<repo-key>/` にあります（共有フォルダには書きません）。

| ファイル | 内容・書かれる時 |
|---|---|
| `production.json` | **確定した本番**。UPDATEがrc 0で成功した時（commit = BUILDの `base_head`。共通engineでは最終検証後に、version・`release_id`・release manifestの `manifest_sha256`・EXE SHA付き）と、検証済みrollbackの時（commit = 復旧先、version・EXE SHA付き）だけ書かれる。失敗したUPDATEでは変わらない |
| `last_release.json` | **直近の試行**（UPDATEの成否を問わず、またはrollback）。本番の根拠にはしない。`production.json` が無い旧状態では、rc 0の場合に限り本番として読む。試行が上書きする前に、`production.json` の無い旧状態の成功記録は `production.json` へ昇格される（`release-migrated-<日時>.json` に保存） |
| `release-<日時>-<build id>.json` | UPDATE試行ごとの履歴（上書きされない） |
| `release-<日時>-rollback.json` | rollback記録の不変コピー（復旧元backup、退避先 `saved_before_restore`、plan id、rollback元SHA）。以後のUPDATE試行で失われない |
| `release-superseded-<日時>.json` | rollback時点で `last_release.json` だった記録（置き換えられた配布） |
| `revoked.json` | **失効SHA**（rollbackで本番から外したSHA、置換先、plan id）。rollbackごとに追記 |

- DCC画面の「Orchestrator candidate フロー」の先頭に `production (DCC記録)` として確定した本番（commit・version・経緯）を表示します。確定していない（失敗した試行しかない）場合は表示しません。
- **失効SHAのBUILDはUPDATEできません。** 失効SHAは `revoked.json`、`rolled_back` のcandidate状態、rollbackである `last_release.json` の和集合で、BUILD記録の `base_head` がこれに含まれると、candidateルート・作業ツリールートを問わず `read_receipt` の段階でUPDATEを停止します（同じSHAを新たにBUILDし直しても同様）。後続のUPDATE試行で `last_release.json` が置き換わっても失効は残ります。
- **rollback後のcandidate**: 本番から外したSHAのOrchestrator candidateは `rolled_back`（日時・復旧先）になり、非active・RUN_DEV / 承認 / pushとも `CANDIDATE_ROLLED_BACK` で拒否され、再利用されません。フローのUPDATE段階は「配布後に本番からrollback済み（本番は <SHA>）」と表示します。以後の新しいcandidateは別のrun idの状態として最初から始まります。
- rollbackは `python -m scripts.dev_control_center.restore_release plan ...`（読み取り専用のdry-run。live配布物の管理対象ファイルと保護データ、復旧元backupの必要ファイルだけを対象にし、共有フォルダ全体や他のbackup世代は走査しない）→ plan確認 → `execute --plan ... --confirm <plan id先頭12文字以上>`。executeはplan内容のdigest（repo・target・backup・復旧先commit / version・置換前のBUILD_INFO・対象ファイル・期待hash・全管理ファイルのstat）を再計算し、live側の変化があれば何も書かずに停止します。最終検証が失敗・完了不能なら置換したアプリファイルだけを戻し（運用データはそのまま）、戻しきれなければ `ROLLBACK_INCOMPLETE` と退避先を表示します。上記の記録はすべて検証成功後にだけ書かれます。

## 共通UPDATE engine（差分UPDATE）

`scripts/dev_control_center/release_update.py`（パイプライン）と `release_engine.py`（安全プリミティブ。`restore_release` と共用: lock、in-use確認、safe path、reparse point拒否、保護guard、検証済み退避、staging、置換、undo、`ROLLBACK_INCOMPLETE`）。`[release.<repo>]` に `engine = "dcc"` があるrepoは、DCCのUPDATEボタンがこのengineを使います（現在next-day-setup）。アプリrepoはUPDATEロジックを持たず、`[release.<repo>]` の設定だけを持ちます。repo固有処理は `release_engine.HOOKS` に登録された読み取り専用の検証hookを名前で許可する場合だけです（設定からのimportはしない。現在なし）。

**設定（`[release.<repo>]`）**: `artifact` / `child_target`、`managed`（管理対象。`*` は1階層、`**` は任意階層）、`protected` / `protected_names`（運用データ。managedに一致しても除外）、`critical`（前後SHA-256）、`operational_roots`（運用データを探す唯一のフォルダ）、`final_swap`（最後に置換する順。EXEが最後）、`in_use`、`manifest`、`lock` / `legacy_locks`、`backup_dir` / `backup_retention`（既定5）、`build_info` / `build_info_keys`、`hooks`。読み込み時に全パスを検証し、保護対象のmanifest・lock、管理対象外のfinal_swap、未登録hookは `CONFIG_INVALID`。

next-day-setup: managed = `DinnerSystem.exe`・`_internal/**`・直下の `*.txt` / `*.bat` / `*.vbs`（`update_delta.ps1` の配布対象と同じ）。protected = `update_shared_folder.ps1` / `update_delta.ps1` の保護（`保存データ` / `print_work` / `logs` / `log` / `backup` の各階層、`*.log`、`_internal/outputs`、`SumatraPDF-settings.txt`、`closing_tasks.json` / `master_settings.json` / `ui_prefs.json`）に加え、稼働中アプリが自分で書く直下の `config/`（`app_dir()/config` の印刷設定。どの更新も配布していない）と直下の `outputs/`。成果物内の `_internal/master_settings.json` 等（同梱の既定値）は保護対象として配布しません。lockは `.dcc-release.lock` と旧updaterの `.nds-update.lock` を同時に保持します。

**流れ**（DCC: 配布先を選ぶ → dry-run → 結果を確認ダイアログで表示 → 「はい」だけでexecute。実行中は画面から停止できません）:

| 段階 | 内容 |
|---|---|
| [1/7] Provenance | BUILD記録が `ready`、失効SHAでない、成果物・入力がBUILD後に不変、dirtyでない、BUILDしたSHA == local HEAD == origin/<branch>（ls-remote）、candidateルートは承認 == push == BUILD SHA、成果物の `BUILD_INFO` のSHA == BUILD SHA、成果物EXE == `BUILD_INFO` のEXE SHA-256 |
| [2/7] Production | DCCの `production.json` のcommit == 配布先の `BUILD_INFO`（違えば `PRODUCTION_MISMATCH` で停止）、配布先が失効SHAなら停止。release manifestの信頼判定（下記） |
| [3/7] Delta | 管理対象だけを比較。unchanged / modified / new / 削除候補 / retained（管理対象外）/ protected に分類 |
| [4/7] Backup | modifiedだけを `backup/dcc_release_<日時>_<release id>/files/` へ退避しSHA-256照合、同フォルダに `backup_manifest.json`（release id、source commit、置換前の本番commit、modified: 旧hash・新hash・backup hash、new: 新hash、日時）を記録。newは元が無いので退避不要 |
| [5/7] Staging | 全変更を配布先の同じフォルダへstageしSHA-256照合。ここまでliveファイルは不変。その後、起動防止としてEXEを共有なしで開いて保持し（内容はその保持handle経由でhash）、どのPCからも起動できない状態にする（起動済みなら `IN_USE` で停止） |
| [6/7] Apply | EXE以外 → `BUILD_INFO.txt` → EXEの順に置換。起動防止はEXE自身を置き換える瞬間だけ外し、置換直後に新EXEで取り直して最終検証・巻き戻しの間も保持。各書き込みの直前にパスを再検証（途中でjunction等に差し替えられたフォルダへは書かない）。失敗時は今回置換したものだけを逆順に検証済み退避から戻し、今回追加したファイル（内容が書いた時のままのものだけ）と作ったフォルダを削除 |
| [7/7] Final | 変更ファイルのSHA-256、unchangedファイルのstat不変、final-swapファイル、配布先BUILD_INFO == 新BUILD、EXE == BUILD_INFO、critical SHA-256不変、運用データのメタデータ不変、stage残骸なし、hook。失敗 → 巻き戻し（運用データの変化は `OPERATIONAL_CHANGED`: アプリファイルだけ戻しデータは残す） |

最終検証の成功後にだけ、配布先のrelease manifest（`DCC_RELEASE_MANIFEST.json`）をatomicに置き換え、続いてDCC記録（`production.json` / `last_release.json` / 履歴 / `releases/<release id>.manifest.json`、candidateなら `deployed`）を書き、最後に保持世代を超えた古いengine backupだけを削除します。失敗・停止した試行は `last_release.json` と履歴に `returncode 1` と `code` で残り、`production.json` は変わりません。

**dry-run**: 配布先へは一切書きません（lockも作らない）。走査するのは直下のファイル、管理対象のフォルダ（`_internal`）、`operational_roots` だけで、`backup/` や無関係なフォルダには入りません。表示: 本番SHA、新BUILD SHA、各分類の件数、backup対象と容量、コピー容量、推定時間、manifestの信頼可否と理由、使用中のEXE。planはローカル（`%LOCALAPPDATA%/ShizenDev/DCC/builds/<repo-key>/update-plans/`）に保存し、plan id（本文のdigest）の先頭12文字以上の確認がexecuteに必要です。executeはplan digest・設定digestを検証し、provenance（BUILD / candidate / origin）、成果物、production記録、配布先BUILD_INFO、manifest、planが見た全管理ファイルのstatを再計算して、dry-run後に変化があれば何も書かずに `PLAN_DRIFT` で停止します。

**release manifest v2**（`DCC_RELEASE_MANIFEST.json`）: `schema_version: 2`、`release_id`、`repo`、`deployed_commit`、`version`、`build_id`、`artifact`（tree SHA-256・EXE SHA-256・BUILD_INFO）、`provenance`（route・branch・HEAD・origin・candidate）、`build_timestamp`、`released_at`、`engine_version`、`previous_release_id` / `previous_commit`、`files`（path・size・SHA-256・配布後のmtime）。旧NDSの `DEPLOY_MANIFEST.json` は使いません（残置。restoreが旧full backupを戻す時だけ使う）。

**manifestの信頼**: 次の全部が成り立つ時だけ差分の基準にし、size + mtimeが記録と一致するファイルは読まずに比較します。1つでも欠ければ「未信頼」として管理対象の全ファイルをSHA-256で検証し、削除候補も出しません。

- 構造が正しい（全entryが管理対象の正しいパス、重複なし、size / SHA-256 / mtimeあり）
- `deployed_commit` == 配布先 `BUILD_INFO` == `production.json` のcommit、`release_id` == `production.json`
- manifestファイル自体のSHA-256 == `production.json` の `manifest_sha256`（UPDATE成功時に記録。編集・差し替えを検出）
- 配布先のEXEと `BUILD_INFO.txt` の実SHA-256 == manifest、EXE == `BUILD_INFO` のEXE SHA-256

metadataだけで「変更なし」と判定したファイルも、executeでは書き込み前に実SHA-256で確認します（dry-runは速いまま、中身の保証はexecuteで取る）。size・mtimeを戻した改変が見つかれば何も書かずに `UNCHANGED_CONTENT_MISMATCH` で止め、そのmanifestを以後信頼しません（`manifest-distrust.json`。次のdry-runは全管理ファイルを検証して修復対象にする）。modifiedは退避時に実SHA-256で照合します（`SAVE_HASH_MISMATCH`）。manifestの組み立て・書き込みを含め、最初の置換以後のどんな失敗でも巻き戻し、完全に戻せた時だけ中断マーカーを消します。backup保持処理の失敗は、確定済みのreleaseを失敗にしない警告です。

**削除候補**: 信頼済みmanifestで管理対象だったのに新BUILDに無く、配布先に残っているファイルだけ。dry-runは停止理由とし、削除は決してしません。DCCで「管理対象外として残す」を選ぶとdry-runをやり直し（`--acknowledge-orphans`）、以後は通常の管理対象外ファイルになります。配布先だけにある未知のファイル・運用データは一覧表示して残し、停止理由にしません。ただし信頼済みmanifestがあり、新BUILDが新規に置くパスに管理外のファイルがある、または管理対象パスにフォルダがある / 親がファイルの場合は `PATH_COLLISION` で停止します。前回の中断で残ったstageファイル（`.dcc-stage` / `.dcc-undo`）があれば停止します。

**中断**: 配布先へ最初に書く前にローカルへ `update-inflight.json` を置き、成功または完全な巻き戻しの後に消します。`ROLLBACK_INCOMPLETE`（退避先を表示）やプロセス停止で残った場合、次のdry-run / executeは `INTERRUPTED` で停止します。配布先を確認・復旧した後、`python -m scripts.dev_control_center.release_update clear-interrupted --repo <repo> --confirm <release id先頭12文字以上>` で解除します。

**backup保持**: `backup_dir` 直下の `dcc_release_*` で、同じrepoの完全な `backup_manifest.json` を持つものだけが対象です。新しい順に `backup_retention` 世代（今回分は必ず）を残し、それより古いものを削除します（中にreparse pointがあれば削除しない）。旧updaterの `update_before_*`、restoreの `rollback_before_*`、他repo・不完全なbackupには触れません。

**CLI**: `python -m scripts.dev_control_center.release_update plan --repo <repo> --target <配布先> [--branch main] [--acknowledge-orphans]`（rc 0: 実行可能、2: 停止理由あり）→ `execute --plan <plan.json> --confirm <plan id先頭12文字以上>`（rc 3: `ROLLBACK_INCOMPLETE`）。

## 既存entrypointとの接続

正式CMDの存在検査は維持しますが、DCCは手動CMDを実行しません。RUN / BUILDは `entrypoints.py` からPython / PowerShell / dotnetの処理本体へ接続します。UPDATEは確認済みの配布元・配布先を明示します。元のCMD / PowerShellとダブルクリック時のpauseは変更しません。

| repo | 成果物 | UPDATE接続 |
|---|---|---|
| next-day-setup | dist/DinnerSystem | 共通UPDATE engine（`[release.next-day-setup]`、上記）。update_shared_folder.ps1 はDCCから実行しない |
| beverage-inventory-ordering-system | python_app/dist/在庫発注管理アプリ | 既存更新PS1のSourcePath / TargetPath |
| menu-sheet-generator | publish | UPDATE.cmdと同じ4ファイルを非対話adapterでコピー |
| food-cost-calculation-system | Development/releases | 既存更新PS1のSourceRoot / HddRoot。HddRoot配下のFoodCostCalculationへ更新 |

アプリ側の安全条件はバイパスしません。飲料BUILDは既存のclean必須、翌日準備UPDATEは既存のdirty build拒否等が残ります。これらの緩和は対象repoで別途対応が必要です。未登録repoのRUN / BUILDは下記の非対話入口宣言が必要です。UPDATEは引数・成果物の契約が確認されるまで停止します。ソース配布型のQRアプリなど、BUILD入口を持たないrepoに架空の成功BUILDを作りません。

## Orchestratorと終了

Orchestratorのrunは独立worker processが所有し、DCCの実行中操作（`ACTIVE_OPERATIONS`）ではありません。Orchestratorの実行中・失敗・quota・crash・stale・usage取得失敗が、同じrepoを含む通常のRUN / BUILD / UPDATEをロックすることはありません（isolated worktreeで動くため）。RUN / BUILD / UPDATE自身の同一repo・同一出力先の競合だけを止めます。

Orchestrator画面の×は画面を閉じるだけ、DCC終了はclient終了だけでrunは継続します（終了を保留するのはRUN / BUILD / UPDATE実行中だけ）。DCC起動時に実行中runを検出して操作ログとボタン（「AI Orchestrator ● 実行中 N」）へ表示し、画面を開くと同じrunへ再接続して進捗・ログ・usage・AI安全停止を使えます。AI安全停止はそのrunのprocess treeだけを終了します。成果物（candidate）の適用はユーザー確認後のfast-forwardのみで、sourceが移動していれば保留します。DCC自身の更新も実行中操作がある間は停止します。

## 検証

`python -B -m unittest discover -s tests -p "test_dev_control_center*.py" -v` と `python -B -m scripts.dev_control_center.app --self-check` を使用します。UI検証はWindowsのTkで1080×720のボタン表示と子画面を確認します。実配布・プリンター・外部サービスはmock検証と区別します。

## バックグラウンド実行

RUN / BUILD / UPDATEは事前検査・hash計算・subprocess待機をworkerで処理します。Windowsコンソールは非表示、stdinは閉じ、stdout / stderrをまとめてDCCログへ逐次転送します。RUN対象のGUI画面は通常どおり表示します。完了時は実際の終了コードを表示します。BUILD中もDCCの移動、ログ閲覧、repo切替が可能です。同じrepoの競合操作だけを停止し、別repoの操作は続けられます。「このrepoの実行を停止」は明示確認後に子process treeを停止します。停止・失敗BUILDはUPDATE対象になりません。

監査したRUN入口: 翌日準備、飲料、原価、備品、QR、メニュー、DCC。BUILD入口: 翌日準備のbuild_exe_entry.py、飲料の既存準備・clean検査・Tests・build_exe.py、原価のbuild_release.ps1、メニューのdotnet build / publish。メニューBUILDのExplorer自動表示も行いません。入口未実装のcall-reception / shizen-launcherは停止します。備品のタスク登録やQRの対話deployへ暗黙にフォールバックしません。

新しいrepoは、正式入口に加えてrepoルートの `dcc_entrypoints.json` に非対話の処理本体を宣言できます（schema 1）。例:

```json
{"schema": 1, "build": {"script": "tools/build.py", "cwd": ".", "args": [], "python": ".venv/Scripts/python.exe"}}
```

runも同じ形式です。scriptはrepo内の `.py` / `.ps1`、cwdと任意pythonもrepo内です。PowerShellはNonInteractive、Pythonはunbufferedで実行します。処理本体は入力待ち・pause・コンソールの明示起動を含めず、失敗を非0で返す必要があります。未対応repoでは手動CMDを隠して呼ぶことはせず停止します。既知repoの手動入口を変更する際は、DCC adapter側の準備・安全条件も整合してください。
