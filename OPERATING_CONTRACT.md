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
→ PASSならprovider非依存のFinal Review Gate
→ FAIL / HANG / ERROR / BLOCKEDならClaude diagnosis → repair → 再Verification
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
4. 内容を確認して「AI開発開始」。Claude → Verification → Final Review Gateで `development-management` を変更する。
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

AI Orchestrator v0.6は、正常時を直線、明示的な失敗時だけRecovery Loopとする。

```text
TK × Work: 共同設計・TaskSpec確定
↓
DCC: TaskSpec受け渡し、安全な実行・状態管理
↓
Claude MAIN IMPLEMENTATION
↓
独立Tests / 機械的Verification
├─ PASS → Final Review Gate → PASS → local candidate
└─ FAIL / HANG / implementation ERROR / BLOCKED
   ↓
   Claude diagnosis（read-only）→ Claude repair → 独立Verification
   ├─ PASS → Final Review Gate
   └─ FAIL → 新しい結果・履歴を材料にRecovery継続

Final Reviewの明示的FAILもRecoveryへ戻す。
Final Review未接続 / PENDINGはreview_pendingで停止し、candidateを作らない。
```

- 一発成功時はRecovery 0回。Astra調査設計・mandatory review・固定外側ループを呼ばない。Codex CLIも実行の必須依存ではない。
- MAIN IMPLEMENTATION、Recovery diagnosis、Recovery repairは別の役割・prompt。diagnosisはRead / Glob / Grepのみで、MCP・shell・編集・sub-agentを使用しない。前後の差分不変も検証する。
- 大きなタスクという理由でmulti-agentを起動しない。必要時に診断視点を追加できる境界だけを持つ。Work実接続・別provider追加は今回行わない。
- Recoveryは失敗結果、直前の差分、TaskSpec、過去iterationを参照する。失敗・原因仮説・修正fingerprintとログ・Verification結果・進展判定をrun_dirへ永続化する。
- 同じ失敗と同じ修正状態が再出現した場合、または同じ失敗のまま修正状態が変わらない場合は `RECOVERY_NO_PROGRESS` で停止。時間・heartbeatの変化だけを進展と扱わない。
- `--max-rounds` はRecoveryだけの上限（0〜30、既定30）。通常実装やFinal Reviewは消費しない。上限で `RECOVERY_LIMIT`、candidateを生成・適用しない。
- 既存の12turn上限と、空diffでturn上限到達時だけ同一sessionを最大2回resumeする仕組みは維持する。これは失敗したimplementationの継続であり、成功時に追加callしない。
- quota枯渇、診断provider異常、Git安全境界違反、worktree改ざん・source変化はfail-close。安全違反をAI修正対象にしない。Final Review decisionファイルだけの誤り（下記）は例外で、`review_pending` を維持する。
- Testsはstdout進捗・10秒heartbeat・timeoutのprocess tree停止を維持する。provider timeoutも子process tree終了後にRecoveryへ渡す。

### Final Review Gate

特定AI providerに固定しない外部interfaceとする。`final-review-request.json` にTaskSpec、base SHA、差分、Verification結果、run_id、Recovery回数とrequest_idを記録する。

外部reviewerは同じrequest_idに対する `PASS / FAIL / PENDING` と根拠summaryを返す。未接続時にTests PASSをReview PASSへ読み替えない。WorkによるTaskSpec照合は将来この境界へ接続する。

今回の外部連携はJSONファイル方式。`--resume-review <run_dir> --final-review-decision <file>` と同じrepo / TaskSpec / test / max-roundsでレビュー待ちrunを継続できる。sourceと差分が変わっていないことを再検証し、既存のVerificationを利用する。PASSなら既存candidateハーネスへ進み、FAILならClaude Recoveryへ戻る。修正後は新しいReview要求を発行し、古い承認・否認を再利用しない。

decisionファイルが読み取り不能、request_id不一致、または不正なverdict / 空summaryの場合は、worktree・差分・Verificationに問題がないため `stopped` にせず `review_pending` を維持し、candidateも作らない。`result.json` の `final_review_error`（`resumable: true`、期待する `request_id`）と `status.json` のdetailから、正しいdecisionを指定して `--resume-review` を再実行すれば継続できることが分かる。worktree変化・source変化・quota超過・`RECOVERY_NO_PROGRESS` 等のfail-closeは従来通り。DCCへのWork自動接続とレビュー操作UIは対象外。

### 維持する安全ハーネス

- 一時isolated detached worktree。source repoのbranch / HEAD / tracked clean / originを開始時とcandidate作成前に確認する。
- agentによるcommit / branch変更禁止、child Git push URL無効化。Claudeの `acceptEdits` と限定Bash許可を維持し、permission bypassを使用しない。
- VerificationとReview前後の差分整合、candidate完全40桁SHA、local candidate方式を維持する。
- DCC「AI安全停止」はrun_dir捕捉後だけ可能。OrchestratorとClaude/Codex等の子process treeを停止し、status.json / result.jsonへSTOPPED（保存値 `stopped`）、`error_code = USER_SAFETY_STOP` を永続化する。
- 安全停止ではrun_id / worktree / stage / round / Recovery履歴を保持し、isolated worktree / run logを残す。source mainを変更せず、candidateを適用しない。
- 自動push / BUILD / UPDATE / DEPLOY、force push / reset --hard / stash / 無断rebaseは行わない。実機確認前の本番配布禁止とconfirmed / pushed / BUILD SHA一致は従来通り。

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
