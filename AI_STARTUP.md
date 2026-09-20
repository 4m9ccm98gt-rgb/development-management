# AI Startup

新しいチャットや実行環境で開発を始めるときの最小入口です。

## 1. 最初に読むもの

1. [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)
2. 対象repoのREADMEまたは今回の変更に直接関係する説明
3. 変更対象と、その変更で壊れ得る直接のconsumer / producer

新しいチャットという理由だけでDevelopment文書一式を読みません。

## 2. 標準フロー

```text
ユーザーの要望 / 実機フィードバック
→ ChatGPTが意図・優先順位・受入条件を整理
→ DCC AI依頼
→ Claude実装
→ Tests
→ GPT-6 Astra read-onlyレビュー
→ 必要ならClaude修正
→ local candidate
→ ユーザー確認後だけlocal expected branchへfast-forward
→ RUN_DEV / 必要な実機確認
→ OKなら同じSHAをpush
→ BUILD / UPDATE / DEPLOY
```

`development-management` も同じルートです。別のChatGPT実装ルートや、ユーザーによるCodex / Claude手動レビューは使いません。

## 3. 新規repo

DCCの「セットアップ開始」は正式ローカルへのcloneまでを行い、その後 `development-management` を選択してAI依頼欄へ登録タスクをセットします。

ChatGPT / ユーザーはそのAI依頼へrepo種別、expected branch、初期デモの意図・受入条件を整理します。中央registryの変更自体は「AI開発開始」からClaude → Tests → Astraで行います。ChatGPTはGitHub上のコード・設定を直接編集しません。

Development candidate反映後にControl Centerを更新すると、新repoを選択でき、登録済みの初期AI依頼とテストが自動入力されます。そこから再び同じ「AI開発開始」でClaude → Tests → Astraへ進めます。

## 4. 境界

candidate / push / BUILD / deploy・updateでは [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) の安全条件を再確認します。実行していない検証を確認済みと扱わず、本番データ・秘密情報・既存変更を保護します。
