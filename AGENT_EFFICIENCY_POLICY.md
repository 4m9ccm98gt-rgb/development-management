# Agent Efficiency Policy

AI / coding agent の品質・安全性を維持しながら、不要な再調査・再推論・テスト反復・Codexクレジット消費を抑える正式ルール。

## 優先順位

この文書は **開始時の読み込み、調査範囲、REUSE_MAP、テスト範囲、反復上限、Codex引き継ぎ** の上限を定める。`AI_STARTUP.md`、`AI_OPERATING_MANUAL.md`、`DEVELOPMENT_RULES.md` 等の広い表現より、このティア別上限を優先する。

ただし、正式ソース・Git状態確認、秘密情報保護、実運用データ保護、本番反映制限、ユーザーが明示したフェーズ境界は弱めない。

## 1. 変更ティア

作業開始時に `T0 / T1 / T2 / T3` と1行の blast-radius を宣言する。

- **T0 機械的**: コメント、docstring、ログ、表示文言、整形、挙動を変えない文書・dead code。
- **T1 局所**: 1関数/1コンポーネント内部。公開シグネチャ、戻り値形式、共有状態、永続化、外部契約を変えない。
- **T2 連結・業務影響**: 公開契約、共有utility、設定/CLI、build/deploy/update、金額・売上・価格・在庫、帳票/印刷、CSV/PMS/Sheets/DB、共有フォルダ/HDD、データ移行、複数モジュール間契約。
- **T3 構造的**: framework/runtime移行、major依存更新、repo横断、CI基盤・既定branch・release方式、大規模architecture、本番移行方式。

### ティアの継ぎ目

- 印刷/帳票コードでも、**表示文言だけ**で選択・集計・計算・レイアウト内容を変えないものは T0/T1。「何を・どれだけ印刷/計算するか」を変えるものは T2。
- 新規 CLI flag / 設定keyが**既定値で従来と同一挙動**なら T1。既存keyの意味・既定値を変える、または既定挙動を変えるなら T2。
- module定数/閾値の値変更は、消費者が単一module内なら T1。複数module、永続化、金額/在庫/価格等の業務数値に効くなら T2。
- 依存更新は patch/minor = T2、major = T3。

作業中に上位ティアだと判明したらティアとblast-radiusを更新する。T2以上へ上がり、依頼の安全条件・運用を実質変更する場合は既存のスコープ変更ルールを適用する。

## 2. 開始時の読み込み予算

### 全ティア共通

- 対象 repo / branch / HEAD SHA / dirty tree
- この文書
- 対象 README または `projects/*.md` の今回に必要な箇所
- 引き継ぎの `【確立した事実】` があればそれ

### T0 / T1

- **`AI_STARTUP.md` を開かない。** この文書のルールだけで開始判断を完結させる。
- touched file + 直接の呼び出し元1ホップを上限とする。
- `PROJECT_STATUS`、`VERSION_MATRIX`、`SYSTEM_OVERVIEW`、`docs/decisions`、`LESSONS_LEARNED` 等は今回に直接必要なときだけ読む。
- 「文脈把握のため」の repo 全体 grep/read をしない。

### T2

- `AI_OPERATING_MANUAL.md` / `DEVELOPMENT_RULES.md` の**今回に関係する箇所だけ**読む。
- 変更する契約・形式の producer / consumer、読み書き両側を確認する。
- 金額・在庫・印刷・DB・共有フォルダ等では、該当する安全ルール/設計判断だけ追加で読む。

### T3

- `AI_STARTUP.md` のフル開始チェーンを適用し、repo横断・既存資産・設計判断・移行経路を確認する。

同一セッション/branchで確認済みの文書は、HEAD・文書・前提が変わらない限り再ロードしない。

## 3. REUSE_MAP / 横断調査

他repo・`REUSE_MAP.md` の横断調査は次の場合だけ発火する。

- 新しい機構・方式を導入する
- 既存方式を置換する
- T3のrepo横断/構造変更
- 対象repo内に既存方式がなく再利用候補を探す必要がある

既存機構のバグ修正、表示調整、局所条件変更では発火させない。

## 4. テスト戦略

- **T0**: 構文/import確認または当該ファイルの最小テスト。full禁止。
- **T1**: targeted testのみ。例 `pytest -k <対象> -q --tb=short -p no:cacheprovider`。full禁止。
- **T2**: targeted + blast-radiusで名指しした regression。**regression ≠ full suite**。
- **T3**: automated full regression + 必要な dry-run / 実環境確認。CIで代替できる automated regression をCodexローカルで重複しない。

### T2と automated regression CI

- §9の表で現在branchを automated regression CI がカバーしている場合、Codexはローカルで同じ automated full regression を回さない。push後CIを回帰ゲートとする。
- 実プリンター、実共有サーバー、live IMAP、外部サイト、実HDD等はCIとは別の確認レベル。今回のblast-radiusが触れる場合だけ Windows実機で確認し、CI成功を実機確認済みとは扱わない。
- CIが automated regression をカバーしないbranchでは、修正ループ中にfullを回さない。
- 金額・在庫・価格・帳票・印刷・DB・共有フォルダ・HDD同期に触れるT2だけ、CI未整備branchでは最終チェックポイントでローカルfullを1回許可する。
- そのfullで回帰が出た場合、修正後に**もう1回だけ**fullを許可する（合計2回まで）。2回目でもgreenにならなければ報告へ移る。

成功ログはサマリ1行に圧縮し、FAILED行・短いtracebackだけを残す。その他の禁止事項は§8。

## 5. 反復上限

- 同じ原因仮説に基づく `修正 → targeted test` は **2回まで**。
- 3回目に入る前に `根本原因の仮説 / 試した差分 / 短い失敗ログ / 次の候補` を整理し、再設計または報告へ移る。
- 自分の編集による syntax / import error 等、その場で直せる自明な失敗はカウントしない。数えるのは原因仮説に対するテスト結果だけ。
- 原因仮説を立て直した場合はカウンタをリセットしてよいが、仮説を細分化して無限に続けない。
- 上限到達前は、安全な依頼範囲内で細かい許可待ちを挟まず進める。

## 6. 確立した事実・green baseline

ChatGPT→Codex / 別sessionの引き継ぎには次を含める。

```text
【変更ティア】 T0 / T1 / T2 / T3
【対象】 repo / branch / commit
【確立した事実】 根本原因 + 根拠 / 関係ファイル地図 / 確認済み事項
【棄却した仮説】 確認内容 + 棄却理由
【greenベースライン】 CIまたはテスト結果 + SHA + 日付
【Codexで回すテスト】 targeted / regression の具体対象
【Codexで回さないもの】 再調査 / 不要full / 通常EXE build等
【残作業】 Windows・実機・ローカル依存で未確認のものだけ
```

- `【確立した事実】` が現在HEADでも有効なら再導出しない。差分・矛盾・新しい失敗がある場合だけ再調査する。
- baseline SHA と現在HEADが異なる場合、`git diff <baseline>..HEAD` の変更が今回のblast-radiusに**触れなければ baseline は有効**。
- 触れている場合は影響moduleだけ targeted で再確認し、baseline鮮度のためだけにfullを回さない。
- baselineが無く、CIにも直近greenが無い場合だけ、最初のgreen確立として§4のティア相当テストを1回行う。
- 長期化するT2/T3だけ必要に応じて `INVESTIGATION.md` 等へ固定する。T0/T1で台帳を毎回作らない。

## 7. 常に残す安全弁

- 正式 repo / branch / HEAD SHA / dirty tree
- ティア + blast-radius
- 変更箇所の targeted test
- T2以上の金額・在庫・印刷・共有フォルダ・HDD・DB等のデータ保全
- build/deploy/release変更のdry-runまたは非破壊確認
- commit/push前のdiffレビュー
- 秘密情報・実運用データ・不要生成物の混入確認
- 実機未確認を「確認済み」にしない
- 本番反映・tag・merge等の既存承認ルール

## 8. 禁止する無駄

- T0/T1で開始文書一式・repo全体を読む
- 既存機構の局所修正で他repoを横断する
- targeted failureの診断にfullを使う
- コード/設定/依存変更なしで同じテストを安心のために再実行する
- passログ全文を会話へ貼る
- ChatGPT側で確立済みの根本原因を再導出する
- 通常EXE build / 通常配布更新をCodexへ戻す

## 9. automated regression CI カバレッジ

agentは原則この表を正とし、毎回 `.github/workflows` を総当たりして推定しない。workflowを変更した場合、または実物と矛盾を発見した場合だけ表を更新する。

ここで「あり」は、そのbranchで**決定的に自動実行できる回帰テスト一式**をpush / PR時にCIが実行することを意味する。実プリンター、実共有サーバー、live IMAP、外部サイト、実HDD等の実環境確認をCI済みとは扱わない。

| repo / branch | automated regression CI | workflow / scope |
|---|---|---|
| `next-day-setup / main` | あり | `.github/workflows/tests.yml` / pytest full |
| `beverage-inventory-ordering-system / python-desktop-migration` | あり | `.github/workflows/python-migration-tests.yml` / Python migration pytest |
| `beverage-inventory-ordering-system / main` | なし | `standards.yml` のみ |
| `food-cost-calculation-system / main` | あり | `.github/workflows/tests.yml` / pytest full + release dry-run tests |
| `inventory-reconciliation-system / main` | あり | `.github/workflows/tests.yml` / deterministic unittest + local shift-holiday regression。live IMAP / browser / external-site は必要時の実機確認 |
| `qr-supply-ordering-system / main` | あり | `.github/workflows/tests.yml` / pytest full |
| `menu-sheet-generator / main` | あり | `.github/workflows/tests.yml` / PMS CSV aggregation + GDI pre-spool .NET harnesses |

「なし」のbranchでは§4のCI未整備分岐を使う。現状の主な未整備branchは `beverage-inventory-ordering-system / main`。移行作業の `python-desktop-migration` はCIでカバー済み。

## 10. 完了報告

長いログではなく、次だけを簡潔に報告する。

- 変更ティア / 変更内容
- targeted / regression結果
- CI結果またはCIで確認予定の範囲
- 実機未確認
- branch / commit SHA
- 本番反映の有無

目的は品質を落とすことではない。**事故防止に効く確認を残し、安心感だけの重複確認を削る。**
