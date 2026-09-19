# AI Operating Manual

この文書はDevelopment運用の補助資料です。**正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)** であり、本書は上書きしません。

## 1. 基本方針

Development Control Centerの **AI開発** を標準ルートとします。

- Claude Code: 実装・修正担当
- 独立テスト: 実装とは別の判定
- Codex / GPT-6 Astra: read-only独立レビュー担当
- DCC: repo選択、preflight、進捗、candidate SHA受取、local fast-forward、安全ロック
- ユーザー: RUN_DEVによる実機確認と、本番へ進める最終判断

GitHubだけで実装する旧A-path、手動で実機AIへデバッグ指示を渡す旧B-pathは通常運用から外します。

## 2. DCC AI開発の流れ

1. 対象repoを選択する。
2. AI依頼を入力する。
3. 独立テストコマンドを確認・必要なら編集する。
4. 「AI開発開始」を実行する。
5. DCCがsource repo / branch / clean / origin同期を確認する。
6. Claudeが隔離worktreeで実装する。
7. 自動テストを実行する。
8. Astraがread-onlyレビューする。
9. 指摘があればClaudeが修正し、再テスト・再レビューする。
10. APPROVE後にlocal candidate commitを作る。
11. DCCがmachine-readable resultから完全40桁candidate SHAを受け取る。
12. ユーザー確認後だけlocal expected branchへfast-forwardする。
13. RUN_DEVでユーザーが実機確認する。
14. OKなら同じSHAをpushし、pushed SHA一致を確認する。
15. BUILD / UPDATE・DEPLOYへ進む。

通常の自動反復上限は2ラウンドです。

## 3. エージェント境界

### Claude

- 実装とレビュー指摘修正を担当する。
- source repoではなく隔離worktreeだけを編集する。
- commit / branch変更は行わない。検出したら停止する。
- BUILD / UPDATE / shared folder更新へ進まない。

### Codex / GPT-6 Astra

- 独立レビューだけを担当する。
- read-only sandboxで実行する。
- ファイルを変更しない。
- APPROVEとfindingsが矛盾する出力はfail-closeとする。
- レビュー前後のdiff fingerprintが変わったらcandidateを作らない。

### DCC

- AI処理のstdoutを操作ログへ流す。
- `status.json` / result JSONから状態を受け取る。
- candidateをconsole文字列スクレイピングだけで判断しない。
- local candidate適用前にbase SHA / current HEAD / branch / origin / tracked clean / ancestryを再確認する。
- fast-forward以外でlocal expected branchを動かさない。

## 4. テスト

テスト量は変更内容と検出したい失敗で決めます。

- AI開発開始時に独立テストコマンドを必須とする。
- 変更箇所に対応するtargeted testを優先する。
- 共通処理や広い影響がある場合は必要なregressionを追加する。
- 同じ対象・同じ環境・同じ内容の成功済みテストを理由なく重複実行しない。
- GUI、実紙、printer、LAN、外部サービス、実HDD等は必要に応じてユーザー実機確認へ残す。

## 5. Gitとcandidate

- Git上の正式ソースを基準とし、既存変更を保護する。
- candidateは完全40桁SHAで特定する。
- AI実装は一時detached worktreeで行う。
- candidate commit後はreviewed diffと内容が一致していることを担保する。
- RUN_DEV対象へ移す時はlocal expected branchをfast-forwardだけで進める。
- ユーザーOK後にamend / rebase / squashでSHAを変えない。
- push時にremoteが進んでいたらforceせず停止する。
- **confirmed SHA == pushed SHA == BUILD対象SHA** を守る。

## 6. BUILD / deploy / update

- 実機確認前に本番配布しない。
- 正式BUILD時はHEADがconfirmed SHAで、tracked cleanであることを確認する。
- pushを伴うアプリはpushed SHAがconfirmed SHAと一致していることを確認する。
- BUILDによって配布実体が変わる場合は、完成binaryを配布前に少なくとも起動確認する。
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
