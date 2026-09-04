# GitHub 認証の構成（M2 監査、2026-09-04）

この PC が GitHub とやり取りするための認証は **2 系統あり、独立している**。
片方を再設定しても、もう片方は直らない。

再ログインの操作手順は [operator_runbook.md](operator_runbook.md) の「6. GitHub 認証が切れたときの再設定」。
本書はその背景（何がどこにあり、いつ切れ、切れると何が止まるか）を記録する。
**トークン値・credential 内容そのものは記録しない。**

## 現状（2026-09-04 実機確認）

`gh auth status` の要点（トークン値を除く）:

- アカウント: `4m9ccm98gt-rgb`、active
- 保存方式: **keyring**（Windows 資格情報マネージャー。エントリ名 `gh:github.com:4m9ccm98gt-rgb`）
- Git operations protocol: `https`
- トークン種別: `gho_` プレフィックス = **`gh auth login` のブラウザ／デバイスフローで得た OAuth トークン**
  （PAT `ghp_` でも fine-grained `github_pat_` でもない）
- スコープ: `gist`, `read:org`, `repo`, `workflow`
- `gh` バージョン: 2.97.0

`git` 側:

- `credential.helper=manager`（**Git Credential Manager 2.9.0**）。system の
  `C:\Program Files\Git\etc\gitconfig` に設定。
- 保存方式: Windows 資格情報マネージャー。エントリ名 `git:https://github.com`（username `4m9ccm98gt-rgb`）。
  GCM は GitHub OAuth アプリ "Git Credential Manager" で自前の OAuth を行い、
  短命のアクセストークン + リフレッシュトークンを保持する。
- 全リモートは `https://github.com/4m9ccm98gt-rgb/<name>.git`（SSH ではない）。
- **`gh auth setup-git` は実行されていない** → `git` は `gh` のトークンを使わず、GCM で独立に認証している。

## 2 系統の関係

| 項目 | `gh`（GitHub CLI） | `git push` / `pull`（GCM） |
|---|---|---|
| 使う操作 | `gh pr` / `gh run` / `gh api` / `gh workflow`、`gh` を呼ぶスクリプト | `git push` / `git pull` / `git fetch`（HTTPS） |
| トークン種別 | OAuth `gho_`（`gh auth login`） | GCM が取得する GitHub OAuth トークン（アクセス + リフレッシュ） |
| 保存場所 | Windows 資格情報マネージャー `gh:github.com:...` | Windows 資格情報マネージャー `git:https://github.com` |
| 有効期限 | 既定で固定の期限なし。リフレッシュ機構なし | アクセストークンは短命 → GCM が自動更新。リフレッシュトークンで継続 |
| 期限日を表示できるか | できない（`gh auth status` は「現在有効か」だけ） | できない |
| 現在有効かの確認 | `gh auth status`（exit 0 かつ `X Failed` 行なし）/ `gh api user` | `git ls-remote <private repo>` が exit 0 |
| 再ログイン | `gh auth login`（[operator_runbook.md] 6-1） | 通常は `git push` 時に GCM が自動でブラウザを開く（[operator_runbook.md] 6-2） |

## 失効の条件（両系統に共通）

有効期限の経過ではなく、次のイベントで失効する:

- GitHub → Settings → Applications → **Authorized OAuth Apps** で "GitHub CLI" または
  "Git Credential Manager" の連携を取り消した。
- アカウントのパスワードを変更した（場合により失効）。
- GitHub がセキュリティ上の理由でトークンを無効化した。
- 組織で SSO の再認証が要求された（`repo` / `read:org` が一時的に効かなくなる）。

「あと N 日で切れる」という表示は `gh` にも `git` にもない。
GitHub の Authorized OAuth Apps 画面に「last used」と取り消しボタンはあるが、期限タイマーはない。
→ **能動検知は DEV_DOCTOR の 2 つのチェックで行う**（下記）。

## 失効したとき何が止まるか

| 切れたもの | 止まること | 無事なこと |
|---|---|---|
| `gh` のトークン | `gh pr` / `gh run` / `gh api` / `gh workflow`（PR 作成・CI ログ確認・API 経由の操作）。`gh` を呼ぶスクリプト | `git push` / `git pull` / `git fetch`。**GitHub 上で動いている CI（composite action）自体は無関係**。ローカル作業全般 |
| `git`（GCM）の資格情報 | `git push` / `git pull` / `git fetch`（HTTPS） | ローカルの commit・ブランチ・merge、`gh` コマンド全般 |

CI（`.github/workflows/standards.yml` → `development-management` の composite action）は
GitHub のサーバー上で動く。ローカルの認証が切れても CI の実行には影響しない。
影響するのは「CI の結果を `gh run` で見る」「`.github/` を push する（`workflow` スコープが必要）」などのローカル操作。

## DEV_DOCTOR による検知（2026-09-04 追加）

`scripts/DEV_DOCTOR.ps1` の Toolchain セクションで両系統を点検する:

- **`gh`**: `gh auth status` の **終了コード**で判定（"Logged in" という文字列の有無では判定しない）。
  さらに出力に `X ...(Failed to log in|token ... is invalid|expired|revoked)` があれば失効扱い。
  失効時: `[ERROR] gh auth failed (...). Fix: docs\operator_runbook.md section 6 ...`
- **`git`（GCM）**: プロンプトを無効化（`GIT_TERMINAL_PROMPT=0` / `GCM_INTERACTIVE=never`）した上で
  `git ls-remote --heads https://github.com/4m9ccm98gt-rgb/development-management.git` を実行。
  全 repo が private なので、これは実際の認証テストになる。
  認証失敗（`Authentication failed` / `terminal prompts disabled` / 401 / 403 等）時:
  `[ACTION] git push/pull auth failed (...)`。
  オフライン等で判別不能なときは `[INFO]` に留める（誤検知を出さない）。

いずれも読み取り専用。トークン値は出力しない。
`workflow` スコープ欠落は従来どおり `[ACTION]`。

## 推奨

- `gh` と `git` の認証は**別のまま**でよい。GCM は git 認証を自動更新でき、`gh` の失効に巻き込まれない。
  まとめたい場合は `gh auth setup-git` で git も `gh` のトークンを使わせられるが、
  その場合 `gh` の失効が `git push` も止める点に注意。
- 週次〜月次の `DEV_DOCTOR_CLICK_ME.cmd` 実行で両系統の生存を確認する（[operator_runbook.md] 1）。
