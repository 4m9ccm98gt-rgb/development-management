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
- [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) — AI依頼経路の補助説明
- [AI_CHECKLIST.md](AI_CHECKLIST.md) — candidate / push / BUILD等の境界チェック
- [CAPABILITIES.md](CAPABILITIES.md) — GitHub / Windows / 周辺機器等の能力整理
- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) — Git・テスト・配布・データ保護の補助ルール
- [STARTUP_HANDOFF_POLICY.md](STARTUP_HANDOFF_POLICY.md) — 初回Windows準備が必要な場合だけ参照
- [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) — 旧T0〜T3運用のLegacy Reference。必読ではない

## 現在の開発運用（Phase 1）

GPT相談・指示文作成 → Claude / Codexが正式ローカルrepoで直接実装 → Tests → DCC RUN → ユーザー確認 → BUILD → UPDATE。

DCCはRUN / BUILD / UPDATEを中心に使います。RUN / BUILDはdirtyな作業ツリー・candidateなしで利用でき、GitHubの状態取得に依存しません。UPDATEにはBUILD記録・成果物・配布先の確認と明示操作が必要です。アプリ側の既存制約と対応範囲は [DCC仕様](docs/dev_control_center.md) を参照してください。

`RUN_DEV.cmd` でDCCを起動します。「AI Orchestrator」から既存AI機能を別画面で利用できます。通常開発の必須経路ではありません。Phase 1ではレビューJSON待ちを含む既存機能を維持し、独立run管理・終了後継続・再接続・自動レビュー・quota handoffはPhase 2です。

GPTによるGitHub直接編集・PC同期は標準ルートにしません。GitHubは観測・履歴共有に使用します。運用の安全条件は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を参照します。

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

DCCの通常操作は非対話workerで実行し、進捗ログと終了コードを画面内へ表示します。手動CMDのpauseは維持します。対応入口と新規repoの宣言方法は [DCC仕様](docs/dev_control_center.md#バックグラウンド実行) を参照してください。
