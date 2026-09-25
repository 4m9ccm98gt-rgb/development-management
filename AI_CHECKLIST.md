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
- [ ] Main / Reviewerが別providerで、Tests PASS + Reviewer PASS + 安全チェックPASSを確認した
- [ ] 実行中runは独立worker。画面 / DCCを閉じても停止しないことを前提にした（停止は「AI安全停止」のみ）
- [ ] candidate適用は保留条件（base移動・dirty）を確認してからにした
