# Five-stage Operating Contract rollout — 2026-09-08

## 背景

Codexクレジット削減のため②開発・作成をChatGPT/GitHubへ移したにもかかわらず、③実機投入だけをCodexへ渡したつもりのタスクが④実機確認まで継続し、従来の②+③より大きいクレジット消費が発生した。

Claude独立レビューで、原因はT0〜T3やCI設計ではなく、**工程③と④の未分離、ユーザー操作可能性の欠落、Codexを通常実機確認担当とした役割設計、ChatGPT-primary bootstrap不足**と判定された。

## 採用した設計判断

### 1. 5工程を正式化

1. ①設計 = ChatGPT
2. ②開発・作成 = ChatGPT + GitHub + GitHub Actions
3. ③実機投入 = Codexまたはユーザー。candidate同期とSHA確認のみ
4. ④実機確認 = ユーザー
5. ⑤ビルド・配布・確認 = ユーザーの正式ワンクリック経路

④/⑤で具体的な失敗症状が出た場合だけ⑥Windows障害調査としてCodexを使う。

### 2. ③の停止条件

③をCodexへ渡した場合、正式repo / branch / dirty tree確認、fetch / pull / checkout、`HEAD SHA == candidate SHA`確認までで停止する。

③では以下を禁止:

- アプリ起動
- GUI / Computer-Use
- 機能確認
- 実紙 / printer確認
- 追加テスト / full regression
- candidate再レビュー
- 根本原因再調査
- build
- deploy / UPD

### 3. 担当判定を3軸化

従来の「安全性 ↔ Codexクレジット」に加え、**ユーザーが安全にワンクリック・通常GUIで実施できるか**を正式な軸に追加した。

実機の前にいるユーザー自身を `windows-real` / `real-peripherals` / `shared-server` の能力保有者として扱う。

### 4. CI未カバー領域の既定担当

GUI、実印刷、実HDD、実LAN、live外部接続等がCI未カバーでも、それだけでCodexを発火させない。

まず④/⑤のユーザー確認として残し、ユーザーが実施できない、または具体的な失敗症状が出た場合だけCodex候補にする。

### 5. ChatGPT-primary bootstrap

通常のChatGPT会話ではMemoryやrepo内 `AGENTS.md` の自動発火を前提にしない。

「次に何をするか」「誰へ渡すか」「Codexへ何を指示するか」を回答する前に、短い `OPERATING_CONTRACT.md` の工程担当ゲートを毎回照合する。

## 変更したdevelopment-management文書

- `OPERATING_CONTRACT.md` 新設
- `AGENTS.md`
- `AGENT_EFFICIENCY_POLICY.md`
- `AI_OPERATING_MANUAL.md`
- `AI_CHECKLIST.md`
- `AI_STARTUP.md`
- `CAPABILITIES.md`
- `DEVELOPMENT_RULES.md`

T0〜T3、green baseline、CI drift guard等の健全だった仕組みは維持した。

## 各アプリrepoへのCodex入口ガード

中央DevelopmentをCodexが読み損ねても③が④へ膨張しないよう、次のrepoへ短い `AGENTS.md` を追加した。

- `next-day-setup / main`
- `inventory-reconciliation-system / main`
- `menu-sheet-generator / main`
- `food-cost-calculation-system / main`
- `qr-supply-ordering-system / main`
- `beverage-inventory-ordering-system / main`
- `beverage-inventory-ordering-system / python-desktop-migration`

各 `AGENTS.md` は `【工程】③` の場合にSHA一致で停止し、アプリ起動 / GUI / 実機確認 / 追加テスト / build / deployを禁止する。

## ChatGPT常駐用の短文

repo文書だけでは通常ChatGPTチャットに自動注入されないため、ChatGPTのCustom Instructions / Project Instructions等へ常駐させる場合は次を使用する。

```text
開発作業では development-management/OPERATING_CONTRACT.md を工程担当の正本とする。
①設計=ChatGPT、②開発=ChatGPT+GitHub+CI、③実機投入=candidate同期とSHA確認だけ、④実機確認=ユーザー、⑤build/deploy=ユーザーの正式ワンクリック操作。
Codexは③同期または、④/⑤でユーザーが再現した具体的Windows障害の調査だけに使う。
③ではHEAD SHA==candidate SHAを確認したら停止。アプリ起動、GUI、機能確認、実紙、追加テスト、再調査、build、deployは禁止。
CI未カバーの実機確認はまずユーザーへ渡す。
ユーザーが安全にRUN_DEV / *_CLICK_ME / UPDATE_*を実行できる場合、Codexに代行させない。
Codex指示前に毎回、現在工程とOPERATING_CONTRACTを照合する。
調査・テスト量はAGENT_EFFICIENCY_POLICYのT0〜T3に従う。
```

## 今後の効果測定

次の実タスクで③だけをCodexへ渡し、以下を確認する。

- Codexがアプリを起動しない
- GUI / Computer-Useを開始しない
- 追加テストをしない
- SHA一致で停止する
- 従来の②+③や誤った③+④よりクレジット消費が明確に低い

もし③だけでも異常に高い消費が残る場合、その時点で初めてCodexの現在の課金・PC操作セッション自体のコスト問題として切り分ける。

## 完了判定

ClaudeレビューのCritical/Highで指摘された工程設計欠陥は文書上解消した。

ただし、通常ChatGPTチャットへrepo内文書を自動注入する仕組みはGitHub文書だけでは作れないため、**ChatGPT側の常駐指示設定は別レイヤー**として扱う。repo側では常駐用短文を正本化し、通常会話ではChatGPTが毎回 `OPERATING_CONTRACT.md` を照合する運用とする。
