# Orchestrator Phase 2 検証記録（2026-09-25）

仕様は [ai_orchestrator.md](ai_orchestrator.md)、判断は [decisions.md](decisions.md)。commit / push・実配布・UPDATEは行っていません。

## 自動テスト

`python -B -m unittest discover -s tests` — **304件成功**（Phase 1の通常Development / RUN / BUILD / UPDATE / DCC選択・非同期・hover回帰テストを含む。旧Orchestratorの内部実装に固定されていたテスト約70件は、廃止した外部Final Review・Recovery・DCC子プロセス方式とともに削除し、新方式のテストへ置換）。providerはfake、Git・process・状態機械・Tkは実物。

| ファイル | 内容 |
|---|---|
| `test_ai_orchestrator_engine.py`（36） | Claude→Codex / Codex→Claude、FAIL#1自己修正、FAIL#2でReviewer、指摘のMain自動受渡し、repair後の再Tests、PASS後の必須最終レビュー、Reviewer FAIL→修復loop、完成条件、同一failure・最大iteration・進展なし・レビューloop・最大時間の停止、quota非retry、transientのみ有界retry、provider異常保存、Reviewerの書込検知、call数 / Tests回数 / failure履歴 |
| `test_ai_orchestrator_providers_usage.py`（26） | 実出力形式のClaude stream-json / Codex JSONLのparse・エラー分類、役割検証、usage表示（取得成功・取得不能は推測なし・last known・account / context分離・throttle・警告・秘密非保存） |
| `test_ai_orchestrator_host.py`（22） | start検証（既定Claude/Codex・保存・同一provider拒否・dirty / 未push / API課金env / 二重起動）、実Gitでcandidate・source不変、sourceが進んだ時の適用保留、agentのcommit検知、Tests hangのtree終了、stop、bytecode除外、Windows ACL正規化 |
| `test_ai_orchestrator_lifecycle.py`（11） | **実際の独立workerプロセス**: client消滅後の継続、再起動後の検出と二重起動拒否、dead / PID再利用 / heartbeat途絶（unresponsive）/ 自動整理、安全停止が当該run tree（子・孫・worker）だけを終了し無関係pythonは生存、非協調workerの強制停止、他repoは無影響 |
| `test_dev_control_center_orchestrator_view.py`（24） | 画面のroles・start引数、usage表示、run状態、停止確認、閉じてもrun不変、monitor |

## 実provider疎通（実Claude Code 2.1.278 / Codex CLI 0.155.1、使い捨てGit repo）

| # | 構成 | 結果 |
|---|---|---|
| 1 | Claude Main → Codex Reviewer（小さな追加タスク） | Tests PASS → Codex最終レビューPASS → candidate作成（約30秒）。source HEAD・作業ツリー無変化、pushなし |
| 2 | Claude Main → Codex Reviewer（Testsが順に3件の隠れた要件を報告） | FAIL#1 → Main自己修正、FAIL#2 → **Codexが失敗分析**（Reviewer投入）→ 指示がMainへ自動受渡し → Tests PASS → Codex最終レビューPASS。Main 3 / Reviewer 2 call、Tests 3回 |
| 3 | **Codex Main → Claude Reviewer** | 完成（Main 2 / Reviewer 1）。Windows sandboxのCodexが作ったファイルが独立Testsから読めず1回FAIL → Codex自身がACLを修復して復旧。以後の実装でMain呼出し後にACL正規化を追加 |
| 4 | DCC相当のclientがrunを開始し、直後に強制終了（`os._exit`） | worker（別process）は `running / implementing` のまま継続 |
| 5 | 実DCC Appを再起動 | 10秒以内に実行中runを検出しボタン「AI Orchestrator ● 実行中 1」と操作ログへ表示。画面を開くと同runを自動選択し、Main / Reviewer・stage・Tests / call回数・usage・停止ボタンを復元。同repoの二重起動は `ActiveRunExists` で拒否 |
| 6 | 画面から「AI安全停止」 | `stopped / USER_SAFETY_STOP`。ClaudeのCLI子processとworkerが終了。実行前後のpython / node / claude / codex processの一覧は、当該runの分を除き無変化（無関係processは停止していない） |

初回実行では、Tests実行が生成した `__pycache__`（fixtureに.gitignore無し）を「Tests中のworktree変化」と検知して `SAFETY_VIOLATION` で停止した（fail-closedは期待どおり）。`PYTHONDONTWRITEBYTECODE` の設定とbytecode cacheのdiff / candidate除外を追加して解消。

## usageで実際に取得できた項目

| 項目 | Claude | Codex |
|---|---|---|
| 5時間枠 使用率 / 残り | ○（`rate_limit_event`。Desktopアプリの値と整合: 5時間 27→34%、週間 4→5%、reset時刻一致） | ○（`account/rateLimits/read`: 73%→98%使用 等、実測） |
| 週間枠 | ○ | ○（7日枠） |
| reset時刻 | ○ | ○ |
| credit残高 | **取得不能**（overageの有効 / 無効のみでprovider CLIは残高を返さない） | ○（`balance`、実測「0」） |
| plan | 表示しない（`claude auth status`は取得可だが認証情報を扱うため未使用） | ○（`plus`） |
| context使用量（call単位） | ○（37,734 / 1,000,000 token を実呼出しで取得） | ○（17,441 / 258,400。window=`codex debug models`の値×effective%、設定modelから特定） |

Claudeの利用枠は無料の問合せ手段がなく、実呼出し中にだけ届く。そのためrun中は自動反映、それ以外は「残量更新」（最小1回呼出し、600秒throttle）または last known 表示。Claude Code自体のstatusline用JSON（`rate_limits`）は対話UI専用で、非対話 `-p` からは取得できない。

## 未検証事項

- **実providerのquota枯渇時の実メッセージ**: 判定は既知の文言（`hit your limit` / `usage limit` / `credit balance is too low` 等）の単体テストのみ。Codexの残量が実測で2%まで下がったため、実際に枯渇させる確認は避けた。
- 数時間単位の実放置運転、Windows再起動をまたぐ運用、DCC以外（タスクスケジューラ等）からのworker起動。
- 大規模repo（worktree作成やACL正規化の所要時間）、`unresponsive`状態の実機再現（heartbeat threadの停止）。実機ではPID+作成時刻+heartbeatの判定を単体・実processテストで確認。
- Claude Main + Claude Reviewer等の同一provider構成（仕様上、通常は選択不可）。
- DCC画面上でのAIによるTask入力から開始までの手操作（開始処理自体は画面コード経由でテストと実行済みだが、実マウス操作は未実施）。
- `CREATE_BREAKAWAY_FROM_JOB` が許可されないJob環境ではJob外起動にフォールバックする（その場合DCCのJobが終了されるとworkerも終了し得る）。今回の環境では継続を確認。

## 残るリスク

- Claude / Codexの出力形式（`rate_limit_event`、`app-server` JSON-RPC等）はCLI更新で変わり得る。usageは補助情報のため、変化してもrunは止まらず「取得不能」表示になる。
- Codex sandboxの権限モデル（Windows ACL）はCLIの版に依存。最悪でも独立Testsが失敗し、repair回数を消費して人間へ返る。
- usageの残量が少ないrunは途中でquotaに達し得る。その場合は `PROVIDER_QUOTA` で停止し、自動切替はしない。
- 完成後のworktreeは削除し、それ以外（needs_human / stopped / failed）は調査用に保持する。手動整理が必要（`git worktree remove`）。
