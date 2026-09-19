# development-management AI入口ガイド

このリポジトリでは、開発運用の正本を [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) とします。

最初に必要なのは、今回が **A: ChatGPT fast path** か、ユーザー指定の **B: Debug escape path** かを確認することです。

## 基本

- 通常はAで、ChatGPTがGitHub上の調査・実装・テスト追加・candidate作成を担当します。
- GitHub Actionsは補助です。Actions greenを通常candidateの必須条件にしません。
- ユーザーがWindowsへcandidateを反映し、実機確認します。
- 実機NG後も軽い修正ならAを継続できます。
- GitHub↔SYNCの往復が面倒、またはローカル連続デバッグが適切になったら、ユーザー指定でBへ切り替えます。
- Bでは指定されたCodex / Claude等がWindowsローカルrepoで完成まで調査・実装・テスト・デバッグし、local candidate commitをユーザーが確認してからpushします。
- ただし `development-management` 自身の更新はA/Bの通常ルートとは分離し、ChatGPTがGitHub上で実装し、merge前にCodex + Claudeの独立レビューを両方通します。詳細は `OPERATING_CONTRACT.md` を優先します。
- ユーザーが特定エージェントを名指ししたら、その指定を別エージェントへ勝手に置き換えません。

## 常に守ること

- 実機確認前に本番配布しない。
- NG candidateを本番へ進めない。
- confirmed SHA == pushed SHA == BUILD対象SHA を守る。
- candidate確認開始時と正式BUILD時は tracked clean を確認する。
- force push、履歴破壊、無断rebaseを行わない。
- 本番データ、秘密情報、ローカル設定、Git管理外業務データを保護する。
- 実行していないテストを確認済みと扱わない。
- BUILDで実体が変わるアプリは完成binaryも配布前に確認する。

## 読み込み方針

- `AGENT_EFFICIENCY_POLICY.md` のT0〜T3は現在の必須運用ではありません。
- 新しいチャットという理由だけで長文書一式を読みません。
- 対象README、変更箇所、関連consumer / producer、安全上必要な文書だけを読みます。
- `AI_STARTUP.md` / `AI_OPERATING_MANUAL.md` / `STARTUP_HANDOFF_POLICY.md` は補助資料であり、`OPERATING_CONTRACT.md` を上書きしません。
- 契約の明示的な再確認は、A→B切替、candidate確定、push、BUILD、deploy / update、本番反映などの境界で行えば十分です。

## 手動PowerShell提示

- ユーザーへ複数行PowerShellを貼り付けてもらう場合、Claude / Codex起動、push、sync等の重要コマンドを最終行にしません。
- 重要コマンドの後ろに `Write-Host "DONE"` 等の無害な末尾行を置き、貼り付け末尾の改行不足によるEnter待ちを重要処理に持ち込みません。
- この対策は手動貼り付け時だけです。AI Orchestratorの直接プロセス起動には適用しません。

## GitHub作業

ユーザーが実装・更新を依頼し、ChatGPTがGitHubへ書き込み可能なら、依頼範囲で調査から実装・テスト追加・candidate作成まで進めて構いません。

本番反映、tag、実運用データ更新は、明示的な依頼なしに実施しません。
