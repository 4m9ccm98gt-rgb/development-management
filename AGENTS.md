# development-management AI入口ガイド

このリポジトリは、設計判断、開発ルール、進行状況、AI共同開発知識を管理する司令塔である。

**最初に [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) を確認し、①〜⑤の工程担当、③実機投入の停止条件、④⑤のユーザー既定担当、Codex利用条件を確定する。これらの担当・工程ルールは他のDevelopment文書より優先する。**

そのうえで [AGENT_EFFICIENCY_POLICY.md](AGENT_EFFICIENCY_POLICY.md) を読み、変更ティアと読み込み予算を決める。**T0 / T1 では `AI_STARTUP.md` を開かず、`AGENT_EFFICIENCY_POLICY.md` §2 だけで開始判断を完結させる。** T2 は今回に関係する運用文書だけ追加し、T3 で [AI_STARTUP.md](AI_STARTUP.md) のフル開始チェーンを適用する。詳細な運用基準は [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) を正本とするが、調査範囲・開始文書・REUSE_MAP・テスト範囲・反復上限・Codex引き継ぎについては `AGENT_EFFICIENCY_POLICY.md` の上限を優先する。

作業の担当は、能力だけでなく **安全性 / Codexクレジット / ユーザーが安全にワンクリックできるか** の3軸で判定する。能力定義と正式ローカルリポジトリの同期規約は [CAPABILITIES.md](CAPABILITIES.md) を正本とする。

## 基本方針

- ChatGPTは、GitHubへ直接アクセスできる場合、設計・仕様整理・既存コード調査だけでなく、GitHub上の実装、テスト追加、ブランチ作成、commit、push、PR作成、レビューまでを第一担当とする。
- **Codexは通常の実機確認担当ではない。** 原則、③candidate同期または、④/⑤でユーザーが再現した具体的なWindows実機トラブルの調査だけを担当する。
- **③実機投入をCodexへ渡した場合は、正式repoをcandidateへ同期し `HEAD SHA == candidate SHA` とbranch / dirty treeを確認した時点で停止する。アプリ起動、GUI、機能確認、実紙、追加テスト、build、deployへ進まない。**
- ④実機確認はユーザーが `RUN_DEV.cmd` 等で実施する。CIで確認できないことだけを理由にCodexへ回さない。
- ⑤build / deploy / updateは、既存の `*_CLICK_ME.cmd` / `UPDATE_*.cmd` 等がある場合ユーザーがワンクリックで実行する。
- Python/Windowsアプリは、開発時は原則としてPythonソースから起動できる状態を維持する。EXEは常用の開発実行手段にしない。
- EXEビルドはCodexへ通常依頼しない。必要な場合にユーザーが手動で実行できるワンクリックビルド手順を各アプリに用意する。
- 配布対象のWindowsアプリには、配布先更新用の `update_shared_folder.ps1` と、そのワンクリックラッパー `UPDATE_SHARED_FOLDER.cmd` を原則必須とする。
- ChatGPTだけで完結できるGitHub作業を、Codexクレジットを消費して重複実施しない。
- Codexへ引き継ぐ際は、`OPERATING_CONTRACT.md` §7 の形式を使い、`【工程】`、candidate SHA、green baseline、`【Codexで行う】`、`【Codexで行わない】`、停止条件を必ず明記する。
- **③同期タスクの `【Codexで行わない】` には、アプリ起動 / GUI操作 / 機能確認 / 実紙印刷 / 追加テスト / full regression / candidate再レビュー / 再調査 / 通常build / 通常deploy を固定で含める。**
- ユーザーへ長いPowerShellやGit操作を手打ちさせるのは最終手段とする。ただし、既存の安全な `RUN_DEV.cmd` / `*_CLICK_ME.cmd` / `UPDATE_*.cmd` のダブルクリックはユーザーの既定担当であり、最終手段ではない。
- チャットを唯一の情報源にせず、重要な設計判断、仕様変更、運用変更、Lessons Learnedを `development-management` へ記録する。
- Gitは正式ソースを基準とし、既存変更を保護する。commit、push、タグ作成はユーザーの明示的な指示がある場合にのみ行う。

## ChatGPT会話での継続適用

通常のChatGPTチャットでは、repo内 `AGENTS.md` やMemoryが毎ターン自動発火する前提を置かない。

ソフトウェア開発について「次に何をするか」「誰に渡すか」「Codexへ何を指示するか」を回答する直前に、最低限 [OPERATING_CONTRACT.md](OPERATING_CONTRACT.md) の工程担当を照合する。

> この次工程は①〜⑤のどこか。Codex指示なら③同期のみ、または具体症状付き⑥か。④/⑤をCodexへ渡していないか。ユーザーが安全にワンクリックでできる作業をCodexへ戻していないか。

同一チャットで過去にDevelopmentを確認済みでも、この担当チェックは省略しない。

## GitHubプロジェクト初期確認ルール

新規チャットで GitHub リポジトリをプロジェクトとして開いた場合は、機能追加・修正に着手する前に、ティアに応じた必要範囲だけ次の手順を適用する。

- `OPERATING_CONTRACT.md` で現在工程と担当を確認する。
- GitHub から取得した内容だけを使用する。
- 既存・旧運用のローカルフォルダは参照しない。
- 最初はコードを変更せず、必要範囲の現状確認を行う。
- 今回に必要なファイルが揃っていることを確認する。
- Python/Windowsアプリのソース起動・手動EXEビルド・配布更新経路は、今回の変更に関係する場合だけ確認する。
- ChatGPTから直接触れないWindows確認は、まず④ユーザー確認として切り出す。ユーザーが実施できない、または具体的な失敗症状が出た場合だけCodex候補とする。
- ブラウザアプリ等で実行環境を直接確認できる場合は、今回の変更に関係する起動・コンソールエラーを確認する。
- 確認できた GitHub 上の状態を正本（Single Source of Truth）とする。
- 問題が見つかり、対応が依頼スコープや安全条件を大きく変える場合は、原因と対応案を報告してユーザーの指示を待つ。

初期確認中は、依存関係の導入やアプリ起動に伴う通常の生成物を除き、リポジトリのコード・設定・文書を変更しない。生成物が発生した場合は、確認結果とともに報告する。