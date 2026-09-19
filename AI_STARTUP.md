# AI Startup

新しいチャットや実行環境で開発を始めるときの最小入口です。

## 1. 最初に読むもの

1. [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)
2. 対象repoのREADMEまたは今回の変更に直接関係する説明
3. 変更対象コードと、その変更で壊れ得る直接のconsumer / producer

新しいチャットという理由だけでDevelopment文書一式を読みません。

`AGENT_EFFICIENCY_POLICY.md` のT0〜T3、読み込み予算、CI必須ゲートは現在の必須運用ではありません。

## 2. 通常はDCC AI開発

```text
DCCで対象repoを選択
→ AI依頼 + テストコマンド
→ Claude実装
→ 自動テスト
→ GPT-6 Astra read-onlyレビュー
→ 必要ならClaude修正 + 再テスト + 再レビュー
→ local candidate
→ RUN_DEVでユーザー実機確認
→ OKなら同じSHAをpush
→ BUILD / UPDATE・DEPLOY
```

AI処理はlocal candidateで停止し、push / BUILD / UPDATE / DEPLOYへ自動進行しません。

## 3. 開始前の最低条件

- 正式repo / expected branchが特定できる。
- tracked working treeがclean。
- local HEADと想定origin HEADが一致している。
- Claude Code / Codex CLI / Gitが利用可能。
- API課金環境変数が意図せず有効になっていない。
- 今回の変更を検証する独立テストコマンドが指定されている。

DCCのAI開発ボタンが安全条件を満たさず無効な場合、条件をforceで回避しません。

## 4. 初回ローカル準備

ローカルrepo、runtime、依存関係、`RUN_DEV`、BUILD / UPDATE入口等の初回準備が必要なら、今回必要な範囲だけ整えます。

- ユーザーへ長いGit / PowerShell手順を覚えさせるより、DCCと既存の安全なワンクリック入口を優先します。
- 初回準備のためだけに、将来工程すべての入口監査を必須にしません。
- DCCが利用不能な場合の例外復旧は、ユーザーが明示した時だけ個別に扱います。

## 5. 境界で確認すること

毎ターンではなく、主に次の境界で `OPERATING_CONTRACT.md` を再確認します。

- AI開発を開始するとき
- candidateを確定するとき
- RUN_DEVで実機確認を始めるとき
- ユーザーがcandidateをOKしたとき
- pushするとき
- BUILDするとき
- deploy / update / 本番反映するとき

常に、実行していない検証を「確認済み」と扱わず、本番データ・秘密情報・既存変更を保護します。
