# Orchestrator入力契約（AIが起動用の依頼を書くための正本）

GPT・Claude・Codexが「AI Orchestratorで実行する依頼」を書くときは、この文書だけを見れば足りるようにします。Orchestratorのソースコードを読みに行く必要はありません。エンジン内部の動作（ループ・上限・安全ハーネス）は [Orchestrator仕様](ai_orchestrator.md)、運用全体は [OPERATING_CONTRACT.md](../OPERATING_CONTRACT.md) が正本です。

ここに書いた規則は `tools/ai_orchestrator/taskspec.py`・`tools/ai_orchestrator/review.py`・`tools/ai_orchestrator/orchestrator.py` の実装に合わせてあり、完成例は `tests/test_orchestrator_input_contract.py` で実際の解析関数に通して検証しています。実装を変えたらこの文書とテストも合わせて直してください。

## 1. 何を渡すのか（DCCのOrchestrator画面の入力欄）

Orchestratorへの入力は「1つの指示文」ではなく、DCCのOrchestrator画面の次の欄です。

| 欄 | 必須 | 中身 |
|---|---|---|
| 対象repo | 必須 | プルダウンでrepo名を選ぶ。「自動」を選ぶと、Task本文の「対象リポジトリ:」行から決まる |
| Task | 必須 | 依頼本文（このあと2章の書式） |
| Tests | repoによる | 独立テストのコマンド**1本**。repoに既定値があれば空欄でよい（下表） |
| 仕様ファイル | 任意 | 受入条件をJSONで固定したいときだけ（4章） |
| Main AI / Reviewer AI | 既定のまま | 既定は Main=Claude、Reviewer=Codex。同じAIは選べない |

AIが依頼を作るときは、ユーザーがそのまま貼れるように **「対象repo」「Task」「Tests」の3つを分けて** 出力します。

### 選べるrepo名と既定のTests

| repo名（そのまま書く） | 既定のTests（空欄ならこれが使われる） |
|---|---|
| development-management | `python -m unittest discover -s tests -v` |
| next-day-setup | `python -m pytest -q` |
| photo-capture-relay | `python -m pytest -q` |
| shizen-launcher | `python -m unittest discover -s tests -v` |
| beverage-inventory-ordering-system | なし（Tests欄に必ず書く） |
| call-reception-assistant | なし（Tests欄に必ず書く） |
| food-cost-calculation-system | なし（Tests欄に必ず書く） |
| inventory-reconciliation-system | なし（Tests欄に必ず書く） |
| menu-sheet-generator | なし（Tests欄に必ず書く） |
| qr-supply-ordering-system | なし（Tests欄に必ず書く） |

正は `scripts/repo_types.toml` と `scripts/dev_control_center_repos.toml`（`[branches]` / `[initial_tests]`）です。`archived`・`knowledge` 種別のrepo（kitchen-calendar など）は選べません。

## 2. Task本文の書式（必須規則）

**R1. 先頭行に対象リポジトリを書く。**
`対象リポジトリ: <repo名>` を先頭10行以内に1行で書きます（全角コロン可、名前の後ろの括弧注記は無視されます）。名前は1章の表と完全一致（大文字小文字は区別しない）。プルダウンで選んだrepoと食い違うと開始前に `TASK_REPO_MISMATCH` で止まり、「自動」選択でこの行が無いと `TASK_REPO_UNRESOLVED` で止まります。

**R2. 「受入条件」という語は、受入条件の見出しで1回だけ使う。**
Orchestratorは本文の中で「受入条件」「受け入れ条件」「acceptance」を含む**最初の行**から受入条件を読み取ります。それより前の文中に「受入条件を満たすように」などと書くと、そこから誤って読み取られます。

**R3. 受入条件は見出し直後の箇条書きにする。**
`- ` で始まる1項目1行。1件につき1つの確認できる事実を書きます（「〜できること」「〜と表示されること」「〜のテストが追加されていること」）。20件まで。21件目以降は捨てられます。ここに書いた項目がそのまま `C1, C2…` として**実装前に固定**され、Reviewerは原則これ以外の理由で差し戻せません。逆に言えば、書き漏らした要件は後から足せません。

**R4. 受入条件の後ろは見出しで区切る。**
受入条件の次の節は `## ` で始まる見出しにします（`## 範囲外` `## 制約` `## 補足` など）。区切りが無いと最大40行先まで受入条件に含まれます。

**R5. commit・push・BUILD・UPDATEを指示しない。**
Main AIは隔離されたworktreeで作業し、commit / push は禁止されています（Orchestratorが自分でcandidateを作ります）。「GitHubに反映して」「pushまで」「EXEをビルドして配布」などを書くと、守れない指示として混乱の元になります。push以降はDCCで人間が行います。

**R6. アプリの目的は書かなくてよい。**
`projects/<repo名>.md` の「目的」節が自動でMain・Reviewerへ渡ります。Taskには今回の変更だけを書きます。

**R7. Testsは実在して今すぐ通るコマンド1本。**
Tests欄は1行1コマンドです。複数のテストを走らせたいときはテストランナー側でまとめます（例: `python -m pytest -q`）。Orchestratorはこのコマンドが通ること（Tests PASS）を完成条件にするので、存在しないテストファイルや、変更前から落ちているテストを指定すると完成しません。新しいテストは受入条件で「〜のテストを追加すること」と求めます。

## 3. テンプレート

AIはこの形をそのまま埋めて出力します。

````text
【対象repo】<repo名>
【Tests】<コマンド、または「空欄（既定値を使う）」>
【Task】↓ここから下を全部Task欄へ貼る

対象リポジトリ: <repo名>

## 変更内容
<何を・なぜ変えるか。現状の問題と、変更後のふるまい>

## 受入条件
- <確認できる事実1>
- <確認できる事実2>
- <追加・更新するテスト>

## 範囲外
- <今回やらないこと>

## 補足
- <関連ファイル、注意点など。無ければ節ごと省く>
````

## 4. 仕様ファイル（TaskSpec JSON・任意）

受入条件を文章からの読み取りに頼らず確実に固定したいとき（長い条件、箇条書きが崩れやすいコピー元など）だけ使います。UTF-8のJSONファイルとして保存し、画面の「仕様ファイル」で選びます。**Task欄は仕様ファイルを使うときも必須**です。

```json
{
  "schema_version": 1,
  "target_repo": "next-day-setup",
  "criteria": [
    {"id": "C1", "text": "部屋番号が4桁の予約でも、印刷プレビューで全桁が切れずに表示されること"},
    {"id": "C2", "text": "4桁の部屋番号で列幅を確認する自動テストが追加されていること"}
  ]
}
```

- `criteria` は1〜20件。`text` は空不可・1件1000文字まで。`id` は省略可（省いた項目は C1, C2… と自動採番）。ただし重複不可で、明示したidと自動採番が重なっても拒否されるため、**付けるなら全件に付ける**のが安全。
- `schema_version` は書くなら `1`。`target_repo` は任意だが、書くなら選んだrepo・Task本文の「対象リポジトリ:」行と一致させる。
- 1か所でも違反があればファイル全体が拒否されます（`SPEC_INVALID`）。部分的には使われません。
- 仕様ファイルを使うと、Task本文の「## 受入条件」節は読み取りに使われません（Main / Reviewerには本文として渡ります）。

## 5. 開始前の確認と、止まったときの対処

「開始」を押すと確認画面が出ます。**「完了条件の一覧」が `C1: …` `C2: …` と項目ごとに分かれていること**を必ず確認してください。「依頼文からは抽出されませんでした」と出たら、R2〜R4のどれかが崩れています（そのまま開始するとReviewer AIが条件を作り、クレジットを1回分使います）。

| 表示・コード | 原因 | 対処 |
|---|---|---|
| `TASK_REPO_MISMATCH` | プルダウンとTaskの「対象リポジトリ:」行（または仕様ファイル）が違う | どちらかを直す |
| `TASK_REPO_UNRESOLVED` | 「自動」なのに対象リポジトリ行が無い／名前が登録に無い | R1の通りに書く |
| 独立Testsコマンドが未設定 | 既定Testsの無いrepoでTests欄が空 | Tests欄に書く |
| `SPEC_INVALID` | 仕様ファイルの形式違反 | 4章の規則を確認 |
| `SOURCE_DIRTY` / 未コミットの変更 | 正式repoにcommitしていない変更がある | 変更をcommitするか片付けてから開始 |
| local / origin が分岐・先行 | 正式repoのmainがGitHubとずれている | pushまたは同期してから開始 |
| `API_BILLING_ENV` | API課金用の環境変数がある | その環境変数を外す |

DCCは開始時、正式repoがcleanなら自動でmainへ切り替えて最新化します（`prepare_source`）。作業途中の変更があるときだけ止まります。

## 6. 完成例（このまま通ることをテストで確認済み）

```text
対象リポジトリ: next-day-setup

## 変更内容
翌日準備の印刷プレビューで、部屋番号が4桁のときに右端が切れて読めない。
部屋番号の列幅を内容に合わせて広げ、4桁でも全桁が表示されるようにする。

## 受入条件
- 部屋番号が4桁の予約でも、印刷プレビューで全桁が切れずに表示されること
- 3桁以下の部屋番号の表示位置と列幅が、変更前と変わらないこと
- 4桁の部屋番号で列幅を確認する自動テストが追加されていること
- 既存のテストがすべてPASSすること

## 範囲外
- 印刷レイアウト全体のデザイン変更
- 部屋番号以外の列の幅

## 補足
- 予約データや設定ファイルの中身は変更しない
```
