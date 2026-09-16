# Operating Contract

この文書は、Development運用で常時適用する最小契約です。

目的は、**実装品質を保ちながら、ChatGPT / Codex / Claude / GitHub Actions の利用制限で開発全体を止めないこと**です。

## 1. 絶対に残す安全条件

- ユーザー実機確認前に本番配布しない。
- 実機確認でNGになったcandidateを本番へ進めない。
- ユーザーが確認したcandidateを完全SHAで特定できるようにする。
- 最終的に **confirmed SHA == pushed SHA == BUILD対象SHA** を成立させる。
- candidate確認開始時と正式BUILD時は tracked clean を確認する。
- 本番データ、秘密情報、ローカル設定、共有先を不用意に変更しない。
- force push / 履歴破壊 / 無断rebaseで承認済みSHAを置き換えない。
- ユーザーが Codex / Claude 等の特定エージェントを指定した場合、その指定作業では指定エージェントを維持する。

## 2. A — ChatGPT fast path

通常の開発はこの経路を第一候補とします。

```text
仕様・要望
→ ChatGPTがGitHub上で既存コードを調査
→ 実装 + 必要なテスト追加
→ 利用可能な自動検証
→ GitHub candidate SHA確定
→ ユーザーが正式同期入口でローカルへ反映
→ ユーザー実機確認
→ OKなら正式BUILD / 配布
```

- GitHub Actionsは**補助検証**です。Actions greenをcandidate完了の必須条件にしません。
- Actionsが利用不能でも、実行できる検証結果と未実施項目を明示すれば開発を継続できます。
- 自動テストを実行できる環境が無い場合、実行していないテストを「確認済み」と扱いません。
- 軽い修正なら、実機NG後もAで修正を続けて構いません。
- GitHub→同期→実機確認の往復が面倒、またはWindowsローカルでの連続デバッグが適切とユーザーが判断したらBへ切り替えます。

## 3. B — Debug escape path

ユーザーが「Codexでやって」「Claudeに渡して」等と明示した場合、その指定エージェントがWindowsローカルrepoでデバッグを完結させる経路です。

```text
B開始時に local HEAD / expected origin / branch を確認
→ ローカルworking treeで調査・実装・targeted test・必要なregression・デバッグ
→ 自動テスト上で完成
→ local candidate commit
→ tracked clean + candidate SHA確認 + 差分レビュー
→ ユーザーがそのlocal candidateを実機確認
→ NGならローカル修正へ戻る
→ OKなら同じcandidate SHAをfast-forwardでpush
→ confirmed SHA == pushed SHA を確認
→ 正式BUILD / 配布
```

### B開始時

- `git fetch` 後、作業開始の土台が想定originと一致していることを確認する。
- origin側が想定外に進んでいる場合は、forceで押し切らず停止する。
- 本番データ・秘密情報・Git管理外業務データは開発対象に混ぜない。

### Bのデバッグ中

- 修正ごとのpush、GitHub Actions待ち、GitHub→Windowsの再同期は必須にしない。
- working treeで修正とテストを繰り返してよい。
- 復旧目的の途中local commitは許可するが、毎反復のcommitを義務化しない。

### local candidate確定時

- candidate commit後に tracked clean を確認する。
- 直前の既知良好SHAからcandidateまでの**実差分を一度レビュー**する。`diff --stat`だけでなく、一時デバッグコード、仮パス、閾値変更、不要ファイル等が残っていないかを見る。
- ユーザー実機確認の対象SHAを明示する。

### ユーザーOK後

- OK後にamend / rebase / squash等でcandidate SHAを変更しない。
- pushはfast-forward前提。remoteが動いていたら停止して再評価する。
- push後、pushed SHAがユーザー承認SHAと一致することを確認する。

## 4. 実機確認とBUILD

- ユーザー実機確認はcandidateの業務上の正しさ、GUI、実紙、LAN、外部サービス等を確認する最終安全境界です。
- 正式BUILD前に **HEAD == confirmed SHA** と tracked clean を確認します。
- Nuitka / PyInstaller / .NET/WPF等、BUILDで配布実体が変わるアプリは、完成binaryを配布前に少なくとも起動確認し、変更内容に応じて該当機能を確認します。
- ソース実行と配布binaryの確認を同一視しません。

## 5. GitHub Actions

- Actionsは独立環境の補助検証として利用できます。
- Actionsの利用制限・待ち時間だけを理由に通常開発を停止しません。
- ローカルで同等の決定的テストを完了しているBでは、同じテストのActions再実行を完了条件にしません。
- Actions自体、依存関係、共通CI基盤等を変更した場合は、その変更に必要なActions確認を行います。

## 6. 読み込み・判断コスト

- T0〜T3の必須分類は使用しません。
- 毎ターンこの契約を再読・再報告する必要はありません。
- この契約を明示的に再確認する主な境界は、**A→B切替、candidate確定、push、BUILD、deploy / update、本番反映**です。
- 調査は依頼と変更に必要な範囲を読むことを原則とし、理由のない全repo・全文書読み込みや同一テストの重複実行を行いません。

## 7. 他文書との関係

- 本書がDevelopment運用の正本です。
- `AGENT_EFFICIENCY_POLICY.md` は旧運用の履歴・参考資料であり、必読ポリシーではありません。
- `AI_STARTUP.md` / `AI_OPERATING_MANUAL.md` / `STARTUP_HANDOFF_POLICY.md` / `AGENTS.md` は本書を上書きしません。
- 詳細文書と本書が競合する場合は本書を優先します。

運用の安全性は、工程数やAIの確認回数ではなく、**確認対象のSHA、必要な検証、ユーザー実機確認、BUILD対象の一致**で担保します。
