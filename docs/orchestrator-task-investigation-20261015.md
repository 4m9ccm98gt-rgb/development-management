# Orchestrator Task欠落・Main timeout調査（2026-10-15）

## 結論

Mainの1回の呼び出しの既定値だけを1800秒から3600秒へ変更する。Reviewer 1200秒、Tests 1800秒、Run全体360分、権限とその他の運用ルールは変更しない。実装・修正・resumeは共通の `agent_timeout` を使う。既存Runは保存済みlimitsを使うので、変更は新しく開始するRunに適用される。

本文欠落は **Run作成時の保存本文に既に存在する**。今回の証拠だけでは、DCCに渡した元の文字列、クリップボード、入力操作、入力欄のどの境界かを確定できない。再現できない上限を想定した入力処理の変更は行わない。

## 読み取り調査の証拠

対象は `%LOCALAPPDATA%/ShizenDev/AIOrchestrator/runs/` の次の2件。既存Runには書き込んでいない。両Runのbaseは `3a1866703509d62faa7d0e87e23cba0265440006`（調査開始時の正式repo HEADと同じ）。依頼文の原本コピーは `C:/Users/suisy/Documents/Development/verification/` に見つからず、同フォルダにあったのは前日のテストtimeout検証ログだけ。

| Run | task文字数 | UTF-8 bytes | 改行区切り行数 | 受入条件の開始行 | 固定件数と由来 | 保存された末尾 |
|---|---:|---:|---:|---:|---|---|
| 20261015-133718-512378 | 3086 | 7494 | 54 | 42 | 11、criteria_source=task | C11相当の文の次の行が単独の `-` |
| 20261014-131217-704479 | 2490 | 5966 | 48 | 44 | 4、criteria_source=spec | 4件目の「確認す」で終端 |

文字数はPythonの `len(run.jsonのtask)`。UTF-8 bytesは同文字列をencodeした長さで、ファイルのCRLFやJSONエスケープの長さではない。両Runとも `task.md`（末尾改行を除き改行を正規化）と `run.json.task` は一致し、「範囲外」「制約」の後続セクションは存在しない。前回の `spec.json` も4件で、4件目は同じ未完の文章。今回の受入条件ブロックは13行、前回は5行である。

`run_report()` のtask欄も、CRLFを正規化すると保存本文を全文含む。報告作成による末尾の切り捨てではない。今回の単独 `-` は内容のある箇条書きに該当しないため、`criteria_from_acceptance()` が11件を返す。前回の明示specは抽出を通さず4件を使用する。taskから抽出しても4件になる。従って、件数の相違は保存時点までに欠けた本文・specと整合する。

両Runの `final_result` は `needs_human / PROVIDER_ERROR`、`main_calls=1`、`tests_run_count=0`、`review_calls=0`。今回のログは14:07:25に `command timed out after 1800s: cmd.exe` を記録する。Testsの1800秒とは別の、Main呼び出しのtimeoutである。

## 経路の確認

- `scripts/dev_control_center/orchestrator_view.py`: 入力は `tk.Text(height=6)`。heightは表示行数。入力長のvalidateや独自paste制限はない。`start_run()` が `get("1.0", "end").strip()` で取得し、`_pending_start["task"]`、`_confirm_start()` の `StartRequest.task` へそのまま渡す。draft保存も全文で、stripは前後の空白だけ。
- `tools/ai_orchestrator/orchestrator.py`: `prepare_run()` はstrip後の本文を `new_record()` と `task.md.write_text()` にそのまま渡す。保存時に文字数やバイト数で切らない。CLIには `--task-file` もある。
- `spawn_worker()` の引数はPython/module/worker/`--run-dir`/パス。Task本文はコマンドラインに載らない。workerはrun.jsonを読み、`Engine.task` が本文を保持する。Main/Reviewer用テンプレートにはこの本文を渡す。
- `providers.py` と `common.py`: providerのpromptは `run_streaming(input_text=prompt)` からUTF-8のstdinへ書く。Task本文をcmd.exeの引数に展開する経路ではない。commitメッセージの72文字制限、branch用slugの制限は本文保存やpromptには影響しない。
- `review.py`: 受入条件抽出には次見出しまたは後続40行、固定件数には20件の既存上限がある。ただし対象Runの13行/5行、11件/4件には到達しない。これらは本文全体の保存や「範囲外」「制約」を削らないため、本件の原因ではない。今回これらの抽出ルールは変更しない。
- `runstate.py`: 報告のtask表示は末尾50000文字で、上限超過は先頭省略を明示する。今回の文字数はそれ以下であり、観測された末尾欠落とは方向も異なる。

**切れ位置の規則:** 保存本文で観測できるのは、今回は受入条件12件目の箇条書き記号直後、前回は4件目の文中で終わることだけ。共通の文字数・UTF-8バイト数・行数の閾値は確認できない。元依頼全体の文字数や入力前後の値の記録がないので、外部入力手段に別の上限があった可能性は否定できない。DCCへ入力した文字列自体が既に短かった、または入力操作で末尾が渡らなかった仮説は、保存経路に切り詰めがなく長文も通ることと整合するが、確定原因としては扱わない。

## 最小の確認手順（有料AI呼び出し不要）

1. 日本語で長い前文、16件の受入条件、`## 範囲外`、`## 制約`、最後に一意な `END-OF-TASK-16` を含むUTF-8の原本ファイルを用意する。原本の文字数とUTF-8 bytesを記録する。
2. 問題が起きたときと同じ方法でDCCのTask入力欄へ渡す。**開始ボタンを押す前に** Task欄を全選択・コピーし別ファイルへ保存し、原本と改行正規化後に比較する。末尾マーカーの有無も確認する。これでコピー元から入力欄までの欠落を切り分ける。
3. 開始確認画面で16件目まであることを確認し、開始はキャンセルする。欄には全文があるのに条件が減った場合は、各条件が40行の抽出窓内にあるか、途中の見出し判定、20件上限、spec読み込みの有無を確認する。
4. 自動検証では `test_long_japanese_task_reaches_start_request_in_full` を実行する。実際のTk欄に3万文字超の日本語（絵文字を含む）を挿入し、確認画面とStartRequestまで検証する。起動先をfakeにするため実Run・provider・source変更は発生しない。これは当時のクリップボード内容や外部入力操作の再現ではない。
5. `test_long_japanese_task_is_saved_and_reported_in_full` は一時Git repoとstateで同じ長文のprepare_run、run.json再読込、task.md、報告全文、16条件を比較する。実Runの新規開始は必要ない。元の入力手段だけで再現する場合は、その手段へ渡す文字列と入力欄から回収した文字列を、サイズを変えて比較して閾値を絞る。

## 修正と検証

本体変更は `Limits.agent_timeout=3600` のみ。仕様表を追随し、両providerのMain実装・修正呼び出しへ3600秒が渡ること、Reviewer=1200、Tests=1800、全体=360分を維持するテストを追加した。長文経路のテストは本文欠落の切り分けと再発検知のため追加した。起動前に元入力の欠落を判定するには原本や文字数・hash等の別の基準が必要であり、単独の本文から黙った欠落を一般的に判定することはできない。必要になれば、全文ファイル入力と末尾確認のUIを別途設計できるが、今回その範囲のUI変更はしない。

実行コマンドはいずれも `python -m unittest discover -s tests -p <下記ファイル名> -q`（PYTHONUTF8=1）。

| 関連テスト | 結果 |
|---|---|
| test_ai_orchestrator_engine.py | 38件 PASS |
| test_ai_orchestrator_budget_criteria.py | 38件 PASS |
| test_dev_control_center_orchestrator_view.py | 66件 PASS（Tkを実際に実行、skipなし） |
| test_ai_orchestrator_host.py | 23件 PASS |

新規の報告比較テストは初回、WindowsのCRLFと入力のLFの差で失敗した。比較側だけ改行を正規化し、再実行でPASSした。本体の文字列や保存形式は変更しない。全体テストは実行せず、依頼に従い関連範囲に限定した。`git diff --check` も実行した。
