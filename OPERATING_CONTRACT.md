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
| ① 設計 | ChatGPT | 方針・受入条件・変更ティアを確定。実装前ならここで止まる |
| ② 開発・作成 | ChatGPT + GitHub + GitHub Actions | GitHub上の実装、tier相当targeted/regression、必要ならcandidate SHAのCI green確認 |
| ③ 実機投入 | Codex またはユーザー | 正式ローカルrepoをcandidateへ同期し、branch / HEAD SHA / dirty treeを確認して**停止** |
| ④ 実機確認 | **ユーザー** | `RUN_DEV.cmd` 等で起動、GUI操作、機能確認、実紙確認などを実施し結果を報告 |
| ⑤ ビルド・配布・確認 | **ユーザー** | 既存 `*_CLICK_ME.cmd` / `UPDATE_*.cmd` 等のワンクリック経路を実行し結果を確認 |

④/⑤で具体的な失敗症状が出た場合だけ、例外工程としてCodexのWindows障害調査へ進みます。

## 3. 工程③「実機投入」の厳格な停止条件

③をCodexへ渡した場合、行ってよいのは原則次だけです。

- 正式repo確認
- 想定branch確認
- dirty tree確認と既存変更保護
- `git fetch`
- 必要な `git pull --ff-only` / checkout / switch 等によるcandidate同期
- `HEAD SHA == candidate SHA` の確認
- 結果報告

**HEAD SHA一致を確認したら必ず停止します。**

③では次を行いません。

- アプリ起動
- GUI / Computer-Use
- 機能確認
- 実紙印刷
- 実プリンター操作
- 追加テスト
- full regression
- candidateの再レビュー
- 根本原因の再調査
- build
- deploy / UPD
- 本番反映

③の目的は「GitHub candidateを実機へ正しく置くこと」であり、「candidateを実機で検証すること」ではありません。

## 4. 工程④「実機確認」はユーザー既定

ユーザーが通常担当するもの:

- `RUN_DEV.cmd` 等のワンクリック起動
- GUIを開く・見る・通常操作する
- 修正箇所を確認する
- 実紙印刷を行う
- 実データを壊さない範囲の実機確認
- 画面表示・症状・エラーをChatGPTへ報告する

「CIでは確認できない」「Windows実機が必要」は、Codex利用の自動トリガではありません。まずユーザーの④で確認します。

## 5. 工程⑤「ビルド・配布・確認」はユーザー既定

既存の安全なワンクリック経路がある場合、ユーザーが実行します。

例:

- `BUILD_EXE_CLICK_ME.cmd`
- `BUILD_RELEASE.cmd`
- `UPDATE_SHARED_FOLDER.cmd`
- `UPDATE_HDD_CLICK_ME.cmd`
- その他、対象repoで正式化されたワンクリックbuild / deploy / update手順

長いPowerShell/Gitの手打ち、conflict解消、force push、履歴書き換え、`.git` 内部操作、実運用DBや秘密情報の直接編集、共有フォルダへの手動 `robocopy` はユーザー標準操作にしません。

## 6. Codexを使う条件

Codexは通常の実機確認担当ではなく、**ユーザー操作だけでは解決しないWindows実機トラブルの調査担当**です。

原則として次の場合だけ使用します。

- ③candidate同期をCodexへ明示的に任せる場合
- ④/⑤でユーザーが具体的な失敗症状を再現した場合
- 起動しない
- `*_CLICK_ME.cmd` が具体的な行・エラーで停止する
- Windows固有エラー
- printer / driver / shared folder / HDD / 外部Windowsアプリの異常
- GitHub・CI・ユーザー報告だけでは原因を切り分けられない実機状態の調査
- 2台同時など、ユーザー1人では物理的に成立しない試験

**無症状の「念のため実機確認」はCodexへ依頼しません。**

## 7. Codexへ渡す指示の必須形式

Codex指示は必ず `【工程】` から始めます。

```text
【工程】③ 実機投入のみ / ⑥ Windows障害調査
【変更ティア】T0 / T1 / T2 / T3
【対象】repo / branch / candidate SHA
【確立した事実】確認済み事項
【green baseline】CI / test + SHA
【Codexで行う】今回必要な作業だけ
【Codexで行わない】アプリ起動 / GUI操作 / 機能確認 / 実紙印刷 / 追加テスト / full regression / candidate再レビュー / 再調査 / 通常build / 通常deploy
【停止条件】③なら HEAD SHA == candidate SHA を確認した時点
【報告】branch / HEAD / dirty tree / 実施結果 / エラーのみ
```

⑥障害調査では、`【症状】` を必須とします。症状のない⑥は開始しません。

## 8. ChatGPTの毎ターン継続ゲート

通常のChatGPT会話ではrepo内 `AGENTS.md` やMemoryが自動発火する前提を置きません。

ソフトウェア開発について「次に何をするか」「誰に渡すか」「Codexへ何を指示するか」を回答する直前に、ChatGPTは最低限この契約を照合します。

セルフチェック:

> この次工程は①〜⑤のどこか。Codex指示なら③同期のみ、または具体症状付き⑥か。④/⑤をCodexへ渡していないか。ユーザーが安全にワンクリックでできる作業を有料AIへ戻していないか。

同一チャットで過去にDevelopmentを読んでいても、この工程担当チェックは省略しません。

## 9. 他文書との関係

- T0〜T3、読み込み予算、テスト範囲、反復上限、CI baselineは `AGENT_EFFICIENCY_POLICY.md` を維持します。
- 詳細な運用・Git・フェーズ規律は `AI_OPERATING_MANUAL.md` を維持します。
- 能力定義は `CAPABILITIES.md` を維持します。
- ただし、**①〜⑤の担当、ユーザー既定操作、③の停止条件、Codex利用条件は本文書が最優先**です。

この契約の目的は「AIにできることを最大化する」ことではありません。**安全を落とさず、ユーザーが安全にできる工程はユーザーへ残し、Codexを本当に実機AIが必要な場面だけに限定すること**です。
