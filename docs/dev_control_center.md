# Development Control Center — Phase 1

正本は [OPERATING_CONTRACT.md](../OPERATING_CONTRACT.md)。`RUN_DEV.cmd` / `DEV_CONTROL_CENTER.pyw` が起動入口です。

## 画面

メインはrepo選択、RUN / BUILD / UPDATE、AI Orchestrator入口を上部へ配置します。最小1080×720。AI依頼、Main / Reviewer選択、Claude / Codex残量、run状態・ログ、candidate、AI安全停止はOrchestrator別画面に置きます。別画面は実行中runの一覧・再接続を持ち、DCCメインの表示領域を圧迫しません。repo登録指示はコピー可能な別画面で生成し、Claude / Codex直接実装へ渡せます。

## 操作と成果物

RUN / BUILDはcandidate、tracked clean、GitHub取得成功を要求しません。起動直前に正式repo / origin / entrypointを再検査します。Orchestrator内部のclean条件は別です。

BUILDは非対話adapterから既存の処理本体を実行し、`%LOCALAPPDATA%/ShizenDev/DCC/builds/<repo-key>/` にlatest.jsonとbuild ID別記録を保存します。repo、base HEAD、dirty、開始・終了日時、build ID、入力fingerprint、成果物パス・全ファイルの集約SHA-256、結果を保持します。前回成功は新しいBUILD開始時に無効化します。

入力監視はtrackedファイルとGitで無視されない新規ファイルを対象とし、成果物ディレクトリは除外します。Gitで無視するローカルbuild設定は `.dcc-build-inputs.json` に相対ファイルパスの配列を指定して監視に含めます（内容は記録しない）。依存関係・外部ツールの全変更や瞬間的な変更を完全追跡する再現ビルド保証ではありません。入力不安定・失敗・成果物欠落はUPDATE不可です。

UPDATEの成果物hash計算はUI外のworkerで行います。UPDATEはBUILD記録、入力fingerprint、成果物hash、配布先、更新スクリプトを確認画面へ渡し、ユーザー承認後に再検査します。実行workerでも出力先ロック取得後に同じ条件を検証します。DCC経由の同じ出力先のBUILD / UPDATEはprocess間で排他します。外部ツールによる直接変更はこのロックには従わないため、配布中に外部BUILDや編集を重ねないでください。

## 既存entrypointとの接続

正式CMDの存在検査は維持しますが、DCCは手動CMDを実行しません。RUN / BUILDは `entrypoints.py` からPython / PowerShell / dotnetの処理本体へ接続します。UPDATEは確認済みの配布元・配布先を明示します。元のCMD / PowerShellとダブルクリック時のpauseは変更しません。

| repo | 成果物 | UPDATE接続 |
|---|---|---|
| next-day-setup | dist/DinnerSystem | update_shared_folder.ps1 のSourcePath / TargetPath |
| beverage-inventory-ordering-system | python_app/dist/在庫発注管理アプリ | 既存更新PS1のSourcePath / TargetPath |
| menu-sheet-generator | publish | UPDATE.cmdと同じ4ファイルを非対話adapterでコピー |
| food-cost-calculation-system | Development/releases | 既存更新PS1のSourceRoot / HddRoot。HddRoot配下のFoodCostCalculationへ更新 |

アプリ側の安全条件はバイパスしません。飲料BUILDは既存のclean必須、翌日準備UPDATEは既存のdirty build拒否等が残ります。これらの緩和は対象repoで別途対応が必要です。未登録repoのRUN / BUILDは下記の非対話入口宣言が必要です。UPDATEは引数・成果物の契約が確認されるまで停止します。ソース配布型のQRアプリなど、BUILD入口を持たないrepoに架空の成功BUILDを作りません。

## Orchestratorと終了

Orchestratorのrunは独立worker processが所有し、DCCの実行中操作（`ACTIVE_OPERATIONS`）ではありません。Orchestratorの実行中・失敗・quota・crash・stale・usage取得失敗が、同じrepoを含む通常のRUN / BUILD / UPDATEをロックすることはありません（isolated worktreeで動くため）。RUN / BUILD / UPDATE自身の同一repo・同一出力先の競合だけを止めます。

Orchestrator画面の×は画面を閉じるだけ、DCC終了はclient終了だけでrunは継続します（終了を保留するのはRUN / BUILD / UPDATE実行中だけ）。DCC起動時に実行中runを検出して操作ログとボタン（「AI Orchestrator ● 実行中 N」）へ表示し、画面を開くと同じrunへ再接続して進捗・ログ・usage・AI安全停止を使えます。AI安全停止はそのrunのprocess treeだけを終了します。成果物（candidate）の適用はユーザー確認後のfast-forwardのみで、sourceが移動していれば保留します。DCC自身の更新も実行中操作がある間は停止します。

## 検証

`python -B -m unittest discover -s tests -p "test_dev_control_center*.py" -v` と `python -B -m scripts.dev_control_center.app --self-check` を使用します。UI検証はWindowsのTkで1080×720のボタン表示と子画面を確認します。実配布・プリンター・外部サービスはmock検証と区別します。

## バックグラウンド実行

RUN / BUILD / UPDATEは事前検査・hash計算・subprocess待機をworkerで処理します。Windowsコンソールは非表示、stdinは閉じ、stdout / stderrをまとめてDCCログへ逐次転送します。RUN対象のGUI画面は通常どおり表示します。完了時は実際の終了コードを表示します。BUILD中もDCCの移動、ログ閲覧、repo切替が可能です。同じrepoの競合操作だけを停止し、別repoの操作は続けられます。「このrepoの実行を停止」は明示確認後に子process treeを停止します。停止・失敗BUILDはUPDATE対象になりません。

監査したRUN入口: 翌日準備、飲料、原価、備品、QR、メニュー、DCC。BUILD入口: 翌日準備のbuild_exe_entry.py、飲料の既存準備・clean検査・Tests・build_exe.py、原価のbuild_release.ps1、メニューのdotnet build / publish。メニューBUILDのExplorer自動表示も行いません。入口未実装のcall-reception / shizen-launcherは停止します。備品のタスク登録やQRの対話deployへ暗黙にフォールバックしません。

新しいrepoは、正式入口に加えてrepoルートの `dcc_entrypoints.json` に非対話の処理本体を宣言できます（schema 1）。例:

```json
{"schema": 1, "build": {"script": "tools/build.py", "cwd": ".", "args": [], "python": ".venv/Scripts/python.exe"}}
```

runも同じ形式です。scriptはrepo内の `.py` / `.ps1`、cwdと任意pythonもrepo内です。PowerShellはNonInteractive、Pythonはunbufferedで実行します。処理本体は入力待ち・pause・コンソールの明示起動を含めず、失敗を非0で返す必要があります。未対応repoでは手動CMDを隠して呼ぶことはせず停止します。既知repoの手動入口を変更する際は、DCC adapter側の準備・安全条件も整合してください。
