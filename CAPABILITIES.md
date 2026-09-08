# 能力ベースの担当判定（Capabilities）

## この文書の位置づけ

- 作業をエージェント名（ChatGPT / Codex / Claude Code）だけで割り当てず、そのセッションやユーザーが実際に持つ「能力」で判定する。
- **工程担当・③実機投入の停止条件・④⑤のユーザー既定担当・Codex利用条件は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を最優先する。**
- 既存の設計判断「ChatGPTをGitHub側の第一実装担当とし、ソース起動を標準とし、EXEは手動ビルド、配布更新もワンクリック化する」の意図は維持する。
- 記述が競合する場合、担当・工程は `OPERATING_CONTRACT.md`、能力定義は本文書、開始文書・テスト予算は [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を優先する。

## 背景（なぜ能力ベースにするか）

- 1つのセッションが複数の能力を同時に持つことがある。例：Windows実機上のClaude Codeは、GitHub書き込みも実機操作も同時にできる。
- しかし「能力を持つ」ことと「その能力を有料AIに使わせるべき」は別問題。**実機の前にいるユーザーも `windows-real` / `real-peripherals` / `shared-server` の能力保有者として扱い、安全なワンクリック操作はユーザーを既定担当とする。**
- GitHub candidateを正式ローカルへ同期する③と、起動・GUI・実紙等の④を分離しないと、同期だけの依頼が高コストなComputer-Useへ膨張する。
- 新しいツールが増えても判定ルールが陳腐化しないようにする。

## 能力の定義

| 能力 | 意味 | 典型的に持つ主体 |
|---|---|---|
| `github-rw` | 対象GitHubリポジトリの読み書き（ブランチ、commit、push、PR） | GitHub連携ChatGPT、`gh` / `git` を持つ実機AI |
| `sandbox-exec` | 隔離環境でのコード実行（構文確認、単体テスト、`compileall`、lint） | GitHub Actions、Codexクラウド、実行環境を持つAI |
| `windows-real` | 実Windows機の操作：正式ローカルrepo、実 `.venv`、実GUI、実ファイルシステム | **実機の前にいるユーザー**、実機上のCodex / Claude Code等 |
| `real-peripherals` | 実プリンター、外付けHDD等の物理機器 | **実機の前にいるユーザー**、対応環境の実機AI |
| `shared-server` | 共有配布サーバーへのアクセス、複数PC試験 | **対象ネットワークのユーザー**、対象ネットワーク上の実機AI |

各主体は必要能力を持つか確認する。ただし、能力だけで担当を決めず、`OPERATING_CONTRACT.md` の **安全性 / Codexクレジット / ユーザー操作可能性** の3軸を先に適用する。

## 作業種別 → 必要能力と既定担当

| 作業 | 必要能力 | 既定担当 / 境界 |
|---|---|---|
| ① 設計、コード調査、仕様整理 | GitHub読み取り等 | ChatGPT |
| ② GitHub上の実装・テスト追加・ブランチ・commit・push・PR | `github-rw` | ChatGPT + GitHub Actions |
| ② 単体テスト / `compileall` / lint | `sandbox-exec` | GitHub Actions / ChatGPT側で可能な実行環境 |
| **③ candidate同期** | `windows-real` | Codexまたはユーザー。**起動・確認なし。HEAD SHA一致で停止** |
| **④ Pythonソース版の実機起動・GUI・機能確認** | `windows-real` | **ユーザー** |
| **④ 実プリンター / 実紙確認** | `real-peripherals` | **ユーザー** |
| **⑤ 正式EXEビルド（`BUILD_*_CLICK_ME.cmd`）** | `windows-real` | **ユーザーのワンクリック**。通常はCodexタスクにしない |
| **⑤ 配布更新（`UPDATE_SHARED_FOLDER.cmd` / HDD更新等）** | `windows-real` + `shared-server` または `real-peripherals` | **ユーザーのワンクリック** |
| ⑥ Windows障害調査 | 症状に応じた `windows-real` 等 | ④/⑤で具体症状が出た場合だけCodex |
| 2台同時などユーザー1人では物理的に成立しない試験 | `shared-server` 等 | 必要能力を持つ実機AIを例外利用可 |

## ③正式ローカルリポジトリへのcandidate同期規約

③を行う主体が `Development\repos` 配下の正式ソースに触れる場合：

1. 対象repoが正式パスであることを確認する。
2. 想定branchを確認する。
3. dirty treeを確認し、既存の未コミット変更があれば保護する。意図不明なら停止して報告する。
4. `git fetch` を行う。
5. 必要なら `git pull --ff-only` / checkout / switch 等で指定candidateへ同期する。競合したら停止して報告する。
6. `git rev-parse HEAD` で **HEAD SHA == candidate SHA** を確認する。
7. branch / HEAD / dirty tree / 実施結果を報告して**停止する**。

③では次を行わない：

- アプリ起動
- GUI / Computer-Use
- 機能確認
- 実紙 / プリンター確認
- 追加テスト / full regression
- candidate再レビュー / 根本原因再調査
- build / deploy / UPD

`github-rw` のみで `windows-real` を持たないセッションは、自分のpushが既存のローカルcloneへ届いている保証が無い。次の③で同期する。

## ④/⑤ユーザー操作の扱い

ユーザーは `windows-real` の正式な能力保有者です。次はAIへ押し戻さずユーザー既定とします。

- `RUN_DEV.cmd` 等の起動
- 通常GUI確認
- 修正箇所の機能確認
- 実紙確認
- `BUILD_*_CLICK_ME.cmd`
- `UPDATE_*_CLICK_ME.cmd` / `UPDATE_SHARED_FOLDER.cmd` 等の正式ワンクリック更新

ユーザーに任せないもの：長い手打ちPowerShell/Git、conflict解消、force push、履歴書き換え、`.git`内部操作、複数repo横断同期判断、実運用DB/認証情報/実データの直接編集、共有先への手動 `robocopy`。

## Codexの位置づけ

Codexは「実機確認担当」ではなく、次の2用途へ限定する。

1. 明示された③candidate同期
2. ④/⑤でユーザーが再現した具体的なWindows障害の調査

無症状の「念のため実機確認」、ユーザーが安全に実施できる④/⑤の代行には使わない。

## Claude Code等の実機AIの位置づけ

実機AIが `github-rw` + `sandbox-exec` + `windows-real` を同時に持っていても、**能力があるから①〜⑤を通しで担当させる、とはしない。** `OPERATING_CONTRACT.md` の工程分離を維持する。

③同期タスクならHEAD一致で停止する。⑥障害調査なら具体症状の範囲だけ調査する。

## 軽量レーン（小規模修正）

T0/T1の文書・調査範囲は [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を正とする。担当判定はティアに関係なく [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を適用する。
