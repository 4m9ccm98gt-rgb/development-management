# Operating Contract

Development運用の正本。通常Development、DCC、AI Orchestratorの責務を分離します。

## 通常Development（Phase 1）

GPT相談・要件整理・設計・指示文作成 → Claude / Codexが正式ローカルrepoで直接実装 → Tests → DCC RUN → ユーザー実機確認 → BUILD → UPDATE。
Claude / Codexは用途・利用可能量・ユーザー判断で選択します。GPTは必要に応じてコード・ログ・設計をレビューします。GPTによるGitHub直接編集とPC同期、credit削減目的の編集・同期を標準ルートにしません。GitHubの観測・調査は可能です。

通常DevelopmentはDCCやOrchestratorを経由せず開始できます。AI依頼、isolated worktree、local candidate、Final Review Gate、review_pending、decision JSONの中継、request_id、Recovery fingerprint、confirmed SHAによるhandoffは通常開発の必須条件ではありません。

## DCCメイン

repo選択、RUN、BUILD、UPDATE、AI Orchestrator別画面への入口を提供します。GitHub状態は観測情報です。AI詳細は別画面へ置きます。

| 操作 | 条件 |
|---|---|
| RUN | 正式repo / originと正式RUN入口を確認。現在の作業ツリーを実行。candidate、tracked clean、GitHub取得成功、candidateとHEADの一致は不要 |
| BUILD | 正式repo / BUILD入口を確認。dirtyな作業内容も対象。設定・依存関係とデータ保護は各repoの既存build処理が検証。DCCは同じ出力先のBUILD / UPDATE競合を防止し、入力変化を検出した成果物をUPDATE可能にしない |
| UPDATE | 明示的なユーザー操作のみ。BUILD記録、成果物hash、配布先、更新処理を確認し、確認後の変化を実行直前に再検証。未確認・不一致なら停止 |

BUILD記録はrepo、base HEAD、dirty / clean、日時、build ID、成果物パスとSHA-256、入力fingerprint、終了結果をローカルへ保存します。秘密情報の内容は保存しません。HEADだけでdirty成果物を特定しません。対象・入力範囲・既存アプリ側の制約は [DCC仕様](docs/dev_control_center.md) を参照します。

## 共通の安全条件

- 既存ユーザー作業、本番データ、秘密情報、ローカル設定、Git管理外業務データを保護する。
- force push、reset --hard、stash、rebaseを無断実行しない。commit / push / タグ作成は明示指示がある場合のみ。
- テスト可能な変更ではTestsを実施し、未実施の検証を確認済みと書かない。
- 実機確認前に本番配布しない。BUILDで実体が変わる場合は完成成果物も確認する。
- AI判断による自動UPDATE / DEPLOYは禁止。操作は自動連続しない。
- 通常操作とOrchestratorは別の実行状態を持つ。同じrepoの競合は停止できるが、AI異常やレビュー待ちを理由にDCC全体をロックしない。

## AI Orchestrator（任意の正式な第二ルート）

DCC → 別画面のAI Orchestrator → 独立run worker。長時間・無人でAI開発を完成まで進める自動運転モードです。通常Developmentの必須経路ではありません。詳細は [Orchestrator仕様](docs/ai_orchestrator.md)。

Phase 2の標準フロー: Main AI（既定Claude）が実装 → 独立Tests。Tests FAIL #1はMain自身が修正、FAIL #2からReviewer AI（既定Codex、読み取り専用）が失敗分析してMainへ自動で修正指示。Tests PASS後は必ずReviewerが最終レビューし、修正後は必ずTestsを再実行する。完成条件は **Tests PASS + Reviewer PASS + 安全チェックPASS**（同一diff）。Main / ReviewerはClaude / Codexから選択でき、同一providerは選択不可。レビュー結果・decision JSONを人間が中継する操作は標準フローに存在しない。

人間へ返す（`needs_human`）のは、完成、安全上継続不可、provider利用不能（quota / 認証 / 異常）、Task自体に人間判断が必要、上限到達（repair iteration・同一failure・同一指摘・進展なし・最大時間）、process / worktreeを信頼できない場合だけ。quotaは再試行せず、providerの自動切替もしない。usage（残量）は補助表示で、run停止・provider切替の根拠にしない。

runはrun単位の独立workerが所有し、DCCとOrchestrator画面は監視・操作するclientにすぎない。画面を閉じる・DCCを閉じる・DCCを再起動してもrunは継続し、再起動後に検出・再接続して進捗・ログ・usageを再表示する。停止は明示的な「AI安全停止」だけで、そのrunが所有するprocess treeだけを終了する（名前による一括killは禁止）。実行中判定はPIDだけで行わず、run ID・process作成時刻・heartbeatで確認し、確認できなければ「接続不能・状態確認が必要」とする。

Orchestrator内部の安全ハーネス（isolated detached worktree、source保護、agentのcommit / push / deploy / source main直接変更の禁止、Tests前後のdiff確認、failure履歴、run記録、process tree管理）はOrchestrator専用で、通常Developmentへ強制しない。Orchestratorの実行中・失敗・quota・crash・stale・usage取得失敗で、通常Developmentや他repoのRUN / BUILD / UPDATEをロックしない（同一repoでOrchestratorが起動中の二重起動だけを防ぐ）。実行中にsource側へ通常Developmentの変更が入った場合は開発を止めず、成果物の適用を保留してbase再確認後にだけ適用する。成功時もpush / BUILD / UPDATEは行わず、local candidateの適用はユーザー確認後のfast-forwardのみ。

Phase 3以降の課題: 安全なquota handoff（現在は常にfail-close）。

## 新規repo・初回準備

「セットアップ開始」は既存のclone確認を維持し、登録指示を別画面へ表示します。指示をClaude / Codexへ渡して正式repoで直接実装できます。Orchestratorの使用は任意です。登録定義は scripts/repo_types.toml と scripts/dev_control_center_repos.toml を使用します。

## 文書の読み方

通常は本書、対象README、変更箇所と直接のconsumer / producer、安全上必要な文書だけを読みます。補助文書は本書を上書きしません。重要判断と必要な検証結果を記録し、同じ説明を大量に重複しません。

### 手動PowerShell貼り付け

- ユーザーへ複数行PowerShellを貼り付け実行してもらう場合、状態変更・外部影響・長時間処理を伴う重要コマンド（例: Claude / Codex起動、`git pull` / merge / push、sync、BUILD、deploy）をコードブロックの最終行に置かない。
- PowerShellでは貼り付け末尾の改行が無いと最終行だけ未実行のまま残る場合がある。非対話コマンドで、stdinがパイプ等により明示されている場合だけ、重要処理の後ろに `Write-Host "DONE"` 等の無害な末尾行を置く。末尾行自身がEnter待ちで未実行になるのは許容し、その `DONE` 表示を重要処理の完了判定には使わない。
- Claude / Codex等を対話モードで起動する場合は、後続の貼り付け行を子プロセスが入力として受け取る可能性があるため、同じ複数行貼り付けブロックへ混在させない。準備行を先に実行し、対話起動は別の単独コマンドとして明示する。
- Developmentの手動レビューでは、可能な限り `$prompt | claude.cmd -p ...` や `$prompt | codex.cmd exec ... -` のような非対話モードを使い、重要な開始行を最終行にしない。
- この規則は手動貼り付け用PowerShellにだけ適用する。AI Orchestratorは `claude.cmd` / `codex.cmd` を子プロセスとして直接起動するため、このEnter待ち対策のためにOrchestrator本体を変更しない。

DCCのRUN / BUILD / UPDATEは非対話の処理本体をバックグラウンド実行し、コンソールを前面表示せず、出力と終了コードをDCCへ返します。手動CMDのpauseには依存せず、UI応答を維持します。実行中は同じrepo・出力先の競合を止めます。接続契約は [DCC仕様](docs/dev_control_center.md) を参照してください。
