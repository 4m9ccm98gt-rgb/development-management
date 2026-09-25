# Development / DCC Phase 1 検証記録

記録日: 2026-09-25。対象は正式 development-management のみ。
基点HEAD: `0b8785ebab3948982b1c8a774e6703badc4d349b`。commit / push未実施。

## 変更

- 通常DevelopmentをGPT相談 → Claude / Codexの正式ローカルrepo直接実装 → Tests → DCC RUN → ユーザー確認 → BUILD → UPDATEへ変更。
- DCCメインをRUN / BUILD / UPDATE中心に配置。AI詳細は別Toplevelへ分離。通常画面とAI画面の選択・実行状態を分離し、同じrepoの競合だけを制御。
- RUN / BUILDからcandidate・tracked clean・GitHub取得成功への依存を撤去。UPDATEは明示確認とBUILD記録、成果物・配布先・更新スクリプトの検証を使用。
- BUILD workerがローカルへprovenanceを記録。入力変化・失敗・成果物欠落・成果物未更新をUPDATE不可とし、同じ出力先を排他。
- 新規repo登録はコピー可能なClaude / Codex向け指示を生成。AI依頼欄への強制投入を廃止。
- provider異常はAI画面の状態・ログに残し、モーダルエラーで通常画面をブロックしない。
- 正本と補助文書を整合。古い進行記録は旧運用と明示。

## 検証済み

- 変更前のDCC回帰テスト: 249件成功。
- 変更後の全テスト: `python -B -m unittest discover -s tests -q` — 322件成功（71.578秒）。
- 実Windowsの一時repo・実CMDで、空白を含むパスのdirty BUILDとprovenance生成を確認。
- 成果物／入力／更新スクリプト／配布先の確認後変更、失敗BUILD、古い成果物、出力先競合、UPDATE取消での非実行を確認。
- review_pending / provider異常後のロック解放、他repoのAI実行と通常操作の分離、子画面を閉じて再表示できることを検証。
- 正式ランチャーと同じ `scripts.dev_control_center.app_setup.App` の実Tk起動を確認。9件のmanaged repoを認識し、dirtyなdevelopment-managementを選択してRUNが有効になることを確認。
- 実画面1080×720でRUN / BUILD / UPDATE / Orchestrator入口の全矩形が画面内（主要ボタンの上端135px）。メインのAI詳細は非表示、別画面では表示。別画面を閉じてもメインは存続。
- registry self-check、変更PythonのAST構文検査、git diff --check成功。

## 未実施・残る制約

- 実アプリの重量級BUILD、実共有フォルダ／実HDDへのUPDATE、実provider E2Eは実施していない。UPDATEは一時環境とmockで検証し、本番配布していない。
- ユーザー指定により他repoを変更していない。飲料アプリのclean必須BUILD／UPDATE、翌日準備のdirty BUILD成果物拒否等、呼出先固有の条件は残る。DCC側でこれらをバイパスしない。
- UPDATE引数を確認した4repoのみadapter接続。その他（ソース配布型・BUILD入口なしを含む）は配布契約が確認されるまでDCC UPDATEを停止する。詳細は [DCC仕様](dev_control_center.md)。
- 入力監視はGit対象ファイルと追加指定したローカル設定が対象。外部依存関係や外部ツールによる配布中の変更まで完全に保証する仕組みではない。
- Phase 1では子画面は非表示にできるが、AI実行中のDCC本体終了は保留する。暗黙にAIを停止しない。独立run manager、DCC終了後継続・再接続、新Primary / Secondaryループ、自動Final Review、quota handoffはPhase 2であり未実装。

## 実機指摘への追加修正: 非対話・バックグラウンド実行

- development-management内だけを修正。各repoの手動CLICK_ME.cmdは変更せず、DCC専用adapterから処理本体を呼ぶ構造へ変更した。前掲の実CMDテストは初回Phase 1の記録であり、現在は非対話本体の実行テストへ更新した。
- 共通subprocess transportはCREATE_NO_WINDOW、stdin閉鎖、stdout / stderr逐次転送、終了コード回収を使用。事前検査・BUILD・UPDATEをUI thread外へ移した。同じrepoの操作を排他し、別repoの操作とUI応答を維持。明示停止を追加。
- 実Windowsの一時Git repoを実TkのDCCからBUILDし、途中ログ、日本語stderr、親・子processのコンソールhandleが0、rc=0 / rc=7、別repoの同時操作、Tk heartbeat、画面移動、明示停止を検証。手動CMDはpauseと非0終了を含むfixtureとして残し、未実行を検証した。
- 全テスト: `python -B -m unittest discover -s tests -q` — **330件成功（82.816秒）**。追加バックグラウンドテスト8件を含む。
- 正式app_setupランチャーのself-checkで9repoを確認。git diff --check成功。
- 本番の重量級BUILD / 配布は未実施。飲料側のclean必須等は維持。未登録の非対話入口や未対応UPDATE契約は停止し、手動CMDへフォールバックしない。詳細は [DCC仕様](dev_control_center.md)。commit / push未実施。

## commit前の実機確認記録

ユーザーからPhase 1の実機確認完了（RUN成功）の報告を受け、commitを依頼された。RUN成功はユーザーの実機確認に基づく。上記の「重量級BUILD未実施」は実装時点の記録。

飲料アプリの実BUILD記録を読み取り、次を確認した（BUILDの再実行・UPDATEはしていない）。

- build ID: `e19d8e553e1b423da383dd8276d26815`
- base HEAD: `255fec8753e77515c85d3b7f618a046d4bca0ef9`、clean
- 終了: `2026-09-25T03:57:52.304349+00:00`、rc=0、status=ready
- inputs_stable / artifact_refreshedともtrue。latest.jsonとbuild ID別記録が一致。
- 現在の成果物hash・入力hashを再計算し記録との一致を確認。
- 成果物SHA-256: `0c423990efbd4ec2ad4cacda6ac9f0203ab14d9c8b4846300439de3801eed3e4`
- 最新の全体テストログは330件成功（82.816秒）。対象repoとtracked / untrackedの全29ファイルがPhase 1関連であること、diff --check成功を確認。

ユーザー指定により今回の変更をまとめてcommitする。push / 本番配布は対象外。
