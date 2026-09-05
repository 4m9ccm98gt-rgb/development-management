# 俺伝（food-cost-calculation-system）の既定ブランチ監査（M3、2026-09-04）

## 背景

`food-cost-calculation-system` の GitHub 既定ブランチは `codex/bootstrap-invoice-reading`。
他の9リポジトリは `main`（archived の kitchen-calendar 含む）。この1本だけ異なる理由は、
Codex セッションが作ったブランチがそのまま trunk になったため（意図的な設計ではない）。
Claude Code 退役後は ChatGPT／Codex + この文書群に依存するため、「なぜこの repo だけ違うのか」を
残さない方がよい。→ `main` 化できるか、依存を全数監査した。

## 依存の全数監査

| # | 依存箇所 | 種類 | `main` 化の影響 |
|---|---|---|---|
| 1 | GitHub の既定ブランチ設定 | GitHub 設定 | 変更対象そのもの。rename API が原子的に更新 |
| 2 | `development-management/scripts/DEV_DOCTOR.ps1` の `$Canon`（`branch = "codex/bootstrap-invoice-reading"`） | **機能依存**（不一致なら `[ACTION] unexpected branch` を誤検出） | `"main"` へ変更（同一コミット） |
| 3 | `food-cost/.github/workflows/standards.yml` | CI | **影響なし**。`on: push` / `on: pull_request` にブランチフィルタ無し＝どのブランチ名でも動く |
| 4 | `food-cost/tools/release/build_release.ps1` | ビルド | **影響なし**。`git branch --show-current` で動的取得し `BUILD_INFO.txt` に記録するだけ（以後 `main` と記録される。情報用）|
| 5 | `food-cost/tools/release/update_hdd.ps1` | 配布 | **影響なし**。`BUILD_INFO.txt` に「Git branch」キーが在ることだけ確認。値は見ない |
| 6 | `food-cost/AI_HANDOFF.md`（`作業ブランチ: codex/bootstrap-invoice-reading`） | 文書 | 文言を `main` へ |
| 7 | `development-management` の AI_STARTUP / PROJECT_STATUS / REPOSITORIES / VERSION_MATRIX / docs/ai_handoff / docs/build_deploy_paths | 文書 | 同一コミットで更新 |
| 8 | `development-management/DAILY_LOG.md` の過去エントリ | 文書（履歴） | そのまま（当時の事実として正しい）|
| 9 | Open PR | GitHub | **なし**（0件）|
| 10 | ブランチ保護 / ルールセット | GitHub | **なし**（private + GitHub Pro 無しのため機能自体が無効）|
| 11 | 他リポジトリの workflow | CI | **なし**。food-cost のブランチ名を参照する workflow は存在しない（beverage の `python-migration-tests.yml` は自分の `python-desktop-migration` を見るだけ）|
| 12 | 正式ローカル clone `Development\repos\food-cost-calculation-system` | ローカル | clean・HEAD=origin・0/0。ローカル rename 手順で追従（下記）|
| 13 | 旧 clone `C:\Users\suisy\Documents\ChatGPT\food-cost-calculation-system` | ローカル | remote 無し・commit 無し・obsolete（[pc_repo_audit.md](pc_repo_audit.md) #3）。影響なし |
| 14 | `origin/claude/ci-pin-v1` / `claude/ci-standards` / `claude/standardize-run-dev` | GitHub | squash merge 済み PR の残骸。rename は触れない。別途削除してよい（M3 とは独立）|
| 15 | 配布済み `releases/*/BUILD_INFO.txt` | 過去の成果物 | `Git branch: codex/bootstrap-invoice-reading` と記録済み。害のない歴史的事実 |
| 16 | 旧 clone / 使い捨てディレクトリの文書 | 文書（管理対象外） | `ChatGPT\food-cost-calculation-system\AI_HANDOFF.md`（obsolete、remote 無し・#3）、`開発環境整備プロジェクト\projects\food-cost-calculation-system.md` / `REPOSITORIES.md` / `VERSION_MATRIX.md`（旧 dev-mgmt clone、`recovery/from-old-clone-docs` で別途最新化中・#1）に文言のみ。**機能依存なし**。`Codex\` 配下は food-cost への remote を持たず機能依存はあり得ない |

**機能依存は #2（DEV_DOCTOR の `$Canon` 1行）だけ。** 他はすべて文書か、ブランチ名非依存の仕組み。
外部（正式ソース外）の参照は旧 clone / 使い捨てディレクトリの文言のみで、いずれも操作上の役割なし。

## 判断: A（`main` へ移行する）

理由:

- GitHub のブランチ改名は**ネイティブかつ非破壊**の操作。commit / 履歴 / SHA を保持し、
  既定ブランチ設定を更新し、Open PR を張り替え（今回 0 件）、旧 `codex/...` の web/API リンクに
  リダイレクトを張る。**force push も履歴の作り直しも無い。**
- 逆操作（`main` → `codex/bootstrap-invoice-reading` へ再改名）も同じ API でできる。**可逆。**
- 依存面積が小さく全数把握済み（機能依存は 1 行）。
- 退役直前に「この repo だけ既定ブランチが違う」恒久的な引っかかりを消せる。
  新規セッションが `git switch main` して失敗する事故を防ぐ。
- CI・ビルド・配布はブランチ名非依存であることを確認済み。

B（現状維持）を採らない理由: 現状維持の唯一の利点は「変更リスクゼロ」だが、rename は可逆・非破壊で
リスクが十分小さく、放置コスト（毎回の説明・事故可能性）の方が大きい。

## 実施手順（非破壊・可逆）

### 前提チェック（2026-09-04 実施済み）

- 正式ローカル: `git status` クリーン、HEAD == `origin/codex/bootstrap-invoice-reading`、ahead/behind = 0/0
- Open PR: 0 件 / ブランチ保護: 無し / food-cost のブランチ名を参照する外部 CI: 無し

### 1. GitHub 側（ネイティブ改名）

```
gh api --method POST "repos/4m9ccm98gt-rgb/food-cost-calculation-system/branches/codex/bootstrap-invoice-reading/rename" -f new_name=main
```

これで既定ブランチが `main` になり、旧名リンクにリダイレクトが張られる。

### 2. 正式ローカル clone の追従

```
cd C:\Users\suisy\Documents\Development\repos\food-cost-calculation-system
git branch -m codex/bootstrap-invoice-reading main
git fetch origin --prune
git branch -u origin/main main
git remote set-head origin -a
```

確認: `git status` クリーン、`git rev-parse HEAD` == `git rev-parse origin/main`、
`git rev-list --left-right --count HEAD...origin/main` が `0  0`。

### 3. 機能依存の更新（同一 PR/コミット）

- `development-management/scripts/DEV_DOCTOR.ps1` の `$Canon`:
  `food-cost-calculation-system` の `branch` を `"main"` へ。

### 4. 文書の更新

- `food-cost/AI_HANDOFF.md`: `作業ブランチ: main`
- `development-management`: AI_STARTUP.md / PROJECT_STATUS.md / REPOSITORIES.md / VERSION_MATRIX.md /
  docs/ai_handoff.md / docs/build_deploy_paths.md の `codex/bootstrap-invoice-reading` 記述を `main` へ
  （DAILY_LOG の過去エントリは歴史的記録としてそのまま）。

### 5. 検証

- `gh repo view 4m9ccm98gt-rgb/food-cost-calculation-system --json defaultBranchRef -q .defaultBranchRef.name` → `main`
- `git ls-remote --symref origin HEAD`（food-cost clone 内）→ `ref: refs/heads/main`
- `DEV_DOCTOR_CLICK_ME.cmd` → food-cost が `[OK]`（`[ACTION] unexpected branch` が出ない）
- `python development-management/scripts/check_standards.py --repo <food-cost>` → 指摘なし
- `BUILD_俺伝_CLICK_ME.cmd` は次回実ビルド時に `BUILD_INFO.txt` の `Git branch` が `main` になることを確認（経路は H7 で確認済み、ブランチ名非依存）

### 6. ロールバック

```
gh api --method POST "repos/4m9ccm98gt-rgb/food-cost-calculation-system/branches/main/rename" -f new_name=codex/bootstrap-invoice-reading
```

＋ ローカルで `git branch -m main codex/bootstrap-invoice-reading` と upstream 再設定、文書を戻す。
commit は一切失われない。

## 状態 — 完了（2026-09-04）

- 監査・判断・手順設計: 完了。
- **手順 1（GitHub 改名 API）: ユーザーが実行済み。** 既定ブランチは `main`。GitHub 側の全ブランチ一覧は
  `main` のみ（旧名 `codex/bootstrap-invoice-reading` は GitHub がリダイレクト）。
- **手順 2（正式ローカルの追従）: 完了。** `git branch -m codex/bootstrap-invoice-reading main` →
  `git fetch origin --prune`（旧 `origin/codex/bootstrap-invoice-reading` 追跡枝は自動削除）→
  `git branch -u origin/main main` → `git remote set-head origin -a`。
  検証: ローカル HEAD SHA は改名前後で **`1940db031df7214f8ad087c6fd6c83492427a32b` のまま不変**
  （履歴の書き換えなし）、`git status` クリーン、ahead/behind 0/0、`origin/HEAD` symref は `refs/heads/main`。
  重複していた `.git/config` の `[branch "main"]` セクション（旧 `main` の残骸 + rename 後の追記）も統合済み。
- **手順 3（機能依存の更新）: 完了。** `scripts/DEV_DOCTOR.ps1` の `$Canon` を `"main"` へ。
- **手順 4（文書更新）: 完了。** `food-cost/AI_HANDOFF.md`、development-management の
  AI_STARTUP.md / PROJECT_STATUS.md / REPOSITORIES.md / VERSION_MATRIX.md / docs/ai_handoff.md /
  docs/build_deploy_paths.md（H7 実施当時の記録として旧名を残し脚注で明示）/
  scripts/BOOTSTRAP_DEV_PC.ps1（コメント）を更新。全文検索で残存する `codex/bootstrap-invoice-reading`
  はすべて「旧ブランチ名」と分かる歴史的記録（DAILY_LOG.md の当日以前の記録、本書内の当時の記述）。
- **手順 5（検証）: 完了。** `DEV_DOCTOR_CLICK_ME.cmd` → food-cost `[OK]`（`[ACTION] unexpected branch` なし）。
  `check_standards.py --repo food-cost-calculation-system` → 指摘なし。
  `gh repo view ... --json defaultBranchRef` → `main`。`git ls-remote --symref origin HEAD` → `refs/heads/main`。
  `BOOTSTRAP_DEV_PC.ps1` の live 検出（`git ls-remote --symref`）が `main` を正しく取得することを再確認。
