# Operating Contract

この文書は、Development運用で常時適用する最小契約です。

目的は、**DCCを中心にAI開発を高速に回しつつ、実機確認・candidate SHA・BUILD対象の一致を崩さないこと**です。

## 1. 標準ルート

通常アプリの開発は Development Control Center の **AI開発** を使います。

実装工程の基本役割は次のとおりです。

- ユーザー: 目的・違和感・優先順位・実機結果を伝える。細かいAI間の受け渡しは担当しない。
- ChatGPT: ユーザー意見を抽出し、Claudeへ渡す開発タスク・受入条件へ変換する。通常アプリの実装担当にはならない。
- Claude: 隔離worktreeで実装・修正する。
- 独立テスト: 機械的に検証する。
- GPT-6 Astra: read-onlyで独立レビューする。

```text
ユーザーの要望 / RUN_DEVフィードバック
→ ChatGPTが意図・優先順位・受入条件を抽出
→ DCC AI依頼へ変換
→ Claudeが隔離worktreeで実装
→ 独立テスト
→ GPT-6 Astraがread-onlyレビュー
→ 必要ならClaudeが修正
→ local candidate commit
→ DCCがcandidate SHAを取得
→ ユーザー確認後だけlocal expected branchへfast-forward
→ RUN_DEVでユーザー実機確認
→ OKなら同じSHAを正式push
→ confirmed SHA == pushed SHA を確認
→ BUILD
→ UPDATE / DEPLOY
```

通常アプリでは、GitHubだけでChatGPTが実装してcandidateを作る旧A-path、およびユーザーが手動でCodex / Claude間の受け渡しを行う旧Bデバッグ入口は標準運用ではありません。

### 新規repoセットアップ

新規repoは「管理登録だけ」で止めず、**初回AI開発へ接続できる状態**までをセットアップとします。

```text
GitHubでrepo作成
→ DCC「セットアップ開始」
→ 正式ローカルへclone
→ ChatGPTへセットアップ依頼
→ ChatGPTがrepo種別 / expected branch / 初期デモの意図・受入条件を整理
→ development-managementへ管理登録
→ initial_ai_tasks / initial_tests を登録
→ Control Center更新
→ DCCが初期AI依頼・テストを自動入力
→ ユーザーは対象repoで「AI開発開始」
→ Claude実装
→ Tests
→ Astraレビュー
→ local candidate
→ RUN_DEVでユーザーが実物を確認
```

新規repoセットアップ時のChatGPTは、対象アプリ本体、RUN_DEV、BUILD、UPDATE / DEPLOY、テストコードを実装・完成検証しません。実装判断とコード作成はClaude、独立レビューはAstraへ渡します。

新規repo登録だけの定型変更（`scripts/repo_types.toml`、`scripts/dev_control_center_repos.toml`、管理一覧、初期AI依頼/テスト登録）は設定登録として扱い、**ユーザーへCodex / Claudeの手動レビュー操作を要求しません**。Development本体の実行コード・安全境界・運用契約を変更する場合は、下記のDevelopment更新ルートを使います。

### development-management の更新

`development-management` も通常repoと同じAI Orchestratorを使います。管理基盤だからという理由でChatGPT実装・手動Codex/Claudeレビューへ分岐しません。

```text
ユーザー要望
→ ChatGPTが意図・受入条件を整理
→ DCCで development-management を選択
→ Claudeが隔離worktreeで実装
→ Developmentの独立テスト
→ GPT-6 Astraがread-onlyレビュー
→ 必要ならClaude修正
→ local candidate
→ ユーザー確認後だけlocal mainへfast-forward
→ 必要な実機確認
→ OKなら同じSHAを正式push
→ Control Center更新
```

- Development自身も実装担当はClaude、独立reviewerはAstraです。
- ChatGPTは仕様化・意見抽出・宣言的なrepo登録を担当し、Developmentの実行コード変更を直接実装しません。
- 新規repoの定型登録だけ（repo種別、expected branch、初期AI依頼、初期テスト等）は宣言的設定変更としてChatGPTが行えます。
- ユーザーへCodex / Claudeの手動受け渡しを要求しません。
- 自己更新でもsource repo不変、tracked clean、origin同期、candidate SHA固定、fast-forwardだけの安全条件は変えません。

## 2. 絶対に残す安全条件

- ユーザー実機確認前に本番配布しない。
- 実機確認でNGになったcandidateを本番へ進めない。
- candidateは完全40桁SHAで特定する。
- 最終的に **confirmed SHA == pushed SHA == BUILD対象SHA** を成立させる。
- candidate確認開始時と正式BUILD時はtracked cleanを確認する。
- 本番データ、秘密情報、ローカル設定、共有先、Git管理外業務データを不用意に変更しない。
- force push / reset --hard / stash / 無断rebase等で既存作業や承認済みSHAを壊さない。
- remoteが想定外に進んだ場合はforceで押し切らず停止する。

### 手動PowerShell貼り付け

- ユーザーへ複数行PowerShellを貼り付け実行してもらう場合、状態変更・外部影響・長時間処理を伴う重要コマンド（例: Claude / Codex起動、`git pull` / merge / push、sync、BUILD、deploy）をコードブロックの最終行に置かない。
- PowerShellでは貼り付け末尾の改行が無いと最終行だけ未実行のまま残る場合がある。非対話コマンドで、stdinがパイプ等により明示されている場合だけ、重要処理の後ろに `Write-Host "DONE"` 等の無害な末尾行を置く。末尾行自身がEnter待ちで未実行になるのは許容し、その `DONE` 表示を重要処理の完了判定には使わない。
- Claude / Codex等を対話モードで起動する場合は、後続の貼り付け行を子プロセスが入力として受け取る可能性があるため、同じ複数行貼り付けブロックへ混在させない。準備行を先に実行し、対話起動は別の単独コマンドとして明示する。
- Developmentの手動レビューでは、可能な限り `$prompt | claude.cmd -p ...` や `$prompt | codex.cmd exec ... -` のような非対話モードを使い、重要な開始行を最終行にしない。
- この規則は手動貼り付け用PowerShellにだけ適用する。AI Orchestratorは `claude.cmd` / `codex.cmd` を子プロセスとして直接起動するため、このEnter待ち対策のためにOrchestrator本体を変更しない。

## 3. AI Orchestrator

AI Orchestrator v0.2の標準役割は次です。

- 実装・修正: Claude
- 自動テスト: 対象repoの独立テストコマンド
- 独立レビュー: GPT-6 Astra / read-only
- 最大ラウンド: 2
- 作業場所: source repoではなく一時detached worktree
- 完了点: local candidate
- 自動では行わないもの: push / BUILD / UPDATE / DEPLOY

Orchestratorはsource repoのbranch / HEAD / tracked clean / originを開始時とcandidate作成前に再確認し、agentによるcommit・branch変更やreview後の未レビュー差分をfail-closeします。

## 4. DCCでのcandidate受け渡し

- DCCはOrchestratorのmachine-readable resultからcandidate SHAを取得する。
- console文字列のスクレイピングをcandidate確定根拠にしない。
- candidateを正式ローカルbranchへ反映する前にユーザー確認を挟む。
- local fast-forward時はbase SHA、current HEAD、branch、origin、tracked clean、candidate ancestryを再確認する。
- fast-forwardできない場合は自動修復せず停止する。
- candidate反映後はRUN_DEVで実機確認する。

## 5. 実機確認 / push / BUILD

- RUN_DEVで業務上の正しさ、GUI、印刷、LAN、外部サービス等を必要範囲で確認する。
- 実機確認OK後にcandidate SHAを変更しない。
- pushはfast-forward前提とし、push後にremote SHA == confirmed SHAを確認する。
- 正式BUILD前にHEAD == confirmed SHAかつtracked cleanを確認する。
- Nuitka / PyInstaller / .NET/WPF等、BUILDで配布実体が変わる場合は完成binaryも配布前に確認する。
- ソース実行確認と配布binary確認を同一視しない。

## 6. GitHub / CIの位置づけ

- GitHub / PR / CI表示は観測・同期・SHA確認のために使う。
- GitHub Actionsは補助検証であり、Actions greenだけを実機確認の代わりにしない。
- 同じ決定的テストを、理由なくローカルとActionsで重複実行しない。
- 実プリンター、実共有サーバー、live外部接続、実HDD等は必要なときだけ実機確認する。

## 7. 読み込み・判断コスト

- T0〜T3の必須分類は使用しない。
- 新しいチャットという理由だけで全Development文書を読み直さない。
- 通常は本書、対象repoのREADME、変更箇所と直接のconsumer / producerだけを読む。
- 毎ターンcontractを再報告しない。
- 大きなスコープ変更、不可逆操作、本番影響が新たに必要になった場合だけ追加判断を求める。

## 8. 他文書との関係

- 本書がDevelopment運用の正本です。
- `AI_OPERATING_MANUAL.md` / `AI_CHECKLIST.md` / `AGENTS.md` / `AI_STARTUP.md` は補助資料です。
- `AGENT_EFFICIENCY_POLICY.md` は旧T0〜T3運用のLegacy Referenceです。
- 詳細文書と本書が競合する場合は本書を優先します。

運用の安全性は、工程数ではなく、**candidate SHA、独立テスト、独立レビュー、ユーザー実機確認、confirmed/pushed/BUILD SHA一致**で担保します。
