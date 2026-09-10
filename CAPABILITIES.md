# 能力ベースの担当判定（Capabilities）

## この文書の位置づけ

- 作業をエージェント名（ChatGPT / Codex / Claude Code）だけで割り当てず、そのセッションやユーザーが実際に持つ「能力」で判定する。
- **工程担当・③candidate同期の停止条件・④⑤のユーザー既定担当・Codex利用条件は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を最優先する。**
- 「能力を持つ」ことと「その能力をAIに使わせるべき」は別問題。ユーザーが安全にワンクリックでできる③④⑤はユーザー既定とする。
- 記述が競合する場合、担当・工程は `OPERATING_CONTRACT.md`、能力定義は本文書、開始文書・テスト予算は [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を優先する。

## 能力の定義

| 能力 | 意味 | 典型的に持つ主体 |
|---|---|---|
| `github-rw` | 対象GitHubリポジトリの読み書き（ブランチ、commit、push、PR） | GitHub連携ChatGPT、`gh` / `git` を持つ実機AI |
| `sandbox-exec` | 隔離環境でのコード実行（構文確認、単体テスト、`compileall`、lint） | GitHub Actions、実行環境を持つAI |
| `windows-real` | 実Windows機の操作：正式ローカルrepo、実 `.venv`、実GUI、実ファイルシステム | **実機の前にいるユーザー**、実機AI |
| `real-peripherals` | 実プリンター、外付けHDD等の物理機器 | **実機の前にいるユーザー**、対応環境の実機AI |
| `shared-server` | 共有配布サーバーへのアクセス、複数PC試験 | **対象ネットワークのユーザー**、対象ネットワーク上の実機AI |

各主体は必要能力を持つか確認する。ただし、能力だけで担当を決めず、`OPERATING_CONTRACT.md` の **安全性 / Codexクレジット / ユーザー操作可能性** の3軸を先に適用する。

## 作業種別 → 必要能力と既定担当

| 作業 | 必要能力 | 既定担当 / 境界 |
|---|---|---|
| ① 設計、コード調査、仕様整理 | GitHub読み取り等 | ChatGPT |
| ② GitHub上の実装・テスト追加・ブランチ・commit・push・PR | `github-rw` | ChatGPT + GitHub Actions |
| ② 単体テスト / `compileall` / lint | `sandbox-exec` | GitHub Actions / ChatGPT側で可能な実行環境 |
| **③ candidate同期** | `windows-real` | **ユーザー（`SYNC_CLICK_ME.cmd`）**。起動・確認なし。SHA一致で停止 |
| **④ Pythonソース版の実機起動・GUI・機能確認** | `windows-real` | **ユーザー** |
| **④ 実プリンター / 実紙確認** | `real-peripherals` | **ユーザー** |
| **⑤ 正式EXEビルド** | `windows-real` | **ユーザーのワンクリック** |
| **⑤ 配布更新** | `windows-real` + `shared-server` または `real-peripherals` | **ユーザーのワンクリック** |
| **⑥ Windows障害調査** | 症状に応じた `windows-real` 等 | ③④⑤で具体症状が出た場合だけCodex等の実機AI |
| 2台同時などユーザー1人では物理的に成立しない試験 | `shared-server` 等 | 必要能力を持つ実機AIを例外利用可 |

## ③正式ローカルリポジトリへのcandidate同期規約

③はユーザーが `SYNC_CLICK_ME.cmd` で行う。

1. ChatGPTが②完了時にcandidate branch / candidate SHAを明示する。
2. 同期branchはrepoごとに明示設定する。`origin/HEAD` やdefault branchから推測しない。
3. スクリプトがexpected repo / expected branch / tracked dirty / detached HEAD / local aheadを確認する。
4. `git fetch --prune` を行う。
5. `origin/<branch>` がcandidate SHAと一致することを確認する。一致しなければ停止する。
6. `git merge --ff-only origin/<branch>` のみで同期する。競合・diverge・aheadでは停止する。
7. `git rev-parse HEAD` で **HEAD SHA == candidate SHA** を確認する。
8. tracked clean / branch / HEAD / origin HEAD / expected SHAを `SYNC_RESULT.txt` に記録して**停止する**。

自動switch / stash / reset / rebase / forceは行わない。untracked fileは警告のみで変更しない。

③では次を行わない：

- アプリ起動
- GUI / Computer-Use
- 機能確認
- 実紙 / プリンター確認
- 追加テスト / full regression
- candidate再レビュー / 根本原因再調査
- build / deploy / UPD

`github-rw` のみで `windows-real` を持たないセッションは、自分のpushが既存のローカルcloneへ届いている保証が無い。次の③でユーザーが同期する。

## ④/⑤ユーザー操作の扱い

ユーザーは `windows-real` の正式な能力保有者です。次はAIへ押し戻さずユーザー既定とします。

- `SYNC_CLICK_ME.cmd`
- `RUN_DEV.cmd` 等の起動
- 通常GUI確認
- 修正箇所の機能確認
- 実紙確認
- `BUILD_*_CLICK_ME.cmd`
- `UPDATE_*_CLICK_ME.cmd` / `UPDATE_SHARED_FOLDER.cmd` 等の正式ワンクリック更新

ユーザーに任せないもの：長い手打ちPowerShell/Git、conflict解消、force push、履歴書き換え、`.git`内部操作、複数repo横断同期判断、実運用DB/認証情報/実データの直接編集、共有先への手動 `robocopy`。

## Codex等の実機AIの位置づけ

実機AIが `github-rw` + `sandbox-exec` + `windows-real` を同時に持っていても、**能力があるから①〜⑤を通しで担当させる、とはしない。**

使うのは、③④⑤でユーザーが再現した具体的なWindows障害があり、GitHub / CI / ユーザー報告だけでは切り分けられない⑥だけ。

通常candidate同期、無症状の「念のため実機確認」、ユーザーが安全に実施できる④/⑤の代行には使わない。

## 軽量レーン（小規模修正）

T0/T1の文書・調査範囲は [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を正とする。担当判定はティアに関係なく [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を適用する。
