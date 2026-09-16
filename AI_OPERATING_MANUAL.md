# AI Operating Manual

この文書はDevelopment運用の補助資料です。**正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)** であり、本書は上書きしません。

## 1. 基本方針

運用は次の2経路だけを基本とします。

- **A — ChatGPT fast path**: GitHub上で調査・実装・テスト追加・candidate作成まで進め、ユーザーが同期して実機確認する。
- **B — Debug escape path**: ユーザーが指定したCodex / Claude等がWindowsローカルrepoで完成までデバッグし、local candidate commitをユーザー確認後にpushする。

Actionsは補助検証であり、通常の完了条件へ固定しません。

## 2. ChatGPTの役割

Aでは、利用可能なGitHub機能を使って次を行えます。

- 必要範囲のコード・仕様調査
- 実装
- テスト追加・修正
- branch / commit / push / PR等のGitHub操作
- 実差分レビュー
- candidate SHAの確定
- ユーザー実機確認項目の整理

実行できない自動テストを実施済みとは扱いません。Actionsが利用不能なら、その事実と未確認項目を明示して継続します。

## 3. Bへ切り替えるとき

Bは安全性の上位ティアではなく、**デバッグ摩擦を減らすための別経路**です。

ユーザーが「Codexで」「Claudeに渡して」等と指定したら、その指定された作業でBへ切り替えます。

- B開始時に `git fetch` を行い、local HEAD / expected origin / branchの土台を確認する。
- origin側が想定外に進んでいたらforceで解決せず停止する。
- working treeで調査・修正・targeted test・必要なregressionを繰り返してよい。
- 修正ごとのpush / Actions待ち / GitHub→Windows再同期は不要。
- 完成時にlocal candidate commitを作り、その後tracked cleanを確認する。
- 既知良好SHAからcandidateまでの実差分を一度レビューする。
- ユーザーがそのSHAを実機確認し、NGなら新candidateを作る。
- OK後は承認SHAを変えず、fast-forwardでpushする。

特定エージェント指定を別エージェントへ勝手に変更しません。

## 4. テスト

テスト量はティア番号ではなく、変更内容と検出したい失敗で決めます。

- 実装中は変更箇所に対応するtargeted testを優先する。
- 共通処理や広い影響がある場合は必要なregressionを追加する。
- 同じ対象・同じ環境・同じ内容のテストを安心のためだけに重複実行しない。
- `compileall`、unit test、integration test、build validation、実機確認は役割が異なるため、必要なものを選ぶ。
- GUI、実紙、printer、LAN、外部サービス、実HDD等は必要に応じてユーザー実機確認へ残す。

## 5. Gitとcandidate

- Git上の正式ソースを基準とし、既存変更を保護する。
- candidateは完全SHAで特定する。
- candidate確認開始時は tracked clean を確認する。
- BのユーザーOK後にamend / rebase / squashでSHAを変えない。
- push時にremoteが進んでいたらforceせず停止する。
- **confirmed SHA == pushed SHA == BUILD対象SHA** を守る。

AではGitHub candidateを正式同期入口からWindowsへ反映します。Bではlocal candidateをその場で確認するため、GitHub→Windowsのcandidate同期工程は不要です。

## 6. BUILD / deploy / update

- 実機確認前に本番配布しない。
- 正式BUILD時はHEADがconfirmed SHAで、tracked cleanであることを確認する。
- Nuitka / PyInstaller / .NET/WPF等、BUILDによって配布実体が変わる場合は、完成binaryを配布前に少なくとも起動確認する。
- 本番データ・秘密情報・ローカル設定・共有先を不用意に変更しない。
- 安全な既存 `*_CLICK_ME.cmd` / `UPDATE_*` 等がある場合はそれを利用する。

## 7. スコープと読み込み

- 新しいチャットという理由だけで長文書一式を読み直さない。
- 今回の目的、変更箇所、そのconsumer / producer、安全上必要な資料だけを読む。
- 大きなスコープ変更、不可逆操作、本番影響が新たに必要になった場合はユーザー判断を求める。
- 依頼範囲内の通常調査・実装・テストは、工程名ごとの再承認を挟まず進めてよい。

## 8. 記録

将来の判断に本当に必要な内容だけをGitへ残します。

- 重要な設計・運用判断
- 現在の未解決課題
- 再発防止に価値があるLessons Learned
- candidate SHAと、必要なら検証結果

進行表や同じ状態を複数文書へ重複転記しません。
