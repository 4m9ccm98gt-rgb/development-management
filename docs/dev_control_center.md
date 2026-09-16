# Development Control Center

## 目的

Development Control Center は、各repoの場所・正式スクリプト・candidate SHA・PR / CI状態を探し回らずに、repoの標準化から日常の開発後半までを一画面で進めるWindows向け操作パネルです。

正式起動入口は `DEV_CONTROL_CENTER.pyw` です。Tkinterのみを使い、専用の追加依存はありません。

## 運用モデル

正本は `OPERATING_CONTRACT.md` です。

通常は **A — ChatGPT fast path** を使います。

```text
必要なら SETUP / 標準化
→ ChatGPTで相談・GitHub開発
→ expected branchへcandidate反映
→ Control Centerでcandidate確認
→ SYNC
→ RUN_DEV / ユーザー実機確認
→ BUILD
→ UPDATE / DEPLOY
```

Windowsローカルで連続デバッグしたい場合は、ユーザー判断で **B — Debug escape path** に切り替えます。

Control Centerの `Bデバッグ指示` は、選択repo・ローカルパス・expected branch・candidate情報を含むhandoffをクリップボードへコピーします。Codex / Claude等の指定エージェントへ貼り付けて使います。

## SETUP / 標準化

2026-09-16の初回横断整備結果は [DCC初回セットアップ記録](dcc_initial_setup_20260916.md) を参照してください。local candidateの入口検証と、expected branchへの正式反映・ユーザー実機確認は別の状態として記録しています。

既存の `UPDATE.cmd` / `DEPLOY.cmd` も正式入口として認識します。service / webでBUILD入口がない場合はソース配布として `N/A` を表示します。アプリ未実装の例外は `dev_control_center_repos.toml` の `[unimplemented]` に理由を記録し、RUNはMISSINGのまま、未実装で不要なBUILD・配布だけN/Aにします。実装時はこの例外を削除します。

`SETUP / 標準化` は、単なるChatGPTセッション開始ボタンではありません。選択repoを Development Control Center の正式ライフサイクルへ載せるためのbootstrap / 監査指示を現在のChatGPTへコピーします。

Control Centerがローカルrepoから検出した次の状態を指示へ埋め込みます。

- `SYNC`
- `RUN_DEV`
- `BUILD`
- `UPDATE / DEPLOY`

各入口は `READY / MISSING / MULTIPLE` として扱います。`READY` の正式入口は原則作り直さず、`MISSING / MULTIPLE` だけを優先してGitHub側で整備します。

正本は次の2つです。

- `OPERATING_CONTRACT.md`
- `PROJECT_BOOTSTRAP.md`

Windows desktop repoでは、必要に応じて tracked な `SYNC_CLICK_ME.cmd` / `scripts/SYNC_CANDIDATE.ps1`、`RUN_DEV.cmd`、`BUILD_EXE_CLICK_ME.cmd`、`UPDATE_SHARED_FOLDER.cmd` またはそのrepoの正式同等入口を整えます。

SETUP完了時は、各入口の状態・変更内容・未確認事項・expected branchへ反映された完全40桁candidate SHAを明示し、そこで停止します。RUN / BUILD / UPDATEは自動実行しません。

つまり、既存repoがControl Center一覧には存在するが `SYNC` 等が `MISSING` の場合、まず `SETUP / 標準化` を使って正式入口をGitHub側へ追加し、そのcandidateをControl Centerで `SYNC` します。

## GitHub / PR / CI

選択repoについて `gh` を使い、次を表示します。

- expected branch HEAD
- expected branch向けのopen PR
- open PRがあればPR headのCI状態
- open PRがなければexpected branch HEADのCI状態

GitHub Actionsは補助検証です。`GREEN` をcandidate完成の絶対条件にはしません。

CI APIが一時的に利用できなくてもbranch HEADを取得できる場合は `UNAVAILABLE` と表示し、candidate SHA自体は失いません。

open PRがある間は、その開発途中PRを誤ってcandidate扱いしないため自動candidate入力を止めます。PRがexpected branchへ反映された後、そのbranch HEADを自動candidateへ入れます。

`PR / CIを開く` から、open PRまたは対象commitのChecks画面を開けます。

## candidateとローカル工程

candidateは **完全40桁SHAのみ**受け付けます。

- candidateがローカルHEADと違う → `SYNC`のみ有効
- SYNC成功後に `HEAD == candidate` → `RUN_DEV` / `BUILD` / `UPDATE・DEPLOY` が有効
- tracked dirty / wrong branch / wrong origin → すべて停止
- 正式入口が `MISSING` / `MULTIPLE` → 該当工程を停止

Control Centerは各repoの正式スクリプトを呼ぶだけで、SYNC / BUILD / UPDATEロジック自体は再実装しません。

UPDATE / DEPLOY前には、対象candidate SHAを表示し、ユーザー実機確認と必要なBUILDが完了していることを確認します。

## 新規repo

GitHub上に存在し、`scripts/repo_types.toml` に未登録の非archived・非fork repoは `GitHub未登録repo` に表示します。

`セットアップ開始` は次を行います。

1. 正式 `Development\repos\<repo>` 配下にrepoが無ければ `gh repo clone`
2. 既存の非Gitディレクトリがあればfail-close
3. development-managementへの正式登録・expected branch設定・必要な標準入口整備をChatGPTへ依頼するA-path指示をコピー

ユーザーがcloneコマンド、registryファイル名、標準入口の作り方を暗記する前提にはしません。

新規repoが管理対象へ登録された後も、正式入口が不足していれば `SETUP / 標準化` で同じ監査を行えます。

## Control Center自身の更新

Control Centerは `development-management/main` とローカルHEADを比較します。

- mainが同一 → `最新版`
- mainが新しく、CIが `FAILED` ではない → `更新する` を有効化
- CI `PENDING` / `NO CHECKS` / `UNAVAILABLE` は状態を表示した上で更新可能
- CI `FAILED` は自動更新を停止

`更新する` は正式 `SYNC_CLICK_ME.cmd` を `--no-pause` で呼びます。成功後は `DEV_CONTROL_CENTER.pyw` を自動再起動します。

通常のダブルクリックSYNCでは従来どおりpauseします。

## 安全条件

- origin一致
- expected branch一致
- tracked clean
- candidateは完全40桁SHA
- RUN / BUILD / 配布時は `local HEAD == candidate`
- force push / reset / stash / branch切替はControl Centerが勝手に行わない
- Git管理外の業務データや秘密情報を変更しない
- 工程は自動連続しない

## CI

`.github/workflows/dev-control-center.yml` で次を確認します。

- registry / explicit branch契約
- 正式入口の検出と曖昧時fail-close
- 完全40桁candidate SHA
- GitHub未登録repo検出
- CI状態集約
- Actions greenをcandidate必須条件にしない契約
- open PR中の自動candidateブロック
- SETUP / A / B prompt契約
- `SYNC_CLICK_ME.cmd --no-pause`
- Python compile
- registry self-check

GUIの見た目、`gh` 認証済みWindows実機での取得・clone・各ボタンのクリック感はユーザー実機確認で扱います。
