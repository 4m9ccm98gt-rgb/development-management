# Development Control Center

## 目的

Development Control Center は、各repoの場所・正式スクリプト・candidate SHA・PR / CI状態を探し回らずに、repoの標準化から日常の開発後半までを一画面で進めるWindows向け操作パネルです。

正式起動入口は `DEV_CONTROL_CENTER.pyw` です。Tkinterのみを使い、専用の追加依存はありません。

## 運用モデル

正本は `OPERATING_CONTRACT.md` です。

実装・設定変更の開始点は常に **AI依頼欄** です。`development-management` 自身も通常repoと同じManaged Repositoryです。

```text
GPTがAI依頼を整理
→ AI依頼欄 + テスト欄 → AI開発開始
→ Claude実装 → 独立Tests → GPT-6 Astra read-only review → local candidate
→ Control Centerでcandidate確認 → RUN_DEV / ユーザー実機確認
→ BUILD
→ UPDATE / DEPLOY
```

repoを選択すると、`dev_control_center_repos.toml` の `[initial_ai_tasks]` / `[initial_tests]` がAI依頼欄・テスト欄へ自動入力されます（ユーザー入力済みの内容が優先）。

## SETUP / 標準化

正式反映・検証結果とローカル保留は [2026-09-16 最終セットアップ記録](dcc_final_setup_20260916.md) を参照してください。既存PR作業branch上のrepoは、入口が存在してもexpected branch不一致として安全停止します。

2026-09-16の初回横断整備結果は [DCC初回セットアップ記録](dcc_initial_setup_20260916.md) を参照してください。local candidateの入口検証と、expected branchへの正式反映・ユーザー実機確認は別の状態として記録しています。

既存の `UPDATE.cmd` / `DEPLOY.cmd` も正式入口として認識します。service / webでBUILD入口がない場合はソース配布として `N/A` を表示します。アプリ未実装の例外は `dev_control_center_repos.toml` の `[unimplemented]` に理由を記録し、RUNはMISSINGのまま、未実装で不要なBUILD・配布だけN/Aにします。実装時はこの例外を削除します。

既存repoの標準入口が不足していれば、その内容をAI依頼欄から依頼します。

## 新規repo

GitHub上に存在し、`scripts/repo_types.toml` に未登録の非archived・非fork repoは `GitHub未登録repo` に表示します。

`セットアップ開始` は次を行います。

1. 正式 `Development\repos\<repo>` 配下にrepoが無ければ `gh repo clone`
2. 既存の非Gitディレクトリがあればfail-close
3. `development-management` を自動選択し、そのAI依頼欄へrepo登録タスクをセット（「AI開発開始」でClaude → Tests → Astraにより登録）

ユーザーがcloneコマンド、registryファイル名、標準入口の作り方を暗記する前提にはしません。登録後にDCCを更新して新repoを選択すると、`initial_ai_tasks` / `initial_tests` が自動入力されます。

## Control Center自身の更新

Control Centerは `development-management/main` とローカルHEADを比較します。

- mainが同一 → `最新版`
- mainが新しく、CIが `FAILED` ではない → `更新する` を有効化
- CI `PENDING` / `NO CHECKS` / `UNAVAILABLE` は状態を表示した上で更新可能
- CI `FAILED` は自動更新を停止

`更新する` は正式 `SYNC_CLICK_ME.cmd` を `--no-pause` で呼びます。成功後は `DEV_CONTROL_CENTER.pyw` を自動再起動します。

通常のダブルクリックSYNCでは従来どおりpauseします。

## repo選択の非同期読込

repo選択・全状態更新・起動時のself-update確認・未登録repo確認では、git / gh / ファイル走査をUIスレッドで実行しません。
すべて `scripts/dev_control_center/loader.py` のdaemon workerで実行し、結果だけを50ms周期のheartbeatでUIへ反映します。

- **根本原因（コード追跡で確認済み）**: 従来は `<<ListboxSelect>>` のたびに `inspect_repo`（git 6回）、`discover_entrypoints`
  （`git ls-files` + ファイルstat）、`fetch_github_state`（gh 4回、各timeout 20s）をUIスレッドで直列実行していました。
  起動時も約12 git + 9 gh が直列でした。どの項が実機で支配的かは**未確認**です（`gh` が有力な仮説）。
  下記の計測で確認します。
- **scope**: repo scope（local / github / suggest）は `(repo, kind)` ごとにlatest-wins。GLOBAL scope（`remote_repos` / `self_update`）は
  repo切替で取り消しません。
- **cancel_repo_scope**: repoを離れる・工程開始/終了・同repo再選択は単一の `cancel_repo_scope(repo, reason)` を通り、
  そのrepoのPENDINGとRUNNINGを取り消します（通知は出しません）。cancel対応worker（git/gh/走査はcancel Eventを約0.2s周期で確認）は
  すぐ空き、新しいrepoは古い処理の期限を待ちません。cancelを無視するworkerだけは、cancel時刻から
  `SUPERSEDE_GRACE`（暫定10s）後に放棄され、置換workerが起動します。この最悪待ち時間（grace + 1 tick）は通常経路の目標とは分けて扱います。
- **期限とresource**: LOCAL 30s / GITHUB 60s / GLOBAL 90s（暫定）。PENDING期限はworkerに触れず、RUNNING期限はそのworkerだけを放棄し、
  timeoutは `TerminalNotice` として1回だけ通知（fail closed）。上限は放棄数ではなく総live thread数（pool size + 4）。
  放棄workerが戻れば復帰（rehabilitate）または退役。resultとnoticeは1つのlockで排他的に決まります。
- **整合性**: 表示stateは `lifecycle_epoch` のstamp付きで、accessor（`authoritative_local/github`）経由でのみ参照します。
  repo選択・全状態更新・工程開始/終了・AI適用の直前で必ずepochを進め、古い結果・古いGitHub状態は判断に使いません。
  candidateの由来（NONE/USER/AI/AUTO）は `CandidateProvenance` だけが書き、`NONE iff 空` を守ります。
  AUTOのcandidateは選択のたびにクリアされ、新しいGitHub結果で再反映されます（GitHub結果が届くまで一時的に空）。
  USER / AIのcandidateは切替後も保持されます。
- **確認dialog**: RELEASE確認・AI candidate適用確認・新規repo clone確認・self-update確認は、開始時にsnapshotを取り、
  dialog中は結果適用を保留し、承認後にsnapshotが変わっていれば実行せず中止します。
- **安全条件は変更なし**: `decide_lifecycle`、`launch()` の条件、`apply_local_candidate` の自己検証、CMD/BAT限定、
  push / BUILD / UPDATEを自動化しない点は従来どおりです。GitHub状態が無くても手入力candidateで動く従来仕様も同じです。
- **未対応（従来どおり同期）**: `apply_local_candidate`、self-updateのSYNC実行、`clone_new_repository` はユーザー操作起点の同期処理のままです。
  GitHub状態表示キャッシュ（設計step 16）と gh 並列化（step 17）は、計測結果で必要性が出た場合のみ入れる設計のため未実装です。

### 計測（DCC_TIMING）

`DCC_TIMING=1` でDCCを起動すると、標準エラーへ次を出力します（無効時は無出力）。

- `startup-to-operable`、`select-to-LOCAL-shown`、`select-to-GITHUB-shown`
- gh呼び出しごとの所要時間（`gh:api repos/.../branches/...`、`gh:pr list`、check-runs、status、`gh:repo list`）
- UI heartbeat遅延（`ui-lag`、終了時 `ui-lag-summary` の p95 / max）
- `repo-scope-cancel`（取消したPENDING/RUNNING数）、`superseded-worker-returned`、`superseded-worker-abandoned`、`timeout-*`、`abandon` など

実機手順:

1. `python scripts/measure_dcc_selection.py --iterations 5` で各repoのgit / 走査 / `fetch_github_state`（endpoint別）を測る（読み取りのみ）。
2. `DCC_TIMING=1` でDCCを起動し、最大repoを5回選択、遅いネットワーク条件、非Git/低速FSのrepoがあればそれ、
   さらに遅い2repoを跨ぐ A→B→C の連続切替（最後のクリックからCのLOCAL表示まで）を記録する。
3. 目標（暫定・実機測定前は未確認）: 起動から1s以内に操作可能、選択・読込中のheartbeat遅延 p95 ≤ 100ms / max ≤ 250ms、
   典型repoでLOCAL表示 ≤ 1s。cancel無視workerが残る場合の追加待ち（≤ grace + 1 tick）は別枠で報告する。
   この目標を超えた場合は「目標未達」と報告する。

## 安全条件

- origin一致
- expected branch一致
- tracked clean
- candidateは完全40桁SHA
- RUN / BUILD / 配布時は `local HEAD == candidate`
- force push / reset / stash / branch切替はControl Centerが勝手に行わない
- Git管理外の業務データや秘密情報を変更しない
- 工程は自動連続しない

## CI

`.github/workflows/dev-control-center.yml` で次を確認します。

- registry / explicit branch契約
- 正式入口の検出と曖昧時fail-close
- 完全40桁candidate SHA
- GitHub未登録repo検出
- CI状態集約
- Actions greenをcandidate必須条件にしない契約
- open PR中の自動candidateブロック
- 新規repo登録prompt契約
- `SYNC_CLICK_ME.cmd --no-pause`
- Python compile
- registry self-check

GUIの見た目、`gh` 認証済みWindows実機での取得・clone・各ボタンのクリック感はユーザー実機確認で扱います。
