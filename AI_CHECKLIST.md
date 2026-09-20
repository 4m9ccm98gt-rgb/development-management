# AI Checklist

必要な境界でだけ使う短いチェックです。正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## AI開発開始時

- [ ] 対象repo / expected branchが正しい
- [ ] local HEAD == origin HEAD
- [ ] tracked clean
- [ ] 本番データ・秘密情報・Git管理外業務データを保護できる
- [ ] 開始点はDCCのAI依頼欄（GPTが意図・優先順位・受入条件を整理済み）
- [ ] AI依頼が具体的
- [ ] 独立テストコマンドが設定されている

## Orchestrator中

- [ ] Claudeは隔離worktreeで実装している
- [ ] Claudeはcommit / branch変更 / pushをしていない
- [ ] tests pass
- [ ] Astraはread-only review
- [ ] review後にdiffが変化していない
- [ ] 最大2ラウンドを超えていない

## local candidate確定時

- [ ] candidateは完全40桁SHA
- [ ] source repoが開始時baseから動いていない
- [ ] candidateはbaseのfast-forward子孫
- [ ] DCCのmachine-readable resultでcandidateを受け取った
- [ ] local expected branchへ反映する前にユーザー確認を挟んだ
- [ ] local fast-forward後はtracked clean

## RUN_DEV実機確認

- [ ] ユーザーが実際に確認するcandidate SHAが明確
- [ ] 変更箇所に応じてGUI / 印刷 / LAN / 外部サービス等を確認した
- [ ] NGならそのcandidateを本番へ進めない

## ユーザーOK後 / push

- [ ] 承認後にamend / rebase / squash等でSHAを変えていない
- [ ] pushはfast-forward
- [ ] remoteが想定外に進んでいない
- [ ] pushed SHA == confirmed SHA

## BUILD / UPDATE / DEPLOY

- [ ] HEAD == confirmed SHA
- [ ] tracked clean
- [ ] BUILD対象SHA == pushed SHA
- [ ] BUILDで実体が変わるアプリは完成binaryを必要範囲で確認した
- [ ] 実機確認前の本番配布ではない
- [ ] confirmed SHA == pushed SHA == BUILD対象SHA

## 不要なもの

- T0〜T3の必須分類
- 全Development文書の毎回読み直し
- 同じテストの無意味な重複実行
- Actions green待ちだけを理由にした開発停止
- 長い定型完了報告

## development-management 更新時・新規repo登録時

- [ ] 通常repoと同じくDCCのAI依頼欄から開始した
- [ ] 新規repoは「セットアップ開始」でcloneを確認し、AI依頼欄へ登録タスクがセットされた
- [ ] Claude → 独立Tests → GPT-6 Astra read-only review を通った
- [ ] local candidateの完全SHAをユーザーが確認してから反映した
- [ ] `[branches]` / `[initial_ai_tasks]` / `[initial_tests]` が登録されている
