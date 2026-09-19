# AI Checklist

必要な境界でだけ使う短いチェックです。正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## AI開発開始時

- [ ] 対象repo / expected branch / HEADが特定できている
- [ ] tracked working treeがclean
- [ ] local HEAD == expected origin HEAD
- [ ] 本番データ・秘密情報・Git管理外業務データを保護できる
- [ ] AI依頼が明確
- [ ] 独立テストコマンドが設定されている
- [ ] API課金環境変数が意図せず有効になっていない

## 実装・レビュー中

- [ ] Claudeは隔離worktreeだけを編集している
- [ ] Claudeがcommit / branch変更していない
- [ ] child Gitからpushできない
- [ ] テストPASSを確認した
- [ ] Astraはread-onlyレビュー
- [ ] review前後のdiff fingerprintが一致
- [ ] 変更要求があればClaude修正 → 再テスト → 再レビュー
- [ ] 最大2ラウンドの境界を越えて自動反復していない

## candidate確定時

- [ ] Tests PASS + Astra APPROVE
- [ ] candidateを完全40桁SHAで特定した
- [ ] source repoのbase HEADが開始時から動いていない
- [ ] originが想定外に進んでいない
- [ ] reviewed diff以外の変更が混ざっていない
- [ ] push / BUILD / UPDATE / DEPLOYは未実施

## local expected branchへ適用するとき

- [ ] ユーザーがlocal candidate適用を確認した
- [ ] base SHA == current local HEAD
- [ ] branch / origin / tracked cleanが安全
- [ ] candidateがbaseのfast-forward descendant
- [ ] ff-onlyで適用した
- [ ] 適用後HEAD == candidate SHA
- [ ] tracked clean

## RUN_DEV / 実機確認

- [ ] 実機確認対象SHAが完全40桁で特定できる
- [ ] RUN_DEVで対象機能を確認した
- [ ] GUI / 実紙 / printer / LAN / 外部サービス等、変更に必要な実機項目を確認した
- [ ] NGなら旧candidateを本番へ進めず、新candidateとして再確認する

## ユーザーOK後 / push

- [ ] 承認後にamend / rebase / squash等でSHAを変えていない
- [ ] remoteが想定外に進んでいない
- [ ] pushはfast-forward前提
- [ ] pushed SHA == confirmed SHA

## BUILD / deploy

- [ ] HEAD == confirmed SHA
- [ ] pushed SHA == confirmed SHA（pushを伴うアプリ）
- [ ] tracked clean
- [ ] BUILDで実体が変わるアプリは完成binaryを配布前に起動確認した
- [ ] 実機確認前の本番配布ではない
- [ ] NG candidateではない
- [ ] confirmed SHA == pushed SHA == BUILD対象SHA

## 不要な確認

次は毎回の必須チェックではありません。

- 旧A/B経路の分類
- T0〜T3の分類
- 全Development文書の読み直し
- 毎ターンのcontract再照合
- 同じテストのActions / ローカル重複実行
- Actions green待ちだけを理由にした開発停止
- 固定フォーマットの長い完了報告
