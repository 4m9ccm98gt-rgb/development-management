# development-management

`development-management` は、AIと人が共同開発するための共通ルール・設計判断・運用知識を管理するリポジトリです。

## 最初に読むもの

開発運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

新しいチャットだからという理由だけで、管理文書一式を読みません。

通常は次だけで開始します。

1. [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)
2. 対象repoのREADMEまたは今回に直接関係する説明
3. 変更対象コードと必要な関連箇所

詳細が必要な場合だけ、次を参照します。

- [AGENTS.md](AGENTS.md) — AI向け短い入口ガイド
- [AI_STARTUP.md](AI_STARTUP.md) — 新しい環境での最小開始手順
- [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) — A/B運用の補助説明
- [AI_CHECKLIST.md](AI_CHECKLIST.md) — candidate / push / BUILD等の境界チェック
- [CAPABILITIES.md](CAPABILITIES.md) — GitHub / Windows / 周辺機器等の能力整理
- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) — Git・テスト・配布・データ保護の補助ルール
- [STARTUP_HANDOFF_POLICY.md](STARTUP_HANDOFF_POLICY.md) — 初回Windows準備が必要な場合だけ参照
- [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) — 旧T0〜T3運用のLegacy Reference。必読ではない

## 現在の開発運用

Development Control Centerでは **AI開発を標準ルート** とします。

```text
要望
→ Claudeが隔離worktreeで実装
→ 独立テスト
→ GPT-6 Astraがread-onlyレビュー
→ 必要ならClaude修正
→ local candidate commit
→ RUN_DEVでユーザー実機確認
→ 確認済みSHAを維持して次工程へ
→ BUILD / 配布
```

GitHubだけで実装してcandidateを作る旧A-path、および手動でCodex / Claudeへ指示文を渡す旧Bデバッグ入口は通常DCC UIから外します。GitHub / PR / CIの状態表示は、同期・確認・将来のpush検証に必要な観測情報として残します。

### development-management 自身の更新

Development管理repoだけは通常アプリのDCC開発ルートとは分離します。

```text
ChatGPTがGitHub上で実装
→ Codex独立レビュー
→ Claude独立レビュー
→ 指摘があればChatGPT修正
→ 両方approve
→ merge
→ WindowsへSYNC
```

DevelopmentではChatGPTが実装担当、CodexとClaudeが独立reviewerです。両reviewerのapprove前にmergeしません。

## AI Development Orchestrator

v0.2は **Claude実装 → 自動テスト → GPT-6 Astra read-onlyレビュー → 必要ならClaude修正** を最大2ラウンドで実行し、ローカルcandidateで停止します。

Development Control Centerから選択repoへAI依頼と独立テストコマンドを渡して起動できます。成功時はDCCがmachine-readable resultから完全40桁candidate SHAを受け取り、確認後だけローカルexpected branchへfast-forwardしてRUN_DEVによる実機確認へ繋げます。

AI処理だけでpush / BUILD / UPDATE / DEPLOYは行いません。詳細は [docs/ai_orchestrator.md](docs/ai_orchestrator.md) を参照してください。

## 最重要の安全条件

- 実機確認前に本番配布しない。
- NG candidateを本番へ進めない。
- candidateを完全SHAで特定する。
- **confirmed SHA == pushed SHA == BUILD対象SHA** を守る。
- candidate確認開始時と正式BUILD時はtracked cleanを確認する。
- force push / 履歴破壊 / 無断rebaseを行わない。
- 本番データ、秘密情報、ローカル設定、Git管理外業務データを保護する。
- BUILDで配布実体が変わるアプリは完成binaryも配布前に確認する。

## 管理対象

各アプリの正式ローカルパスは [REPOSITORIES.md](REPOSITORIES.md)、必要な個別情報は `projects/*.md` を参照します。

このリポジトリには、コード本体、秘密情報、実運用設定、顧客データ、業務データを置きません。

## 記録方針

重要な情報だけを残します。

- 長期的に必要な設計・運用判断
- 再発防止に価値があるLessons Learned
- 現在の未解決課題
- 必要なcandidate / release情報

仕様・運用が変わらない修正で、README・PROJECT_STATUS・複数管理文書を形式的に更新しません。同じ状態を複数文書へ重複転記しないことを優先します。
