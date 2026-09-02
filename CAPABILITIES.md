# 能力ベースの担当判定（Capabilities）

## この文書の位置づけ

- 作業をエージェント名（ChatGPT / Codex / Claude Code）で割り当てるのではなく、そのセッションが実際に持つ「能力」で判定する。
- 既存の設計判断「ChatGPTをGitHub側の第一実装担当とし、Codexを実機作業へ優先配分する」「ソース起動を標準とし、EXEは手動ビルド、配布更新もワンクリック化する」の意図はそのまま維持する。本文書はその判定基準を、エージェントの種類が変わっても壊れない形に置き換える。
- 記述が競合する場合、[AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) / [AGENTS.md](AGENTS.md) / [AI_STARTUP.md](AI_STARTUP.md) のエージェント名ベースの担当記述より、本文書を優先する。旧記述は将来ポインタへ整理する。

## 背景（なぜ能力ベースにするか）

- 1つのセッションが複数の能力を同時に持つことがある。例：Windows実機上のClaude Codeは、GitHub書き込みも実機操作も同時にできる。エージェント名ベースだと、この場合の担当が決まらない。
- 「ChatGPTがGitHubを更新 → Codexが実機で実装」を成立させるには、実機側が作業前に `git pull`、作業後に `git push` する必要がある。この同期を誰がやるか明文化されておらず、ローカルとGitHubがずれてハンドオフが切れた実例がある（2026-09-02、`DEVELOPMENT_RULES.md` / `REUSE_MAP.md` がローカル未コミットのまま `main` が遅延）。
- 新しいツールが増えても判定ルールが陳腐化しないようにする。

## 能力の定義

| 能力 | 意味 | 典型的に持つセッション |
|---|---|---|
| `github-rw` | 対象GitHubリポジトリの読み書き（ブランチ、commit、push、PR） | GitHub連携ChatGPT、`gh` / `git` を持つClaude Code、一部のCodex |
| `sandbox-exec` | 隔離環境でのコード実行（構文確認、単体テスト、`compileall`、lint） | Codexクラウド、Claude Code、GitHub Actions |
| `windows-real` | 実Windows機の操作：`C:\Users\suisy\Documents\Development\repos` 配下の正式ソース、実 `.venv`、実GUI、実ファイルシステム | 実機上のCodex、実機上のClaude Code |
| `real-peripherals` | 実プリンター、外付けHDD等の物理機器 | 実機の前にいる人、対応環境のCodex |
| `shared-server` | 共有配布サーバーへの書き込み、複数PC同時試験 | 対象ネットワーク上のセッション、実機の前にいる人 |

各セッションは作業開始時に「自分がどの能力を持つか」を確認し、タスクが要求する能力と照合する。持たない能力が必要になったら、その部分だけを持つ側へ引き継ぐ。

## 作業種別 → 必要能力

| 作業 | 必要能力 | 補足 |
|---|---|---|
| コード調査、設計、仕様整理 | 読み取りのみ（能力不問） | |
| GitHub上の実装・テスト追加・ブランチ・commit・push・PR | `github-rw` | 設計文脈を持つ側が一貫して担当する |
| 単体テスト / `compileall` / lint 実行 | `sandbox-exec` | |
| Pythonソース版のWindows実機起動・実GUI確認 | `windows-real` | |
| 正式EXEビルド（`BUILD_*_CLICK_ME.cmd`） | `windows-real`（ユーザーのワンクリック） | 通常はCodexのタスクにしない |
| 配布更新（`UPDATE_SHARED_FOLDER.cmd` / HDD更新） | `windows-real` ＋ `shared-server` または `real-peripherals` | 通常はユーザーのワンクリック |
| 実プリンター確認 | `real-peripherals` | |
| 共有サーバー上での複数PC同時更新試験 | `shared-server` | |

## 正式ローカルリポジトリの同期規約（必須）

`windows-real` を持つセッションが `Development\repos` 配下の正式ソースに触れる場合：

- **作業前**：対象リポジトリで `git fetch` し、想定ブランチであること・意図しない未コミット変更が無いことを確認する。他者の未コミット変更は保護する。behind がある場合は `git pull --ff-only`（競合したら停止して報告する）。
- **作業後**：意図した変更を `git commit` + `git push` する。push しない場合は、引き継ぎ文と管理文書に「未コミットで残す理由」を明記する。
- **「編集したが push していない」は未完了工程として扱う。** GitHub連携のみのセッション（例：ChatGPT）からは見えず、消えたように見える。
- `github-rw` のみで `windows-real` を持たないセッションは、自分の push が既存のローカルcloneへ届いている保証が無い。次に `windows-real` を持つセッションが pull する。

## Claude Code（実機上）の位置づけ

- 実機上のClaude Codeは通常 `github-rw` ＋ `sandbox-exec` ＋ `windows-real` を同時に持つ。1タスクを調査から実装・実機確認まで通しで担当でき、`real-peripherals` / `shared-server` だけを引き継げばよい。
- この場合も同期規約は同じ。着手前に pull、完了時に commit + push する。

## 軽量レーン（小規模修正）

1ファイルに閉じ、ビルド・配布・業務データ・複数リポジトリ・アーキテクチャに影響しない変更は、確認文書を絞ってよい：

- [AGENTS.md](AGENTS.md)、[AI_MEMORY.md](AI_MEMORY.md)（「ユーザー特性・作業スタイル」を含む）、対象の `projects/*.md` を読む
- 作業して、[DAILY_LOG.md](DAILY_LOG.md) に記録する

ビルド・配布・業務データ・複数リポジトリ・アーキテクチャに関わる変更は、[AI_STARTUP.md](AI_STARTUP.md) の完全な確認順序に従う。
