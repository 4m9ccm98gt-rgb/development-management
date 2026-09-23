# AI Operating Manual

この文書はDevelopment運用の補助資料です。**正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)** であり、本書は上書きしません。

## 1. 基本方針

実装・設定変更の開始点は、常にDCCの **AI依頼** 欄です。通常アプリも `development-management` 自身も新規repo登録も同じ経路です。

```text
GPTがAI依頼を整理
→ DCC AI依頼欄 → AI開発開始
→ Claude実装
→ Tests
→ Final Review Gate
→ 明示的失敗時だけClaude diagnosis → repair → 再Verification
→ local candidate
→ RUN_DEV実機確認
→ OK後に同じSHAをpush
→ BUILD
→ UPDATE / DEPLOY
```

GPTはユーザーの意図・要望・優先順位・受入条件をAI依頼へ整理する役割で、標準運用ではGitHub上のコード・設定を直接編集しません。GitHub / PR / CIは観測情報として扱います。

## 2. Claudeの役割

Claudeは隔離worktree内で実装・修正を担当します。

- source repoへ直接commitしない
- branchを変更しない
- pushしない
- BUILD / UPDATE / DEPLOYしない
- 指定タスクの範囲を最小限に保つ
- `acceptEdits` + `--allowedTools` で許可された検査・テスト系Bashだけを使う（`bypassPermissions` は使わない）
- 明示的な失敗があればRecovery diagnosis → repair → 再Verificationへ進む

## 3. RecoveryとFinal Review

失敗時だけClaude diagnosis / repairを呼び、独立Verificationへ戻します。
Final Reviewはprovider非依存の外部Gateで、PASSした成果物だけcandidateにします。
未接続時はreview_pending。Astraを通常経路の必須providerにしません。
詳細はOPERATING_CONTRACT.mdを参照します。

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
- Final Review PASS
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

現在の標準構成は **Claude実装 + 独立Verification + Final Review Gate** です。

2026-09-19の同一smoke taskでは、ユーザー観測でClaude 1% / Codex(Astra) 1%の利用表示でした。これは固定コスト保証ではなく、役割反転前より軽い傾向を確認した実測です。

## 9. 記録

Gitへ残すのは将来の判断に必要な情報だけです。

- 長期的な設計・運用判断
- 再発防止に価値があるLessons Learned
- 現在の未解決課題
- 必要なcandidate / release情報

進行状況の重複転記は避けます。
