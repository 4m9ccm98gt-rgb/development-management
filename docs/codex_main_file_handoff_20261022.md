# Codex Main → 独立Testsのファイル受け渡し（2026-10-22）

## 結論

Windows実環境で障害を再現し、空のRun専用コンテナにworker本人の
読み取り・実行（RX）を継承設定することで解消した。
Main終了後に他ユーザー所有ファイルのDACLを変更する方式は廃止する。
Main後、diff取得前、独立Tests前、candidate作成前にworker自身で読み取りを検証する。
E案の共有Python設定、Codexのworkspace-write / elevated sandbox、Reviewerのread-only指定は変更しない。

開発は専用branch `codex/main-permission-handoff-20261022`、専用worktreeで直接実施した。
本番Taskの再投入、既存Runの修復・再開、main / UI / WF-6 / 報告箱branchへの適用はしていない。

## 実際の停止経路

該当Runは `20261022-194912-963477`。
証拠は `%LOCALAPPDATA%/ShizenDev/AIOrchestrator/runs/<run-id>/` の
`run.json`、`events.log`、`tests/run-001.txt`、`calls/main-001.log`、
`calls/main-002.log`、`calls/main-summary-001.txt`、`calls/main-summary-002.txt`。
すべて読み取り専用で調査した。

| 時刻（JST） | 実際の処理 |
|---|---|
| 19:49:17 | implementing開始、Main call #1 |
| 19:55:30 | testing開始、独立Tests起動 |
| 20:04:58 | 1379件 / 566.044秒、44 errors、3 skippedで失敗 |
| 20:04:59 | repairing、Main call #2（Reviewerは未起動） |
| 20:06:38 | Mainの `IMPLEMENTATION_STATUS: BLOCKED` を検出し `needs_human / TASK_BLOCKED` |

`tests_run_count=1`、`tests_fail_count=1`、`repair_iteration=1`、
`main_calls=2`、`review_calls=0`、candidateなし。
**独立Testsは未起動ではなく、起動して失敗した。**
`TASK_BLOCKED` はACL補正やTests runnerが直接生成したコードではなく、
`Engine._call_main()` のMain最終報告の判定で生成された。

Main #1は取り込み完了・関連890件成功を報告。
Main #2は新規40ファイルの権限問題を報告し、関連52件成功、独立Tests成功は未確認とした。
これらのMain内実行は独立Tests成功と同一視しない。

独立Testsの代表的なスタックは、unittestのモジュール収集 / importlibの
`exec_module → get_code → get_data` から新規の
`scripts/dev_control_center/orchestrator_lanes.py` を開く時点の
`PermissionError: [Errno 13] Permission denied`。
Main #2の実コマンド出力には、40ファイルが `CodexSandboxOffline` 所有、
明示的なsuisy ACEなしというACL一覧と `whoami` の出力が残っている。
現在も通常ユーザーから該当新規ファイルのOpenRead / Get-Aclは拒否され、既存app.pyは読める。
既存ファイル・親ディレクトリには旧補正によるsuisyの明示的Mがある。

当時の独立Testsの実効SIDそのものはログに保存されていないため、遡及して確定できない。
コード上はworkerの `run_streaming → cmd.exe → python` であり、別ユーザーへの切替はない。
今回の実機検証ではMain / 独立Testsの双方で `whoami /user` を記録した。

## 根本原因と旧処理の問題

このPCのDCC Pythonは3.13.14。実装の `tempfile.mkdtemp()` は
`os.mkdir(path, 0o700)` を呼び、生成直後（Codex起動前）のDACLは
`OWNER RIGHTS / SYSTEM / Administrators: (OI)(CI)(F)` だった。
worker本人のSIDへの継承ACEはなかった。
`OWNER RIGHTS` は新規ファイルの所有者に従うため、Sandboxが作ったファイルでは
Sandboxユーザーに対して有効となり、workerの読み取りを保証しない。
通常のDocuments配下ではsuisyの継承Fがあり、同じ作成操作でも失敗しない。
**Tempと異なる配置での成功だけでは、この障害の改善確認にならない。**

旧 `GitHost.normalize_permissions()` には次の問題があった。

- 既に読めない / WRITE_DACを持たないファイルへ、hostが `icacls /grant user:M` を試みていた。
- 終了コードを確認せず、例外も握りつぶしていた。さらに実測では `/C /Q` が
  `Successfully processed 0 files; Failed processing 1 files` とAccess deniedを出しても **終了コード0**。
- 読み取り再検証がなく、失敗した状態でdiff / 独立Testsへ進んだ。
- `exists()` やGit列挙が読めない子を飛ばし得る。今回の小規模再現でも、読めない新規サブディレクトリ内は旧補正対象から脱落した。
- `status --porcelain -z` のrename追加レコードを通常レコードとして扱う。
  `resolve()` 後の対象自身の境界確認がなく、リンク先を対象にできる。
- 400件で黙って打ち切る。untrackedファイルの読み取り失敗もdiff内でbinary扱いに隠され得る。
- USERNAME / USERDOMAINから組み立てた名前であり、実効worker SIDを使っていなかった。

## 採用方式と安全条件

`create_worktree()` が `mkdtemp()` で作った**空の専用親フォルダだけ**に、
Git checkout前・agent起動前に `*<worker SID>:(OI)(CI)(RX)` を追加する。
SIDは `whoami.exe /user /fo csv /nh` で取得・形式検証する。
このSIDは新規ファイルの所有者とは独立して読み取り可能となる。
元のprivate DACLを保持し、Everyone / Usersへの付与、M / Fの追加、
所有者変更、`/T`、`/reset`、`/C`、既存Runへの遡及適用は行わない。

初期化は、対象が空の通常ディレクトリで、祖先を含めreparse pointでないことを確認してから行う。
agentが触ったパスをACL変更コマンドへ渡す経路自体がなくなる。
対象はOrchestrator自身が直前に生成したprivateコンテナであり、タスク入力やGitパスから選ばない。
icaclsの非ゼロ終了・stderr・起動失敗は `WORKTREE_ACCESS_SETUP_FAILED` でcheckout前に停止。
管理者再実行、takeown、Sandbox無効化、別Providerへの切替はしない。

`normalize_permissions()` の互換入口は残すが、処理は読み取り検証のみ。
GitのNUL区切り `ls-files --cached --others --exclude-standard -z` を使い、
全Git可視ファイルと親ディレクトリをworkerの権限で実際に開く。
件数上限は設けない。削除済みtrackedパスは許容する。
パストラバーサル、絶対パス、ADS、Junction等のreparse point、
シンボリックリンク、複数ハードリンク、特殊ファイルは `WORKTREE_ACCESS_UNSAFE` で停止。
列挙不全や読み取り不可は `WORKTREE_ACCESS_UNREADABLE` で停止し、
Tests / Reviewer / candidateへ進まない。診断には相対パスとエラー種別を記録し、ファイル内容は含めない。
untracked diffのOSErrorもbinary placeholderへ変換しない。

Windows Sandboxは専用ユーザー・ACLで境界を設ける。
この変更はCodexの設定やユーザー境界を緩めず、host側の受取権限を整える。
参考: [official OpenAI documentation: Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox)。
今回の成否は一般説明ではなく、下記の実CLI出力とOSの読み取り結果で判断した。

## Windows実機検証

CLIは `codex-cli 0.155.1`。実 `CodexProvider.run_main()` の
`--sandbox workspace-write` と既存設定 `windows.sandbox=elevated` を使用。
Mainは既存E案設定の `C:/ProgramData/ShizenDev/Python313/python.exe`、
独立Testsはhost側Python 3.13.14を使用した。

実機ログ・driver・JSONL・ACL記録の保存先:
`C:/Users/suisy/Documents/Development/verification/codex-permission-20261022/`。
再実行手順の実体は同ディレクトリの `runtime_driver.py`。
SHA-256: `cc77cdcfaba37a5666e6ab626bb678ad6e95c659b056a1f7fa5b69035a69a44f`。
実CLIを呼ぶため自動テストには組み込まない。

| 検証 | 結果 / 証拠 |
|---|---|
| 修正前・同じTemp配置、ルート / 新規サブディレクトリの計3ファイル | 読み取り拒否を再現。`temp-repro-main.json` |
| 旧normalize呼び出し | 新規ファイルの補正失敗、終了0でも読めない。`original-normalize.json` |
| 新gateを旧失敗worktreeに適用 | 実際の列挙不全を検出しTests起動前停止。`runtime-failure-gate.json` |
| 小規模・既存編集1 + 新規module1 + 新規test1 | 独立Tests **2件PASS**、candidate commit成功 |
| 拡大・既存編集1 + 新規module40 + 新規test1 | 独立Tests **2件PASS**（ループで40module全件import / 値検証）、candidate commit成功 |
| Main実効ユーザー | `CodexSandboxOffline`、SID末尾1011。新規ファイル所有者も同じ |
| 独立Tests実効ユーザー | `suisy`、SID末尾1001。`cmd.exe`経由のwhoami出力をTestsログに保存 |
| 新規ファイル・ディレクトリのACL | 所有者1011を保持し、1001への継承RX（0x1200a9）が存在 |
| host gate → 独立Tests前後のACL | root / 既存編集 / 新規 / 未変更ファイル・ディレクトリのSDDL一致 |
| source fixtureの未変更ACL・HEAD | 検証前後一致、mainは移動していない |
| Sandbox外の書き込み | source fixture直下とhome直下の排他的新規作成が両方PermissionError。hostでも不存在確認 |
| 外部通信 | 1.1.1.1:443がWinError 10013で拒否。timeoutを成功扱いしていない |
| Git互換性 | diff → Tests前後fingerprint一致 → add / commit / candidate SHA取得成功 |

`runtime-main-1.json` / `runtime-main-40.json` のcommand_execution完了イベントは終了0。
AI最終メッセージだけでなく、実コマンド出力を確認した。
独立Testsの実出力は `runtime-tests-1.txt` / `runtime-tests-40.txt`、
SDDL・source不変・candidate SHAは `runtime-results.json` に保存。
candidateは隔離したfixture repo内だけで作成し、対象repoの本番candidateとして扱っていない。
UI / Reviewer / 本番Taskを含む長時間Runを再投入した検証ではない。

## 回帰・変更ファイル

- `tools/ai_orchestrator/worktree_access.py`: fresh container初期化、読み取りgate。
- `tools/ai_orchestrator/orchestrator.py`: 初期化接続、snapshot / Tests / candidateのgate、
  untrackedのNUL区切りと読み取りエラーの明示、cleanup保持の記録。
- `tests/test_ai_orchestrator_worktree_access.py`: 実Git、405ファイル、削除、空白・日本語、
  Junction / hardlink / traversal、列挙警告、読み取り・初期化失敗時の停止。
- `tests/test_ai_orchestrator_host.py`: post-agent ACL書換えの旧期待を、書換え禁止の期待へ変更。
- 本書。

providers.py / engine.py / common.py / runstate.py / settings.py の呼出経路を調査した。
Providerコマンド・環境、共有Python設定、Main / Reviewer選択、Tests FAIL修復ループは変更していない。
Claude Main / Codex Reviewerは既存provider・role・worker回帰テストで確認する。
今回、その2役の有料実CLIを再呼出してはいない（2026-10-15の実機確認記録も保持）。

関連284件PASS（270.647秒）。
`python -B -m unittest discover -s tests -v`: **1630件、失敗0、skip 3**
（1040.037秒、終了コード0）。ログは `full-tests.log`。
subprocessのResourceWarningが出たが、テスト失敗はない。
全体回帰の開始後に追加したcleanup保持の記録等については、
最終変更後のhost 28件PASS（128.484秒）、access 9件PASS（3.186秒）で確認した。
これらのログは `final-host-tests.log` / `final-access-tests.log`。
ACL不変のhostテストは実icaclsの結果を比較する検証へ強化し、単独再実行でもPASS。
`git diff --check` と `git diff --cached --check` もPASS。

## 副作用・未確定事項・運用判断

- RXは読み取り・収集・import・candidate作成に必要な権限に限定する。
  agent所有の新規ディレクトリへのhost書き込み・削除までは保証しない。
  実際に小規模fixtureの完了後cleanupが失敗しworktreeが残ることを確認した
  （`runtime-cleanup.json`）。権限を拡大せず、Runへ `worktree_cleanup=retained` と
  `WORKTREE_CLEANUP_RETAINED` を記録する。candidate成功を取り消さず、残存を黙殺しない。
- Sandbox初期化自体は従来どおりRun worktreeへSandbox SIDのACEを設定する。
  ここでいうACL不変は、その初期化後のhandoff / Testsと、source・対象外領域についての確認。
  初期化前後のRun worktreeのDACLが完全に同一という意味ではない。
- Git ignore対象の生成物は読み取りgateの対象外。Tests自体の失敗は従来どおり記録され、成功に置換しない。
- リンクを使うrepoやhostがagent所有ディレクトリへ書き込むTestsは、今回の読み取り専用契約では停止 / 失敗し得る。
  その際に自動で権限を追加しない。既存RunのACLも自動修復しない。
- 任意の既存ACL、別のWindows / CLI版まで一律保証するものではない。
  事後gateは将来の継承・CLI不整合を早期に検出するために残す。
  全Git可視ファイルの読み取りをsnapshotごとに行うため、大きなrepoではI/Oが増える。
- 本番再投入の判断: **このbranchを正式に取り込んだworkerから新しいRunとして実行することは可**。
  現在のmain / 起動済みworkerにはまだ修正がないため、そのまま再投入してよいという意味ではない。
  元の失敗Runの再開やUI統合Taskの完成・実機表示確認を今回の成功に含めない。
