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

<!-- 旧cloneから救出（フェーズ規律） -->
- [ ] 確認できたことを最初に明示したか
- [ ] 現在のフェーズを宣言したか
- [ ] 今作ろうとしている成果物は現在のフェーズで許可されているか
- [ ] ユーザーが依頼していない次フェーズへ進もうとしていないか
- [ ] 仮説を事実、原因、設計、Codex向け指示へ昇格させていないか
