# AI Startup

新しいチャットや実行環境で開発を始めるときの最小入口です。

## 1. 最初に読むもの

1. [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)
2. 対象repoのREADMEまたは今回の変更に直接関係する説明
3. 変更対象コードと、その変更で壊れ得る直接のconsumer / producer

新しいチャットという理由だけでDevelopment文書一式を読みません。

`AGENT_EFFICIENCY_POLICY.md` のT0〜T3、読み込み予算、CI必須ゲートは現在の必須運用ではありません。

## 2. 通常はA — ChatGPT fast path

```text
ChatGPTがGitHub上で調査・実装・テスト追加
→ 利用可能な自動検証
→ GitHub candidate SHA
→ ユーザーが正式同期入口でWindowsへ反映
→ ユーザー実機確認
→ OKならBUILD / 配布
```

GitHub Actionsは補助であり、利用不能だけを理由に開発を止めません。

## 3. 面倒になったらB — Debug escape path

ユーザーがCodex / Claude等を明示した場合、その指定エージェントがWindowsローカルrepoで連続デバッグします。

```text
開始時にlocal HEAD / origin / branch確認
→ working treeで調査・実装・テスト・デバッグ
→ local candidate commit
→ tracked clean + 実差分レビュー
→ ユーザー実機確認
→ OKなら同じSHAをfast-forward push
→ BUILD / 配布
```

Bの詳細条件は `OPERATING_CONTRACT.md` を正とします。

## 4. 初回ローカル準備

ローカルrepo、runtime、依存関係、`RUN_DEV`、BUILD / UPDATE入口等の初回準備が必要なら、今回必要な範囲だけ整えます。

- 外部実機AIを自動的な必須担当にしません。
- ユーザーがCodex / Claude等を指定した場合は、その指定を維持します。
- ユーザーへ長いGit / PowerShell手順を覚えさせるより、既存の安全なワンクリック入口を優先します。
- 初回準備のためだけに、将来工程すべての入口監査を必須にしません。

## 5. 境界で確認すること

毎ターンではなく、主に次の境界で `OPERATING_CONTRACT.md` を再確認します。

- A → Bへ切り替えるとき
- candidateを確定するとき
- pushするとき
- BUILDするとき
- deploy / update / 本番反映するとき

常に、実行していない検証を「確認済み」と扱わず、本番データ・秘密情報・既存変更を保護します。
