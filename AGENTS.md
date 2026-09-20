# development-management AI入口ガイド

開発運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 単一路線

実装・設定変更の開始点は、常にDCCの「AI依頼」欄です。通常repo、`development-management` 自身、新規repo登録で経路は同じです。

```text
AI依頼 → Claude実装 → 独立Tests → GPT-6 Astra read-only review → local candidate
```

- GPTの役割は、ユーザーの意図・要望・優先順位・受入条件をAI依頼へ整理することです。標準運用ではGitHub上のコード・設定を直接編集しません。
- 実装・修正はDCCのOrchestratorが起動するClaudeが隔離worktreeで行います。
- ユーザーが特定エージェントを名指ししても、開発開始経路は増やしません。
- 新規repoはDCCの「セットアップ開始」から `development-management` のAI依頼欄へ登録タスクをセットし、同じ経路で登録します。

## 常に守ること

- 実機確認前に本番配布しない。
- NG candidateを本番へ進めない。
- confirmed SHA == pushed SHA == BUILD対象SHA を守る。
- candidate確認開始時と正式BUILD時は tracked clean を確認する。
- force push、履歴破壊、無断rebaseを行わない。
- 本番データ、秘密情報、ローカル設定、Git管理外業務データを保護する。
- 実行していないテストを確認済みと扱わない。
- BUILDで実体が変わるアプリは完成binaryも配布前に確認する。

## 読み込み方針

- 新しいチャットという理由だけで長文書一式を読みません。
- 対象README、変更箇所、関連consumer / producer、安全上必要な文書だけを読みます。
- `AGENT_EFFICIENCY_POLICY.md` は旧運用のLegacy Referenceで、必須ではありません。
- 補助資料は `OPERATING_CONTRACT.md` を上書きしません。

## 手動PowerShell提示

- 複数行PowerShellでは、状態変更・外部影響・長時間処理を伴う重要コマンドを最終行にしません。
- 非対話コマンドでは無害な末尾行を使えますが、対話型CLIは同じ貼り付けブロックへ混在させません。
- 詳細条件と例外は `OPERATING_CONTRACT.md` の「手動PowerShell貼り付け」を正とします。AI Orchestratorの直接プロセス起動には適用しません。
