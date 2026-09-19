# Operating Contract

この文書は、Development運用で常時適用する最小契約です。

目的は、**実装品質と本番安全性を維持しながら、Development Control Center（DCC）から一貫したAI開発フローでcandidateを作り、ユーザー実機確認まで安全に進めること**です。

## 1. 絶対に残す安全条件

- ユーザー実機確認前に本番配布しない。
- 実機確認でNGになったcandidateを本番へ進めない。
- ユーザーが確認したcandidateを完全40桁SHAで特定する。
- 最終的に **confirmed SHA == pushed SHA == BUILD対象SHA** を成立させる。
- candidate確認開始時と正式BUILD時は tracked clean を確認する。
- 本番データ、秘密情報、ローカル設定、共有先、Git管理外業務データを不用意に変更しない。
- force push / 履歴破壊 / 無断rebaseで承認済みSHAを置き換えない。
- 実行していないテストや実機確認を「確認済み」と扱わない。

## 2. 標準ルート — DCC AI開発

通常のアプリ開発はDevelopment Control Centerの **AI開発** を標準ルートとします。

```text
仕様・要望
→ DCCで対象repoを選択
→ AI依頼 + 独立テストコマンドを指定
→ source repo / branch / tracked clean / origin同期を確認
→ 一時detached worktreeを作成
→ Claudeが実装
→ 自動テスト
→ GPT-6 Astraがread-onlyレビュー
→ 必要ならClaude修正 → 再テスト → Astra再レビュー
→ APPROVE後にlocal candidate commit
→ DCCが完全40桁candidate SHAを取得
→ ユーザー確認後だけlocal expected branchへfast-forward
→ RUN_DEVでユーザー実機確認
→ OKなら同じcandidate SHAをfast-forward push
→ pushed SHA == confirmed SHA を確認
→ 正式BUILD / UPDATE・DEPLOY
```

### AI実装中

- AI編集は隔離worktreeで行う。
- source repoのworking treeを実装作業場にしない。
- Claudeは実装担当。commit / branch変更を検出したら停止する。
- Codex / GPT-6 Astraは独立レビュー担当でread-onlyとする。
- 通常は最大2ラウンド。延々と自動反復しない。
- 子プロセスからのpushを禁止する。
- candidate直前にsource repoとoriginが想定から動いていないことを再確認する。

### local candidate確定時

- 自動テストPASS + Astra APPROVE後だけcandidateを作る。
- candidate SHAを完全40桁で記録する。
- candidate commit後の内容がレビュー済みdiffと一致することを担保する。
- DCCからlocal expected branchへ戻す場合は、base SHA不変・candidate ancestry・branch・origin・tracked cleanを再確認し、fast-forwardだけを許可する。
- この段階ではpush / BUILD / UPDATE / DEPLOYを行わない。

### ユーザー実機確認後

- NGならそのcandidateは本番へ進めず、新candidateとして再確認する。
- OK後にamend / rebase / squash等でcandidate SHAを変更しない。
- pushはfast-forward前提。remoteが想定外に進んでいたら停止して再評価する。
- push後、pushed SHAがconfirmed SHAと一致することを確認する。

## 3. 旧A/B経路の扱い

旧 **A — ChatGPT fast path** と旧 **B — Debug escape path** は標準Development運用から外します。

- DCC通常UIにGitHubだけで実装する入口は置かない。
- 手動でCodex / Claudeへデバッグ指示文を渡す入口も通常UIに置かない。
- GitHub / PR / CI表示は観測・同期・push確認のために残す。
- DCC自体やdevelopment-managementの管理変更など、標準アプリ開発フロー外の作業は必要に応じてGitHub上で実施してよいが、本番安全条件は同じ。
- DCCが利用不能などの例外時は、ユーザーが明示して個別復旧する。旧A/Bを自動的に標準ルートへ戻さない。

## 4. 実機確認とBUILD

- ユーザー実機確認はcandidateの業務上の正しさ、GUI、実紙、LAN、外部サービス等を確認する最終安全境界です。
- 正式BUILD前に **HEAD == confirmed SHA** と tracked clean を確認します。
- 正式pushを行うアプリでは **pushed SHA == confirmed SHA** も確認します。
- Nuitka / PyInstaller / .NET/WPF等、BUILDで配布実体が変わるアプリは、完成binaryを配布前に少なくとも起動確認し、変更内容に応じて該当機能を確認します。
- ソース実行と配布binaryの確認を同一視しません。

## 5. テストとGitHub Actions

- 実装時は変更内容に対応する独立テストを必須入力とするのが原則です。
- テストコマンドを安全に推定できる場合はDCCが初期値を提案してよい。推定できない場合は空欄のままにし、ユーザーが指定する。
- GitHub Actionsは独立環境の補助検証です。Actions greenをlocal candidateの必須条件にはしません。
- Actionsの利用制限・待ち時間だけを理由に通常開発を停止しません。
- 同じ対象・同じ環境・同じ内容のテストを安心のためだけに重複実行しません。
- Actions自体、依存関係、共通CI基盤等を変更した場合は、その変更に必要なActions確認を行います。

## 6. 読み込み・判断コスト

- T0〜T3の必須分類は使用しません。
- 毎ターンこの契約を再読・再報告する必要はありません。
- この契約を明示的に再確認する主な境界は、**AI開発開始、candidate確定、実機確認OK、push、BUILD、deploy / update、本番反映**です。
- 調査は依頼と変更に必要な範囲を読むことを原則とし、理由のない全repo・全文書読み込みや同一テストの重複実行を行いません。

## 7. 他文書との関係

- 本書がDevelopment運用の正本です。
- `AGENT_EFFICIENCY_POLICY.md` は旧運用の履歴・参考資料であり、必読ポリシーではありません。
- `AI_STARTUP.md` / `AI_OPERATING_MANUAL.md` / `AI_CHECKLIST.md` / `CAPABILITIES.md` / `DEVELOPMENT_RULES.md` / `STARTUP_HANDOFF_POLICY.md` / `AGENTS.md` は本書を上書きしません。
- 詳細文書と本書が競合する場合は本書を優先します。

運用の安全性は、工程名やAIの確認回数ではなく、**確認対象のSHA、必要なテスト、独立レビュー、ユーザー実機確認、push / BUILD対象SHAの一致**で担保します。
