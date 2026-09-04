# DEV DOCTOR - 実機の開発環境ヘルスチェック

`check_standards.py` が GitHub 側の「標準を満たしているか」を見るのに対し、
DEV DOCTOR はこの Windows PC 側の「道具・clone・venv・バックアップが健全か」を見る。
読み取り専用。何も変更しない。

## 使い方

1. `development-management\scripts\DEV_DOCTOR_CLICK_ME.cmd` をダブルクリックする。
2. 画面の一番下の **Summary**（OK / WARN / ERROR の数）を見る。
3. 全文が `%USERPROFILE%\DEV_DOCTOR_report.txt` に保存される。
   **このファイルの中身をそのまま ChatGPT 等に貼れば、状態を判断してもらえる。**

## 見るもの

| セクション | 内容 |
|---|---|
| Toolchain | git / python(py) / gh の有無とバージョン。**GitHub 認証を2系統とも点検**: `gh`（`gh auth status` の終了コードで失効判定 + scope）、`git` push/pull（GCM。private repo への `git ls-remote` で実認証テスト）。詳細 [github_auth.md](github_auth.md) |
| Canonical repos | `Development\repos` の9リポジトリ: ブランチ（想定と違えば警告）・GitHub との同期（behind/ahead）・未コミット件数・`.venv` の Python 版・run/build/deploy 入口の有無 |
| Backups | 直近の `DevDataBackups\devdata-*` の日付（古いと警告）・`E:` バックアップドライブの接続 |
| Disk | `C:` の空き容量 |
| Other git repos under Documents | 正規パス外の clone を発見して列挙。未コミットがあるものは `REVIEW`（未 push 作業の可能性）。**削除しない**。詳細は [pc_repo_audit.md](pc_repo_audit.md) |
| Summary | OK / WARN / ERROR 件数と次の一言 |

## 判定の4段階

意図的な状態で警告が埋もれないよう、指摘を4段階に分ける。

| 段階 | 意味 | 対応 |
|---|---|---|
| **[ERROR]** | 先に直す | ツールが無い / repo が clone されていない / **gh 未認証・トークン失効** |
| **[ACTION]** | 要対応 | 追跡ファイルの未コミット変更、自分の upstream より behind、既定でも作業中でもない想定外ブランチ、バックアップが8日超、gh の workflow scope 欠落、**git（GCM）push/pull 認証の失敗** |
| **[INTENTIONAL]** | 現在意図的な状態。無視してよい | 登録済みの作業ブランチ（例: beverage の `python-desktop-migration`）、archived repo のブランチ状態 |
| **[INFO]** | 許容 / 参考 | `.venv` 未作成（RUN_DEV が作る）、未追跡ファイルのみ、`E:` 未接続、正規パス外の clone 一覧 |

Summary 行は ERROR → ACTION の順で見る。INTENTIONAL / INFO は件数が多くても気にしない。

## よくある [ACTION] と対処

| ACTION | 対処 |
|---|---|
| `N modified tracked file(s) uncommitted` | 中身を確認。必要なら commit/push、不要なら破棄。**放置しない**（PC 故障で失われる） |
| `behind N vs its upstream` | `git pull`（未コミットがあれば先に内容確認） |
| `on 'xxx', expected default 'main'` | 想定外ブランチ。意図的なら DEV_DOCTOR.ps1 の `$ActiveBranch` に登録、違えば `git switch main` |
| `last dev-data backup is N days old` | `BACKUP_DEV_DATA_CLICK_ME.cmd` を実行 |
| `gh token missing 'workflow' scope` | `gh auth refresh -s workflow`、または `gh auth login` をやり直す |
| `gh auth failed (token invalid / expired / revoked)` | [operator_runbook.md](operator_runbook.md) 6-1（`gh auth login`）|
| `git push/pull auth failed` | [operator_runbook.md](operator_runbook.md) 6-2（GCM 再ログイン）。ローカル git は無事、push/pull だけ止まる |

## 意図的な作業ブランチを追加するには

`DEV_DOCTOR.ps1` の `$ActiveBranch` に `"<repo>" = "<branch>"` を足す。以後その repo が
そのブランチにあるときは [ACTION] ではなく [INTENTIONAL] になる。archived repo は
`$Archived` 配列に足す。
