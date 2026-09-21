# Operating Contract

この文書は、Development運用で常時適用する最小契約です。

目的は、**DCCを中心にAI開発を高速に回しつつ、実機確認・candidate SHA・BUILD対象の一致を崩さないこと**です。

## 1. 単一の開発ルート

実装・設定変更の開始点は、**常にDCC（Development Control Center）の「AI依頼」欄**です。
対象は通常アプリ、`development-management` 自身、新規repo登録のすべてで、別の開発開始経路はありません。

```text
ユーザーの要望
→ GPTが意図・優先順位・受入条件をAI依頼へ整理
→ DCCで対象repoを選び、AI依頼欄 + テスト欄へ入力
→ 「AI開発開始」
→ Claudeが隔離worktreeで実装
→ 独立Tests
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

### GPTの役割

- GPTはユーザーの意図・要望・優先順位・受入条件を、DCCのAI依頼として貼れる形へ整理する。
- 標準運用ではGitHub上のコード・設定を直接編集しない。
- AI依頼にはrepo名、目的、受入条件、触れてはいけない範囲、独立テストコマンドを含める。

### 管理対象

- `development-management` はDCCのManaged Repositoriesへ登録済みで、通常repoと同じAI Orchestrator対象。RUN_DEVは `RUN_DEV.cmd`（DCC起動）。
- 変更は `scripts/repo_types.toml`（種別）と `scripts/dev_control_center_repos.toml`（`[branches]` / `[initial_ai_tasks]` / `[initial_tests]`）が正。

### 新規repo登録

1. DCCの「GitHub未登録repo」で対象を選び「セットアップ開始」を押す。
2. 正式ローカルへのcloneを確認する（既存ファイルは上書きしない）。
3. DCCが `development-management` を自動選択し、AI依頼欄へrepo登録タスクをセットする。
4. 内容を確認して「AI開発開始」。Claude → Tests → Astraで `development-management` を変更する。
5. local candidateの確認・反映・DCC更新後、新repoを選ぶと `initial_ai_tasks` / `initial_tests` が自動入力される。

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

AI Orchestrator v0.4 HOLの標準役割は次です。

- 実装・修正: Claude
- 自動テスト: 対象repoの独立テストコマンド
- 独立レビュー: GPT-6 Astra / read-only
- 最大ラウンド: 30（進捗がある限り自動継続。candidate完成または真に人間判断が必要な停滞まで人間へ返さない）
- 作業場所: source repoではなく一時detached worktree
- 完了点: local candidate
- 自動では行わないもの: push / BUILD / UPDATE / DEPLOY
- Claudeの権限: `--permission-mode acceptEdits` + `--allowedTools` で許可した検査・テスト・interpreter系Bashのみ（`bypassPermissions` / `--dangerously-skip-permissions` は使わない）。agent側のgit pushは無効化し、git履歴を変える操作は許可しない
- Claude実装の `--max-turns` は80。max-turns到達は即失敗扱いにせず、途中worktreeをTests / Astraで評価して継続する

Orchestratorはsource repoのbranch / HEAD / tracked clean / originを開始時とcandidate作成前に再確認し、agentによるcommit・branch変更やreview後の未レビュー差分をfail-closeします。

### Human-on-the-loop 自動ループ

正式進行は次の順序とする。

```text
User request
↓
GPT
症状・目的・期待結果・制約・受入条件をTaskSpec化
原因・修正方法は推測で確定しない
ユーザーの提案/気付きは、明示要件でない限りoptional observationとして分離
↓
Claude: INVESTIGATE / DESIGN（read-only）
実repo・コード・テスト・契約を調査し、根拠付きで原因と設計を作る
↓
Astra: DESIGN REVIEW（read-only）
調査根拠・誤診・別原因・安全性・regression・過剰設計を独立レビュー
↓
Claude: DESIGN JUDGMENT（read-only）
ACCEPT / DISPUTE / NEEDS_CLARIFICATION をfindingごとに判断
↓
Astra: RECONSIDERATION（read-only）
WITHDRAW / MODIFY / UPHOLD
↓
必要ならClaudeが追加調査・設計改訂
↓
設計承認
↓
Claude IMPLEMENTATION
↓
Tests
↓
Astra implementation review
↓
Claude judgment
↓
必要ならAstra reconsideration / Claude repair
↓
candidate
```

- 調査/設計stageではコード変更を禁止し、diff fingerprint不変をOrchestratorが検証する。
- GPTは原因や実装修正を症状から推測で確定しない。
- 「調査して直して」は正式な1タスクとして扱う。
- Claude = Implementer / Technical Owner。調査・設計・実装・技術判断を担当する。
- Astra = Independent Reviewer。調査設計と実装の両方を独立に疑う。
- Orchestrator = Moderator / State Machine。設計議論、実装、Tests、review、retryを管理する。
- Astraのfindingは即実装命令ではなく、まずClaudeが技術判断する。
- Claudeの反論はAstraが再評価する。
- 設計段階で残ったfindingは設計改訂へ戻し、承認された設計だけ実装へ進む。
- Tests FAIL / HANG時はClaude自己診断とAstra独立診断を別々に取得し、両診断とraw test logをClaudeへ渡して修正する。
- 実装reviewで議論後も残ったfindingだけをBLOCKING_REPAIR_REQUESTとしてClaudeへ渡す。
- 大きなdiffは自動分割reviewし、単純なdiff size超過だけで人間へ返さない。
- Testsは進捗をstdoutへ流し、10秒heartbeatを表示する。timeout/hang時はprocess treeを終了し、通常のtest failure診断ループへ移る。
- parser揺れ（approved / approve等）は安全に正規化する。provider/protocol failureは同じstage内でretryする。
- 最大30roundは調査設計と実装を合わせた総予算とする。
- 通常運用ではユーザーがClaude / Tests / Astraのループを手動仲介しない。


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
- `README.md` / `AI_OPERATING_MANUAL.md` / `AI_CHECKLIST.md` / `AGENTS.md` / `AI_STARTUP.md` / `STARTUP_HANDOFF_POLICY.md` は正本と整合する補助資料です。
- `AGENT_EFFICIENCY_POLICY.md` は旧T0〜T3運用のLegacy Referenceです。
- 詳細文書と本書が競合する場合は本書を優先します。

運用の安全性は、工程数ではなく、**candidate SHA、独立テスト、独立レビュー、ユーザー実機確認、confirmed/pushed/BUILD SHA一致**で担保します。
