# DCC初回セットアップ正式反映結果 — 2026-09-16

## 結果とローカル保留

全7アプリのDCC初回整備PRとdevelopment-managementの固定candidate PRをmainへ反映した。全7アプリのmain上の入口をDCC実装で検出し、期待状態との一致を確認した。既存candidateはamend/rebase/squashせず履歴内に保持。残り6件と管理repoはmerge commit方式で反映した。

**ローカル導入はmenu / next-dayの2repoのみ保留。** 既存PRの作業branchとmainが分岐しているため、自動branch切替・merge・reset・stashはしない。既存checkoutとopen PRを保持し、別のdetached worktreeでmain上の入口を検証した。これは既存checkoutの起動許可を意味しない。

管理repoは正式SYNCでmainへfast-forwardし、DCCの正式入口によるself-checkと非表示Tk画面生成に成功した。全7選択の表示、candidate一致時のボタン状態、wrong branch時の全lifecycle無効化を確認。アプリRUN/BUILD/UPDATE/DEPLOYは呼んでいない。

| repo | merge済みPR | 確認したmain SHA | main上のSYNC / RUN / BUILD / UPDATE・DEPLOY | 既存checkout |
|---|---|---|---|---|
| beverage-inventory-ordering-system | [#48](https://github.com/4m9ccm98gt-rgb/beverage-inventory-ordering-system/pull/48) | `868bf5209e9f20245be8d4e2b7bbfc1efeaec7be` | READY / READY / READY / READY | mainと一致、tracked CLEAN |
| call-reception-assistant | [#3](https://github.com/4m9ccm98gt-rgb/call-reception-assistant/pull/3) | `86fe6f04fb346081f8936e862451db54f0b33f89` | READY / MISSING / N/A / N/A | mainと一致、tracked CLEAN |
| food-cost-calculation-system | [#4](https://github.com/4m9ccm98gt-rgb/food-cost-calculation-system/pull/4) | `eea065cd055bccb961cd6eabf44c69bd42e7d8a9` | READY / READY / READY / READY | mainと一致、tracked CLEAN |
| inventory-reconciliation-system | [#4](https://github.com/4m9ccm98gt-rgb/inventory-reconciliation-system/pull/4) | `1aefa22153a9ac4e82d2bdf18e45dcf962d5f84d` | READY / READY / N/A / READY | mainと一致、tracked CLEAN |
| menu-sheet-generator | [#5](https://github.com/4m9ccm98gt-rgb/menu-sheet-generator/pull/5) | `f54b0021e72ad6d74edd2a70e9937f989df90d83` | READY / READY / READY / READY | `fix/translation-selection-stability` を保全、lifecycle停止 |
| next-day-setup | [#20](https://github.com/4m9ccm98gt-rgb/next-day-setup/pull/20) | `5949f8f9e9d4f8c36af9c917dc67b9113435d1eb` | READY / READY / READY / READY | `chatgpt/add-breakfast-forfeit` を保全、lifecycle停止 |
| qr-supply-ordering-system | [#6](https://github.com/4m9ccm98gt-rgb/qr-supply-ordering-system/pull/6) | `cd416440fecb7ae772f993b5e141c9d7097ed3b5` | READY / READY / N/A / READY | mainと一致、tracked CLEAN |
| development-management | [#14](https://github.com/4m9ccm98gt-rgb/development-management/pull/14) | `8b2b8e90d5e275124c6d4fa2956fb5735645bff5`（本体PRのmerge SHA） | DCC起動入口・registry確認成功 | main、安全なfast-forward成功。追補の最終SHAはGit履歴を参照 |

beverage #48は前工程中に外部操作でmergeされ、その後別作業のEXE名変更commit `868bf5209e9f20245be8d4e2b7bbfc1efeaec7be` がmainへ反映されていた。本タスクでその業務変更を実装・BUILD・配布していない。上表は最終確認時のmain HEAD。

## 検証

- 各PRのhead完全SHA、main base、1コミットのみ、変更ファイル集合、git diff --checkを再確認。残り6件はmerge後もcandidateがorigin/mainの祖先であることを確認。
- DCC既存27件、検出回帰5件成功。MISSING / READY / N/A / MULTIPLE、originホスト詐称、repo typeを確認。
- 追補SYNC制御テスト12件（main用・テンプレート・中央bootstrap、計35シナリオ）成功。実PowerShellとGitテストダブルでsuccess / ff-only / dirty / local ahead / wrong origin / ホスト詐称 / wrong branch / detached / fetch失敗 / candidate不一致 / 短縮SHA / 非対話入力不足を検証。中央bootstrapのSHA不足はMandatoryパラメータであり、短縮SHAの早期停止を確認。
- 正式入口 `python DEV_CONTROL_CENTER.pyw --self-check` 成功、active repo数7。archived / knowledgeは除外、expected branchは全main。
- 非表示Tk上で実際のAppを生成し、全7repoを選択。アプリ起動・BUILD・配布処理は呼んでいない。画面の見た目やユーザーによるクリック操作は未確認。
- 全7mainのlifecycle検出一致。menu / next-dayは独立検証worktree上。他5repoは既存main checkoutで一致。
- 既存のアプリ検証結果は [初回local candidate記録](dcc_initial_setup_20260916.md) を参照。今回、アプリのsuiteやBUILDは再実行していない。

## SYNC補助経路の追補

main用SYNCだけでなく、`templates/windows-python-app/scripts/SYNC_CANDIDATE.ps1` と `scripts/BOOTSTRAP_REPO_SYNC.ps1` のorigin照合を同じ厳格なgithub.comホスト条件に揃えた。テンプレートのNoPause時入力不足も停止する。新機能ではなく既存fail-close契約の整合。固定candidate `18a78ceac8c80cc6e9446d4af74cc5b9dc00d402` は保持し、追補を別commit/PRとして管理する。

## Actionsと未確認事項

Actionsは支払いまたは利用上限の理由でジョブ開始前に停止。FAILURE表示はCI内テスト失敗を示さない。ユーザー指示に従いgreen待ちは行っていない。前工程のローカル検証を補助根拠として記録し、未実行を実行済みとは扱わない。

全repo共通でユーザー実機確認・実紙・LAN・外部サービス・配布物の動作・本番配布は未実施。本番データ、共有先、秘密情報、ローカル専用設定は本タスクで変更していない。call-receptionのアプリ本体は未実装、利用者向けランチャーは対象外。

## 保持したopen PRと次回の最初の操作

| repo | 残るopen PR | 次回ユーザーの最初の操作 |
|---|---|---|
| beverage-inventory-ordering-system | [#43](https://github.com/4m9ccm98gt-rgb/beverage-inventory-ordering-system/pull/43) 起動時に正式配布版を自動取得するランチャーを追加, [#2](https://github.com/4m9ccm98gt-rgb/beverage-inventory-ordering-system/pull/2) Start Python desktop migration | DCCでmain SHAを確認。既存open PRにより自動candidate入力が止まるため、確認したmain SHAを手動入力してユーザーRUN確認へ。 |
| call-reception-assistant | なし | DCCでSYNC READY / RUN MISSING / BUILD・配布N/Aを確認。アプリ実装は別工程。 |
| food-cost-calculation-system | なし | DCCでmain candidateとローカル一致を確認し、RUNからユーザー実機確認へ。BUILD・配布はまだ行わない。 |
| inventory-reconciliation-system | なし | DCCでmain candidateとローカル一致を確認し、RUNからユーザー実機確認へ。BUILD・配布はまだ行わない。 |
| menu-sheet-generator | [#4](https://github.com/4m9ccm98gt-rgb/menu-sheet-generator/pull/4) Fix translation selection and add safe candidate synchronization | 既存PR作業を保全したままmainへ移る工程を別途指定。現在はDCCのRUN/同期を進めない。 |
| next-day-setup | [#18](https://github.com/4m9ccm98gt-rgb/next-day-setup/pull/18) Add right-click breakfast forfeit handling, [#1](https://github.com/4m9ccm98gt-rgb/next-day-setup/pull/1) Fix closing task sheet generation in dinner bulk print | 既存PR作業を保全したままmainへ移る工程を別途指定。現在はDCCのRUN/同期を進めない。 |
| qr-supply-ordering-system | なし | DCCでmain candidateとローカル一致を確認し、RUNからユーザー実機確認へ。BUILD・配布はまだ行わない。 |
| development-management | なし | DEV_CONTROL_CENTER.pywを開き、repoと状態を確認。DCC整備PRは完了時に全件merge済みとして扱う。 |

既存checkoutの実際の検出: menuは全入口READYだがwrong branchで停止。next-dayは作業branchにSYNCが未反映のためSYNC MISSING、他入口READY、wrong branchで停止。main側の入口不足とは区別する。

## 保全したパス

- 元のrepo配置: `C:\Users\suisy\Documents\Development\repos`。既存branchを切り替えていない。
- main検証専用: `C:\Users\suisy\Documents\Development\dcc-setup-20260916\merged-main\menu-sheet-generator` と `next-day-setup`。
- 追補の独立作業先: `C:\Users\suisy\Documents\Development\dcc-setup-20260916\development-management-final`。
