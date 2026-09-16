# AI Checklist

必要な境界でだけ使う短いチェックです。正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 開始時

- [ ] 今回は通常の **A: ChatGPT fast path** か、ユーザー指定の **B: Debug escape path** か
- [ ] 対象repo / branch / HEADが特定できている
- [ ] 既存変更・本番データ・秘密情報を保護できる
- [ ] 今回に必要なコード・仕様だけを読んでいる

## candidate確定時

- [ ] candidateを完全SHAで特定した
- [ ] candidate確認開始時にtracked cleanを確認した
- [ ] 実行したテストと未実施項目を区別した
- [ ] 実差分を一度レビューし、一時デバッグコード・仮パス・不要変更が残っていない

## AでWindowsへ同期するとき

- [ ] 想定repo / branch / candidate SHAが一致している
- [ ] 安全な正式同期入口を使う
- [ ] conflict / diverge / local ahead等をforceで自動修復しない
- [ ] 同期後のHEADがcandidate SHAでtracked clean

## Bへ切り替えるとき

- [ ] ユーザーが使用する実機AIを指定した、またはB利用を明示した
- [ ] 指定エージェントを別エージェントへ置き換えていない
- [ ] `git fetch` 後、local HEAD / expected origin / branchの土台を確認した
- [ ] originが想定外に進んでいる場合はforceせず停止する

## Bのlocal candidate

- [ ] 自動テスト上で完成してからcandidate commitを作った
- [ ] candidate commit後はtracked clean
- [ ] 既知良好SHAからcandidateまでの実差分をレビューした
- [ ] ユーザーが確認するcandidate SHAを明示した
- [ ] NGなら新candidateとして再確認し、旧OKを流用していない

## ユーザーOK後 / push

- [ ] 承認後にamend / rebase / squash等でSHAを変えていない
- [ ] pushはfast-forward前提
- [ ] pushed SHA == confirmed SHA

## BUILD / deploy

- [ ] HEAD == confirmed SHA
- [ ] tracked clean
- [ ] BUILDで実体が変わるアプリは完成binaryを配布前に起動確認した
- [ ] 実機確認前の本番配布ではない
- [ ] NG candidateではない
- [ ] confirmed SHA == pushed SHA == BUILD対象SHA

## 不要な確認

次は毎回の必須チェックではありません。

- T0〜T3の分類
- 全Development文書の読み直し
- 毎ターンのcontract再照合
- 同じテストのActions / ローカル重複実行
- Actions green待ちだけを理由にした開発停止
- 固定フォーマットの長い完了報告
