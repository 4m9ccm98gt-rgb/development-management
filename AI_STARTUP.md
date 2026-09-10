# AI Startup

このファイルは、新しいチャットや別の実行環境が安全に作業を開始するための入口です。

## 最優先

1. **[OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)** で工程①〜⑤、担当、③停止条件、④⑤ユーザー既定、Codex利用条件を確認する。
2. [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) で変更ティア T0〜T3 と読み込み・テスト予算を決める。
3. 対象repo / branch / HEAD SHA / dirty treeを確認する。

通常のChatGPT会話ではMemoryやrepo内 `AGENTS.md` が自動発火する前提を置かない。**「次に何をするか」「誰へ渡すか」「Codexへ何を指示するか」を答える前は、同一チャットでも `OPERATING_CONTRACT.md` の短い工程ゲートを毎回照合する。**

## T0 / T1

T0/T1では本ファイルの残りを読まなくてよい。

- `OPERATING_CONTRACT.md`
- `AGENT_EFFICIENCY_POLICY.md`
- 対象READMEまたは `projects/*.md` の必要部分
- touched file + 直接caller 1 hop

を基本上限とする。

## T2

原則次だけ追加する。

1. [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) の今回に関係する部分
2. [AI_CHECKLIST.md](AI_CHECKLIST.md)
3. 能力判定が必要なら [CAPABILITIES.md](CAPABILITIES.md)
4. [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) の今回に関係するdomain節
5. 対象README / `projects/*.md`
6. 金額・在庫・印刷・DB・共有・build/deploy等に関係する場合だけ該当decision / lesson

## T3

構造変更・repo横断・移行では次を必要範囲で確認する。

1. `OPERATING_CONTRACT.md`
2. `AGENT_EFFICIENCY_POLICY.md`
3. `AI_OPERATING_MANUAL.md`
4. `AI_CHECKLIST.md`
5. `CAPABILITIES.md`
6. `DEVELOPMENT_RULES.md`
7. `PROJECT_STATUS.md`
8. `VERSION_MATRIX.md`
9. `SYSTEM_OVERVIEW.md`
10. `docs/decisions.md`
11. `LESSONS_LEARNED.md`
12. 対象 `projects/*.md` / README

退役前整備の運用文書は必要時だけ参照する。

## 標準工程

```text
① 設計                ChatGPT
② 開発・作成          ChatGPT + GitHub + GitHub Actions
③ candidate同期       ユーザー。SYNC_CLICK_ME.cmdで同期しSHA一致で停止
④ 実機確認            ユーザー
⑤ build/deploy/update ユーザーの正式ワンクリック経路
⑥ Windows障害調査     ③④⑤で具体症状が出た場合だけCodex等の実機AI
```

### ③の停止条件

`SYNC_CLICK_ME.cmd` で想定branch、tracked clean、`HEAD SHA == origin SHA == candidate SHA` を確認して報告したら停止。

③では以下を禁止する。

- アプリ起動
- GUI / Computer-Use
- 機能確認
- 実紙 / printer確認
- 追加テスト / full regression
- candidate再レビュー / 再調査
- build / deploy / UPD

同期対象branchはrepoごとに明示し、`origin/HEAD` やdefault branchから推測しない。

## Windowsアプリ標準

- candidate同期は `SYNC_CLICK_ME.cmd` からユーザーが実施できる。
- 開発版は `RUN_DEV.cmd` 等からユーザーが起動できる。
- EXEは `BUILD_*_CLICK_ME.cmd` 等でユーザーがワンクリックbuildできる。
- 配布更新は `UPDATE_*` / `UPDATE_SHARED_FOLDER.cmd` 等でユーザーがワンクリック実行できる。
- CI未カバーのGUI・実紙・実HDD・実LAN等は、まず④/⑤ユーザー確認へ渡す。
- Codexはワンクリック操作の代行ではなく、具体的な失敗症状のWindows障害調査に使う。

## 作業前チェック

- 現在工程①〜⑤と担当
- 変更ティア / blast radius
- repo / branch / HEAD / dirty tree
- ChatGPTでGitHub側を完結できるか
- CIカバレッジ
- ③のcandidate branch / candidate SHA
- ④/⑤でユーザーが安全に確認できる範囲
- Codexが必要なら具体症状付き⑥か

## 禁止事項

- チャットだけに重要判断を残す
- 正式ソース以外で開発
- 秘密情報・認証情報・実運用データをGit管理
- CI greenだけで実機確認済みと扱う
- ChatGPTとCodexでGitHub実装を二重化
- ③同期タスクでアプリ起動 / GUI / 実機確認 / 追加テストへ進む
- ユーザーが安全にできる③④⑤をCodexへ代行させる
- 無症状の「念のため実機確認」をCodexへ依頼
- targeted failure診断にfull suiteを使う

## 新しいChatGPT会話へ常駐させる短い契約

```text
開発作業では development-management/OPERATING_CONTRACT.md を工程担当の正本とする。
①設計=ChatGPT、②開発=ChatGPT+GitHub+CI、③candidate同期=ユーザーのSYNC_CLICK_ME、④実機確認=ユーザー、⑤build/deploy=ユーザーの正式ワンクリック操作。
③は想定branch / tracked clean / HEAD SHA==candidate SHAを確認したら停止。アプリ起動、GUI、機能確認、実紙、追加テスト、再調査、build、deployは禁止。
Codexは③④⑤でユーザーが再現した具体的Windows障害の⑥調査だけに使う。
CI未カバーの実機確認はまずユーザーへ渡す。
ユーザーが安全にSYNC_CLICK_ME / RUN_DEV / *_CLICK_ME / UPDATE_*を実行できる場合、Codexに代行させない。
Codex指示前に毎回、現在工程とOPERATING_CONTRACTを照合する。
調査・テスト量はAGENT_EFFICIENCY_POLICYのT0〜T3に従う。
```

## 記録

将来の判断に必要なものだけを記録する。

- 重要判断: `docs/decisions.md`
- 現在地・未解決: `PROJECT_STATUS.md`
- 再発防止: `LESSONS_LEARNED.md`
- project固有: `projects/*.md`
- 変更履歴: `CHANGELOG.md`
