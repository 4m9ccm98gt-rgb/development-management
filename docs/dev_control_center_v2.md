# Development Control Center v2

## 位置づけ

v2 は、初版の「各repoの正式入口を一画面から起動する発射台」を維持しつつ、実使用で見えた摩擦を減らす試験版です。

初版ランチャー `DEV_CONTROL_CENTER.pyw` は壊さず残し、v2 は `DEV_CONTROL_CENTER_V2.pyw` から起動します。使用感を確認してから正式ランチャーへ昇格します。

## v2で追加するもの

### 1. ChatGPTを開くボタンをやめる

通常はChatGPTを先に開いてからControl Centerを使うため、`①② ChatGPT開発` は主導線から外します。

代わりに `STARTUP SETコピー` を用意します。選択中repo、明示candidate branch、`OPERATING_CONTRACT.md` / `STARTUP_HANDOFF_POLICY.md` / `AGENT_EFFICIENCY_POLICY.md`、T0〜T3の開始規律を含む開始指示をクリップボードへコピーします。ChatGPTのブラウザは開きません。

### 2. GitHub / PR / CIを同じ画面で見る

選択repoについてGitHub CLI (`gh`) から次を取得します。

- 明示されたexpected branchのHEAD SHA
- 最新のopen PR
- 開発中PRがexpected branch向けなら、そのPR head SHAのcheck runs / commit status
- 該当PRがなければ、expected branch HEADのcheck runs / commit status

開発中PRがある間は、そのPR headのCI状態を表示して `PENDING` / `FAILED` を見つけやすくします。PR headが `GREEN` でも、まだexpected branchへmergeされていないためcandidate SHAは自動確定しません。

PRが閉じてexpected branchへ反映された後、expected branch HEADのCIが `GREEN` の場合だけ、そのSHAをcandidate欄へ自動入力します。

`PENDING` / `FAILED` / `NO CHECKS` ではcandidateを自動確定しません。手入力済みcandidateは自動値と同じ場合を除いて上書きしません。

### 3. GitHubに作られた新規repoを検出する

`scripts/repo_types.toml` に未登録で、GitHub上に存在する非archived・非fork repoを `GitHub未登録repo` として表示します。

`セットアップ開始` は次だけを行います。

1. 正式パス `Development\repos\<repo>` が無ければ `gh repo clone` でcloneする
2. 既存パスが非Gitディレクトリならfail-closeで停止する
3. `PROJECT_BOOTSTRAP.md` / `STARTUP_HANDOFF_POLICY.md` に沿った管理登録・標準入口整備の指示をクリップボードへコピーする

Control Center自身が `repo_types.toml` やbranch registryをローカルで勝手に編集・commitしません。正式登録・恒久入口の追加は従来どおりGitHub側の②開発で行います。

これによりユーザーがclone・registry・標準入口の手順を暗記する必要はありません。

## 4. Control Center自身の更新

v2は `development-management/main` のGitHub状態を確認します。

更新候補は次の条件をすべて満たした場合だけ有効にします。

- ローカル `development-management` が正式origin
- branch = `main`
- tracked clean
- GitHub `main` HEADがローカルHEADと異なる
- GitHub `main` HEADのCIが `GREEN`

`更新する` は正式 `SYNC_CLICK_ME.cmd` にcandidate SHAを渡します。Control Centerから呼ぶ場合だけ `--no-pause` を追加し、既存のダブルクリック利用では従来どおりpauseします。

更新後はControl Centerを閉じて開き直します。v2では更新後の自動再起動までは行いません。

## 工程境界

画面の主導線は次です。

```text
STARTUP SET → PR / CI → ③ SYNC → ④ RUN_DEV → ⑤ BUILD → ⑤ UPDATE / DEPLOY
```

- GitHub表示・candidate自動入力は②と③の間の探索コストを減らすだけで、③〜⑤を自動連続実行しない
- 開発中PRがある間はPR headのCIを表示し、candidate自動確定はmerge後までブロックする
- ③は正式SYNC入口へcandidate SHAを渡すだけ
- ④はユーザー実機確認
- ⑤は正式ワンクリックbuild / update / deploy
- tracked dirty / wrong branch / wrong origin / entrypoint MISSING・MULTIPLEでは従来どおり停止

## GitHub CLI

GitHub状態取得、新規repo検出、初回cloneには既存の `gh` 認証を利用します。

`gh` が使えない場合もローカルrepoの状態表示と既存のSYNC / RUN / BUILD / UPDATEは利用できます。GitHub関連機能だけエラー表示にします。

## CI

v2専用の `.github/workflows/dev-control-center-v2.yml` で次を確認します。

- 既存Control Centerテスト
- GitHub未登録repoのフィルタ
- GitHub repo一覧JSONの解釈
- CI状態の GREEN / PENDING / FAILED / NO CHECKS
- open PR中のcandidate自動確定ブロック
- merge後branch greenのcandidate確定
- STARTUP SET / 新規repoセットアップ指示
- Control Center呼び出し向け `SYNC_CLICK_ME.cmd --no-pause` 契約
- `scripts/dev_control_center` と両ランチャーのcompile
- v2 registry self-check

GUIの見た目、`gh` 認証済み実PCでの取得速度、新規repo clone、実際のボタン配置は④ユーザー実機確認として扱います。
