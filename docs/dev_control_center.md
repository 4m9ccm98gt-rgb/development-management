# Development Control Center

## 目的

Development Control Center は、各repoの場所・正式スクリプト・candidate SHA・PR / CI状態を探し回らずに、repoの標準化から日常の開発後半までを一画面で進めるWindows向け操作パネルです。

正式起動入口は `DEV_CONTROL_CENTER.pyw` です。Tkinterのみを使い、専用の追加依存はありません。

## 運用モデル

正本は `OPERATING_CONTRACT.md` です。

実装・設定変更の開始点は常に **AI依頼欄** です。`development-management` 自身も通常repoと同じManaged Repositoryです。

```text
GPTがAI依頼を整理
→ AI依頼欄 + テスト欄 → AI開発開始
→ Claude実装 → 独立Tests → GPT-6 Astra read-only review → local candidate
→ Control Centerでcandidate確認 → RUN_DEV / ユーザー実機確認
→ BUILD
→ UPDATE / DEPLOY
```

repoを選択すると、`dev_control_center_repos.toml` の `[initial_ai_tasks]` / `[initial_tests]` がAI依頼欄・テスト欄へ自動入力されます（ユーザー入力済みの内容が優先）。

## SETUP / 標準化

正式反映・検証結果とローカル保留は [2026-09-16 最終セットアップ記録](dcc_final_setup_20260916.md) を参照してください。既存PR作業branch上のrepoは、入口が存在してもexpected branch不一致として安全停止します。

2026-09-16の初回横断整備結果は [DCC初回セットアップ記録](dcc_initial_setup_20260916.md) を参照してください。local candidateの入口検証と、expected branchへの正式反映・ユーザー実機確認は別の状態として記録しています。

既存の `UPDATE.cmd` / `DEPLOY.cmd` も正式入口として認識します。service / webでBUILD入口がない場合はソース配布として `N/A` を表示します。アプリ未実装の例外は `dev_control_center_repos.toml` の `[unimplemented]` に理由を記録し、RUNはMISSINGのまま、未実装で不要なBUILD・配布だけN/Aにします。実装時はこの例外を削除します。

既存repoの標準入口が不足していれば、その内容をAI依頼欄から依頼します。

## 新規repo

GitHub上に存在し、`scripts/repo_types.toml` に未登録の非archived・非fork repoは `GitHub未登録repo` に表示します。

`セットアップ開始` は次を行います。

1. 正式 `Development\repos\<repo>` 配下にrepoが無ければ `gh repo clone`
2. 既存の非Gitディレクトリがあればfail-close
3. `development-management` を自動選択し、そのAI依頼欄へrepo登録タスクをセット（「AI開発開始」でClaude → Tests → Astraにより登録）

ユーザーがcloneコマンド、registryファイル名、標準入口の作り方を暗記する前提にはしません。登録後にDCCを更新して新repoを選択すると、`initial_ai_tasks` / `initial_tests` が自動入力されます。

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
- 新規repo登録prompt契約
- `SYNC_CLICK_ME.cmd --no-pause`
- Python compile
- registry self-check

GUIの見た目、`gh` 認証済みWindows実機での取得・clone・各ボタンのクリック感はユーザー実機確認で扱います。
