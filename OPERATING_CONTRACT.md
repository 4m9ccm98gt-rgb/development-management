# Operating Contract

この文書は、通常のChatGPTチャットを含む全開発セッションで常時適用する最小契約です。

**担当・工程・Codex利用条件については、この文書を `AGENTS.md`、`AGENT_EFFICIENCY_POLICY.md`、`AI_OPERATING_MANUAL.md`、`CAPABILITIES.md`、`DEVELOPMENT_RULES.md`、`AI_STARTUP.md` より優先します。**

## 1. 判断軸

担当は次の3軸で決めます。

1. **安全性**: 誤操作・データ損失・本番影響を安全に抑えられるか。
2. **Codexクレジット**: Codexを使う価値が消費量に見合うか。
3. **ユーザー操作可能性**: 既存のワンクリック経路や単純なGUI操作で、ユーザーが安全・簡単に実施できるか。

ユーザーが安全にワンクリックまたは通常GUI操作で実施できる工程を、単に「ChatGPTから触れない実機作業だから」という理由でCodexへ回しません。

## 2. 標準5工程

| 工程 | 既定担当 | 完了条件 |
|---|---|---|
| ① 設計 | ChatGPT | 方針・受入条件・変更ティアを確定 |
| ② 開発・作成 | ChatGPT + GitHub + GitHub Actions | GitHub上で実装・PR・必要なテストを完了し、**candidate branchの採用SHAについてCI greenを確認**してcandidate SHAを記録 |
| ③ candidate同期 | **ユーザー** | `SYNC_CLICK_ME.cmd` を実行し、想定branch / tracked clean / `HEAD SHA == candidate SHA` を確認して**停止** |
| ④ 実機確認 | **ユーザー** | `RUN_DEV.cmd` 等で起動、GUI、機能、実紙など必要な実機確認を行い結果を報告 |
| ⑤ build / deploy / update | **ユーザー** | 既存 `*_CLICK_ME.cmd` / `UPDATE_*.cmd` 等の正式ワンクリック経路を実行し結果を確認 |

通常フローではAIは①②まで。③④⑤をCodexへ代行させません。

## 3. 工程③の境界

③は「GitHubで確定したcandidateを正式ローカルrepoへ安全に置く」工程です。

- 同期対象branchはrepoごとに**明示設定**する。`origin/HEAD` や現在のdefault branchから推測しない。
- ChatGPTは②完了時にcandidate SHAを明示する。
- ユーザーは `SYNC_CLICK_ME.cmd` を実行し、必要ならcandidate SHAを貼り付ける。
- スクリプトは expected repo / expected branch / tracked dirty / local ahead / detached HEAD / SHA不一致を検出したら**自動修復せず停止**する。
- 同期は `git fetch --prune` と `git merge --ff-only` のみを使用する。`reset --hard` / rebase / force / stash自動実行はしない。
- `HEAD SHA == candidate SHA`、origin SHA一致、tracked cleanを確認したら③完了として停止する。
- 結果は `SYNC_RESULT.txt` に保存する。
- `.venv`、業務データ、ローカル設定、Git管理外データは変更しない。

③ではアプリ起動、GUI、機能確認、実紙、追加テスト、candidate再レビュー、再調査、build、deploy、UPD、本番反映を行いません。

## 4. 工程④「実機確認」はユーザー既定

ユーザーが通常担当します。

- `RUN_DEV.cmd` 等のワンクリック起動
- GUI表示・通常操作・修正箇所の確認
- 実紙・実プリンター確認
- 実データを壊さない範囲の実機確認
- 画面表示・症状・エラーのChatGPTへの報告

「CIでは確認できない」「Windows実機が必要」「GUIを見たい」は、単独ではCodex利用のトリガにしません。

## 5. 工程⑤「build / deploy / update」はユーザー既定

既存の安全なワンクリック経路がある場合、ユーザーが実行します。

例:

- `BUILD_EXE_CLICK_ME.cmd`
- `BUILD_RELEASE.cmd`
- `UPDATE_SHARED_FOLDER.cmd`
- `UPDATE_HDD_CLICK_ME.cmd`
- その他、対象repoで正式化されたワンクリックbuild / deploy / update手順

長いPowerShell/Gitの手打ち、conflict解消、force push、履歴書き換え、`.git`内部操作、実運用DBや秘密情報の直接編集、共有フォルダへの手動 `robocopy` はユーザー標準操作にしません。

## 6. 例外工程⑥「Windows障害調査」

Codex等の実機AIを使うのは、③④⑤で**ユーザーが再現した具体的な失敗症状**があり、GitHub / CI / ユーザー報告だけでは切り分けられない場合だけです。

典型例:

- `SYNC_CLICK_ME.cmd` が conflict / detached HEAD / local ahead / Git異常などで停止し、ユーザー操作だけでは解決できない
- アプリが起動しない
- `*_CLICK_ME.cmd` が具体的な行・エラーで停止する
- Windows固有エラー
- printer / driver / shared folder / HDD / 外部Windowsアプリの異常
- ユーザー1人では物理的に成立しない複数PC試験

無症状の「念のため実機確認」、通常の同期、通常のGUI確認、通常build、通常deployにはCodexを使いません。

## 7. ⑥へ渡す必須形式

```text
【工程】⑥ Windows障害調査
【変更ティア】T0 / T1 / T2 / T3
【症状】ユーザーが再現した具体的エラー・挙動
【対象】repo / branch / HEAD SHA / candidate SHA
【確立した事実】確認済み事項
【green baseline】CI / test + SHA
【調査範囲】その症状の切り分けに限定
【Codexで行わない】症状と無関係な再実装 / full regression / 通常build / 通常deploy / scope拡大
【報告】確認した事実 / 原因候補 / 必要な次アクション / 未確認事項
```

症状のない⑥は開始しません。

## 8. ChatGPTの毎ターン継続ゲート

ソフトウェア開発について「次に何をするか」「誰に渡すか」「Codexへ何を指示するか」を回答する直前に、毎回この契約を照合します。

> 今は①〜⑤のどこか。通常フローでAIが担当するのは①②まで。③はユーザーの `SYNC_CLICK_ME.cmd`、④⑤はユーザー。Codexへ渡すなら具体症状付き⑥か。ワンクリックで安全にできる作業を有料AIへ戻していないか。

同一チャットで過去に確認済みでも、この工程担当チェックは省略しません。

## 9. 他文書との関係

- T0〜T3、読み込み予算、テスト範囲、反復上限、CI baselineは `AGENT_EFFICIENCY_POLICY.md`。
- 詳細運用・Git・フェーズ規律は `AI_OPERATING_MANUAL.md`。
- 能力定義は `CAPABILITIES.md`。
- **①〜⑤の担当、③の完了条件、⑥の発火条件は本書を最優先**します。

この契約の目的は「AIにできることを最大化する」ことではありません。安全を落とさず、ユーザーが安全にできる工程はユーザーへ残し、Codexを本当に実機AIが必要な障害調査だけに限定することです。
