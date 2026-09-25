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

## 開発ルート

通常DevelopmentではClaude / Codexが正式ローカルrepoで直接実装します。DCCはRUN / BUILD / UPDATE、Orchestratorは任意の別画面です。詳細は `OPERATING_CONTRACT.md` を参照します。

- GPTは要望・優先順位・受入条件をAI依頼へ整理する。標準運用ではGitHub上のコード・設定を直接編集しない。
- `sandbox-exec` が利用できれば自動検証に使う。GitHub Actionsはその一実装であり必須ではない。
- `windows-real` / `real-peripherals` が必要な確認はユーザー実機確認へ残す。

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
