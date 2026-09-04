# AI Checklist

新しいチャットを開始するときは、次を順番に確認します。

- [ ] [AI_STARTUP.md](AI_STARTUP.md)
- [ ] [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md)
- [ ] [PROMPT_PRINCIPLES.md](PROMPT_PRINCIPLES.md)
- [ ] [AI_MEMORY.md](AI_MEMORY.md)
- [ ] [PROJECT_STATUS.md](PROJECT_STATUS.md)
- [ ] [VERSION_MATRIX.md](VERSION_MATRIX.md)
- [ ] [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)
- [ ] [docs/decisions.md](docs/decisions.md)
- [ ] [LESSONS_LEARNED.md](LESSONS_LEARNED.md)
- [ ] GitHub上でChatGPTが直接進められる作業か
- [ ] Windows実機でしか確認できずCodexが必要な作業か
- [ ] Python/Windowsアプリならソース起動経路があるか
- [ ] EXE配布するアプリなら手動ワンクリックビルドがあるか
- [ ] 配布対象なら `UPDATE_SHARED_FOLDER.cmd` / `update_shared_folder.ps1` があるか
- [ ] Codexへ通常のEXEビルドを依頼しようとしていないか
- [ ] `development-management` へ残す内容があるか

対象プロジェクトがある場合は、対象の `projects/*.md`、README、Git状態、関連する管理文書も確認します。

- [ ] 確認できたことを最初に明示したか
- [ ] ユーザーがフェーズを限定している場合、その境界内に収まっているか（限定がなければ依頼範囲内で調査→設計→実装→検証を連続してよい）
- [ ] 仮説を事実・原因・設計・Codex向け指示へ昇格させていないか
- [ ] AI 側で安全に実行できる作業を、理由なくユーザーへ戻していないか
