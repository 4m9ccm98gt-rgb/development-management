# 能力ベースの担当判定（Capabilities）

この文書は、各主体が何を実行できるかを整理する補助資料です。運用の正本は [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) です。

## 能力

| 能力 | 意味 | 典型的に持つ主体 |
|---|---|---|
| `github-rw` | GitHub上の調査・branch・commit・push・PR等 | GitHub連携ChatGPT、git/ghを持つ実機AI |
| `sandbox-exec` | 隔離環境での自動テスト・lint・build validation等 | Actions、実行環境を持つAI |
| `windows-real` | 実Windowsローカルrepo、実GUI、実ファイルシステム | ユーザー、実機AI |
| `real-peripherals` | printer、HDD等の物理機器 | ユーザー、対応実機AI |
| `shared-server` | 共有先、LAN、複数PC等 | 対象ネットワークのユーザー、対応実機AI |

能力を持つことと、その主体を必須担当にすることは別です。

## A — ChatGPT fast path

Aでは `github-rw` を持つChatGPTがGitHub上の調査・実装・テスト追加・candidate作成を担当できます。

- `sandbox-exec` が利用できれば自動検証に使う。
- GitHub Actionsは `sandbox-exec` の一実装であり、必須ではない。
- `windows-real` が必要な確認はユーザー実機確認へ残す。

## B — Debug escape path

ユーザーがCodex / Claude等を指定し、そのエージェントが `windows-real` を持つ場合、Windowsローカルrepoで調査・実装・テスト・デバッグを連続して行えます。

Bでは、能力が揃っている実機AIへローカル開発をまとめて渡すこと自体を禁止しません。

- B開始時にlocal HEAD / expected origin / branchを確認する。
- 完成後にlocal candidate commitを作る。
- candidate SHAとtracked cleanを確認し、実差分をレビューする。
- ユーザーがそのcandidateを実機確認する。
- OK後に同じSHAをfast-forwardでpushする。

## ユーザー

ユーザーは正式な `windows-real` / `real-peripherals` の能力保有者です。

通常の実機確認、GUI、実紙、printer、LAN、共有先、完成binaryの起動確認等はユーザーが直接確認できます。

安全な `SYNC_CLICK_ME.cmd` / `RUN_DEV.cmd` / `BUILD_*_CLICK_ME.cmd` / `UPDATE_*` 等がある場合は、長い手打ちコマンドよりそれを優先します。

## 能力不足時

- その場で実行できないテストを実施済みと扱わない。
- Actionsが使えないだけで開発を止めない。
- Windows実機確認が必要ならユーザー確認へ残すか、ユーザーが指定したBの実機AIへ渡す。
- 特定エージェントが指定されている場合、別エージェントへ勝手に置き換えない。

担当判断のためにT0〜T3分類や毎ターンの能力表再確認は必要ありません。
