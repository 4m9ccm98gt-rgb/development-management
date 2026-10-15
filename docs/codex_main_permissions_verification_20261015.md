# Codex Main permission profile 検証（2026-10-15、push停止）

追記: A案は不採用。ユーザー指示により、下記の試作コード・テスト差分は破棄した。
このファイルだけを検証履歴として保存する。以下は破棄前の実装と検証の記録。

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
