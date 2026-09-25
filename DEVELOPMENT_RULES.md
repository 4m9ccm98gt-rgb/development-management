# 開発ルール

この文書は実装・配布・データ保護の補助ルールです。運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 正式ソース

- GitHub上の正式repoを基準にする。
- 既存変更を保護し、force push / 無断rebase / 履歴破壊を行わない。
- 秘密情報、認証情報、実運用設定、顧客データ、業務データ、cache、実行結果をGit管理しない。
- 設定例はダミー値の `*.example.*` 等を使用する。

## 開発ルートと確認

通常DevelopmentはClaude / Codexが正式ローカルrepoで直接実装します。GPTは相談・要件整理・設計・指示文作成を担当します。DCCはRUN / BUILD / UPDATEを担当し、Orchestratorは別画面の任意の第二ルートです。

RUN / BUILDはcandidateやtracked cleanを要求しません。UPDATEは成果物と配布先を明示し、BUILD記録・hash・ユーザー実機確認を根拠に明示操作で行います。Orchestrator内部candidateの安全条件は専用文書を参照します。

## テスト

- 変更箇所に対応するtargeted testを優先する。
- 共有処理や広い影響がある場合だけ必要なregressionを追加する。
- 同じ対象・環境・内容の成功済みテストを理由なく重複実行しない。
- `compileall`、unit test、integration test、build validation、実機確認は別目的として必要なものを選ぶ。
- GUI、実紙、printer、LAN、共有先、外部サービス、実HDD等は必要に応じてユーザー実機確認へ残す。

## Windowsアプリ

- 開発版は可能なら `RUN_DEV.cmd` 等の安全な入口から起動できる状態を維持する。
- 正式BUILD / updateには既存の `BUILD_*_CLICK_ME.cmd` / `UPDATE_*` 等を優先する。
- BUILDは現在の作業内容を記録し、入力が変化した成果物を無条件に配布しない。
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
