# AI Development Orchestrator v0.6 — Recovery

運用の正本は [OPERATING_CONTRACT.md](../OPERATING_CONTRACT.md)。DCCのAI依頼欄から起動し、local candidateまでで停止する。

## 通常経路

TaskSpec → Claude MAIN IMPLEMENTATION → 独立Tests / Verification → Final Review Gate → PASSならlocal candidate。

一発成功ならClaude実装1回、Recovery 0回、Codex/Astra 0回。Astra調査設計とmandatory reviewは呼ばない。CLIの `--review-model` は旧呼出元の互換用で、providerを起動しない。

## Recovery

Tests FAIL / HANG、implementation ERROR / BLOCKED、明示的Final Review FAIL時だけ開始する。

Claude diagnosis（read-only）→ Claude repair → 独立Verification。成功後はFinal Review Gateへ戻る。

- `--max-rounds`: Recovery上限0〜30、既定30。通常実装はround 0。
- `--agent-timeout`: provider呼出し上限。timeout時はprocess tree終了後に失敗を扱う。
- `--test-timeout`: test commandごとの上限、既定600秒。10秒heartbeatとHANG/TIMEOUT診断を維持。
- Claude実装のmax-turnsは12。空diffのturn上限到達時だけ同一sessionを最大2回resumeする既存処理を維持。
- diagnosisは別call・別promptでRead / Glob / Grepのみ許可。MCP・shell・編集・sub-agentは無効。差分不変も確認する。
- `result.json.recovery_history`: iteration、failure、diagnosis、repair fingerprint / log、verification、progressを保存。履歴は次の診断・修正へ渡す。
- 同じ失敗・同じ修正状態の再出現、または無変更で同じ失敗が継続した場合は `RECOVERY_NO_PROGRESS`。上限は `RECOVERY_LIMIT`。どちらもcandidateなし。
- quota枯渇や安全境界違反はRecovery対象にせず停止。

## Final Review interface

Workは未接続。特定AIによる固定reviewは実行しない。

`run_dir/final-review-request.json` に次を記録する。

- schema_version / run_id / base_sha
- task（TaskSpec全文）/ diff / verification結果
- recovery_iterations / request_id（上記内容のSHA-256）

未接続時は `review_pending` でworktreeを保持し、追加AI callを行わない。DCCは「FINAL REVIEW待ち」と表示し、candidate適用へ進まない。

外部reviewerは、TaskSpecと成果物を照合後、次のJSONをrun_dirやworktreeの外に保存する。

```json
{"request_id": "要求に含まれる完全request_id", "verdict": "PASS", "summary": "照合結果の根拠"}
```

verdictは `PASS / FAIL / PENDING`。未設定、未知の値、空summary、request_id不一致、読み取り不能なdecisionはcandidateを作らない。ただしこれはdecisionファイルだけの誤りなので `stopped` にせず `review_pending` を維持し、`final_review_error`（`resumable: true`、期待する `request_id`、再実行を促す詳細）を `result.json` に、同じ詳細を `status.json` のdetailに記録する。正しいdecisionで `--resume-review` を再実行すれば継続できる。worktree変化・source変化・quota超過等の安全違反は従来通りfail-closeで `stopped`。

既存の `run` 引数（repo / TaskSpec / test / max-rounds）に `--resume-review <run_dir> --final-review-decision <JSONのパス>` を加えるとレビュー待ちrunを継続する。これは新規実装を開始する経路ではなく、保存済みGateの継続用interface。source branch / HEAD、TaskSpec、test commands、予算、worktree差分の一致を要求する。保存済みVerificationを利用するため、承認継続だけではAIもTestsも再実行しない。PASSならcandidate、FAILならRecoveryへ戻る。修正後は新しい要求を生成し、再承認まで停止する。

Work自動接続とDCCレビュー操作UIは今回の対象外。将来のadapterは同じrequest / verdict契約を使う。

## 安全境界とログ

- source branch / HEAD / origin / tracked clean確認、isolated detached worktree、agentによるGit履歴変更検出、child push無効化を維持。
- Verification / Final Reviewが確認した差分とcandidateの整合を確認。
- DCC「AI安全停止」、run_dir捕捉後だけ停止可能、子process tree終了、STOPPED永続化は既存経路を維持。
- 停止時は `error_code=USER_SAFETY_STOP` とrun_id / worktree / stage / round / Recovery履歴を保持。source main非変更、candidate非適用。
- `%LOCALAPPDATA%/ShizenDev/AIOrchestrator/runs/<run-id>` にTaskSpec、Claude出力、診断・修正prompt、test logs、Review request、status.json / result.jsonを保存。
- candidateは完全40桁SHA。適用はDCCの既存ユーザー確認と安全なfast-forwardで行う。
- push / BUILD / UPDATE / DEPLOY、実機確認前の本番反映は行わない。

## 回帰検証

標準ライブラリのunittestを使用する。providerはmock化し、実行回数とstage遷移を検証する。実Gitのcandidate/source保護とDCCのprocess-tree停止テストも含む。実Claude / Work接続のE2Eをmockテストと同一視しない。
