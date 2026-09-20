# AI Operating Manual

この文書はDevelopment運用の補助資料です。**正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)** であり、本書は上書きしません。

## 1. 基本方針

通常アプリの日常開発は Development Control Center の **AI開発** を標準とします。

実装・設定変更はrepo種別に関係なくDCCのAI依頼欄から開始します。ChatGPTによるGitHub直接編集を標準経路にせず、Claude → Tests → Astraへ統一します。

`development-management` 自身も同じAI Orchestratorを使い、例外ルートへ分けません。

```text
AI依頼
→ Claude実装
→ Tests
→ GPT-6 Astra read-onlyレビュー
→ 必要ならClaude修正
→ local candidate
→ RUN_DEV実機確認
→ OK後に同じSHAをpush
→ BUILD
→ UPDATE / DEPLOY
```

旧A/Bルートは通常UIから外し、GitHub / PR / CIは観測情報として扱います。

### development-management

Development自身もDCCで対象repoとして選択し、Claude実装 → Tests → Astra read-onlyレビュー → local candidateを使います。

- ChatGPTは要望・受入条件の整理を担当し、実行コードを直接実装しない。
- ユーザーへCodex / Claudeの手動レビュー操作を要求しない。
- source main / origin / tracked cleanを開始前後で確認する。
- candidate後のlocal main反映はfast-forwardだけに限定する。
- Control Center更新も確認済みcandidate SHAを維持する。

## 2. Claudeの役割

Claudeは隔離worktree内で実装・修正を担当します。

- source repoへ直接commitしない
- branchを変更しない
- pushしない
- BUILD / UPDATE / DEPLOYしない
- 指定タスクの範囲を最小限に保つ
- テスト失敗またはAstra指摘があれば修正する

## 3. Astraの役割

GPT-6 Astraは独立reviewerです。

- read-only
- 実装agentと役割を分離する
- diff / task / test resultを確認する
- structured JSONでapprove / changes_requestedを返す
- approveとfindingが同居する矛盾出力はfail-close
- review後にworktree差分が変わった場合はcandidate化しない

## 4. テスト

- DCCのテスト欄に対象repoの独立テストコマンドを指定する。
- DCCはrepo構成から保守的な候補を提案できるが、必要ならユーザーが編集する。
- 原則としてテスト必須。意図的な例外だけ `--allow-no-tests` を使う。
- targeted / regression / integration等は変更内容に応じて選ぶ。
- 同じ内容を安心のためだけに重複実行しない。

## 5. candidate

candidate作成前に以下を満たします。

- source repoのbranch / HEAD / originが開始時から変わっていない
- source repoがtracked clean
- agentがcommit / branch変更していない
- tests pass
- Astra approve
- review対象diffとcandidate作成前diffが一致

candidateはlocal branch + 完全40桁SHAで識別します。

## 6. DCCへの受け渡し

Orchestratorは `--result-file` でmachine-readable JSONを書き、DCCはそこからcandidate SHAとusage countを受け取ります。

candidate成功後も自動では正式branchへ反映しません。DCCがユーザー確認を出し、YESの場合だけ安全条件を再確認してlocal expected branchへfast-forwardします。

## 7. 実機確認後

- RUN_DEVで実機確認する。
- NGなら同じSHAを本番へ進めない。
- OK後にcandidate SHAをamend / rebase / squashしない。
- pushはfast-forward前提。
- pushed SHA == confirmed SHAを確認する。
- BUILD前にHEAD == confirmed SHAかつtracked cleanを確認する。
- UPDATE / DEPLOYは最後に行う。

## 8. 使用量と役割分担

現在の標準構成は **Claude実装 + Astraレビュー** です。

2026-09-19の同一smoke taskでは、ユーザー観測でClaude 1% / Codex(Astra) 1%の利用表示でした。これは固定コスト保証ではなく、役割反転前より軽い傾向を確認した実測です。

## 9. 記録

Gitへ残すのは将来の判断に必要な情報だけです。

- 長期的な設計・運用判断
- 再発防止に価値があるLessons Learned
- 現在の未解決課題
- 必要なcandidate / release情報

進行状況の重複転記は避けます。
