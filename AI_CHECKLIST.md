# AI Checklist

> **先に [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) で工程①〜⑤と担当を確認し、その後 [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) で変更ティア T0〜T3 を決める。**
> 工程担当は `OPERATING_CONTRACT.md`、調査・テスト予算は `AGENT_EFFICIENCY_POLICY.md` を正とする。

## すべてのティアで確認

- [ ] [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md)（現在工程・③停止条件・④⑤ユーザー既定・⑥Codex条件）
- [ ] [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md)（変更ティア・読み込み予算・テスト予算・反復上限・CI代替条件）
- [ ] 対象 repo / branch / HEAD SHA / dirty tree
- [ ] 引き継ぎに `【確立した事実】` があればそれ
- [ ] 対象 README または `projects/*.md` の今回に直接必要な箇所
- [ ] 同一sessionで確認済みの文書・事実を理由なく再ロード / 再導出していない

## 毎ターンの工程担当セルフチェック

ソフトウェア開発について「次に何をするか」「誰に渡すか」「Codexへ何を指示するか」を答える前に毎回確認する。

- [ ] この次工程は①〜⑤のどこか
- [ ] 通常フローでAIが担当するのは①設計と②開発までか
- [ ] ③candidate同期はユーザーの `SYNC_CLICK_ME.cmd` になっているか
- [ ] ④実機確認をCodexへ渡していないか
- [ ] ⑤build / deploy / updateをCodexへ渡していないか
- [ ] Codex指示なら **ユーザーが再現した具体症状付き⑥Windows障害調査** か
- [ ] ユーザーが安全に `SYNC_CLICK_ME.cmd` / `RUN_DEV.cmd` / `*_CLICK_ME.cmd` / `UPDATE_*.cmd` でできる作業を有料AIへ戻していないか

同一チャットで過去にDevelopmentを読んでいても、この工程担当チェックは省略しない。

## T0 / T1 はここで止める

上記に加えて、対象fileと直接の呼び出し元1ホップを通常上限とする。T1/T2判定のために必要な場合だけ2ホップ目を確認する。

- `AI_STARTUP.md` は開かない。
- `AI_OPERATING_MANUAL.md`、`PROJECT_STATUS.md`、`VERSION_MATRIX.md`、`SYSTEM_OVERVIEW.md`、`docs/decisions.md`、`LESSONS_LEARNED.md` は今回に直接必要でない限り開かない。
- 既存機構の局所修正では REUSE_MAP / 他repo横断調査を発火させない。
- 2ホップ以内で金額・売上・価格・在庫・数量・帳票・印刷・DB・業務日付へ流れる共有utility変更なら最低T2へ上げる。

## T2 で追加

- [ ] [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) は `スコープ変更時の確認` / `Git運用` / `フェーズ規律` を基本にし、必要時だけ⑥障害調査条件
- [ ] [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) は `開発環境と検証` / `Git管理と情報保護` + 今回のdomain節1つを基本にする
- [ ] [CAPABILITIES.md](CAPABILITIES.md)（能力判定が必要な場合）
- [ ] 変更する契約・形式の producer / consumer 両側
- [ ] CI-covered branchでローカルfullを省略する場合、未カバー領域 / CI skip領域にblast-radiusが触れないか

## T3 で追加

- [ ] [AI_STARTUP.md](AI_STARTUP.md) のフル開始チェーン
- [ ] `PROMPT_PRINCIPLES.md` / `AI_MEMORY.md` / `PROJECT_STATUS.md` / `VERSION_MATRIX.md` / `SYSTEM_OVERVIEW.md` / `docs/decisions.md` / `LESSONS_LEARNED.md` の必要箇所

## ③ candidate同期ゲート

- [ ] ChatGPTが②完了時にcandidate branch / candidate SHAを明示した
- [ ] candidate branchはrepoごとに明示設定され、`origin/HEAD` から推測していない
- [ ] ユーザーが `SYNC_CLICK_ME.cmd` を実行する
- [ ] tracked dirty / wrong repo / wrong branch / detached HEAD / local ahead / SHA不一致では自動修復せず停止する
- [ ] `HEAD SHA == origin SHA == candidate SHA` と tracked cleanを確認した
- [ ] SHA一致後にアプリ起動 / GUI / テスト / build / deployへ進んでいない

## ⑥ Codex障害調査ゲート

- [ ] ユーザーが③④⑤で再現した具体的な `【症状】` がある
- [ ] GitHub / CI / ユーザー報告だけでは原因を特定できない理由がある
- [ ] 調査範囲をその症状に限定した
- [ ] 通常同期 / 通常GUI / 通常build / 通常deployの代行ではない

症状のない「念のため実機確認」はCodexへ渡さない。

## 完了ゲート

- [ ] 自分の変更箇所のtargeted testを実行した
- [ ] T2/T3でCIをローカルfullの代替に使った場合、**candidate SHAのCI greenを実際に確認した**
- [ ] `CI確認予定` / `CI実行中` をterminal completionとして扱っていない
- [ ] CI未カバー領域にblast-radiusが触れる場合、その確認を**まず④ユーザー実機確認として残した**
- [ ] 列挙型CIで新しいdeterministic test/harnessを追加した場合、drift guardを含むworkflow列挙も同一変更で更新した

## 判断・記録（該当時のみ）

- [ ] GitHubでChatGPTが直接進められる作業か
- [ ] Python/Windowsアプリなら、今回に関係する場合だけ同期・ソース起動・手動build・配布更新経路を確認したか
- [ ] ③④⑤のワンクリック操作をユーザー既定として扱ったか
- [ ] Codexへ通常の同期 / GUI確認 / EXE build / 通常配布更新を依頼していないか
- [ ] `development-management` へ残す将来有用な事実・運用/設計変更があるか
- [ ] 確認できたことと未確認を分けたか
- [ ] ユーザーがフェーズを限定した場合、その境界内か
- [ ] 仮説を事実・原因・設計・Codex指示へ昇格させていないか
- [ ] ユーザーへ長い手打ちコマンドを不必要に押し戻していないか
