# 設計判断

重要な設計判断は、チャットだけで終わらせず必ずここへ記録する。
将来の開発者やAIが「なぜその設計になったか」を理解できることを目的とする。

新しい判断を追加するときは、必要に応じてルートの [DECISION_TEMPLATE.md](../DECISION_TEMPLATE.md) を使用する。

## 作業割り当てをエージェント名から「能力ベース」に切り替える

- 日時: 2026-09-02（JST）
- 決定内容: ChatGPT / Codex というエージェント名で作業を割り当てるのではなく、セッションが実際に持つ能力（`github-rw` / `sandbox-exec` / `windows-real` / `real-peripherals` / `shared-server`）で判定する。判定基準は [CAPABILITIES.md](../CAPABILITIES.md) を正本とする。
- 理由:
  - 1セッションが複数能力を同時に持つ場合（実機上のClaude Code等）、エージェント名ベースでは担当が決まらない。
  - 「ChatGPTがGitHub更新 → Codexが実機実装」の運用には、実機側の作業前 pull・作業後 push が必要だが、誰の責任か未明文化で、ローカルとGitHubがずれてハンドオフが切れた（本件、2026-09-02）。
  - ツール構成が変わっても判定ルールが陳腐化しないようにする。
- 採用案: 能力の定義表 ＋ 「作業種別→必要能力」表 ＋ 正式ローカルリポジトリの同期規約（pull前・push後を必須化）を [CAPABILITIES.md](../CAPABILITIES.md) に置く。
- 却下案:
  - 案: エージェント名ベースの現行記述を維持し、Claude Code を第3の担当として追記するだけにする。
  - 却下理由: 能力が重なるケースと新ツール追加のたびに記述が増え、同じ陳腐化を繰り返す。
- 影響範囲: [AI_OPERATING_MANUAL.md](../AI_OPERATING_MANUAL.md) / [AGENTS.md](../AGENTS.md) / [AI_STARTUP.md](../AI_STARTUP.md) のエージェント名ベースの担当記述は、将来 [CAPABILITIES.md](../CAPABILITIES.md) へのポインタに整理する（今回はポインタ追記のみ、本文は維持）。既存2判断（GitHub側実装の第一担当／ソース起動・手動ビルド・ワンクリック配布）の意図は変更しない。
- 関連リポジトリ: development-management（本件）、food-cost-calculation-system / beverage-inventory-ordering-system（同期規約の適用先）
- 確認状況: 未確認（文書のみ。実運用での効果は次のハンドオフで確認する）
- 関連資料・Issue・コミット: 2026-09-02 の development-management 同期ずれ（`DEVELOPMENT_RULES.md` / `REUSE_MAP.md` がローカル未コミットのまま、`main` が origin より遅延）
- 備考: `templates/windows-python-app/` と `scripts/check_standards.py` は本判断の実装として追加済み（2026-09-02）。テンプレートは `beverage-inventory-ordering-system/python_app/` の実績3スクリプトを汎用化した。`check_standards.py` はアプリがサブディレクトリにある場合も検出し、アプリ種別（desktop / web / service / lib / archived）ごとに必要経路を切り替える。
- 種別情報の管理場所: **`development-management/scripts/repo_types.toml` を唯一の正とする**。横断管理の情報なので司令塔に一元化し、アプリ側のリポジトリには種別マーカーを置かない。`check_standards.py` はこの表の登録値だけを正式判定に使い、未登録は警告する（依存関係からの自動判定は警告文のヒント専用）。アプリ側には `RUN_DEV.cmd` 等の実際に必要な開発用ファイルだけを置く。

### 次の対応

- [x] AGENTS.md / AI_STARTUP.md に CAPABILITIES.md へのポインタを追記する
- [x] `templates/windows-python-app/` と `scripts/check_standards.py` を追加する
- [x] `check_standards.py` にアプリ種別を導入し、Webアプリへの的外れ警告を除去（WARN 13 → 7）
- [x] 種別情報を `repo_types.toml` に一元化し、アプリ側マーカーを廃止（全8アプリ登録、kitchen-calendar は archived）
- [x] NDS パイロット成功: ブランチ `claude/standardize-run-dev`、PR `next-day-setup#2`（Draft 解除済み）。`cmd.exe /c RUN_DEV.cmd`（実ダブルクリック相当）で venv 作成 → `pip install`（12パッケージ）→ `hotel_app.py` 起動 → Tk ウィンドウ生成（1180x720）→ ネットワーク試行 NONE → 正常終了（exit 0）を一時 clone で実機確認。副作用は gitignore 対象の監査ログ1行のみ、正式ソース未変更。`check_standards.py` の NDS 警告解消（WARN 7 → 6）。
- [x] 途中で `.cmd` の落とし穴を修正（非 ASCII コメント / `if(...)` 内の括弧 / `-c` のカンマ / CRLF）。テンプレートと `LESSONS_LEARNED.md` へ反映、両リポジトリに `.gitattributes` 追加。
- [x] PR `next-day-setup#2` を squash merge（`277aa69`）。ブランチ削除。正式ローカルを `main` へ戻して pull 済み。`RUN_DEV.cmd` + `.gitattributes` が main に入った。
- [x] 残り展開完了：food-cost（PR #1 `8008fb7`）、inventory-reconciliation（PR #1 `1ca3793`）、qr-supply（PR #1 `eb2068a`、`DEPLOY.md` 含む Web パターン）。各々一時 clone で `cmd.exe /c RUN_DEV.cmd` end-to-end 実機確認、実運用データ（DB / 資格情報）は SHA-256 不変。
- [x] qr-supply の GitHub/正式ローカルのズレ解消：実アプリ（Phase 1/1.5/発注表取込）を `feature/phase1-implementation` として GitHub へ保存（混入監査済み）→ `qr-supply#2`（`1b3879e`）で `main` へ。標準化 `qr-supply#1` は別履歴（`eb2068a`）。
- [x] 最終 `check_standards.py`：ERROR 0 / WARN 0（9リポジトリ）。**開発環境整備 一巡完了（2026-09-04）**。
- [ ] `check_standards.py` を各リポジトリの GitHub Actions（warning-only）へ追加する（`development-management` 参照が必要）
- [ ] 次のハンドオフで同期規約が機能するか確認する

## Python/Windowsアプリはソース起動を標準とし、EXEは手動ビルド、配布更新もワンクリック化する

- 判断: Pythonで作るWindowsアプリは、日常の開発・確認では正式ソースを `.venv` から直接起動する。EXEは必要時だけユーザーがワンクリックで手動ビルドする。Codexには通常のEXEビルドを依頼しない。
- 標準起動: `RUN_DEV.cmd` または同等のワンクリック起動手段を各Python/Windowsアプリに用意する。
- 標準ビルド: EXE配布するアプリには `BUILD_EXE_CLICK_ME.cmd` または同等のワンクリックビルドを用意し、可能な範囲でテスト、ビルド、成果物確認まで自動化する。
- 標準配布更新: 配布対象アプリには `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須とし、ユーザーがCodexを使わず配布先更新できるようにする。
- 理由: CodexによるEXEビルドはクレジット消費が大きく、単純なビルド・配布作業へ継続的に使う費用対効果が低い。開発版をソース起動可能にし、定型処理をワンクリックスクリプト化することで、CodexをWindows固有不具合の調査や実機でしか確認できない作業へ温存できる。
- 影響: 「実装後はCodexがEXEを作る」を標準フローから外す。通常の開発確認はPythonソース版で行い、EXE固有確認が必要な場面のみユーザーが手動ビルドする。
- Codex例外: 手動ビルドが失敗した、PyInstaller/Nuitka固有エラーが出た、EXEだけで再現する問題がある等、原因調査が必要な場合のみCodexを使用する。
- 配布安全性: 配布スクリプトは配布物と業務データを分離し、共有フォルダ全体への単純な `/MIR` を避け、更新前後の業務データ保持を確認する。
- 適用範囲: 新規アプリだけでなく、今後既存Windowsアプリを改修する際にも可能な範囲で「ソース起動・手動ビルド・手動配布更新」の3経路へ統一する。

## ChatGPTをGitHub側の第一実装担当とし、Codexを実機作業へ優先配分する

- 判断: ChatGPTが対象GitHubへ直接アクセスできる場合、調査・設計に加えてGitHub上の実装、テスト追加、ブランチ作成、commit、push、PR作成、レビューまでChatGPT側で行う。CodexはWindows実機、正式ローカル、実プリンター、共有サーバー、ローカル専用ファイルなどChatGPTから直接扱えない作業を第一担当とする。通常のEXEビルドはCodex担当から除外する。
- 理由: GitHub上だけで完結する作業をCodexへ重複依頼せず、Codexクレジットを実機・ローカル依存作業へ温存しながら、設計から実装・レビューまでの文脈をChatGPT側で連続して保持するため。
- 影響: 従来の「ChatGPTが指示書を作り、Codexが原則実装する」運用は標準ではなくなる。ChatGPTからCodexへ渡す時点では、対象branch/commit、実装済み範囲、テスト結果、残作業、本番反映可否を明示する。
- 安全条件: GitHub上の自動テスト、Pythonソース版のWindows実機確認、EXE確認、共有版確認を分離する。PR merge、安定版タグ、本番共有フォルダ反映、実運用データ更新は、従来どおり明示的な判断と必要な確認を経て行う。
- 初回適用: `beverage-inventory-ordering-system` のPython移行で、ChatGPTが `python-desktop-migration` ブランチとDraft PR #2を作成。以後、CodexはPythonソース版のWindows実機確認など必要な部分に限定し、EXEビルドは手動ワンクリックへ切り替える。

## 正式ソースを `Development\repos` に統一

- 判断: 新規開発、修正、ビルド、コミットは正式パスだけで行う。
- 理由: 複数コピーによる変更分散と、どれが最新か分からない状態を防ぐため。
- 影響: 旧フォルダは参照専用とする。

## 各プロジェクトで `.venv` を使用

- 判断: 依存関係をプロジェクト単位で分離する。
- 理由: Pythonやライブラリの混在を防ぎ、ビルドと再現性を安定させるため。
- 影響: 起動、テスト、ビルドは各リポジトリ直下の`.venv`を使う。

## Google Sheetsを正式参照元に変更

- 判断: スタッフシフトと休館日は所定のGoogle Sheetsを正式参照元とする。
- 理由: 現場で更新される情報を一元参照し、ローカル固定値とのずれを減らすため。
- 影響: 通信・形式異常時の検証と、必要な箇所ではキャッシュ／フォールバックが必要。

## 共有版は配布物と業務データを分離

- 判断: EXEと`_internal`等の配布物を、業務データ・実運用設定から分けて更新する。
- 理由: ランタイムの完全同期と、現場データ保護を両立するため。
- 影響: `_internal`は完全同期するが、共有フォルダ全体への単純な`/MIR`は禁止する。

## GitHubを開発の現在地として使う

- 判断: GitHub上の各業務リポジトリと本管理リポジトリを、共有できる開発履歴・現在地とする。
- 理由: 新規チャット、別環境、別担当者でも履歴と判断を追えるようにするため。
- 影響: 未コミット変更は共有されないため、適切な単位で検証・文書更新・commit・pushを行う。

## call-reception-assistantの初期試作はローカル・無課金・外部非接続とする

- 判断: 初期試作はWindows PCのマイクとスピーカーで完結させ、音声認識・音声合成はローカル実行を基本とする。外部AI API、有料API、電話回線、手間いらず・Hubの実接続、実在庫変更、PMS自動入力は行わない。
- 理由: 社内で対話受付の有用性を無課金かつ安全に検証し、個人情報、予約、在庫、外部サービスへ影響を与えないため。
- 影響: 外部連携は将来交換可能な境界として設計し、初期実装ではモック／スタブだけを使用する。PMS入力は将来もスタッフの手作業とする。

## ケーキ発注書は業務日範囲で休館日前倒しする

- 判断: 受取日は対象業務日＋4日に固定し、休館日または翌日が休館日である業務日を翌日準備の未実行日として、直前の通常実行日に日付別で前倒し印刷する。
- 理由: 休館前日・連続休館中の欠落を防ぎつつ、次の通常実行日を範囲外にすることで永続的な印刷済み管理なしに重複を防ぐため。
- 休館日取得: `inventory-reconciliation-system` と同じGoogle Sheets公開CSV、見出し解析、3日キャッシュ判定を使う。独立配布を維持するため実行時のリポジトリ間依存は作らず、取得・解析契約を `next-day-setup` 内にも明示する。
- 異常時: 有効な休館日情報がない場合は前倒しを行わず通常分だけを実行し、画面とログへ警告を残す。

## 飲料発注システムは在庫管理リポジトリ内のサブシステムにする

- 判断: 飲料発注システムは独立した別プロジェクトにせず、`beverage-inventory-ordering-system` の `apps/ordering/` に移管し、飲料在庫管理システムから起動するサブシステムとして管理する。
- 理由: 商品マスタ、発注先、発注履歴、発注中数量は在庫管理と密接に関係するため、別リポジトリ化するとデータ構造と運用判断が分散する。1プロジェクト内で段階的に統合した方が安全。
- 影響: 単体タスクでの発注アプリ開発は今回の移管で終了し、今後は `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system` を正本にする。実業者名、実FAX番号、実発注履歴はGit管理せず、開発用サンプルデータで起動確認する。

## ビルド成果物に出所（HEAD SHA + 成果物 SHA-256）を残す

- 判断: 配布用ビルドは、成果物と同じフォルダに `BUILD_INFO.txt`（Git branch / commit SHA /
  ビルド日時 / EXE SHA-256 / ビルドモード）を出力する。俺伝 `tools/release/build_release.ps1` の
  方式を標準とし、`next-day-setup/build_exe.py` と `menu-sheet-generator/BUILD_RELEASE.cmd` にも
  同等の出力を足す（次サイクル）。
- 理由: H7（`docs/build_deploy_paths.md`）で、俺伝以外は成果物単体から「どのコミットで作ったか」を
  追跡できないと判明した。退役後に AI 支援が薄い状態で「配布中の EXE の出所」を確認できる必要がある。
- 影響: 配布スクリプト側（`update_hdd.ps1` は既に `BUILD_INFO.txt` の EXE SHA-256 を再照合）でも
  出所チェックを共通化できる。NDS はビルド時のクリーンツリー要求（俺伝 `Assert-CleanWorkingTree` 相当）が
  無いため、`BUILD_INFO.txt` 追加と合わせて未コミット状態の警告も検討する。
- **実施（2026-09-05、next-day-setup）**: `build_exe.py` に `write_build_info()` を追加し、
  `dist/DinnerSystem/BUILD_INFO.txt`（Git branch / commit SHA / working tree clean-dirty 状態 /
  ビルド日時 / アプリバージョン / EXE 名・サイズ・SHA-256）を出力するよう対応済み（PR #5、`614c985`）。
  非本番ビルドで dirty tree・clean tree 双方を実際に検証し、Git HEAD SHA・EXE SHA-256 とも独立再計算値と
  完全一致することを確認済み（[projects/next-day-setup.md](../projects/next-day-setup.md) 参照）。
  クリーンツリー要求（`Assert-CleanWorkingTree` 相当）は既存のビルド運用への影響を避けるため、今回は
  見送り、残課題として記録する。**menu-sheet-generator は未対応のまま。**
- **実施（2026-09-05、next-day-setup、NDS hardening Phase 1）**: 上記で見送ったクリーンツリー要求を
  `build_exe.py` に追加（既定でdirty tree拒否、`--allow-dirty` は非常用override）。あわせて配布側
  （`update_shared_folder.ps1`）にも `Assert-SourceBuildInfo` を追加し、BUILD_INFO.txt記載のEXE SHA-256・
  working tree状態・コミットが現在の正式HEADと一致することを配布前に検証するようにした
  （PR #6、`0d134be`。詳細は [projects/next-day-setup.md](../projects/next-day-setup.md)）。
  **menu-sheet-generator はBUILD_INFO.txt自体が未対応のまま。**

## JSON保存はアトミック書き込み＋破損時隔離を、重要度の高いファイルから段階的に適用する

- 判断: NDSの各種JSON設定・業務データファイルについて、直接 `Path.write_text()` で上書きする方式から、
  一時ファイル書き込み＋fsync＋再パース検証＋`os.replace()`によるアトミック書き込みへ移行する。
  読み込み失敗時は「不存在（初回起動）」と「壊れている」を区別し、壊れている場合は元ファイルを
  そのまま保護した上で別名複製（隔離）し、黙って初期化・上書きしない。
  NDS全体を一度に書き換えるのではなく、重要度の高いファイルから段階的に適用する。
- 理由: レビューで `master_settings.json` が破損時に警告なく既定値へフォールバックし、そのまま保存すると
  元の内容が失われる可能性が指摘された。直接上書き方式はクラッシュ・電源断・書き込み中断時に
  ファイルそのものを壊すリスクもある。
- 採用案: 共通ヘルパー `next-day-setup/dinner_system/json_safety.py`（`atomic_write_json` /
  `backup_existing_file` / `quarantine_corrupted_file`）を新設し、`master_settings.json`・
  日次保存データ（`保存データ/YYYY-MM-DD.json`）・`closing_tasks.json` の順に適用（NDS hardening
  Phase 2、PR #7、`754d214`）。
- 却下案: NDS全JSON I/Oを一度に書き換える一括対応。却下理由: 影響範囲が大きく、業務中の日次運用を
  壊すリスクがレビュー方針（大規模リファクタリング回避）に反する。
- 影響: `ui_prefs.json`・`print_preparation.json`等の低優先度JSONは当面現状維持。SQLiteと日次JSONの
  整合性統一（`seats`/`staff_assignments`/`closing_task_snapshot`はSQLiteに存在しない）は別課題として
  次サイクルへ持ち越し。詳細は [projects/next-day-setup.md](../projects/next-day-setup.md) と
  next-day-setup 側 `docs/JSON_SAFETY_PHASE2.md` を参照。
- 関連リポジトリ: next-day-setup。
- 確認状況: 実施済み。ローカル・GitHub Actions CIで検証済み、実物の設定ファイルコピーで後方互換確認済み。

## 日次JSON/SQLiteの不整合は検出のみ行い、自動修復・自動上書きは一切しない

- 判断: NDSの日次保存データ（`保存データ/{date}.json`、正本）とSQLite（`kitchen_data.sqlite3`）の
  PMS取込履歴の間に食い違いを検出した場合、どちらか一方をもう一方に合わせて自動的に上書き・復元する
  ことはせず、`messagebox.showwarning`でユーザーに知らせるだけに留める。同様に、SQLite側に
  `operator_state_backup`テーブルを追加して`seats`/`staff_assignments`/`closing_task_snapshot`
  （従来SQLiteに一切存在しなかった日次JSON唯一のコピー）のベストエフォート冗長コピーを持たせるが、
  これも自動復元機能は持たせず、日次JSONを正本のまま維持する。
- 理由: 日次JSONとSQLiteは保存タイミング・トランザクション境界が異なり（3B調査で判明）、どちらが
  「正しい」かをコードが機械的に判断できるとは限らない。誤った側へ自動的に揃えると、手動で調整した
  席割・担当割・締め作業の配置（SQLiteには存在しない情報）を silently 失う恐れがある。
- 採用案: `compare_kitchen_snapshot_provenance`によるPMS取込ID比較（`match`/`json_stale`/
  `sqlite_stale`/`no_snapshot`/`unknown`の5分類、警告表示のみ）と、`operator_state_backup`テーブル
  （読み出し関数のみ提供、自動復元なし）を、NDS hardening Phase 3（PR #8、`9606da9`）として実装。
  あわせて`monthly_tasks.json`・締め作業日次スナップショットの「破損時に空状態へ静かにリセットする」
  挙動も、`ScheduledTaskStateLoadError`/`ClosingTaskDailyLoadError`を送出し元ファイルを変更しない
  設計へ変更（PR前の全call-site監査で、印刷系の未保護呼び出し元2箇所も追加修正）。
- 却下案: 不一致検出時にSQLite側の最新取込内容で日次JSONを自動上書きする案。却下理由: `seats`/
  `staff_assignments`/`closing_task_snapshot`はSQLiteに存在しないため、上書きすればこれらのJSON専有
  データを失う。逆に日次JSONの内容でSQLiteを上書きする案も、SQLite側の`business_day_snapshot`履歴
  （`version`管理）と矛盾するため却下。
- 影響: 復旧はあくまで「人が判断して行う」ことが前提。将来、復旧候補として`operator_state_backup`を
  実際に使うUIを作る場合は、`work_data_saved_at`が必ずしも最新のバックアップ成功時刻ではない
  （SQLite側保存が失敗すると古い値のまま残る）ことを踏まえ、日次JSON側の保存日時と必ず突き合わせる
  必要がある（[projects/next-day-setup.md](../projects/next-day-setup.md)、next-day-setup 側
  `docs/PHASE3_DATA_CONSISTENCY.md`参照）。
- 関連リポジトリ: next-day-setup。
- 確認状況: 実施済み。ローカル・GitHub Actions CIで検証済み、一時環境でのリカバリーシナリオテストと
  呼び出し元回帰テストで確認済み。自動復元・自動上書きロジックが存在しないことをgrepで確認済み。

<!-- 以下は旧cloneの未push编集から救出した設計判断。canonical に未反映だったもの。 -->

## 期間限定タスクエンジンを採用する

- 判断: 月末棚卸しを棚卸し専用機能として増築せず、条件に応じて締め作業を生成・割り振る共通の「期間限定タスクエンジン」として実装する。新しい期間限定業務は原則としてコード修正ではなくマスタ設定の追加で対応する。
- 理由: 月初作業、季節作業、年末年始対応、定期点検などが増えるたびに専用処理を追加すると保守性が低下するため、条件付き業務の発生・配置・完了・持ち越しを共通化する。
- 構造: タスク定義 `scheduled_tasks` と発生インスタンス `scheduled_task_instances` を分離する。状態ファイル名 `monthly_tasks.json` は安全な互換のため維持し、当日の配置は既存の日別スナップショットで管理する。
- 対応条件: 月末を含む指定日数、月初から指定日数、任意の日付範囲。同一年と年またぎを安定した期間IDで扱う。
- マスタ項目: 業務負荷、対象シフト、最低残りポイント、強制配置、手動移動制限、出現条件、持ち越し設定、同時発生上限、完了必須、表示順、備考をタスク単位で設定できる。
- 状態: `open` / `completed` のみ。持ち越し無効でも過去状態を削除・自動完了せず、期間外では表示と同時上限計算から外す。完了必須タスクは配置・保存だけで完了にせず、確認付きの明示操作で完了させる。
- 後方互換: 旧 `monthly_tasks` 定義、旧 `tasks` 状態、旧モジュール直下 `monthly_tasks.json` を読込時に変換する。実運用データは初期化せず、画面表示だけでは移行保存・旧ファイルの書換えを行わない。
- 保存先: `保存データ/締め作業/monthly_tasks.json`。配布物と業務データの分離方針を維持する。
- 今後の拡張候補: 曜日、予約人数、使用会場、休館日前、イベント、手動トリガー。複雑な条件式（AND / OR）は現時点の実装対象外とする。
- 効果: 締め作業システムを、固定タスクを割り振る仕組みから、条件に応じて業務を生成・割り振る基盤へ拡張する。

## 台帳カレンダーの休館日表示は注意喚起に限定する

- 判断: 夕食・朝食の日付選択と保存データカレンダーでは、既存の休館日取得結果を読み取り専用で表示し、休館日・休館前日も選択可能なままとする。
- 表示: 休館日を最優先し、対象日が休館日でなければ翌日が休館日の場合だけ休館前日とする。これにより連続休館中の日は休館日表示を維持する。
- 理由: 日付選択時の認識漏れを防ぎつつ、過去データ確認や例外運用を妨げず、台帳読込・印刷処理への影響を避けるため。
- 異常時: 3日以内の有効キャッシュもなければ通常表示へフォールバックし、取得不能を画面とログへ残してカレンダーは継続利用する。

## 発注書への振り分けは手配先だけを管理する

- 判断: PMSから検出した手配先名を蓄積し、`発注書ID → 手配先名集合` の紐づけだけを補助システムで管理する。
- 理由: 商品名キーワードの保守を不要にしつつ、PMSの商品・手配マスタを補助システム側へ重複構築しないため。
- 影響: ケーキ発注書は紐づけ手配先の全手配枠を対象とする。未紐づけ手配先は一覧に残るだけで出力しない。
- 拡張: 印刷履歴は受取日、発注書ID、日時、方法、結果を持ち、将来の花束・酒類等の発注書でも共用できる構造とする。


## QR物品発注は独立したPython Webプロジェクトにする

- 判断: 一般物品のQR発注は `qr-supply-ordering-system` として独立させ、Flask、SQLite、HTML、CSS、JavaScriptで構築する。
- 理由: スマートフォンからインストール不要で利用し、複数端末の依頼を一元保存しながら、飲料の在庫・売上・棚卸・発注履歴から障害範囲とデータを分離するため。
- 保存: SQLiteはアプリケーションだけが操作し、WAL、外部キー、トランザクションを利用する。実DB、実FAX番号、業務データはGit管理しない。
- 接続: 飲料システムとは相互URLリンクだけを許可し、コード、DB、マスタ、履歴、実行時依存を共有しない。
- QR: 商品ID付きURLだけを格納し、商品名やFAX番号などの変更可能情報は埋め込まない。

## 既存発注表はプレビュー確認後にトランザクション取込する

- 判断: 元のFAX発注表は読み取り専用で解析し、候補ごとに新規・既存紐づけ・対象外・保留を利用者が選択した後だけSQLiteへ確定する。
- 理由: 表記ゆれ、FAX・単位不足、重複候補、発注履歴の誤認を自動取込でマスタへ混入させず、元ファイルと実DBを保護するため。
- 照合: 発注先は名称＋FAX、商品は発注先＋名称＋単位＋入数の一意な完全一致だけを自動紐づけする。表示名は保持し、照合時だけ空白を正規化する。
- ID: `VENDOR-NNNN`と`SUPPLY-NNNN`をトランザクション内で単調増加させ、欠番を再利用しない。QRは商品ID URLのままとする。
- 安全性: マクロ・数式・外部リンクを実行せず、一時ファイルを削除し、ファイルSHA-256と判断結果だけを取込監査へ残す。実業者名・FAX・商品情報はGitへ記録しない。
