# development-management AI入口ガイド

このリポジトリは、設計判断、開発ルール、進行状況、AI共同開発知識を管理する司令塔である。

**最初に [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を確認し、①〜⑤の工程担当、③candidate同期の停止条件、④⑤のユーザー既定担当、Codex利用条件を確定する。これらの担当・工程ルールは他のDevelopment文書より優先する。**

そのうえで [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を読み、変更ティアと読み込み予算を決める。T0 / T1 では `AI_STARTUP.md` を開かず、T2 は今回に関係する運用文書だけ追加し、T3 で [AI_STARTUP.md](AI_STARTUP.md) のフル開始チェーンを適用する。詳細運用は [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md)、能力定義は [CAPABILITIES.md](CAPABILITIES.md) を参照する。

## 基本方針

- ChatGPTは、GitHubへ直接アクセスできる場合、設計・仕様整理・既存コード調査だけでなく、GitHub上の実装、テスト追加、ブランチ作成、commit、push、PR作成、レビューまでを第一担当とする。
- **通常フローでAIが担当するのは①設計と②開発まで。**
- **③candidate同期はユーザーが `SYNC_CLICK_ME.cmd` で実施する。** ChatGPTは②完了時にcandidate branch / candidate SHAを明示する。
- ③は `HEAD SHA == candidate SHA`、origin SHA一致、tracked cleanを確認した時点で停止する。アプリ起動、GUI、機能確認、実紙、追加テスト、build、deployへ進まない。
- ④実機確認はユーザーが `RUN_DEV.cmd` 等で実施する。CIで確認できないことだけを理由にCodexへ回さない。
- ⑤build / deploy / updateは、既存の `*_CLICK_ME.cmd` / `UPDATE_*.cmd` 等がある場合ユーザーがワンクリックで実行する。
- **Codex等の実機AIは、③④⑤でユーザーが再現した具体的な失敗症状があり、GitHub / CI / ユーザー報告だけでは切り分けられない⑥Windows障害調査だけに使う。**
- 無症状の「念のため実機確認」、通常同期、通常GUI確認、通常build、通常deployをCodexへ依頼しない。
- Python/Windowsアプリは、開発時は原則としてPythonソースから起動できる状態を維持する。EXEは常用の開発実行手段にしない。
- 配布対象のWindowsアプリには、安全なワンクリックbuild / update経路を原則用意する。
- ChatGPTだけで完結できるGitHub作業を、Codexクレジットを消費して重複実施しない。
- ユーザーへ長いPowerShellやGit操作を手打ちさせるのは最終手段とする。ただし、安全な `SYNC_CLICK_ME.cmd` / `RUN_DEV.cmd` / `*_CLICK_ME.cmd` / `UPDATE_*.cmd` のダブルクリックはユーザーの標準工程である。
- チャットを唯一の情報源にせず、重要な設計判断、仕様変更、運用変更、Lessons Learnedを `development-management` へ記録する。
- Gitは正式ソースを基準とし、既存変更を保護する。

## ChatGPT会話での継続適用

通常のChatGPTチャットでは、repo内 `AGENTS.md` やMemoryが毎ターン自動発火する前提を置かない。

ソフトウェア開発について「次に何をするか」「誰に渡すか」「Codexへ何を指示するか」を回答する直前に、最低限 [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) の工程担当を照合する。

> この次工程は①〜⑤のどこか。通常AI担当は①②まで。③はユーザーの `SYNC_CLICK_ME.cmd`、④⑤はユーザー。Codex指示なら具体症状付き⑥か。ユーザーが安全にワンクリックでできる作業を有料AIへ戻していないか。

同一チャットで過去にDevelopmentを確認済みでも、この担当チェックは省略しない。

## GitHubプロジェクト初期確認ルール

新規チャットで GitHub リポジトリをプロジェクトとして開いた場合は、機能追加・修正に着手する前に、ティアに応じた必要範囲だけ次の手順を適用する。

- `OPERATING_CONTRACT.md` で現在工程と担当を確認する。
- GitHub から取得した内容だけを使用する。
- 既存・旧運用のローカルフォルダは参照しない。
- 最初はコードを変更せず、必要範囲の現状確認を行う。
- 今回に必要なファイルが揃っていることを確認する。
- Python/Windowsアプリでは、今回に関係する場合だけ `SYNC_CLICK_ME.cmd` / ソース起動 / 手動EXEビルド / 配布更新経路を確認する。
- ChatGPTから直接触れないWindows確認は、まず④ユーザー確認として切り出す。具体的な失敗症状が出た場合だけ⑥Codex候補とする。
- 確認できた GitHub 上の状態を正本（Single Source of Truth）とする。
- 問題が見つかり、対応が依頼スコープや安全条件を大きく変える場合は、原因と対応案を報告する。

初期確認中は、依存関係の導入やアプリ起動に伴う通常の生成物を除き、リポジトリのコード・設定・文書を変更しない。生成物が発生した場合は、確認結果とともに報告する。
