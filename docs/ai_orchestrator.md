# AI Orchestrator（Phase 2 — 長時間放置できる自動開発モード）

運用の正本は [OPERATING_CONTRACT.md](../OPERATING_CONTRACT.md)。通常Developmentの必須経路ではなく、DCCの別画面から使う任意の第二ルートです。isolated worktreeで実装し、Tests PASS + Reviewer PASS + 安全チェックPASSの**local candidate**で停止します。push / BUILD / UPDATE / DEPLOYは行いません。

## 全体像

```text
ユーザー → DCC（Orchestrator画面）→ start_run
                                   └─ 独立worker process（run単位）
                                        Main AI 実装 → Tests
                                          FAIL #1  : Main自身が原因分析・修正 → Tests
                                          FAIL #2〜: Reviewer(read-only)が失敗分析 → Mainへ自動で修正指示 → Tests
                                          Tests PASS: Reviewer最終レビュー
                                            FAIL: Mainへ自動で修正指示 → Tests → 再レビュー
                                            PASS: 安全チェック → completed（local candidate）
```

ユーザーがレビュー結果・decision JSONを中継する操作はありません。人間へ返すのは「完成」「安全上継続不可」「provider利用不能」「人間判断が必要」「上限到達」「process / worktreeを信頼できない」場合だけです（`needs_human`）。

## 構成（`tools/ai_orchestrator/`）

| module | 責務 |
|---|---|
| `orchestrator.py` | CLI（`start` / `run` / `worker` / `stop` / `status` / `usage` / `doctor`）、Git baseline・isolated worktree・candidate、`start_run`（独立worker起動） |
| `engine.py` | Main / Reviewerループ。**providerを名指ししない**（役割 `main` / `reviewer` のみ）。上限は `Limits` |
| `providers.py` | `ClaudeProvider` / `CodexProvider`。1回のCLI呼出しを `AgentResult` へ変換し、quota / auth / transient等を分類 |
| `usage.py` | `UsageProvider`（`ClaudeUsageProvider` / `CodexUsageProvider`）と表示整形。account枠とcontextを別概念で保持 |
| `runstate.py` | 状態機械、`run.json`、heartbeat、liveness判定、repoロック、安全停止、stale整理 |
| `review.py` | Reviewer JSONの厳格parse、failure / review fingerprint |
| `common.py` | process tree制御・process identity（PID + 作成時刻）・原子的JSON |
| `prompts/` | `main_implementation.md` / `main_repair.md` / `reviewer.md`（provider非依存） |

DCC側は `scripts/dev_control_center/orchestrator_view.py`（別画面。`RunMonitor` がrunファイルを背景threadで監視）。DCCメインにAI詳細は置きません。

## Main / Reviewer

- Orchestrator画面で Main AI / Reviewer AI を Claude / Codex から選択。**初期値は Main=Claude、Reviewer=Codex**。両方向（Claude→Codex、Codex→Claude）を実providerで確認済み。
- 独立レビューの意味を優先し、**同一providerは選択不可**（画面が自動で入れ替え、`start` は `SAME_PROVIDER_ROLES` で拒否）。CLIの `--allow-same-provider` を明示した場合だけ許可し、runへ `same_provider_override` を記録します。
- Mainだけがworktreeを編集（Claude: `acceptEdits` + 許可Bashのみ、gitの書込系は含めない / Codex: `--sandbox workspace-write`）。Reviewerは読み取り専用（Claude: `Read,Glob,Grep`のみ・shell / editor / MCP無し / Codex: `--sandbox read-only`）。Reviewer呼出し前後でdiff fingerprintを比較し、変更があれば `SAFETY_VIOLATION`。
- Windowsでsandbox化されたCodexが作るファイルは所有者ACLの都合で独立Testsから読めないことがあるため、Main呼出し後に**変更されたファイルと親directoryだけ**へ実行ユーザーのmodify権限を付与します（`icacls`、無関係な範囲は変更しない）。

## 受入基準の固定とクレジット保護

Reviewerの後出し指摘でループが増え、Reviewer（既定Codex）のクレジットが小さな修正で尽きるのを防ぐための仕組みです。

- **基準は実装前に固定します。** Taskに「受入条件」節があればその箇条書きを `C1, C2…` としてそのまま固定基準にします（Reviewer呼出し無し・クレジット消費無し）。無ければ、実装前にReviewerが1回だけ基準を作成します（read-only。使えない返答が2回続けばTaskSpec全体を基準にして**それ以上呼ばない**）。基準は `run.json` の `criteria` / `criteria_source`（`task` / `reviewer` / `task_fallback`）に保存され、Mainには実装前から、Reviewerには全レビューに同じものが渡されます。
- **最終レビューは固定基準で判定します。** blocker / major の指摘は、固定基準のID（`criterion`）を示すか、証拠付きの欠陥（category が bug / regression / safety で `evidence` あり）でなければなりません。それ以外（好み・改善案・新しい要件）はOrchestratorが `minor` へ**格下げ**し、記録は残りますが差し戻し理由になりません。格下げの結果 blocking が無くなったFAILはPASSになります（`review_history[].downgraded`）。Tests失敗時の原因分析（failure analysis）の指摘は格下げしません。
- **2回目以降は確認だけです。** 差し戻し後の再レビューには前回のblocking指摘を渡し、「直ったか」と「修正が新たに壊した回帰」だけを見させます（基準の追加は不可）。
- **打ち切られた作業は検証に回しません。** MainがClaudeのturn上限（1呼出しあたり、初回の実装 `main_turns_implementation`=80 / 修正 `main_turns_repair`=40。旧12は複数ファイルの変更で探索だけで尽きた）で中断された場合、差分が一部あっても**Tests・Reviewerへ進めず**、同じsessionで最大 `max_main_resumes`（2）回、続きの呼出しも同じ上限が新たに与えられます（実装なら最大240ターン）。それでも終わらなければ `MAIN_TURN_LIMIT`（`needs_human`）で停止し、worktreeは保存します（Codexは呼びません）。
- **予算で強制停止します。** 上表の `max_review_calls` / `max_review_tokens` / `max_main_tokens`。最終レビューがFAILで、次のレビューを呼べない予算状態なら、修正のためにMainを呼ばずにその場で `REVIEW_BUDGET` で停止します。停止は呼出しの間で判定するため、実行中の1回を途中で切ることはありません。
- **アプリの目的を自動で渡します。** `projects/<repo名>.md` の「正式な目的 / 目的 / 役割 / 概要」節（最初に見つかったもの、1500字まで）をMain・Reviewerへ渡します。Taskに目的を書く必要はありません。該当節が無いrepoは「未記録」として扱います。

## Tests FAIL → Reviewer投入

- Testsが2回FAIL（`reviewer_trigger_fails`、既定2）するまでReviewerを呼びません。FAIL #1 はMainが原因分析して自己修正します。
- FAIL #2 以降、およびReviewerが一度でも投入された後のFAILは、Reviewerが**失敗分析（原因・修正指示）**を返し、その内容がOrchestrator内部で自動的にMainの修復promptへ入ります。
- **Tests PASSだけでは完成にしません。** PASS後は必ずReviewerが最終レビューします。Reviewer FAILならMain修正 → **Tests再実行** → 再レビュー。修正後にPASS / レビューPASSを使い回しません（完成時にTests・レビュー・現在のdiff fingerprintの一致を検証）。
- Reviewerへ渡す情報: 元Task、受入条件（Taskの「受入条件/Acceptance」節）、base、変更ファイル一覧、diff stat / diff、Tests結果、Main作業概要、過去のTests FAILとfailure fingerprint、repair履歴、運用契約、対象repoの`AGENTS.md` / `OPERATING_CONTRACT.md`。
- Reviewer出力は1つのJSON（`verdict: PASS|FAIL|NEEDS_HUMAN`、`findings[]`（severity / category / file / problem / evidence / instruction）、`root_cause`、`instructions_for_main`、`needs_human_reason`）。曖昧な回答は拒否します: blocker / major付きのPASS、Tests FAIL中のPASS、指示の無いFAIL、理由の無いNEEDS_HUMAN。不正なら1回だけ再依頼し、なお不正なら `REVIEW_UNPARSABLE`。

## 状態機械

`created → preflight → implementing → testing → (repairing → testing)* / reviewing → finalizing → completed`。任意の実行中stageから `needs_human` / `failed` / `stopping → stopped`。終端は `completed / needs_human / stopped / failed`（遷移不可）。不正遷移は `ILLEGAL_TRANSITION`。

run記録（`run.json`）: run ID、repo、Task、Main / Reviewer、stage、Tests実行 / FAIL / 連続FAIL回数、failure fingerprintと出現回数、repair iteration、Main / Reviewer call数、review履歴・repair履歴・failure履歴、provider error・quota error、worktree、candidate、apply状態、worker（PID・作成時刻token）、開始 / heartbeat / 終了時刻、final result。

## 上限（`runstate.Limits`。CLIの `--max-repair-iterations` 等で変更可、runへ保存）

| 項目 | 既定 | 超えた場合 |
|---|---|---|
| `reviewer_trigger_fails` | 2 | （Reviewer投入のtrigger） |
| `max_repair_iterations` | 12 | `MAX_REPAIR_ITERATIONS` |
| `max_same_failure` | 3 | 同一failure fingerprint → `SAME_FAILURE_REPEATED` |
| `max_same_review` | 3 | 同一指摘の繰り返し → `REVIEW_LOOP` |
| `max_no_change_repairs` | 2 | 差分が変わらない修正が連続 → `NO_PROGRESS` |
| `max_review_rounds` | 4 | `MAX_REVIEW_ROUNDS`（Reviewerの判定回数。旧既定12） |
| `max_review_calls` | 8 | `REVIEW_BUDGET`（受入基準作成・形式不正の再依頼を含む全Reviewer呼出し。次の呼出しの**前**に停止） |
| `max_review_tokens` | 1,000,000 | `REVIEW_BUDGET`（Reviewer累計トークン＝入力＋出力。0で無制限。呼出し間で判定） |
| `max_main_tokens` | 0（無制限） | `MAIN_BUDGET`（Main累計トークン。Claude: 入力＋cache作成＋出力、cache読取は除外 / Codex: 入力＋出力） |
| `max_provider_retries` | 2 | transientのみ（下記） |
| `max_runtime_minutes` | 360 | `MAX_RUNTIME` |
| `agent_timeout` / `review_timeout` / `test_timeout` | 1800 / 1200 / 600秒 | process tree終了後、providerは `PROVIDER_ERROR`、Testsは失敗（`HANG`） |

**Tests runner問題**: 終了コード0でも出力が `Ran 0 tests` / `NO TESTS RAN` / `collected 0 items` / `no tests ran` ならFAIL（`TEST RUNNER: 0 tests ran...` の診断行を付与）。0 tests、またはランナー起動不能（`is not recognized...`、`python: No module named <runner>`、`command not found`）は `failure_history[].runner_problem` に記録します。1回目はMainへ「discoveryを壊したなら直す。コマンド自体の問題ならテストを動かさず `IMPLEMENTATION_STATUS: BLOCKED`」と伝えて1回だけ修正させ、**連続2回目は Reviewer・追加repairを呼ばず `TEST_RUNNER_PROBLEM` で `needs_human`**（同一failureの無駄なAI呼出しを防ぐ）。

failure fingerprintは、所要時間・時刻・temp path・アドレス・行番号を正規化し、失敗したtest名とエラー文で同一性を判断します（iteration数だけでは「同じ問題の繰り返し」を判断しません）。すべての上限は `needs_human` で終了し、無限loopはありません。

## provider異常・quota

- quota / credit / rate limitはretryしません（`PROVIDER_QUOTA`、`quota_errors`へ記録）。auth異常は `PROVIDER_AUTH`。それ以外の異常は `PROVIDER_ERROR`（`provider_errors`へ記録）。
- 再試行するのは一時的な障害（overloaded、接続断、Claudeの`another Claude Code process is refreshing` OAuth更新競合など）だけで、最大 `max_provider_retries` 回・段階待機付き。
- 二重process・同時編集・context不整合・役割崩壊の恐れがあるため、**自動provider切替は行いません**（fail-close）。`providers.py`の役割抽象が将来の安全なhandoffの拠り所です。usageの残量だけを理由にMain / Reviewerを切り替えたり止めたりしません。

## 残量表示（usage）

account / plan枠と、session / callのcontextは**別概念**として保存・表示します（混在させません）。取得できた値だけ表示し、無い値は「取得不能」、古い値は `last known`（`FRESH_SECONDS`=180秒超）。推測値は出しません。usage取得の失敗・遅延でrunは止まらず、認証情報・トークン・アカウントIDはキャッシュへ保存しません（`%LOCALAPPDATA%/ShizenDev/AIOrchestrator/usage/*.json`）。

| 項目 | Claude Code 2.1.x | Codex CLI 0.155.x |
|---|---|---|
| 取得方法 | `claude -p --output-format stream-json --verbose` の `rate_limit_event`（実呼出し中にだけ出る。無料の問合せは無い） | `codex app-server --stdio` のJSON-RPC `account/rateLimits/read`（トークン消費なし） |
| 利用枠 / 週間枠 | ○（`unifiedWindows.five_hour / seven_day.utilization`。0〜1の割合として扱い%表示） | ○（`primary` / `secondary` の `usedPercent`、`windowDurationMins`） |
| reset時刻 | ○（`resetsAt`） | ○（`resetsAt`） |
| credit残高 | **取得不能**（overage状態のみ。残高は出ない） | ○（`credits.balance` / `hasCredits` / `unlimited`） |
| plan | 取得不能（`claude auth status`は認証情報にplan名を含むが、機微情報を保存しないため未使用） | ○（`planType`） |
| context使用量 | ○（直近assistantのusage合計 / `modelUsage.contextWindow`） | 使用tokenは○（`turn.completed.usage`）。windowは `codex debug models` の `context_window × effective_context_window_percent` と設定modelから算出。modelを特定できない場合はwindow「取得不能」 |
| 更新の仕方 | runの実呼出しごとに自動反映。「残量更新」で最小の1回呼出し（`MIN_PROBE_INTERVAL`=600秒で抑制） | 画面を開いた時・run開始時・「残量更新」で取得（45秒で抑制） |

残量が少ない場合（残り15%未満）は「Main AIの利用可能量が少ないため、長時間Taskを完走できない可能性があります」等の警告のみ表示します。

## process lifecycle と再接続

- `start_run` はrun単位の**独立worker**（`python -m tools.ai_orchestrator.orchestrator worker --run-dir ...`）を、コンソール無し・stdio共有無し・可能ならJob Object外（`CREATE_BREAKAWAY_FROM_JOB`）で起動します。DCCのTkinterやstdout pipeへrunの寿命は依存しません。
- 画面の×は画面を閉じるだけ、DCC終了はclient終了だけでrunは継続。停止は明示的な「AI安全停止」のみ。
- 生存判定: **PIDだけで判断しません。** `worker.pid` + プロセス作成時刻token + `heartbeat.json`（5秒毎、30秒で失効）を突き合わせ、`running`（同一processで新鮮）/ `unresponsive`（processは在るがheartbeat途絶＝「接続不能・状態確認が必要」。実行中と断定せず、二重起動も許可しない）/ `lost`（workerが確実に不在）/ `finished` / `starting` を区別。
- `lost`は自動整理: そのrunが登録した子processだけ（PID+作成時刻で検証）を終了し、`failed / WORKER_LOST` を記録してrepoロックを解放します（worktreeは保存）。
- 二重起動防止: repo単位のロックファイル。他repoのrunや通常操作（RUN / BUILD / UPDATE）はロックしません。
- DCC起動時に実行中runを検出して操作ログ・ボタン（「AI Orchestrator ● 実行中 N」）へ表示。Orchestrator画面は同じrunへ再接続し、repo・Main / Reviewer・stage・Tests回数・FAIL回数・開始時刻・usage・ログ・AI安全停止を復元します。
- AI安全停止: `control.json`で依頼 → workerが自分のprocess tree（Claude / Codex / Tests）を終了し `stopped`（`stopped_by_user`、停止時のstage、process終了結果）を記録。応答が無ければ、workerのPID+作成時刻を検証したうえでworker treeと登録済み子processだけを強制終了。名前による一括killはしません。

## 開始時のsource repo準備（DCCから開始した場合）

DCCは `prepare_source=True`（CLIは `--prepare-source`）で開始します。repoロック取得後、次を自動で行います。

1. Git repositoryであること（`NOT_A_GIT_REPO`）、merge / rebase / cherry-pick等が進行中でないこと（`SOURCE_OPERATION_IN_PROGRESS`）、detachedでないこと（`SOURCE_DETACHED`）を確認。
2. tracked fileに未コミット変更があれば**何も変更せず停止**（`SOURCE_DIRTY`、変更ファイルを表示）。untracked fileは従来通り対象外（branch切替で上書きになる場合はgit自身が拒否し `SOURCE_SWITCH_FAILED`）。
3. `origin/<管理branch>` をfetchし、local branchとの関係を判定。ahead（`SOURCE_AHEAD`）・diverged（`SOURCE_DIVERGED`）は**branch切替前に停止**。merge / reset / rebaseはしない。
4. 管理branch以外にいれば `git switch <branch>`（元のbranchは削除しない）、behindなら `git merge --ff-only`（= `pull --ff-only`）。
5. その後、従来の `repo_baseline`（clean・branch一致・HEAD == origin）で改めて検証。

stash / reset --hard / force checkout / branch削除は行いません。行った操作は `run.json` の `source_preparation` と `events.log`（`[source]`）へ記録します。同じrepoのrunが動作中ならロックで拒否され、sourceは動かしません。

## 既定Testsとコマンドの解釈

- repo別の既定Testsは `scripts/dev_control_center_repos.toml` の `[initial_tests]`。Orchestrator画面でrepoを選ぶと自動入力され、編集できます（編集内容はrepo別draftとして保持）。設定値はDCCの推測コマンド（`suggest_test_command`）より優先。未設定repoだけ推測値を使います。`--test` 必須・`--allow-no-tests` は明示例外のまま。
- **repo-local venv**: source repoに `.venv\Scripts\python.exe`（POSIXは `.venv/bin/python`）があれば、独立Testsのprocessに限りその `Scripts` / `bin` をPATHの先頭へ置き `VIRTUAL_ENV` を設定します。Testsコマンドは書き換えず、`python` / `pytest` がrepoのvenvへ解決されます。cwdはisolated worktreeのままなので、テストされるのはworktree側のコードです（`.venv` はgit管理外でworktreeに存在せず、コピーもしません）。venvが無いrepoは従来通りPATH上のPython。Main / Reviewer AIの環境には影響しません。使用したvenvはTests出力の `(repo-local venv first on PATH: ...)` に表示されます。next-day-setupの既定Testsは正式runnerに合わせ `python -m pytest -q`（pytestはrepoの `.venv` に導入済み）。
- Testsコマンドは**POSIX shell（Git Bash等）での意味**を基準にします。Windowsでは `cmd.exe /d /s /c` で実行するため、cmdがquoteとして扱わない `'...'` だけを等価な `"..."` へ変換します（`-p 'test_*.py'` → `-p "test_*.py"`）。double quote内の `'`、未対応の `'`、`%`、`\"`、`'...'` 内の `"` を含む場合は意味を保証できないため**変換せずそのまま**実行します。それ以外の文字は変更しません。変換した場合はTests出力に `(executed by cmd.exe as: ...)` を表示します。

## source repoとの競合

Orchestratorはisolated detached worktreeで動作し、開始時にsourceのclean / branch / origin同期を確認します。実行中にsource側で通常Development（commit / 編集）が進んでも、通常Developmentを禁止せず、runも失敗させません。成果物は `apply_status`（`ready` / `held_base_moved` / `held_source_dirty`）で表示されます。完了runのcandidateはDCCの「Orchestrator candidate フロー」（RUN_DEV → 承認 → push → BUILD → UPDATE、同一SHA）で扱い、Orchestrator画面の「DCCで実機確認へ（RUN_DEV）」はそのrepoをDCCで選択するだけです。source branchへの反映は承認後のpush工程（fast-forwardのみ、base移動なら停止）だけで行います。詳細は [DCC仕様](dev_control_center.md#orchestrator-candidateフロー)。

## 安全境界（Orchestrator専用ハーネス。通常Developmentへ強制しない）

isolated worktree、agentのcommit / branch付替え検出（Main呼出し・Tests・完了前に毎回）、childのpush無効化（`GIT_CONFIG_*`）、API billing環境変数の拒否（`--allow-api-billing`で明示許可）、Tests前後のdiff不変確認、`__pycache__` / `.pyc`のdiff・candidate除外と `PYTHONDONTWRITEBYTECODE`、candidate commitはworktree内のbranch（push無し）、worktreeは完成時のみ削除（それ以外は調査用に保存）。

## ログ・保存先

`%LOCALAPPDATA%/ShizenDev/AIOrchestrator/runs/<run-id>/`: `run.json` / `heartbeat.json` / `control.json` / `events.log` / `task.md` / `worker.out` / `calls/`（各provider呼出しの生出力・Main要約）/ `tests/`（Tests出力）。`AI_ORCHESTRATOR_STATE_ROOT`で変更可。

- すべて**BOM無しUTF-8**です。Windows PowerShell 5.1の `Get-Content` は既定でBOM無しファイルをCP932として読むため文字化けして見えます（ファイル自体は正常）。直接読む場合は `Get-Content -Encoding UTF8` を使ってください。通常はDCCの「ログをコピー」を使います。
- DCC Orchestrator画面の選択中runに「ログをコピー」（`runstate.run_report`: run id・repo・stage / final_result・source_preparation・candidate・task・tests・回数・failure / repair / review history・provider / quota error・events.log・worker.out・最新Tests出力を1つのテキストでClipboardへ。無いファイルは省略、長いログは末尾を採用）と「runフォルダを開く」があります。
- worktreeは `<temp>/ai-orch-<repo>-<run-id>-*/<repo名>` です。checkout directory名からrepo名を導くテスト（例: next-day-setupのSYNC契約テスト）がsourceと同じ結果になるよう、repoと同じ名前にしています。

### 子process出力のencoding

子processへは `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` を渡してUTF-8出力に統一します（git、Claude CLI / Codex CLI（node）は元々UTF-8）。ただしWindowsのconsole program（cmd.exe自身のメッセージ、taskkill、icacls、pipeへ書くWindows PowerShell 5.1）はconsoleの無い状態でOEM code page（日本語WindowsではCP932）で出力し、UTF-8へ切り替えられません。同じpipeに両方が混在するため、`common.decode_output` は**行単位で** UTF-8 → OEM code page の順にdecodeし、どちらでも読めないbyteだけを置換します（reader threadは例外で止まりません）。DCCのRUN / BUILD / UPDATE出力（`processes.stream`）も同じ `OutputDecoder` を使います。出力を使わない `taskkill` はDEVNULLへ捨てます。`events.log` の画面表示は行境界でだけ読み進め、UTF-8文字を途中で切りません。

## Main AIとOrchestratorの責務

Main AIに見えるのはbase commitのdetached worktreeだけです。source repoの準備（branch切替・origin同期）、独立Tests、repair / review回数、candidate作成・適用状態はOrchestratorが自分で保証し `run.json` / `events.log` へ記録し、DCCの「source準備」欄とログコピーに表示します。これらをMain AIへ確認させるTaskは書かないでください（Main用promptでも「Orchestratorが記録する事実は確認しようとせず、blockingとしない」と明示しています）。

## 実装Taskとverification-only Task

- Orchestratorは**実装Task専用**です。完成は「差分あり + Tests PASS + Reviewer PASS + 安全チェックPASS → candidate」だけで、差分が無ければ `NO_CHANGES`（`needs_human`）、Mainが人間判断を要すると報告すれば `TASK_BLOCKED` で、candidate readyにはなりません（変更なしで成功扱いにする経路はありません）。
- 「実機確認のみ・コード変更不要」のTaskはOrchestratorへ渡さず、DCC（source準備はrun記録で確認）・通常DevelopmentのTests実行で確認します。Orchestratorの動作確認は、小さな実装Task（例: 文書1行の追加）で行うとcandidateまで確認できます。
- 将来verification-onlyを正式対応する場合は、candidateを作らない**別の終端stage**（例: `verified`）とし、AIを呼ばず独立Testsだけを実行する形を想定します（`completed` / candidate readyとは混同させない）。現時点では未実装です。

## 旧Final Review JSON

`review_pending` / `request_id` / `--resume-review` / decision JSON中継は**廃止**しました（標準フローがOrchestrator内部で完結するため）。

## テスト

標準ライブラリのunittest。providerとworktreeはfake、Git・process・状態機械は実物: `test_ai_orchestrator_engine.py`（ループ・上限・provider異常）、`test_ai_orchestrator_providers_usage.py`（実出力形式のparse・usage表示）、`test_ai_orchestrator_host.py`（実Git・start検証・安全境界）、`test_ai_orchestrator_lifecycle.py`（**実際の独立workerプロセス**: client消滅後の継続、再接続、二重起動拒否、stale、安全停止のtree限定）、`test_dev_control_center_orchestrator_view.py`（画面・monitor）。実Claude / Codex疎通はmockテストと別に手動で確認し、結果は [Phase 2検証記録](development-orchestrator-phase2.md) に記載します。
