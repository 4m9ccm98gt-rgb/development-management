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
