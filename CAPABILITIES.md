# 能力ベースの担当判定（Capabilities）

この文書は、各主体が何を実行できるかを整理する補助資料です。運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 能力

| 能力 | 意味 | 典型的に持つ主体 |
|---|---|---|
| `github-rw` | GitHub上の調査・branch・commit・PR等 | GitHub連携ChatGPT、git/ghを持つ実機環境 |
| `isolated-edit` | source repoを直接汚さず隔離worktreeで編集 | AI Orchestrator + Claude Code |
| `read-only-review` | 実装を変更せず独立レビュー | Codex / GPT-6 Astra |
| `sandbox-exec` | 自動テスト・lint・build validation等 | ローカル開発環境、Actions、実行環境を持つAI |
| `windows-real` | 実Windowsローカルrepo、実GUI、実ファイルシステム | ユーザー、DCC |
| `real-peripherals` | printer、HDD等の物理機器 | ユーザー |
| `shared-server` | 共有先、LAN、複数PC等 | 対象ネットワークのユーザー |

能力を持つことと、その主体を必須担当にすることは別です。

## 標準Developmentルート

DCCが各能力を次のように組み合わせます。

- DCC: repo選択、preflight、安全ロック、進捗表示、candidate handoff
- Claude Code: `isolated-edit`
- 独立テスト: `sandbox-exec`
- Codex / GPT-6 Astra: `read-only-review`
- ユーザー: `windows-real` / `real-peripherals` / `shared-server` による最終実機確認
- GitHub: push後SHA、PR、CI等の観測・共有

GitHubだけで実装する旧A-path、手動で実機AIへデバッグ指示を渡す旧B-pathは標準ルートにしません。

## ChatGPT / GitHub連携

ChatGPTの `github-rw` は、development-management自体の管理変更、文書更新、DCC実装、PR作成等には利用できます。

通常の管理対象アプリ修正はDCC AI開発を優先し、GitHubだけでcandidateを作る経路をDCCの標準UIには置きません。

## ユーザー

ユーザーは正式な `windows-real` / `real-peripherals` / `shared-server` の能力保有者です。

通常の実機確認、GUI、実紙、printer、LAN、共有先、完成binaryの起動確認等はユーザーが直接確認できます。

安全な `RUN_DEV.cmd` / `BUILD_*_CLICK_ME.cmd` / `UPDATE_*` 等がある場合は、長い手打ちコマンドよりDCCと正式入口を優先します。

## 能力不足時

- その場で実行できないテストを実施済みと扱わない。
- Actionsが使えないだけで開発を止めない。
- Windows実機確認が必要ならユーザー確認へ残す。
- DCC / Claude / Codexの前提が壊れている場合、forceで回避せず停止する。
- 例外復旧はユーザーが明示した時だけ個別に扱う。

担当判断のために旧A/B分類、T0〜T3分類、毎ターンの能力表再確認は必要ありません。
