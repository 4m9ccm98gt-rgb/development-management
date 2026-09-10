# AI Operating Manual

この文書は `development-management` を司令塔として、通常のChatGPTチャットを中心に一貫した開発運用を行うための運用規律です。

## 正本の分担

- **工程①〜⑤、担当、③停止条件、④⑤ユーザー既定、Codex利用条件**: [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)
- **変更ティア、読み込み・調査・テスト予算、反復上限、CI代替**: [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md)
- **能力定義**: [CAPABILITIES.md](CAPABILITIES.md)
- **開発・配布・データ保護の詳細**: [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md)

競合時は上記の役割分担に従います。本文はこれらを上書きしません。

## 標準工程

```text
① 設計
ChatGPT
↓
② 開発・作成
ChatGPT + GitHub + GitHub Actions
↓
③ candidate同期
ユーザー
SYNC_CLICK_ME.cmd → 想定branch / tracked clean / HEAD SHA一致 → 停止
↓
④ 実機確認
ユーザー
RUN_DEV / GUI / 機能 / 実紙等
↓
⑤ ビルド・配布・確認
ユーザー
正式ワンクリック経路
↓
具体的な失敗症状が出た場合だけ
⑥ Windows障害調査
Codex等の実機AI
```

③と④を混同しません。③でアプリを起動した時点で工程逸脱です。

## ChatGPTの役割

GitHubへ直接アクセスできる場合、原則として次をChatGPT側で完結させます。

- 現物調査
- 設計・仕様整理
- GitHub上の実装
- テスト追加
- branch / commit / push / PR
- コードレビュー
- candidate branch / candidate SHAの確定
- GitHub Actionsのgreen確認
- `SYNC_CLICK_ME.cmd` / `RUN_DEV.cmd` / build / update等のワンクリック経路の整備
- ④でユーザーが確認する内容の整理
- ⑥が必要になった場合のCodex指示の作成

GitHubで完結する作業をCodexへ重複依頼しません。

## ユーザーの役割

ユーザーは実機の前にいる正式な `windows-real` / `real-peripherals` 能力保有者です。

既定担当:

- ③ `SYNC_CLICK_ME.cmd` によるcandidate同期
- ④ `RUN_DEV.cmd` 等によるソース起動
- ④ GUI操作・表示確認・通常機能確認
- ④ 実紙印刷・実プリンター確認
- ⑤ `BUILD_*_CLICK_ME.cmd` 等の正式ワンクリックbuild
- ⑤ `UPDATE_*` / `UPDATE_SHARED_FOLDER.cmd` / HDD更新等の正式ワンクリックdeploy/update
- 結果・症状・エラーのChatGPTへの報告

ユーザーに長いPowerShell/Gitを手打ちさせるのは最終手段です。**既存の安全なワンクリック操作は最終手段ではなく標準工程です。**

## ③ candidate同期

③はユーザーの定型操作です。

- repoごとに正式なcandidate branchを明示設定する。`origin/HEAD` やdefault branchから推測しない。
- ChatGPTは②完了時にcandidate branch / candidate SHAを明示する。
- ユーザーは `SYNC_CLICK_ME.cmd` を実行する。
- スクリプトは expected repo / branch / tracked dirty / detached HEAD / local ahead / expected SHAを検査する。
- 同期は `fetch --prune` → `merge --ff-only` のみ。
- stash / reset / rebase / force / 自動branch switchを行わない。
- 成功条件は `HEAD == origin/<candidate-branch> == candidate SHA` かつ tracked clean。
- 成功したら結果を `SYNC_RESULT.txt` に残して停止する。

③ではアプリ起動、GUI / Computer-Use、機能確認、実紙、追加テスト、candidate再レビュー、再調査、build、deploy / UPDを行いません。

## Codexの役割

Codexは通常の実機確認担当でも、通常のcandidate同期担当でもありません。

### ⑥ Windows障害調査

③④⑤でユーザーが再現した**具体症状**があり、GitHub・CI・ユーザー報告だけでは原因を切り分けられない場合だけ使用します。

典型例:

- `SYNC_CLICK_ME.cmd` が conflict / detached HEAD / local ahead / Git異常などで停止し、ユーザー操作だけでは解決できない
- 起動しない
- `*_CLICK_ME.cmd` が具体的なエラーで停止
- Windows固有エラー
- printer / driver / shared folder / HDD / 外部Windowsアプリの異常
- 実機状態を見ないと原因特定できない
- ユーザー1人では物理的に成立しない複数PC試験

「Windows実機が必要」「GUIを見たい」「念のため動作確認」は単独ではCodexトリガになりません。

## Codex指示の必須形式

```text
【工程】⑥ Windows障害調査
【変更ティア】T0 / T1 / T2 / T3
【症状】ユーザーが再現した具体的エラー・挙動
【対象】repo / branch / HEAD SHA / candidate SHA
【確立した事実】確認済み事項
【green baseline】CI / test + SHA
【調査範囲】その症状の切り分けに限定
【Codexで行わない】症状と無関係な再実装 / full regression / 通常build / 通常deploy / scope拡大
【変更禁止】本番反映 / tag / merge 等
【報告】確認した事実 / 原因候補 / 必要な次アクション / 未確認事項
```

症状のない⑥は開始しません。

## 回答前の必須ゲート

ソフトウェア開発について次工程・担当・Codex指示を回答する前に、毎回次を確認します。

1. 今は①〜⑤のどの工程か。
2. 通常AI担当は①②までか。
3. ③はユーザーの `SYNC_CLICK_ME.cmd` か。
4. ④/⑤をCodexへ渡していないか。
5. Codexなら具体症状付き⑥か。
6. ユーザーが安全にワンクリックでできる作業を有料AIへ戻していないか。
7. 変更ティアと調査・テスト予算は `AGENT_EFFICIENCY_POLICY.md` に合っているか。

通常のChatGPT会話ではMemoryやrepo内 `AGENTS.md` の自動発火を前提にしません。同一チャットでもこの短い工程ゲートは毎回適用します。

## Windowsアプリの標準運用

原則4経路を揃えます。

```text
candidate同期: SYNC_CLICK_ME.cmd
開発起動:     RUN_DEV.cmd
正式build:    BUILD_*_CLICK_ME.cmd 等
配布更新:     UPDATE_* / UPDATE_SHARED_FOLDER.cmd 等
```

- 日常開発はソース起動を標準とする。
- EXEは必要時だけ作る。
- candidate同期 / build / deployはユーザーが安全にワンクリックできるようにする。
- これらのスクリプト自体が具体的に失敗した場合だけ⑥Codex候補とする。
- 配布物と業務データを分離し、単純な共有フォルダ全体 `/MIR` を避ける。

## GitHub上での直接実装

ユーザーが実装・修正を依頼し、ChatGPTがGitHubへ書き込み可能なら、その依頼範囲で実装・テスト追加・branch・commit・push・PRまで進めます。

- 既存main / branch / HEADを確認する。
- 大きな変更・移行は専用branch / Draft PRへ隔離する。
- 本番・安定版を無断で壊さない。
- 秘密情報・実運用データ・ローカル専用設定をGitへ入れない。
- `AGENT_EFFICIENCY_POLICY.md` のtier相当テストを行う。
- CI代替を使うT2/T3はcandidate SHAのgreen確認まで②完了にしない。
- Windows実機項目は未確認として④へ渡す。

## スコープ変更時の確認

次が判明した場合は、勝手に大きく範囲を広げません。

- データ消失や他機能への大きな影響
- 大きなデメリット
- 複数方式からユーザー判断が必要
- 本番運用変更が必要
- 当初完了条件では問題を十分に解消できない

依頼された目的を達成するための安全な小規模調査・テスト・補助実装は、過度な確認待ちを挟まず進めます。

## Git運用

- 正式ソースを基準にする。
- 既存変更を保護する。
- commit前に変更内容・影響範囲・未確認事項を整理する。
- ユーザーが「更新して」「実装して」「移行して」等を明示した依頼範囲では、branch / commit / push / PRを進められる。
- tag、本番反映、実運用データ更新は別途明示がない限り行わない。
- ③のローカル同期は実装作業ではない。candidate同期後に新規編集・commitを始めない。

## フェーズ規律（調査／設計／実装／検証）

ユーザーが「調査だけ」「設計だけ」等と段階を限定した場合、その境界を越えません。

最終成果まで依頼された場合は、依頼範囲内で調査 → 設計 → 実装 → ②検証まで連続して進めてよい。ただし、③candidate同期、④実機確認、⑤build/deployは別工程として担当を守ります。

本番反映、tag、実運用データ更新など安定版を確定する操作は、別途明示がない限り行いません。

## development-management運用

チャットを唯一の情報源にしません。将来の判断に必要な内容だけを次へ記録します。

- `docs/decisions.md`: 重要な設計判断
- `PROJECT_STATUS.md`: 現在地・未解決課題
- `LESSONS_LEARNED.md`: 再発防止知見
- `projects/*.md`: プロジェクト固有の現状
- `CHANGELOG.md`: 変更履歴

## ユーザーの開発方針

- 長期保守性を重視する
- `development-management` を司令塔とする
- 一般論より現物を基準にする
- ChatGPTで可能なGitHub作業はChatGPT側で進める
- ③candidate同期、④実機確認、⑤ワンクリックbuild/deployはユーザー既定
- Codexは具体的なWindows障害調査へ温存する
- ユーザーへ長い手打ちコマンドを不必要に押し戻さない
- 安全性・Codexクレジット・ユーザー操作可能性の3軸で担当を決める
