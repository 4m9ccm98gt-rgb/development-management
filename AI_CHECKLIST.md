# AI Checklist

正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)。必要な境界で確認します。

## 通常Development

- [ ] 正式repoと既存変更を確認し、Claude / Codexが直接作業できる
- [ ] 必要なTestsを実施した
- [ ] RUNで現在の作業ツリーを確認した（candidate / cleanは不要）
- [ ] ユーザー実機確認を行った

## BUILD / UPDATE

- [ ] 正式entrypointと必要な設定・依存関係を確認した
- [ ] BUILD記録と入力安定性・成果物hashを確認した
- [ ] 配布成果物と配布先が明示され、ユーザーがUPDATEを指示した
- [ ] 確認後に対象が変化していない
- [ ] 本番データ・秘密情報を保護する

## 任意のOrchestrator

- [ ] 別画面で対象repo・Task・Testsを確認した
- [ ] 専用のsource保護・Review・candidate適用条件を満たす
- [ ] Phase 2の自動レビュー・終了後継続を実装済みと扱っていない
