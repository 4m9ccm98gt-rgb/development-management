# AI Checklist

> **先に [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を読み、変更ティア T0〜T3 を決める。**
> このチェックリストはティアに従う。全項目を無条件に実行しない。

## すべてのティアで確認

- [ ] [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md)（変更ティア・読み込み予算・テスト予算・反復上限）
- [ ] 対象 repo / branch / HEAD SHA / dirty tree
- [ ] 引き継ぎに `【確立した事実】` があればそれ
- [ ] 対象 README または `projects/*.md` の今回に直接必要な箇所
- [ ] 同一sessionで確認済みの文書・事実を再ロード / 再導出していない

## T0 / T1 はここで止める

上記に加えて、対象fileと直接の呼び出し元1ホップのみ。

- `AI_STARTUP.md` は開かない。
- `AI_OPERATING_MANUAL.md`、`PROJECT_STATUS.md`、`VERSION_MATRIX.md`、`SYSTEM_OVERVIEW.md`、`docs/decisions.md`、`LESSONS_LEARNED.md` は今回に直接必要でない限り開かない。
- 既存機構の局所修正では REUSE_MAP / 他repo横断調査を発火させない。

## T2 で追加

- [ ] [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) の今回に関係する箇所
- [ ] [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) の今回に関係する箇所
- [ ] [CAPABILITIES.md](CAPABILITIES.md)（能力判定が必要な場合）
- [ ] 金額・在庫・印刷・DB・共有フォルダ・build/deploy等に関係する場合だけ、該当する `docs/decisions.md` / `LESSONS_LEARNED.md` / `REUSE_MAP.md`
- [ ] 変更する契約・形式の producer / consumer 両側

## T3 で追加

- [ ] [AI_STARTUP.md](AI_STARTUP.md) のフル開始チェーン
- [ ] `PROMPT_PRINCIPLES.md` / `AI_MEMORY.md` / `PROJECT_STATUS.md` / `VERSION_MATRIX.md` / `SYSTEM_OVERVIEW.md` / `docs/decisions.md` / `LESSONS_LEARNED.md` の必要箇所

## 判断・記録（該当時のみ）

- [ ] GitHubでChatGPTが直接進められる作業か / Windows実機でCodexが必要な作業か
- [ ] Python/Windowsアプリなら、今回の変更に関係する場合だけソース起動・手動build・配布更新経路を確認したか
- [ ] Codexへ通常のEXE build / 通常配布更新を依頼していないか
- [ ] `development-management` へ残す将来有用な事実・運用/設計変更があるか
- [ ] 確認できたことと未確認を分けたか
- [ ] ユーザーがフェーズを限定した場合、その境界内か
- [ ] 仮説を事実・原因・設計・Codex指示へ昇格させていないか
- [ ] AI側で安全に実行できる作業を理由なくユーザーへ戻していないか
