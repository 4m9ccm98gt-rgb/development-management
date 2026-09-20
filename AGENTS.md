# development-management AI入口ガイド

このリポジトリでは、開発運用の正本を [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) とします。

## 標準役割

- ユーザー: 目的・違和感・優先順位・実機結果を伝える。
- ChatGPT: ユーザー意見を抽出し、AI依頼・受入条件へ整理する。実行コードの通常実装担当にはならない。
- Claude: AI Orchestratorの隔離worktreeで実装・修正する。
- Tests: 独立テストコマンドで機械検証する。
- GPT-6 Astra: read-onlyの独立reviewer。
- DCC: task / test / candidate / local fast-forward / RUN_DEVへの受け渡しを管理する。

`development-management` 自身もこの標準ルートを使います。ChatGPT実装 + 手動Codex/Claudeレビューへ分岐しません。

## 新しいチャットでの開始

1. `OPERATING_CONTRACT.md` を読む。
2. 対象repoのREADMEと今回の変更に直接関係する箇所だけ読む。
3. ユーザーの要望をClaude向けAI依頼と受入条件へ整理する。
4. 実装が必要ならDCC / AI Orchestratorへ渡す。

新規repoセットアップでも開始点はDCCのAI依頼欄です。ChatGPTはrepo種別・初期デモ要件・受入条件をAI依頼へ整理し、中央registryの変更も対象アプリ本体の実装もClaude → Tests → Astraへ渡します。ChatGPTがGitHub上のコード・設定を直接編集する例外は作りません。

## 常に守ること

- ユーザーへAI間の手動受け渡しを要求しない。
- 実機確認前に本番配布しない。
- NG candidateを本番へ進めない。
- candidateは完全40桁SHAで扱う。
- confirmed SHA == pushed SHA == BUILD対象SHA を守る。
- candidate確認開始時と正式BUILD時はtracked cleanを確認する。
- force push、履歴破壊、無断rebaseを行わない。
- 本番データ、秘密情報、ローカル設定、Git管理外業務データを保護する。
- 実行していないテストを確認済みと扱わない。
- BUILDで実体が変わるアプリは完成binaryも配布前に確認する。

## 補助文書

`AI_STARTUP.md` / `AI_OPERATING_MANUAL.md` / `AI_CHECKLIST.md` / `STARTUP_HANDOFF_POLICY.md` は補助資料です。競合時は必ず `OPERATING_CONTRACT.md` を優先します。
