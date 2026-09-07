# Agent Efficiency Policy

AI / coding agent の品質・安全性を維持しながら、不要な再調査・再推論・テスト反復・Codexクレジット消費を抑える正式ルール。

## 優先順位

この文書は **開始時の読み込み、調査範囲、REUSE_MAP、テスト範囲、反復上限、Codex引き継ぎ、CI代替条件** の上限を定める。`AI_STARTUP.md`、`AI_OPERATING_MANUAL.md`、`DEVELOPMENT_RULES.md` 等の広い表現より、このティア別上限を優先する。

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
- **共有utilityや数値・日付・状態変換の変更が、2 call/import hops以内で金額・売上・価格・在庫・数量・帳票・印刷・DB・業務日付へ流れる場合は最低T2** とする。
- T1判定に迷いがあり、1ホップ先だけでは業務影響を否定できない場合は、判定のためだけに必要な2ホップ目を確認してよい。そこで業務影響が見えたらT2へ上げる。
- T1/T2で迷った場合は上位ティアを選ぶ。余分なCI確認より、業務影響をT1へ落とす方を避ける。

作業中に上位ティアだと判明したらティアとblast-radiusを更新する。T2以上へ上がり、依頼の安全条件・運用を実質変更する場合は既存のスコープ変更ルールを適用する。

## 2. 開始時の読み込み予算

### 全ティア共通

- 対象 repo / branch / HEAD SHA / dirty tree
- この文書
- 対象 README または `projects/*.md` の今回に必要な箇所
- 引き継ぎの `【確立した事実】` があればそれ

### T0 / T1

- **`AI_STARTUP.md` を開かない。** この文書のルールだけで開始判断を完結させる。
- touched file + 直接の呼び出し元1ホップを通常上限とする。§1のティア判定に必要な場合だけ2ホップ目を確認する。
- `PROJECT_STATUS`、`VERSION_MATRIX`、`SYSTEM_OVERVIEW`、`docs/decisions`、`LESSONS_LEARNED` 等は今回に直接必要なときだけ読む。
- 「文脈把握のため」の repo 全体 grep/read をしない。

### T2

固定で長文書を全読みしない。原則として次だけ読む。

- `AI_OPERATING_MANUAL.md`: **`スコープ変更時の確認`、`Git運用`、`フェーズ規律（調査／設計／実装／検証）`**。実機・Codex分業が今回に必要な場合だけ `Codexへ引き継ぐ条件`。
- `DEVELOPMENT_RULES.md`: **`開発環境と検証`、`Git管理と情報保護`** と、変更対象に一致する1つのdomain節（`EXEビルド標準` / `配布先更新の標準` / `俺伝の正式リリース標準` 等）。`既存資産の横断利用` は§3が発火した場合だけ読む。
- 変更する契約・形式の producer / consumer、読み書き両側。
- 金額・在庫・印刷・DB・共有フォルダ等では、今回に該当する安全ルール/設計判断だけ追加する。

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

- §9の表で現在branchを automated regression CI がカバーしている場合、Codexはローカルで同じ automated full regression を回さない。push / PR後のCIを回帰ゲートとする。
- **T2/T3でCIをローカルfullの代替に使った場合、対象candidate SHAのCI greenを実際に確認するまで作業完了として報告しない。** `CI確認予定` は途中状態でありterminal completionではない。
- T2/T3は原則branch / PR上のcandidateでCIを通す。ユーザーがdirect-mainを明示した場合や既存運用がdirect-mainの場合でも、push後の同一SHA green確認は省略しない。
- 実プリンター、実共有サーバー、live IMAP、外部サイト、実HDD、実OCR、実LAN等はCIとは別の確認レベル。今回のblast-radiusが触れる場合だけ Windows実機で確認し、CI成功を実機確認済みとは扱わない。
- **今回のblast-radiusがCIでskipされるtest、または§9の未カバー領域に触れる場合、その領域のtargeted local / real checkはCI-covered branchでも省略しない。**
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

- `【確立した事実】` が現在HEADでも有効なら理由なく再導出しない。ただし**修正前のtargeted再現が、引き継ぎに記載された原因・挙動を支持しない場合、その事実だけをsuspectとして必要範囲を再調査する。** この再調査は§5の同一仮説反復には数えない。
- baseline SHA と現在HEADが異なる場合、`git diff <baseline>..HEAD` の変更が今回のtouched files + 直接依存/消費者、またはblast-radiusに**触れなければ baseline は有効**。
- 触れている場合は影響moduleだけ targeted で再確認し、baseline鮮度のためだけにfullを回さない。
- **baselineが有効でも、自分が今回変更した箇所の§4 targeted testは必ず実行する。** baselineは他領域の再検証を省略する根拠であり、自分の変更を未テストにする根拠ではない。
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
- ChatGPT側で確立済みの根本原因を理由なく再導出する
- 通常EXE build / 通常配布更新をCodexへ戻す
- CI代替を使ったT2/T3を、candidate SHAのCI結果未確認のまま完了扱いする

## 9. automated regression CI カバレッジ

agentは原則この表を正とし、毎回 `.github/workflows` を総当たりして推定しない。workflowを変更した場合、または実物と矛盾を発見した場合だけ表を更新する。

ここで「あり」は、そのbranchで**決定的に自動実行できる回帰テスト一式**をpush / PR時にCIが実行することを意味する。実環境確認や、表の未カバー領域をCI済みとは扱わない。

| repo / branch | automated regression CI | 検出方式 | workflow / scope | CI未カバー・追加確認 |
|---|---|---|---|---|
| `next-day-setup / main` | あり | pytest自動収集 | `.github/workflows/tests.yml` / deterministic pytest set | CIでskipされるGUI/Tk領域、実印刷、共有先は変更時にlocal/real確認 |
| `beverage-inventory-ordering-system / python-desktop-migration` | あり | pytest自動収集 | `.github/workflows/python-migration-tests.yml` / Python migration pytest | 実プリンター、共有サーバー、2PC等は別ゲート |
| `beverage-inventory-ordering-system / main` | なし | — | `standards.yml` のみ | §4のCI未整備分岐 |
| `food-cost-calculation-system / main` | あり | pytest自動収集 | `.github/workflows/tests.yml` / Windows PowerShell 5.1 formal validation dry-run内で pytest + compileall + diff check + release script safety | **real Nuitka standalone/MSVC build、実Tesseract OCR、実HDD/利用PCは未カバー**。`tools/release/**`・build flags・dependency/build変更は正式手動build + launch確認がrelease前に必要 |
| `inventory-reconciliation-system / main` | あり | **列挙 + drift guard** | `.github/workflows/tests.yml` / deterministic unittest 3 modules + local shift-holiday regression | live IMAP / Outlook/Thunderbird / browser / external-site / scheduled-task orchestration / warning mail送信は必要時の実機確認。新しいdeterministic test fileを追加してdrift guardが赤になったら同一変更でworkflow列挙へ追加する |
| `qr-supply-ordering-system / main` | あり | pytest自動収集 | `.github/workflows/tests.yml` / repository deterministic pytest set | 実LAN、camera/QR scan、Windows firewall、populated production DB migration、multi-host運用は別確認。DB migration/schema変更はtargeted migration dry-runを追加する |
| `menu-sheet-generator / main` | あり | **列挙 + drift guard** | `.github/workflows/tests.yml` / main app Release build + PMS CSV aggregation + GDI pre-spool harnesses | GDI pre-spoolはlayout/renderingまで。spooler/driver/紙/物理出力は未カバー。`GdiDirectPrintService.Print`、printer interaction、paper handling変更はrelease前に実プリンター確認が必要 |

列挙型CIでは、drift guardが「新しいdeterministic test / harnessをworkflowへ追加し忘れた」状態をgreenにしないことを必須とする。guardがない列挙CIは automated regression CI「あり」と扱わない。

「なし」のbranchでは§4のCI未整備分岐を使う。現状の主な未整備branchは `beverage-inventory-ordering-system / main`。移行作業の `python-desktop-migration` はCIでカバー済み。

## 10. 完了報告

長いログではなく、次だけを簡潔に報告する。

- 変更ティア / 変更内容
- targeted / regression結果
- **T2/T3でCI代替を使った場合: candidate SHA + CI green確認済み結果**
- 実機未確認 / CI未カバー領域
- branch / commit SHA
- 本番反映の有無

`CI確認予定`、`CI実行中` は途中報告には使えるが、CI代替を使ったT2/T3のterminal completionには使わない。

目的は品質を落とすことではない。**事故防止に効く確認を残し、安心感だけの重複確認を削る。**
