# AI Startup

新しいチャットや実行環境で開発を始めるときの最小入口です。正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 1. 最初に読むもの

1. [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)
2. 対象repoのREADMEまたは今回の変更に直接関係する説明
3. 変更対象コードと、その変更で壊れ得る直接のconsumer / producer

新しいチャットという理由だけでDevelopment文書一式を読みません。

## 2. 開始点は常にDCCのAI依頼欄

```text
GPTが要望・優先順位・受入条件をAI依頼へ整理
→ DCCで対象repoを選択（development-management自身も同じ）
→ AI依頼欄 + テスト欄 → 「AI開発開始」
→ Claude実装 → 独立Tests → Final Review Gate → local candidate
→ ユーザー実機確認（RUN_DEV）→ OKなら同じSHAをpush → BUILD / 配布
```

GPTは標準運用でGitHub上のコード・設定を直接編集しません。

## 3. 新規repo

DCCの「セットアップ開始」が正式ローカルへのcloneを確認し、`development-management` のAI依頼欄へ登録タスクをセットします。「AI開発開始」で同じ経路により登録し、DCC更新後は新repoの `initial_ai_tasks` / `initial_tests` が自動入力されます。

## 4. 初回ローカル準備

ローカルrepo、runtime、依存関係、`RUN_DEV` 等の初回準備は [STARTUP_HANDOFF_POLICY.md](STARTUP_HANDOFF_POLICY.md) を参照します。初回準備でも別の開発開始経路は作りません。

## 5. 境界で確認すること

candidate確定、push、BUILD、deploy / update / 本番反映の境界で `OPERATING_CONTRACT.md` を再確認します。実行していない検証を「確認済み」と扱わず、本番データ・秘密情報・既存変更を保護します。
