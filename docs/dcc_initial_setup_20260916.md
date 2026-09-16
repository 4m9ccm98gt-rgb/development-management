# DCC初回セットアップ — 2026-09-16

## 完了範囲と正式反映の境界

対象7repoのlocal candidateを作成し、DCC実装で入口を検出した。call-receptionはユーザー承認によりSYNCのみ整備。その他6アプリの必要入口はREADY、service/webのBUILDはN/A。

**正式mainへの全repo反映は未完了。push・PR統合・既存作業branchの切替は行っていない。以下のSHAはlocal candidateであり、remote mainの同期用candidateと混同しない。** 4repoは独立worktreeで既存checkoutを保護した。DCC既定パスは従来のrepos配下を維持し、wrong branchの安全停止を緩めていない。

本番データ・設定・秘密情報・共有先は変更していない。正式RUN/BUILD/UPDATE/DEPLOY・タスク登録は未実行。検証内のdry-run・仮配布先・.NET検証ビルドのみ実施。利用者向け起動ランチャー機能は追加していない。

| repo | type | expected branch | SYNC | RUN | BUILD | UPDATE / DEPLOY | local candidate branch | 完全40桁local candidate SHA |
|---|---|---|---|---|---|---|---|---|
| beverage-inventory-ordering-system | desktop | main | READY | READY | READY | READY | main | ef756b77114974d8c75a0e175ca59bb63f2f4871 |
| call-reception-assistant | desktop | main | READY | MISSING | N/A | N/A | main | 40dac9b869d92a7297899b9b259a28f825a6fcc6 |
| food-cost-calculation-system | desktop | main | READY | READY | READY | READY | codex/dcc-initial-setup | a0ff8758b1478de081cd602020bda3955f5ee9dc |
| inventory-reconciliation-system | service | main | READY | READY | N/A | READY | codex/dcc-initial-setup | 4e61d1e8737fa7dabc39ca9da4d6bec0cb48c993 |
| menu-sheet-generator | desktop | main | READY | READY | READY | READY | codex/dcc-initial-setup | 30d67a6dc69ac6f6c156a0b2155c2a044537b539 |
| next-day-setup | desktop | main | READY | READY | READY | READY | codex/dcc-initial-setup | 7b0fa20354ad550c4653ba04296097bd314c8e43 |
| qr-supply-ordering-system | web | main | READY | READY | N/A | READY | main | 27bd6b23ed11a674c2107d4b7ba30701f11ef70a |

## beverage-inventory-ordering-system

- 作業パス: `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`
- 変更: SYNCの40桁SHA・非対話・origin照合を補強。生成物/業務dataをignore。配布時にorderingのlocal設定を除外。既存RUN/BUILD/UPDATEを再利用。
- 検証: 既存suite: 338 passed / 1 skipped。配布変更後targeted: 4 passed。SYNC契約: 1 passed。Python構文88ファイル。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `main` / HEAD `ef756b77114974d8c75a0e175ca59bb63f2f4871` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: READY `python_app\RUN_DEV.cmd`
- build: READY `python_app\BUILD_EXE_CLICK_ME.cmd`
- release: READY `python_app\UPDATE_SHARED_FOLDER.cmd`

## call-reception-assistant

- 作業パス: `C:\Users\suisy\Documents\Development\repos\call-reception-assistant`
- 変更: SYNC・契約テストを追加。アプリ本体未実装のためRUNはMISSING、BUILD/配布はN/A（ユーザー承認済み）。
- 検証: SYNC契約: 1 passed。Python構文1ファイル。アプリsuiteは対象コードなし。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `main` / HEAD `40dac9b869d92a7297899b9b259a28f825a6fcc6` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: MISSING
- build: N/A
- release: N/A

## food-cost-calculation-system

- 作業パス: `C:\Users\suisy\Documents\Development\dcc-setup-20260916\food-cost-calculation-system`
- 変更: SYNC・契約テスト・結果ファイルignoreを追加。既存RUN/BUILD/HDD更新を再利用。
- 検証: suite: 252 passed / 2 skipped / 環境不足2 failed。worktree .venv接続後、失敗2件を含むrelease tests全6件passed。SYNC契約1 passed。Python構文62ファイル。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `main` / HEAD `858e51d984cd800b4dab5deeb9c05ce7eb3deb13` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: READY `RUN_DEV.cmd`
- build: READY `BUILD_俺伝_CLICK_ME.cmd`
- release: READY `UPDATE_HDD_CLICK_ME.cmd`

## inventory-reconciliation-system

- 作業パス: `C:\Users\suisy\Documents\Development\dcc-setup-20260916\inventory-reconciliation-system`
- 変更: SYNC追加。既存定時タスク登録をINSTALL_TASK_CLICK_ME.cmdから呼び出し、終了コードを伝播。
- 検証: 既存unittest 78 passed、ローカル休館日回帰成功。SYNC契約1 passed。Python構文14ファイル。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `main` / HEAD `9b33d50c3dee8e27ac1f5a64f9c1093fe6ed2bb3` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: READY `RUN_DEV.cmd`
- build: N/A
- release: READY `INSTALL_TASK_CLICK_ME.cmd`

## menu-sheet-generator

- 作業パス: `C:\Users\suisy\Documents\Development\dcc-setup-20260916\menu-sheet-generator`
- 変更: SYNC追加。既存PRのRUN_DEV.cmdのみ再利用。既存UPDATE.cmdをDCC側で検出。Pythonテストcacheをignore。
- 検証: PMS CSV/GDI pre-spoolの2ハーネス成功。.NET Debugビルド0警告/0エラー。SYNC契約1 passed。Python構文1ファイル。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `fix/translation-selection-stability` / HEAD `dcbb3c47c0f0212b05d00e4fbebfeb10343832e8` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: READY `RUN_DEV.cmd`
- build: READY `BUILD_RELEASE.cmd`
- release: READY `UPDATE.cmd`

## next-day-setup

- 作業パス: `C:\Users\suisy\Documents\Development\dcc-setup-20260916\next-day-setup`
- 変更: 既存SYNCに非対話入力不足停止・厳格origin照合を追加。既存RUN/BUILD/UPDATEを維持。
- 検証: 既存suite: 787 passed / 4 skipped / 87 subtests passed。SYNC契約1 passed。Python構文111ファイル。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `chatgpt/add-breakfast-forfeit` / HEAD `1a03178deb31fe8c3592bf57c957565b00f43bdc` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: READY `RUN_DEV.cmd`
- build: READY `BUILD_EXE_CLICK_ME.cmd`
- release: READY `UPDATE_SHARED_FOLDER.cmd`

## qr-supply-ordering-system

- 作業パス: `C:\Users\suisy\Documents\Development\repos\qr-supply-ordering-system`
- 変更: SYNC追加。明示先・確認SHA・remote main一致・停止確認によるソースDEPLOYを追加。DB/設定除外、既存アプリファイル退避、dry-runと保全テスト。
- 検証: suite: 26 passed（DEPLOY保全2件含む）。追記後DEPLOY targeted 2 passed。SYNC契約1 passed。Python構文15ファイル。 PowerShell SYNC構文・git diff --check成功。
- local candidate tracked: CLEAN
- 既存checkout: branch `main` / HEAD `27bd6b23ed11a674c2107d4b7ba30701f11ef70a` / tracked CLEAN
- 未確認: ユーザー実機確認、配布先での動作、candidateのremote main反映。Actionsは未実行（今回pushなし）。
- sync: READY `SYNC_CLICK_ME.cmd`
- run: READY `RUN_DEV.cmd`
- build: N/A
- release: READY `DEPLOY_CLICK_ME.cmd`

## development-managementの変更と検証

- registryの7repo / main指定を維持し重複登録なし。archived/knowledgeは対象外。
- UPDATE.cmd / DEPLOY.cmd検出、source service/webのBUILD N/A、未実装repoの明示的N/A、originホストの厳格照合を追加。
- DCC既存27テスト成功。追加検出5テスト成功（MISSING / MULTIPLE / N/A / hostname詐称）。
- 実PowerShell＋Gitテストダブル: 4テスト、11シナリオ成功（success/ff-only/dirty/ahead/origin/branch/detached/fetch失敗/candidate不一致/短縮SHA/入力なし）。実remoteへのSYNC・fast-forwardは未実行。
- 全repoのSYNC実装は同一内容であることを確認し、各repo別static契約も成功。
- Python構文10ファイル成功。DCC GUIのクリック操作は未実施。

## 保持した作業と生成物

- beverageのopen PR #43/#2、menu #4、next-day #18/#1は変更・統合していない。
- 独立worktree: `C:\Users\suisy\Documents\Development\dcc-setup-20260916`。各branchは `codex/dcc-initial-setup`。
- food-costの独立worktreeに既存.venvへのjunctionを作成（依存再導入なし）。dry-runが `Development/logs/release_build.log` を生成。
- テストのcache・.NET bin/obj・仮配布物はGit管理外。飲料の既存data/build/distは削除せずignore補強。
- 配布手順の詳細・未確認事項は各repoのDCC_SETUP.mdにも記録。
