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

### A — ChatGPT fast path

```text
要望
→ ChatGPTがGitHubで調査・実装・テスト追加
→ 利用可能な自動検証
→ GitHub candidate SHA
→ ユーザーがWindowsへ同期
→ ユーザー実機確認
→ OKならBUILD / 配布
```

GitHub Actionsは補助検証です。Actionsの利用制限だけを理由に開発を止めません。

### B — Debug escape path

ChatGPT→GitHub→SYNCの往復が面倒になった場合、ユーザー指定のCodex / Claude等へ切り替えられます。

```text
指定実機AIがWindowsローカルrepoで調査・実装・テスト・デバッグ
→ local candidate commit
→ tracked clean + 実差分レビュー
→ ユーザー実機確認
→ OKなら同じSHAをpush
→ BUILD / 配布
```

Bでは修正ごとのpush、Actions待ち、再SYNCを必須にしません。

## AI Development Orchestrator

Codex実装 → 自動テスト → Claude独立レビュー → Codex修正を自動反復し、ローカルcandidateで停止する実験的なv0.1を `tools/ai_orchestrator/` に置いています。

本番配布・BUILD・UPDATEは自動化しません。詳細は [docs/ai_orchestrator.md](docs/ai_orchestrator.md) を参照してください。

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
