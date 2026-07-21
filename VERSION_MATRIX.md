# Version Matrix

実運用中の版、GitHub上の版、ローカルの作業状態を混同しないための確認表です。

最終調査日: 2026-07-21（JST）

## 判定上の注意

- 「最新確認タグ」はローカルGitで確認できた最新タグであり、実運用中バージョンを保証しない。
- `next-day-setup` と `inventory-reconciliation-system` には未コミット変更がある。これらが実運用版へ反映されている可能性があるため、タグと実運用版の一致は未確認とする。
- 「未確認」は推測で補わず、実機、共有版、本番環境または担当者への確認が必要な項目を示す。

## next-day-setup

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `next-day-setup` |
| 最新確認タグ | `v1.1.0` |
| mainの最新コミット | `b63c756` — `Switch staff shifts to web page`（2026-07-15） |
| 実運用中バージョン | 未確認 |
| デモ機版 | 未確認 |
| 共有版または本番版 | 未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\next-day-setup` |
| 使用Python | Python 3.13、リポジトリ直下の`.venv` |
| 主要依存関係 | `openpyxl 3.1.5`、`Pillow 12.2.0`、`PyInstaller 6.21.0` |
| 最終動作確認日 | 未確認 |
| 確認済み機能 | 未確認 |
| 未確認機能 | Google Sheetsシフト取得、席割・担当割、各種帳票、連続印刷、現場での追加印刷、EXE起動、共有版更新、業務データ保持、`_internal`完全同期 |
| GitHubと実運用版が一致しているか | 未確認 |
| 備考 | `main` に未コミット変更と未追跡ファイルがある。タグ以後の変更や未コミット変更が実運用版へ反映済みかは未確認。 |

## inventory-reconciliation-system

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `inventory-reconciliation-system` |
| 最新確認タグ | `v2.0.0` |
| mainの最新コミット | `1c83abe` — `Remove legacy print platform`（2026-07-15） |
| 実運用中バージョン | 未確認 |
| デモ機版 | 未確認 |
| 共有版または本番版 | 未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\inventory-reconciliation-system` |
| 使用Python | Python 3.13、リポジトリ直下の`.venv` |
| 主要依存関係 | `openpyxl 3.1.5`。標準ライブラリや外部アプリケーションとの連携範囲は別途確認が必要。 |
| 最終動作確認日 | 未確認 |
| 確認済み機能 | 未確認 |
| 未確認機能 | Google Sheets休館日取得、キャッシュ正常系・異常系、在庫照合、手間いらず／JTB取得、PIN取得補助、夜間自動実行、Excel出力、警告メール |
| GitHubと実運用版が一致しているか | 未確認 |
| 備考 | `main` に未コミット変更と未追跡ファイルがある。タグ以後の変更や未コミット変更が実運用版へ反映済みかは未確認。 |

## beverage-inventory-ordering-system

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `beverage-inventory-ordering-system` |
| 最新確認タグ | なし |
| mainの最新コミット | `8d2ab9c` — `Import beverage inventory management system`（2026-07-20） |
| 実運用中バージョン | 正式化前から運用中の飲料在庫管理版。コミットによる版番号は未設定 |
| デモ機版 | 未確認 |
| 共有版または本番版 | ブラウザローカル保存で実運用中。配布先とのファイル一致は未確認 |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system` |
| 使用環境 | ブラウザで`index.html`を起動 |
| 主要依存関係 | 外部パッケージなし。静的HTML、CSS、JavaScript |
| 最終動作確認日 | 2026-07-20 |
| 確認済み機能 | JavaScript構文、ブラウザ起動、コンソールエラーなし、発注中数量を加味した要発注判定の実装、JSON保存・復元 |
| 未確認機能 | 実運用端末とのファイル一致、複数PC共有、飲料発注アプリ統合 |
| GitHubと正式ローカルが一致しているか | 一致。`HEAD`、`main`、`origin/main`はいずれも`8d2ab9c`、Git statusクリーン |
| 備考 | アプリ本体と文書はGitHub反映済み。次は飲料発注アプリの取り込み調査を行う。 |

## call-reception-assistant

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `call-reception-assistant` |
| 最新確認タグ | なし |
| mainの最新コミット | `95bd3ca` — `Record initial repository synchronization`（2026-07-21） |
| 実運用中バージョン | なし |
| デモ機版 | なし（無課金社内試作の設計前） |
| 共有版または本番版 | なし |
| 正式ソースのローカルパス | `C:\Users\suisy\Documents\Development\repos\call-reception-assistant` |
| 使用環境 | Windows PCを予定。技術構成は未決定 |
| 主要依存関係 | 未決定。外部AI API・有料APIは初期試作で使用しない |
| 最終動作確認日 | 未確認（アプリ本体なし） |
| 確認済み機能 | 対象なし。GitHub到達、空リポジトリclone、初期文書構成を確認 |
| 未確認機能 | 全機能。音声認識、音声合成、対話、外部連携はいずれも未実装 |
| GitHubと正式ローカルが一致しているか | 一致。`HEAD`、`main`、`origin/main`はいずれも`95bd3ca`、Git statusクリーン |
| 備考 | 電話回線、手間いらず・Hub実接続、実在庫変更、PMS自動入力は初期対象外。プロジェクト化完了、アプリ本体未実装 |

## menu-sheet-generator

| 区分 | バージョン / コミット | 状態 |
|---|---|---|
| GitHub版 | `main` / `6e97ccea6b8afe237af9b83dc4bae9eae9495cdf` | Private、正式版 |
| 正式ローカル版 | `C:\Users\suisy\Documents\Development\repos\menu-sheet-generator` / 同上 | GitHub `main`と同期、作業ツリー clean |
| 開発版 | 正式ローカル版の`main` / 同上 | 登録時点で正式版と同一 |
| `publish`配布版 | 自己完結型`win-x64` / 同上 | `BUILD_RELEASE.cmd`で再生成可能 |
| 共有フォルダ実運用版 | ワンクリック配布版 / 同上 | 実運用・実プリンター確認済み |

- 最新コミット: `6e97ccea6b8afe237af9b83dc4bae9eae9495cdf`
- 同期状態: GitHub版、正式ローカル版、開発版、`publish`配布版、共有フォルダ実運用版は2026-07-21時点で同一コミット由来。
- 実運用データと配布先実パスはGit管理外。

## development-management

| 項目 | 内容 |
|---|---|
| GitHubリポジトリ名 | `development-management` |
| 最新確認タグ | なし（初回コミット前） |
| mainの最新コミット | なし（初回コミット前） |
| 実運用中バージョン | 未確認 |
| デモ機版 | 対象外（開発知識を管理する文書リポジトリ） |
| 共有版または本番版 | GitHub反映前 |
| 正式ソースのローカルパス | 未確認。現在の作業場所は `C:\Users\suisy\Documents\開発環境整備プロジェクト`。 |
| 使用Python | 対象外（文書のみ） |
| 主要依存関係 | なし（Markdown文書のみ） |
| 最終動作確認日 | 対象外。文書構成確認日は2026-07-16。 |
| 確認済み機能 | 管理文書、AI開始手順、プロジェクト状況、開発ルール、設計判断、テンプレート、全体構成のローカル作成 |
| 未確認機能 | GitHubでの表示、内部リンク、別チャット／別Codex環境からの引き継ぎ、初回clone後の利用性 |
| GitHubと実運用版が一致しているか | 一致していない。ローカル文書は初回コミット／push前。 |
| 備考 | コードを持たない正式な開発知識ベース。現在の全ファイルは未追跡。 |

## 更新手順

1. リリースまたは実運用確認時に、タグ、コミット、配布先の版を確認する。
2. 実機で確認した日付と機能だけを「確認済み」として記録する。
3. `PROJECT_STATUS.md`、対象の`projects/*.md`、`CHANGELOG.md`と同時に更新する。
4. 未コミット変更が配布されている場合は、タグではなくコミットまたは差分を特定してから記録する。
