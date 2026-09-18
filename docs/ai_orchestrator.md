# AI Development Orchestrator v0.1

Codexを実装担当、Claude Codeを独立レビュー担当としてローカルWindows開発を反復し、**ローカルcandidate commitで停止**する開発支援ツールです。

DCCとはまだ統合しません。v0.1では単体で安全性と反復動作を確認します。

## フロー

```text
ユーザーの開発依頼
  ↓
source repoの安全確認
  ↓
一時 detached Git worktree
  ↓
Codex: 実装
  ↓
自動テスト
  ↓
Claude: read-onlyレビュー
  ↓
変更要求あり ─→ Codex修正 ─→ 再テスト ─→ Claude再レビュー
  ↓ APPROVE
originが作業中に進んでいないことを再確認
  ↓
local ai-candidate/... branch + candidate commit
  ↓
STOP
  ↓
ユーザー実機確認
```

push / BUILD / UPDATE / DEPLOYはOrchestratorの責務外です。

## 必要なもの

Windows PC上で以下がコマンドとして利用可能で、各CLIが認証済みであること。

- Git
- Codex CLI
- Claude Code CLI
- 対象repoがoriginのexpected branchと同期済みであること

まず確認:

```powershell
python -m tools.ai_orchestrator.orchestrator doctor
```

## 実行例

```powershell
python -m tools.ai_orchestrator.orchestrator run `
  --repo "C:\\Users\\suisy\\Documents\\Development\\repos\\development-management" `
  --expected-branch main `
  --task "DCCの○○を修正し、回帰テストを追加する" `
  --test "python -m unittest discover -s tests -p \"test_dev_control_center*.py\" -v"
```

長い依頼はUTF-8ファイルでも渡せます。

```powershell
python -m tools.ai_orchestrator.orchestrator run `
  --repo "C:\\path\\to\\repo" `
  --task-file "C:\\path\\to\\task.md" `
  --expected-branch main `
  --test "python -m pytest -q"
```

`--test` は複数回指定できます。

## 安全境界

### source repo

開始前に以下を確認します。

- Git repoである
- detachedではない
- `--expected-branch` と一致
- tracked clean
- `git fetch origin` 後、`HEAD == origin/<branch>`

Codex / Claudeはsource working treeではなく、一時的なdetached worktreeで動きます。

AI処理の各段階でsource repoのbranch / HEAD / tracked cleanが変化していないことを再確認します。

candidate作成直前にはoriginを再fetchし、開始時のorigin SHAから進んでいたら停止します。

### Codex

Codexは `codex exec --ephemeral --sandbox workspace-write` で隔離worktree内だけを編集します。

プロンプト契約で以下を禁止します。

- commit / branch操作 / reset / rebase
- push / PR / merge
- BUILD / UPDATE / DEPLOY / release
- 共有フォルダ・業務データ・本番データ・秘密情報の操作

さらにchild processの一時Git設定で `remote.origin.pushurl=disabled://ai-orchestrator` を上書きし、通常の `git push origin ...` を失敗させます。repo設定自体は変更しません。

Codexがcommitやbranch切替を行ったことを検出した場合はfail-closeします。

### Claude

Claude Codeは非対話 `-p` + JSON出力 + `--permission-mode plan` でレビューします。

レビュー結果は次のどちらかだけです。

- `approve`
- `changes_requested`

`approve`なのにfindingsがある等、矛盾した結果はfail-closeします。

### tests

通常は最低1個の `--test` が必須です。

テストを意図的に実行できない場合だけ `--allow-no-tests` が使えます。ただしcandidate品質の根拠が弱くなるため例外運用です。

### candidate

Claude APPROVE + tests PASS後だけ、隔離worktreeから

```text
ai-candidate/<run-id>-<task>
```

という**ローカルbranch**を作成しcandidate commitを作ります。

pushはしません。

成功後、隔離worktreeは削除しcandidate branchだけ残します。

失敗した場合は診断用に隔離worktreeを残します。

## ログ

Windowsでは通常:

```text
%LOCALAPPDATA%\\ShizenDev\\AIOrchestrator\\runs\\<run-id>\\
```

に以下を保存します。

- task
- Codex prompt/output
- tests
- Claude prompt/raw JSON
- parsed review
- result.json

repo内にはログを保存しません。

## v0.1でやらないこと

- DCC UIへの統合
- 自動push
- 自動merge
- BUILD
- UPDATE / DEPLOY
- 本番反映
- 自動実機確認
- Claude/Codexの判断だけでproduction gateを越えること

v0.1の実機確認後に、DCCからこのOrchestratorを起動しcandidate SHAを受け取る統合を検討します。
