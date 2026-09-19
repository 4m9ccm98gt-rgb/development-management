# Operating Contract

この文書は、Development運用で常時適用する最小契約です。

目的は、**DCCを中心にAI開発を高速に回しつつ、実機確認・candidate SHA・BUILD対象の一致を崩さないこと**です。

## 1. 標準ルート

通常の開発は Development Control Center の **AI開発** を使います。

```text
仕様・要望
→ Claudeが隔離worktreeで実装
→ 独立テスト
→ GPT-6 Astraがread-onlyレビュー
→ 必要ならClaudeが修正
→ local candidate commit
→ DCCがcandidate SHAを取得
→ ユーザー確認後だけlocal expected branchへfast-forward
→ RUN_DEVでユーザー実機確認
→ OKなら同じSHAを正式push
→ confirmed SHA == pushed SHA を確認
→ BUILD
→ UPDATE / DEPLOY
```

GitHubだけで実装してcandidateを作る旧A-path、および手動でCodex / Claudeへ指示文を渡す旧Bデバッグ入口は標準運用ではありません。

## 2. 絶対に残す安全条件

- ユーザー実機確認前に本番配布しない。
- 実機確認でNGになったcandidateを本番へ進めない。
- candidateは完全40桁SHAで特定する。
- 最終的に **confirmed SHA == pushed SHA == BUILD対象SHA** を成立させる。
- candidate確認開始時と正式BUILD時はtracked cleanを確認する。
- 本番データ、秘密情報、ローカル設定、共有先、Git管理外業務データを不用意に変更しない。
- force push / reset --hard / stash / 無断rebase等で既存作業や承認済みSHAを壊さない。
- remoteが想定外に進んだ場合はforceで押し切らず停止する。

## 3. AI Orchestrator

AI Orchestrator v0.2の標準役割は次です。

- 実装・修正: Claude
- 自動テスト: 対象repoの独立テストコマンド
- 独立レビュー: GPT-6 Astra / read-only
- 最大ラウンド: 2
- 作業場所: source repoではなく一時detached worktree
- 完了点: local candidate
- 自動では行わないもの: push / BUILD / UPDATE / DEPLOY

Orchestratorはsource repoのbranch / HEAD / tracked clean / originを開始時とcandidate作成前に再確認し、agentによるcommit・branch変更やreview後の未レビュー差分をfail-closeします。

## 4. DCCでのcandidate受け渡し

- DCCはOrchestratorのmachine-readable resultからcandidate SHAを取得する。
- console文字列のスクレイピングをcandidate確定根拠にしない。
- candidateを正式ローカルbranchへ反映する前にユーザー確認を挟む。
- local fast-forward時はbase SHA、current HEAD、branch、origin、tracked clean、candidate ancestryを再確認する。
- fast-forwardできない場合は自動修復せず停止する。
- candidate反映後はRUN_DEVで実機確認する。

## 5. 実機確認 / push / BUILD

- RUN_DEVで業務上の正しさ、GUI、印刷、LAN、外部サービス等を必要範囲で確認する。
- 実機確認OK後にcandidate SHAを変更しない。
- pushはfast-forward前提とし、push後にremote SHA == confirmed SHAを確認する。
- 正式BUILD前にHEAD == confirmed SHAかつtracked cleanを確認する。
- Nuitka / PyInstaller / .NET/WPF等、BUILDで配布実体が変わる場合は完成binaryも配布前に確認する。
- ソース実行確認と配布binary確認を同一視しない。

## 6. GitHub / CIの位置づけ

- GitHub / PR / CI表示は観測・同期・SHA確認のために使う。
- GitHub Actionsは補助検証であり、Actions greenだけを実機確認の代わりにしない。
- 同じ決定的テストを、理由なくローカルとActionsで重複実行しない。
- 実プリンター、実共有サーバー、live外部接続、実HDD等は必要なときだけ実機確認する。

## 7. 読み込み・判断コスト

- T0〜T3の必須分類は使用しない。
- 新しいチャットという理由だけで全Development文書を読み直さない。
- 通常は本書、対象repoのREADME、変更箇所と直接のconsumer / producerだけを読む。
- 毎ターンcontractを再報告しない。
- 大きなスコープ変更、不可逆操作、本番影響が新たに必要になった場合だけ追加判断を求める。

## 8. 他文書との関係

- 本書がDevelopment運用の正本です。
- `AI_OPERATING_MANUAL.md` / `AI_CHECKLIST.md` / `AGENTS.md` / `AI_STARTUP.md` は補助資料です。
- `AGENT_EFFICIENCY_POLICY.md` は旧T0〜T3運用のLegacy Referenceです。
- 詳細文書と本書が競合する場合は本書を優先します。

運用の安全性は、工程数ではなく、**candidate SHA、独立テスト、独立レビュー、ユーザー実機確認、confirmed/pushed/BUILD SHA一致**で担保します。
