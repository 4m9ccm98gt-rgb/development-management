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
| Toolchain | git / python(py) / gh の有無とバージョン、gh のログイン状態とトークン scope |
| Canonical repos | `Development\repos` の9リポジトリ: ブランチ（想定と違えば警告）・GitHub との同期（behind/ahead）・未コミット件数・`.venv` の Python 版・run/build/deploy 入口の有無 |
| Backups | 直近の `DevDataBackups\devdata-*` の日付（古いと警告）・`E:` バックアップドライブの接続 |
| Disk | `C:` の空き容量 |
| Other git repos under Documents | 正規パス外の clone を発見して列挙。未コミットがあるものは `REVIEW`（未 push 作業の可能性）。**削除しない**。詳細は [pc_repo_audit.md](pc_repo_audit.md) |
| Summary | OK / WARN / ERROR 件数と次の一言 |

## 判定の意味

- **[ERROR]** … 先に直す。多くは「ツールが無い」「repo が clone されていない」「gh 未認証」。
- **[WARN]** … ブロックはしないが要確認。未コミット・behind・想定外ブランチ・venv 未作成・バックアップ古い 等。
- **[INFO]** … 参考情報（正規パス外の clone 一覧など）。

## よくある WARN と対処

| WARN | 対処 |
|---|---|
| `no .venv` | 問題なし。`RUN_DEV.cmd` を1回実行すれば作られる |
| `behind N` | `git pull`（未コミットがある場合は先に内容確認） |
| `on 'xxx', expected 'main'` | 作業ブランチのまま。意図的ならそのまま、違えば `git switch main` |
| `N uncommitted change(s)` | 中身を確認。必要なら commit/push、不要なら破棄。**放置しない**（PC 故障で失われる） |
| `last dev-data backup is N days old` | `BACKUP_DEV_DATA_CLICK_ME.cmd` を実行 |
| `E: backup drive not connected` | 外付け HDD をつないでからバックアップする |
| `gh token missing 'workflow' scope` | `gh auth login` をやり直す |
