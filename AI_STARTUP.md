# AI Startup

このファイルは、新しいチャットや別の実行環境が安全に作業を開始するための入口です。

## 最優先

1. **[OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)** で工程①〜⑤、担当、③停止条件、④⑤ユーザー既定、実機AI利用条件、実機AI User Overrideを確認する。
2. [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) で変更ティア T0〜T3 と読み込み・テスト予算を決める。
3. 対象repo / branch / HEAD SHA / dirty treeを確認する。

通常のChatGPT会話ではMemoryやrepo内 `AGENTS.md` が自動発火する前提を置かない。**「次に何をするか」「誰へ渡すか」「Codex / Claude 等の実機AIへ何を指示するか」を答える前は、同一チャットでも `OPERATING_CONTRACT.md` の短い工程ゲートを毎回照合する。**

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
⑥ Windows障害調査     通常フローでは③④⑤で具体症状が出た場合だけCodex / Claude等の実機AI

実機AI User Override    ユーザーが明示した指定作業に限り、①〜⑤も指定された実機AIへ委任可
```

### 実機AI User Override

ユーザーが「Codexに渡して」「Claudeでやって」「実機AIにやらせて」等、実機AI利用を明示した場合は、通常の担当制限より [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) §2.1 を優先する。

- 指定された作業に限り、①〜⑤の設計・開発・同期導線整備・candidate同期・実機確認・build / deploy / update等も実機AIへ渡してよい。
- 「通常は実機AIを⑥だけに使う」ことを理由に明示指示を拒否しない。
- **Codex / Claude 等の特定エージェントが名指しされたら、そのエージェント指定を維持する。ChatGPTや別エージェントへ勝手に置換しない。**
- **指定エージェントへの直接連携が無い場合は、ChatGPTが作業を自動代行せず、そのエージェントへそのまま渡せる完成済みの指示文を返してhandoff地点で停止する。**
- 担当を変更するのは、ユーザーが明示的に再指定した場合だけ。
- overrideを別作業・別工程へ自動拡張しない。
- candidate SHA、CI、③停止条件、④⑤の完了条件、正式ワンクリック操作、本番反映・承認ルールは維持する。
- ③を実機AIへ渡してもSHA一致確認で停止し、④へ自動進行しない。④・⑤もユーザーが明示した工程だけ実施する。

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
- CI未カバーのGUI・実紙・実HDD・実LAN等は、通常フローではまず④/⑤ユーザー確認へ渡す。
- 通常フローの実機AIはワンクリック操作の代行ではなく、具体的な失敗症状のWindows障害調査に使う。
- **ユーザーが実機AI利用を明示した場合は実機AI User Overrideを適用し、指定範囲では上記の通常担当を上書きしてよい。**

## 作業前チェック

- 現在工程①〜⑤と担当
- 変更ティア / blast radius
- repo / branch / HEAD / dirty tree
- ChatGPTでGitHub側を完結できるか
- CIカバレッジ
- ③のcandidate branch / candidate SHA
- ④/⑤でユーザーが安全に確認できる範囲
- **ユーザーがCodex / Claude 等の実機AI利用を明示したか。明示ありなら指定エージェントと対象範囲はどこか**
- **指定エージェントへの直接連携が無い場合、ChatGPTへ自動代行せずhandoff指示文で停止できているか**
- 明示なしで実機AIが必要なら具体症状付き⑥か

## 禁止事項

- チャットだけに重要判断を残す
- 正式ソース以外で開発
- 秘密情報・認証情報・実運用データをGit管理
- CI greenだけで実機確認済みと扱う
- ChatGPTと実機AIでGitHub実装を二重化
- ③同期タスクでアプリ起動 / GUI / 実機確認 / 追加テストへ進む
- **実機AI User Overrideが明示されていないのに**ユーザーが安全にできる③④⑤を実機AIへ代行させる
- **実機AI User Overrideが明示されていないのに**無症状の「念のため実機確認」を実機AIへ依頼
- 実機AI User Overrideで指定された範囲を超えて、次工程・別作業へ自動進行する
- **指定されたCodex / Claude等が使えないことを理由に、ChatGPTや別エージェントが勝手に作業を代行する**
- targeted failure診断にfull suiteを使う

## 新しいChatGPT会話へ常駐させる短い契約

```text
開発作業では development-management/OPERATING_CONTRACT.md を工程担当の正本とする。
①設計=ChatGPT、②開発=ChatGPT+GitHub+CI、③candidate同期=ユーザーのSYNC_CLICK_ME、④実機確認=ユーザー、⑤build/deploy=ユーザーの正式ワンクリック操作。
③は想定branch / tracked clean / HEAD SHA==candidate SHAを確認したら停止。アプリ起動、GUI、機能確認、実紙、追加テスト、再調査、build、deployは禁止。
通常、Codex / Claude等の実機AIは③④⑤でユーザーが再現した具体的Windows障害の⑥調査だけに使う。CI未カバーの実機確認はまずユーザーへ渡す。
ユーザーが安全にSYNC_CLICK_ME / RUN_DEV / *_CLICK_ME / UPDATE_*を実行できる場合、通常は実機AIに代行させない。
ただし、ユーザーが「Codexに渡して」「Claudeでやって」等と明示した場合、その指定作業に限り通常の実機AI利用制限を上書きする。①〜⑤に属する設計・開発・同期導線整備・candidate同期・実機確認・build/deploy等も指定された実機AIへ渡せる。
特定エージェントが名指しされた場合はその指定を維持する。直接連携が無くてもChatGPTや別エージェントへ勝手に置換せず、指定エージェント向けの完成済みhandoff指示文を返して停止する。
実機AI利用時もcandidate SHA、CI、③停止条件、④⑤の完了条件・正式操作・承認条件は維持し、指定された工程を超えて自動進行しない。
実機AI指示前に毎回、現在工程とOPERATING_CONTRACTを照合する。
調査・テスト量はAGENT_EFFICIENCY_POLICYのT0〜T3に従う。
```

## 記録

将来の判断に必要なものだけを記録する。

- 重要判断: `docs/decisions.md`
- 現在地・未解決: `PROJECT_STATUS.md`
- 再発防止: `LESSONS_LEARNED.md`
- project固有: `projects/*.md`
- 変更履歴: `CHANGELOG.md`
