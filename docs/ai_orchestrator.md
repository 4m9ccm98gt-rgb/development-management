# AI Development Orchestrator v0.3

Claude Codeを実装担当、Codex / GPT-6 Astraを独立レビュー担当としてローカルWindows開発を反復し、**ローカルcandidate commitで停止**する開発支援ツールです。v0.3では `development-management` に限り、Claude自身のplan-mode read-onlyレビューも追加して二重レビューにします。

v0.1の最小スモークテストでは1ラウンドでCodex側7%減、Claude側1%利用だったため、v0.2では役割を反転しています。

## フロー

```text
依頼
  ↓
billing guard / source repo安全確認
  ↓
一時 detached Git worktree
  ↓
Claude: 実装
  ↓
自動テスト
  ↓
Codex / GPT-6 Astra: read-onlyレビュー
  ↓
変更要求あり → Claude修正 → 再テスト → Astra再レビュー
  ↓ APPROVE
local ai-candidate/... branch + candidate commit
  ↓
STOP
```

通常上限は2ラウンドです。push / BUILD / UPDATE / DEPLOYは自動実行しません。

## 進捗表示

v0.3は無言で処理せず、現在の段階とClaude/Codex呼び出し回数を表示します。

```text
[Preflight] Checking CLI tools and billing guard...
[Round 1/2] Claude implementing... (Claude calls: 1, Codex calls: 0)
[Round 1/2] Running automated tests...
[Round 1/2] Tests: PASS
[Round 1/2] Codex/Astra reviewing with gpt-6-astra (read-only)...
[Round 1/2] Codex/Astra: APPROVE
AI ORCHESTRATOR: CANDIDATE READY
```

`status.json` にstage、round、Claude/Codex呼び出し回数も保存します。

## Billing guard

デフォルトでは `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、Claude CodeのBedrock / Vertex / Foundry切替環境変数が有効な場合に停止します。

意図してAPI/第三者課金を使う場合だけ `--allow-api-billing` で解除できます。

## 実行例

```powershell
python C:\Users\suisy\Documents\Development\repos\development-management\tools\ai_orchestrator\orchestrator.py run `
  --repo "C:\path\to\repo" `
  --expected-branch main `
  --task "DCCの○○を修正し、回帰テストを追加する" `
  --test "python -m pytest -q"
```

デフォルトは Claude実装、`gpt-6-astra` レビュー、最大2ラウンドです。レビューmodelは `--review-model` で変更できます。

## 安全境界

- source repoは開始時にbranch / tracked clean / origin同期を確認
- AI編集は一時detached worktreeだけ
- Claudeのcommit / branch操作を検出したら停止
- child Gitのpush URLを無効化
- Codex/Astraはread-only sandbox
- Astraレビュー前後でdiff fingerprintが変わったら停止
- candidate直前にoriginが進んでいないか再確認
- Tests PASS + 必要reviewer全員APPROVE後だけlocal candidateを作成
- push / BUILD / UPDATE / DEPLOYは行わない

## ログ

Windowsでは通常 `%LOCALAPPDATA%\ShizenDev\AIOrchestrator\runs\<run-id>\` に、Claude出力、tests、各reviewer結果、status.json、result.jsonを保存します。

## v0.3でやらないこと

- DCC UI統合
- 自動push / merge
- BUILD
- UPDATE / DEPLOY
- 本番反映
- AI判断だけでproduction gateを越えること

v0.2のスモークテストで役割反転後の利用量を測定し、v0.1と比較してからDCC統合へ進みます。


## DCC integration

Development Control Centerからv0.3を直接起動できます。

1. 対象repoを選択
2. 「AI依頼」を入力
3. DCCが提案したテストコマンドを確認・必要なら編集
4. 「AI開発開始」
5. DCCの操作ログへOrchestrator進捗を表示
6. candidate成功時、DCCが `--result-file` のJSONから完全40桁SHAを取得
7. ユーザー確認後だけlocal expected branchへ `git merge --ff-only` 相当の安全なfast-forward
8. RUN_DEVで実機確認

local fast-forwardは開始時base SHA、current HEAD、branch、origin repo、tracked clean、candidate ancestryを再検証します。source HEADが途中で動いた場合やcandidateがbaseの子孫でない場合は停止します。

DCC統合でもpush / BUILD / UPDATE / DEPLOYは自動実行しません。
