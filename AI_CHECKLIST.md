# AI Checklist

> **先に [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を読み、変更ティア T0〜T3 を決める。**
> このチェックリストはティアに従う。全項目を無条件に実行しない。

## すべてのティアで確認

- [ ] [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md)（変更ティア・読み込み予算・テスト予算・反復上限・CI代替条件）
- [ ] 対象 repo / branch / HEAD SHA / dirty tree
- [ ] 引き継ぎに `【確立した事実】` があればそれ
- [ ] 対象 README または `projects/*.md` の今回に直接必要な箇所
- [ ] 同一sessionで確認済みの文書・事実を再ロード / 再導出していない

## T0 / T1 はここで止める

上記に加えて、対象fileと直接の呼び出し元1ホップを通常上限とする。T1/T2判定のために必要な場合だけ2ホップ目を確認する。

- `AI_STARTUP.md` は開かない。
- `AI_OPERATING_MANUAL.md`、`PROJECT_STATUS.md`、`VERSION_MATRIX.md`、`SYSTEM_OVERVIEW.md`、`docs/decisions.md`、`LESSONS_LEARNED.md` は今回に直接必要でない限り開かない。
- 既存機構の局所修正では REUSE_MAP / 他repo横断調査を発火させない。
- 2ホップ以内で金額・売上・価格・在庫・数量・帳票・印刷・DB・業務日付へ流れる共有utility変更なら最低T2へ上げる。

## T2 で追加

- [ ] [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) は `スコープ変更時の確認` / `Git運用` / `フェーズ規律` を基本にし、必要時だけ `Codexへ引き継ぐ条件`
- [ ] [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) は `開発環境と検証` / `Git管理と情報保護` + 今回のdomain節1つを基本にする
- [ ] [CAPABILITIES.md](CAPABILITIES.md)（能力判定が必要な場合）
- [ ] 金額・在庫・印刷・DB・共有フォルダ・build/deploy等に関係する場合だけ、該当する `docs/decisions.md` / `LESSONS_LEARNED.md` / `REUSE_MAP.md`
- [ ] 変更する契約・形式の producer / consumer 両側
- [ ] CI-covered branchでローカルfullを省略する場合、§9の未カバー領域 / CI skip領域にblast-radiusが触れないか

## T3 で追加

- [ ] [AI_STARTUP.md](AI_STARTUP.md) のフル開始チェーン
- [ ] `PROMPT_PRINCIPLES.md` / `AI_MEMORY.md` / `PROJECT_STATUS.md` / `VERSION_MATRIX.md` / `SYSTEM_OVERVIEW.md` / `docs/decisions.md` / `LESSONS_LEARNED.md` の必要箇所

## 完了ゲート

- [ ] 自分の変更箇所のtargeted testを実行した
- [ ] T2/T3でCIをローカルfullの代替に使った場合、**candidate SHAのCI greenを実際に確認した**
- [ ] `CI確認予定` / `CI実行中` をterminal completionとして扱っていない
- [ ] CI未カバーの実プリンター / 実共有 / live IMAP / 実HDD / 実OCR / 実LAN等にblast-radiusが触れる場合、必要なlocal/real確認を別途残した
- [ ] 列挙型CIで新しいdeterministic test/harnessを追加した場合、drift guardを含むworkflow列挙も同一変更で更新した

## 判断・記録（該当時のみ）

- [ ] GitHubでChatGPTが直接進められる作業か / Windows実機でCodexが必要な作業か
- [ ] Python/Windowsアプリなら、今回の変更に関係する場合だけソース起動・手動build・配布更新経路を確認したか
- [ ] Codexへ通常のEXE build / 通常配布更新を依頼していないか
- [ ] `development-management` へ残す将来有用な事実・運用/設計変更があるか
- [ ] 確認できたことと未確認を分けたか
- [ ] ユーザーがフェーズを限定した場合、その境界内か
- [ ] 仮説を事実・原因・設計・Codex指示へ昇格させていないか
- [ ] AI側で安全に実行できる作業を理由なくユーザーへ戻していないか
