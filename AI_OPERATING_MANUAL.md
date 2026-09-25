# AI Operating Manual

正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)。本書は補助資料です。

GPTは相談・要件整理・設計・問題切り分け・指示文作成・必要なレビューを担当します。Claude / Codexは通常Developmentで正式ローカルrepoを直接編集・検証します。providerは固定しません。

調査だけの依頼では実装へ進みません。実装依頼では対象と完了条件を確認し、既存変更を保護して作業・Testsを行います。ユーザー確認後のBUILD / UPDATEは正本の操作別条件に従います。

Orchestrator固有の隔離worktree、Recovery、candidate、Final Reviewの手順は [専用文書](docs/ai_orchestrator.md) に置き、通常Developmentへ要求しません。

検証結果と未確認事項を分け、重要判断・運用変更を知識ベースへ記録します。commit / pushは明示指示がある場合のみ実施します。
