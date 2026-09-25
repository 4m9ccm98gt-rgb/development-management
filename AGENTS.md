# development-management AI入口ガイド

運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)。開始時は [AI_STARTUP.md](AI_STARTUP.md) の順に確認します。

- GPTは相談・要件整理・設計・Claude / Codex向け指示文作成を担当。
- 通常DevelopmentではClaude / Codexが正式ローカルrepoで直接実装・Testsを行います。DCC / Orchestratorは開発開始の必須経路ではありません。
- DCCメインはRUN / BUILD / UPDATE。Orchestratorは別画面の任意の第二ルート。
- 既存作業・秘密情報・業務データを保護し、無断commit / push / タグ作成・履歴破壊・UPDATEをしません。
- 変更に必要な文書・コードだけを確認し、重要判断と検証結果を記録します。
- GitHubから開いた新規プロジェクトでは変更前にファイル・起動・必要ならブラウザコンソールを確認します。既存障害は勝手に直さず報告します。
