# Codex Main Python 検証（2026-10-15、A案不採用・E案）

追記: A案は不採用。ユーザー指示により、下記の試作コード・テスト差分は破棄した。
このファイルだけを検証履歴として保存する。以下は破棄前の実装と検証の記録。

## A案: permission profile（不採用）

正式repoの直接実装ルートで検証。CLI: `codex-cli 0.155.1`。
DCC Python: `C:\Users\suisy\AppData\Local\Programs\Python\Python313\python.exe`。

未コミットの実装は Codex Main だけに `dcc_codex_main` を指定する。
`:workspace` を継承し、`:root` の広域読み取りを deny、`:minimal` と
`sys.executable` の親フォルダだけ read にする。worktree / temp の書き込みと
`.git` 等の保護は親 profile を維持し、network は false。
Main は `--sandbox` を外し、`--strict-config`、`--ignore-user-config`、
`approval_policy="never"` を使用する。追加権限が設定のマージで混入しないよう
permissions テーブルを置換し、project config がある場合は実行前に停止する。
Reviewer / Claude の呼び出しは変更しない。

profile を用いる CLI が起動できない場合は `CODEX_MAIN_PERMISSION_PROFILE_FAILED`
で停止する。旧 sandbox、ACL変更、`--add-dir`、`writable_roots`、sandbox無効化へ
フォールバックする経路は追加していない。quota / 認証 / timeout / transient の
既存分類は維持する。

## 実環境

HEAD `818c858` から一時的な detached worktree を作り、変更した
`CodexProvider.run_main` から実CLIを呼び出した。worktree は検証後に削除した。
CLI は shell コマンド実行前のセッション初期化で次を返した。

```text
elevated Windows sandbox requires effective `:root` read access
```

| 項目 | 結果 |
|---|---|
| (a) Main 内で python --version | 確認失敗。上記の初期化エラーで実行不可 |
| (b) 同じ Main 内で python -m unittest を1件 | 未確認。同じ初期化エラーで到達不可 |
| (c) ホーム / 他repoへの書き込み拒否 | 未確認。sandbox内の試行に到達不可 |
| (d) Python フォルダへの書き込み拒否 | 未確認。sandbox内の試行に到達不可 |
| (e) ネットワーク拒否 | 未確認。sandbox内の試行に到達不可 |
| (f) Claude Main / Codex Reviewer が従来どおり | 偽部品による引数・環境の確認のみ。実CLIの比較は未実施 |

この Windows elevated 実装では要求された最小読み取り policy を使用できない。
`:root` read の追加は要求範囲を超えるため行わない。実環境の6項目が揃わないため
commit / push は行わず、作業差分を残して停止する。

実CLIログ: `C:\Users\suisy\Documents\Development\verification\codex-main-permissions-runtime-20261015.log`。
全体テストログ: `C:\Users\suisy\Documents\Development\verification\codex-main-permissions-tests-20261015.log`。

## 自動テスト

- 既存 provider テスト48件、追加 permission profile テスト5件: PASS。
- `python -B -m unittest discover -s tests -v`: **1249件 PASS**（622.481秒、終了コード0）。
- 全体テストでは subprocess の ResourceWarning が出た。テストの失敗はない。
- `git diff --check`: PASS。

自動テストの成功は、上記の未達の実環境確認を代替しない。

## E案: 共有配置 Python の設定（同日）

A案のコード差分は破棄し、この検証記録だけを独立した docs commit に保存した。
E案の事前確認は、E案のコードを実装する前に実施した。

### ACL の観測（変更なし）

`icacls C:\ProgramData\ShizenDev\Python313` は終了コード0。

```text
NT AUTHORITY\SYSTEM:(I)(OI)(CI)(F)
BUILTIN\Administrators:(I)(OI)(CI)(F)
CREATOR OWNER:(I)(OI)(CI)(IO)(F)
BUILTIN\Users:(I)(OI)(CI)(RX)
BUILTIN\Users:(I)(CI)(WD,AD,WEA,WA)
```

`python.exe` 自体は SYSTEM / Administrators が `(I)(F)`、Users が `(I)(RX)`。
Users に読み取り・実行権限があることを確認した。フォルダには作成・追記・属性変更の
継承権限もある。ACL を読み取りだけに変更したという意味ではなく、コピー済みの
ACL をそのまま観測した結果であり、今回 ACL は変更していない。

### 事前実行

HEAD `818c858` から一時 detached worktree を作成し、実CLIを
`codex exec --json --sandbox workspace-write -C <worktree> --ephemeral -`
（`-c windows.sandbox="elevated"`）で呼び出した。permission profile や追加rootはない。

- `& 'C:\ProgramData\ShizenDev\Python313\python.exe' --version`: `Python 3.13.14`、終了0。
- 同じ Python で `-B -m unittest test_python_e_probe -v`: 標準ライブラリだけの1件 PASS、終了0。

この成功を確認してから E案を実装した。

### 実装

PC ローカルの `%LOCALAPPDATA%\ShizenDev\DCC\orchestrator_local.toml` に以下を設定した
（このローカル設定ファイルは Git 管理外）。

```toml
[orchestrator]
codex_main_python = 'C:\ProgramData\ShizenDev\Python313\python.exe'
```

Codex Main の開始時だけ設定を読み、既存ファイルかつ名前が `python.exe` か検証する。
run.json に保存して worker へ渡し、呼び出し時にも再検証する。設定ありなら指定Pythonを
PATH の先頭にし、同じファイルを `AI_ORCHESTRATOR_PYTHON` と shell環境へ渡す。
設定なし・空なら e8f98518 の DCC Python / repo venv 優先動作を維持する。
不正設定は固定エラーで停止し、Pythonの切り替えや再実行によるフォールバックはない。
Claude / Reviewer には設定を適用しない。sandbox・ACL・writable_roots・追加dir・profile・
Main / Reviewer ループのルールは変更していない。

### PUSH 前の実環境確認

変更した `CodexProvider.run_main` と実際のローカル設定を使い、別の一時 detached worktree
から実CLIを呼び出した。Windows の検証呼び出しでは上記と同じ elevated 指定を明示した。
AIの要約だけでなく JSONL の `command_execution` 完了イベントの出力と終了コードを確認した。

| 項目 | 結果 |
|---|---|
| (a) `python --version` | `Python 3.13.14`、終了0。`sys.executable` は `C:\ProgramData\ShizenDev\Python313\python.exe` |
| (b) `python -B -m unittest test_python_e_probe -v` | 1件 PASS、終了0 |
| (c) worktree外への書き込み | ホーム直下と元repo直下へ UUID 付き新規ファイルを排他的に作成しようとし、両方 `PermissionError`。ホスト側でも作成されていないことを確認 |
| (d) 外部通信 | Python socketで `1.1.1.1:443` への接続を試し、`PermissionError` / Windows 10013 で拒否。timeout を拒否成功扱いしていない |
| (e) Claude Main / Codex Reviewer | 両方の実呼び出しが `ROLE_PROBE_OK` を返して成功。実行引数を従来のコマンド生成と比較し一致、PATH / AI_ORCHESTRATOR_PYTHON も従来の agent_env と一致 |

検証用 worktree とファイルは削除済み。Python 本体・ACL・sandbox設定ファイルは変更していない。

事前確認ログ: `C:\Users\suisy\Documents\Development\verification\codex-main-python-e-preflight-20261015.log`。
実環境ログ: `C:\Users\suisy\Documents\Development\verification\codex-main-python-e-runtime-20261015.log`。
全体テストログ: `C:\Users\suisy\Documents\Development\verification\codex-main-python-e-tests-20261015.log`。

### E案の自動テスト

追加の偽部品テストでは、設定読み取り・不正値拒否・Mainだけへの適用・空設定の互換性・
repo venv より設定Pythonを優先すること・削除済みPythonでの停止・workerへの受け渡し・
Claude / Reviewer不変・フォールバックしないことを確認した。

- 設定・provider の偽部品テスト8件: PASS。既存 provider テスト48件: PASS。
- 設定の隔離後に host / worker 関連27件を再実行: PASS。
- `python -B -m unittest discover -s tests -v`: **1256件 PASS**（643.044秒、終了0）。
- 全体テストでは subprocess の ResourceWarning が出た。テストの失敗はない。
- `git diff --cached --check`: PASS。

E案は実環境の全5項目と全体テストを満たしたため、ユーザー指示に従い commit / push の対象とする。
