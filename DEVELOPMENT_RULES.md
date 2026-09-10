# 開発ルール

## 正式な知識ベース

- GitHub上の `development-management` を開発の正式な知識ベースとする。
- チャットだけに重要な決定事項を残さない。
- 工程①〜⑤と担当は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を正とする。
- 読み込み・調査・テスト範囲は [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を正とする。
- 能力定義は [CAPABILITIES.md](CAPABILITIES.md) を正とする。
- 判断の理由は `docs/decisions.md`、進行状況は `PROJECT_STATUS.md`、再発防止は `LESSONS_LEARNED.md` に残す。

## ソースと作業場所

- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下のみ。
- 旧フォルダは参照専用。新規開発・修正・ビルド・commitに使わない。
- 作業開始時に対象repo / branch / HEAD SHA / dirty treeを確認する。
- ③candidate同期ではcandidateへ同期するだけで、新規編集を始めない。

## 5工程の担当

| 工程 | 既定担当 | 境界 |
|---|---|---|
| ① 設計 | ChatGPT | 方針・受入条件・tier |
| ② 開発・作成 | ChatGPT + GitHub + GitHub Actions | 実装・targeted/regression・candidate SHAのCI green |
| ③ candidate同期 | **ユーザー** | `SYNC_CLICK_ME.cmd`、想定branch / tracked clean / SHA一致で停止 |
| ④ 実機確認 | **ユーザー** | RUN_DEV / GUI / 機能 / 実紙等 |
| ⑤ ビルド・配布・確認 | **ユーザー** | 正式ワンクリックbuild / update / deploy |

Codex等の実機AIは、③④⑤でユーザーが再現した具体的なWindows障害があり、GitHub / CI / ユーザー報告だけでは切り分けられない場合の⑥調査だけに使用する。

### ③candidate同期で禁止

- 自動branch switch
- stash / reset / rebase / force
- アプリ起動
- GUI / Computer-Use
- 機能確認
- 実紙印刷 / printer操作
- 追加テスト / full regression
- candidate再レビュー / 根本原因再調査
- build
- deploy / UPD

`HEAD SHA == origin SHA == candidate SHA` と tracked cleanを確認したら報告して停止する。

## ChatGPT / Codex / ユーザー分業

- ChatGPTがGitHubへ直接アクセスできる場合、GitHub上で完結する調査、設計、実装、テスト追加、branch、commit、push、PR、レビューはChatGPT側で行う。
- ユーザーは③candidate同期、④実機確認、⑤正式ワンクリックbuild/deployの既定担当。
- Codexは通常の実機確認担当でも通常同期担当でもない。具体症状付きの⑥Windows障害調査へ限定する。
- 同じGitHub作業をChatGPTとCodexで重複しない。
- CI未カバーだからという理由だけでCodexを発火させない。まず④ユーザー確認へ渡す。
- Codex指示は `OPERATING_CONTRACT.md` §7 の形式を使い、`【工程】⑥` と `【症状】` を必須にする。

## ユーザー操作の基準

ユーザーへ任せる標準操作:

- `SYNC_CLICK_ME.cmd` によるcandidate同期
- `RUN_DEV.cmd` 等のダブルクリック起動
- 通常GUI確認
- 修正箇所の機能確認
- 実紙確認
- `BUILD_*_CLICK_ME.cmd` 等の正式ワンクリックbuild
- `UPDATE_*` / `UPDATE_SHARED_FOLDER.cmd` / `UPDATE_HDD_CLICK_ME.cmd` 等の正式ワンクリックupdate

ユーザーへ標準で任せない操作:

- 長いPowerShell/Gitの手打ち
- conflict解消
- force push / 履歴書き換え
- `.git` 内部操作
- 複数repo横断同期判断
- 実運用DB / 認証情報 / 実データの直接編集
- 共有フォルダへの手動 `robocopy`

## candidate同期標準

- repoごとに `SYNC_CLICK_ME.cmd` または同等の正式ワンクリック同期経路を用意する。
- 同期対象branchはrepoごとに明示設定する。`origin/HEAD` やdefault branchから推測しない。
- ChatGPTは②完了時にcandidate branch / candidate SHAをユーザーへ示す。
- スクリプトは expected repo / expected branch / tracked dirty / detached HEAD / local ahead / SHA不一致を検査する。
- 同期は `git fetch --prune` → `git merge --ff-only` のみ。危険状態では自動修復せず停止する。
- untracked fileは警告に留め、変更しない。
- 成功条件は `HEAD == origin/<candidate-branch> == candidate SHA` かつ tracked clean。
- 結果は `SYNC_RESULT.txt` に保存する。

## Python / Windowsアプリの標準実行方式

- 開発時にEXEを作らなくても正式ローカルから起動できる状態を維持する。
- 原則 `RUN_DEV.cmd` または同等のワンクリック起動手順を用意する。
- repo内 `.venv` を正式開発環境とする。
- 日常のUI・機能確認はPythonソース版を優先する。
- EXE固有確認が必要な場合のみ⑤で正式buildする。

## EXEビルド標準

- EXEが必要なWindowsアプリにはユーザー用ワンクリックbuildを用意する。
- 標準名は `BUILD_EXE_CLICK_ME.cmd`。既存正式名称がある場合は互換性を優先する。
- build scriptは可能な限り `.venv`、依存、必要テスト、旧build/dist整理、成果物存在、commit SHA、SHA-256等を自動確認する。
- build出力・cache・runtime dataはGit管理しない。
- **⑤buildはユーザー既定。** Codexを使うのは正式ワンクリックbuildが具体的エラーで失敗し、Windows固有原因の調査が必要な場合だけ。

## 配布先更新標準

- 配布Windowsアプリには安全なupdate scriptを用意する。
- 標準は `update_shared_folder.ps1` + `UPDATE_SHARED_FOLDER.cmd`。既存正式経路があればそれを使う。
- **⑤配布更新はユーザー既定。**
- 配布物と業務データ・実運用設定を分離する。
- 共有フォルダ全体への単純 `robocopy /MIR` を使わない。
- `_internal` 等のruntime領域は必要に応じて完全同期する。
- 更新前後に業務データ保持を確認する。
- update scriptが具体的に失敗した場合だけCodexで原因調査する。

## 俺伝の正式リリース標準

俺伝は次をユーザーが実行する。

1. ②実装・CI確認完了
2. ③ `SYNC_CLICK_ME.cmd` でcandidate同期
3. `BUILD_俺伝_CLICK_ME.cmd`
4. 新しい `俺伝.exe` を起動して④/⑤確認
5. `UPDATE_HDD_CLICK_ME.cmd`
6. 利用PCで `FoodCostCalculation\Updater\俺伝更新.exe`
7. 更新後の主要画面・業務データ保持を確認
8. HDDを安全に取り外す

Codexはこれらが具体的に失敗した場合のWindows障害調査だけに使う。

## 既存資産の横断利用

この節は `AGENT_EFFICIENCY_POLICY.md` §3 の発火条件がある場合だけ適用する。

- 新方式導入・既存方式置換・T3等では、対象repo内既存方式 → `REUSE_MAP.md` / `projects/*.md` → 類似正式ソースの順で確認する。
- 既存機構の局所修正、表示調整、条件変更では横断調査しない。
- 既存方式を流用できない場合は差異を明示して新方式へ進む。
- 再利用可能な新しい方式・教訓は `REUSE_MAP.md` に入口を追記する。

## 開発環境と検証

- 実装後は `AGENT_EFFICIENCY_POLICY.md` のtier相当構文/targeted/regression/CI確認を行う。
- GitHub Actions成功をWindows実機・EXE・共有版・printer確認済みとは扱わない。
- CI未カバー領域はまず④ユーザー確認として残す。
- EXE buildを日常検証の必須条件にしない。
- tagは安定版にのみ作る。実運用未確認の変更へ安定版tagを付けない。
- 生成PowerShellは対象環境に合わせWindows PowerShell 5.1互換の構文・文字コードを考慮する。

## Git管理と情報保護

- 秘密情報、認証情報、実運用設定、顧客データ、業務データ、実行結果、cacheをGit管理しない。
- 設定例はダミー値の `*.example.*` とする。
- 未commit変更はGitHub側から見えないため、③でtracked dirtyを必ず確認し既存変更を保護する。
- force push、履歴書き換え、本番tagは通常工程に含めない。

## 本番反映

- 本番共有フォルダ、実運用DB、実プリンター送信、実HDD更新等は、それぞれ正式手順と承認境界に従う。
- 「⑤ユーザー担当」は本番反映を無条件に許可する意味ではない。ユーザーが明示的にその更新を行う工程に進んだ場合だけ正式ワンクリック経路を使う。
- AIは未確認の本番操作を完了済みと表現しない。

## 記録

仕様・運用・設計変更など将来の判断に使う内容だけREADME / `projects/*.md` / `PROJECT_STATUS.md` / `docs/decisions.md` / `LESSONS_LEARNED.md` / `CHANGELOG.md` へ必要範囲を反映する。

T0/T1で無関係な文書を形式更新しない。
