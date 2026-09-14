# Development Control Center

## 目的

開発時に各リポジトリを開いて `SYNC_CLICK_ME.cmd` / `RUN_DEV.cmd` / BUILD / UPDATE / DEPLOY の場所を探す作業を減らすための、Windows向けローカル操作パネルです。

初版はライフサイクル処理を中央アプリへ移植しません。各リポジトリに存在する正式なワンクリック入口を検出し、その入口を一画面から起動する「発射台」に限定します。

## 起動

正式な `development-management` ローカルrepoで `DEV_CONTROL_CENTER.pyw` をダブルクリックします。

Python標準ライブラリの Tkinter を使うため、Control Center専用の追加依存はありません。

## 画面上の流れ

```text
①② ChatGPT開発 → ③ SYNC → ④ RUN_DEV → ⑤ BUILD → ⑤ UPDATE / DEPLOY
```

各工程は独立しています。ひとつのボタンから後続工程を自動連続実行しません。

- **①② ChatGPT開発**: 対象repo・明示branch・工程境界を含む依頼文をクリップボードへコピーし、ChatGPTを開きます。
- **③ SYNC**: ChatGPTが②完了時に示したcandidate SHAを入力し、対象repoの正式 `SYNC_CLICK_ME.cmd` へそのSHAを渡します。
- **④ RUN_DEV**: 対象repoの正式な開発版起動入口を開きます。
- **⑤ BUILD**: 対象repoの正式なbuild入口を開きます。
- **⑤ UPDATE / DEPLOY**: 対象repo種別に応じた正式な配布・更新入口を開きます。実行前に確認ダイアログを出します。

工程担当と停止条件は `OPERATING_CONTRACT.md` をそのまま適用します。この画面を使うことで③〜⑤を自動化・省略するものではありません。

## リポジトリ一覧とbranch

アプリ種別は既存の `scripts/repo_types.toml` を正として使います。

candidate同期branchは `scripts/dev_control_center_repos.toml` に明示します。`origin/HEAD` やGitHubのdefault branchから推測しません。

正式ローカルrepoは `development-management` の兄弟ディレクトリにある `<repo名>` として解決します。現在の標準配置 `C:\Users\suisy\Documents\Development\repos\<name>` に対応しつつ、ユーザー名をコードへ固定しません。

## 安全条件

Control Centerは便利さのために既存の安全条件を弱めません。

- originが想定GitHub repoと一致しない場合はSYNC/RUN/BUILD/UPDATEを無効化します。
- branchが明示branchと違う場合は無効化します。
- tracked変更がある場合は無効化します。自動stash / reset / branch switchはしません。
- candidate SHAは7〜40桁の16進SHAだけ受け付けます。
- 正式入口が無い場合は `MISSING` と表示して無効化します。
- 同順位の入口が複数あり一意に決められない場合は `MULTIPLE` と表示し、推測して実行しません。
- 一度に実行できるライフサイクル工程は1つだけです。
- UPDATE / DEPLOY前には④実機確認と必要なBUILD完了を確認するダイアログを出します。
- 実際のGit同期・build・配布ロジックは各repoの正式スクリプトに残します。

## 初版で意図的に残すもの

使用感を見てから優先順位を決めるため、初版では次を自動化しません。

- ChatGPTからcandidate SHAをControl Centerへ自動転送すること
- GitHub Actions / PR状態をローカル画面へ直接取得すること
- 各正式スクリプトのログをControl Center内部へ完全統合すること
- Control Center自身のEXE化
- 工程の自動連続実行

まず「repoと更新ファイルを探さなくてよくなったか」「candidate SHA貼付が面倒か」「状態表示に何が足りないか」を実使用で確認し、その結果を次版へ反映します。

## CI

`.github/workflows/dev-control-center.yml` で以下を確認します。

- registry / explicit branch contract
- 正式入口の検出と曖昧時fail-close
- candidate SHA validation
- Python compile
- registry self-check

GUIの見た目とWindows上での実際のクリック感は④ユーザー実機確認として扱います。
