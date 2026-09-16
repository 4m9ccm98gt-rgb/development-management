# 開発ルール

この文書は実装・配布・データ保護の補助ルールです。運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 正式ソース

- GitHub上の正式repoを基準にする。
- 既存変更を保護し、force push / 無断rebase / 履歴破壊を行わない。
- 秘密情報、認証情報、実運用設定、顧客データ、業務データ、cache、実行結果をGit管理しない。
- 設定例はダミー値の `*.example.*` 等を使用する。

## A — ChatGPT fast path

- ChatGPTがGitHubへ書き込み可能なら、依頼範囲でコード調査、実装、テスト追加、branch / commit / push / PR、差分レビュー、candidate SHA確定まで進めてよい。
- Actionsは補助。Actions greenをcandidateの必須条件にしない。
- 実行できないテストを実施済みとは扱わない。
- GitHub candidateをWindowsへ反映する場合は、既存の安全な `SYNC_CLICK_ME.cmd` 等を優先する。

## B — Debug escape path

ユーザーがCodex / Claude等を指定した場合、指定エージェントがWindowsローカルrepoでデバッグを完結させてよい。

- 開始時にlocal HEAD / expected origin / branchを確認する。
- working treeで修正・targeted test・必要なregressionを繰り返す。
- 修正ごとのpush / Actions待ち / 再SYNCは不要。
- 完成時にlocal candidate commitを作り、tracked cleanを確認する。
- 既知良好SHAからcandidateまでの実差分を一度レビューする。
- ユーザー実機確認OK後、同じSHAをfast-forwardでpushする。
- remoteが進んでいたらforceせず停止する。

## candidateと実機確認

- candidateは完全SHAで特定する。
- AではGitHub candidateを同期してユーザーが確認する。
- Bではlocal candidateをそのままユーザーが確認するため、GitHub→Windowsの同期工程は不要。
- 実機確認開始時はHEADがcandidate SHAで、tracked cleanであることを確認する。
- NG candidateを本番へ進めない。
- **confirmed SHA == pushed SHA == BUILD対象SHA** を守る。

## テスト

- 変更箇所に対応するtargeted testを優先する。
- 共有処理や広い影響がある場合だけ必要なregressionを追加する。
- 同じ対象・環境・内容の成功済みテストを理由なく重複実行しない。
- `compileall`、unit test、integration test、build validation、実機確認は別目的として必要なものを選ぶ。
- GUI、実紙、printer、LAN、共有先、外部サービス、実HDD等は必要に応じてユーザー実機確認へ残す。

## Windowsアプリ

- 開発版は可能なら `RUN_DEV.cmd` 等の安全な入口から起動できる状態を維持する。
- 正式BUILD / updateには既存の `BUILD_*_CLICK_ME.cmd` / `UPDATE_*` 等を優先する。
- 正式BUILD時はHEADがconfirmed SHAで、tracked cleanであることを確認する。
- Nuitka / PyInstaller / .NET/WPF等、BUILDで配布実体が変わる場合は完成binaryを配布前に起動確認する。
- 配布物と業務データ・実運用設定を分離する。
- 共有フォルダ全体への無条件な破壊的同期を避ける。

## 本番反映

- ユーザー実機確認前に本番反映しない。
- tag、本番共有フォルダ更新、実運用DB更新、実プリンター送信、実HDD更新等は明示された正式手順で行う。
- AIは未確認の本番操作を完了済みと表現しない。

## 横断調査と記録

- 新方式導入・既存方式置換・repo横断変更など、実際に必要な場合だけ他repoや `REUSE_MAP.md` を確認する。
- 局所修正で理由なく全repoを横断しない。
- 将来の判断に本当に必要な設計・運用変更だけ `docs/decisions.md` / `LESSONS_LEARNED.md` / `projects/*.md` 等へ残す。
- 仕様や運用が変わらない修正で、無関係なREADMEや管理文書を形式的に更新しない。
