# 変更履歴

新しい記録を上に追加します。「確認状況」は、未確認／開発環境確認済み／実運用確認済みを明記します。

## v1.1.2 - 2026-09-01

### Changed

- `beverage-inventory-ordering-system` のPython移行で、旧PySide6タブUIが現行ブラウザUIと大きく異なることをWindows実機で確認。
- Python/PySide6移行自体は継続し、現行 `index.html` / `styles.css` / `app.js` の最終UIをUI仕様正本として全面再構築する方針を正式化。
- WebView等へ逃がさず、PySide6ネイティブUIとして現行の色、余白、寸法、配置、情報密度、操作順を再現する。
- 共有サーバー試験はUI一致確認まで停止する。
- ユーザー手動EXEビルドは成功済みだが、EXE起動成功とUI同等性確認を別ゲートとして管理する。

### Result

データ・業務計算互換性は66/66商品一致のまま維持し、UI品質を独立した本番切替条件として追加した。

確認状況: GitHub上でPySide6 UI全面再構築を実装中。Windows実機で現行ブラウザ版との見比べ・微調整は未完了。

## v1.1.1 - 2026-09-01

### Changed

- Python/Windowsアプリの開発標準を「ソース起動・手動EXEビルド・手動配布更新」の3経路へ統一。
- 日常の開発・確認では `.venv` のPythonソース版を起動し、EXE化を毎回の工程から外した。
- EXE配布するアプリには `BUILD_EXE_CLICK_ME.cmd` または同等のワンクリックビルドを必須化。
- 配布対象アプリには `update_shared_folder.ps1` と `UPDATE_SHARED_FOLDER.cmd` を原則必須化。
- 通常のEXEビルドをCodex担当から外し、手動ビルド失敗やEXE固有不具合の原因調査時だけCodexを使用する方針へ変更。
- `AGENTS.md`、`AI_OPERATING_MANUAL.md`、`AI_CHECKLIST.md`、`AI_STARTUP.md`、`DEVELOPMENT_RULES.md`、`PROJECT_BOOTSTRAP.md`、`REUSE_MAP.md`、`docs/decisions.md`、`PROJECT_STATUS.md`、飲料在庫プロジェクト文書を更新。

### Result

定型的なEXEビルド・配布更新でCodexクレジットを消費せず、ユーザーが必要なときだけワンクリックで実行できる構成を全Windowsアプリの標準とした。CodexはWindows実機でしか確認できない問題の調査へ優先配分する。

確認状況: GitHub管理文書更新済み。各既存アプリへの標準スクリプト実装状況はプロジェクトごとに別途確認する。

## v1.1.0 - 2026-09-01

### Changed

- ChatGPT / Codexの役割分担を更新。
- GitHubへ直接アクセスできるChatGPTは、調査・設計だけでなくGitHub上の実装、テスト追加、branch、commit、push、PR、レビューまで第一担当とする。
- CodexはWindows実機、正式ローカル、EXEビルド、実プリンター、共有サーバー、複数PC試験など、ChatGPTから直接扱えない作業へ優先して使用する。
- GitHub上のテスト成功とWindows実機確認を別の確認レベルとして扱う。
- Codexへの引き継ぎ時は、対象branch/commit、実装済み範囲、テスト結果、残作業、本番反映可否を明記する。
- `AI_OPERATING_MANUAL.md`、`AGENTS.md`、`DEVELOPMENT_RULES.md`、`AI_STARTUP.md`、`docs/decisions.md`、`PROJECT_STATUS.md` を新運用へ更新。
- `projects/beverage-inventory-ordering-system.md` をPython移行の現在地へ更新。

### Result

GitHub上だけで完結する作業をChatGPTとCodexで重複せず、CodexクレジットをWindows実機・ローカル依存作業へ優先配分する運用を正式化。

### First application

- `beverage-inventory-ordering-system` で `python-desktop-migration` / Draft PR #2をChatGPT側で実装。
- 現行実運用JSONによる互換確認とローカルpytest 11件成功までChatGPT側で実施。
- Windows実機、EXEビルド、実プリンター、共有サーバー複数PC試験はCodex側の後工程として分離。

確認状況: v1.1.1でEXEビルド担当を再整理。通常のEXEビルドはCodex担当から除外した。

## v1.0.0 - 2026-07-20

Initial stable release.

### Added

- `AI_OPERATING_MANUAL.md`
- `AI_CHECKLIST.md`
- `PROMPT_PRINCIPLES.md`
- `PROJECT_BOOTSTRAP.md`
- `AGENTS.md`
- AI引き継ぎとAI共同開発フロー
- `AI_STARTUP.md` の開始手順
- ChatGPTとCodexの役割分担
- `development-management` の位置付け
- 新規プロジェクト立ち上げ手順

### Result

`development-management` を「AI共同開発基盤」v1.0.0として正式化。

| 日付 | 変更対象プロジェクト | 変更内容 | 確認状況 |
|---|---|---|---|
| 2026-09-01 | beverage-inventory-ordering-system | 旧PySide6タブUIのUI差異を実機で確認し、現行ブラウザUIを正本としたPySide6全面再構築へ移行。データ互換は維持し、UI同等性を独立本番ゲート化 | GitHub実装中。Windows実機見比べ未完了。共有サーバー試験停止 |
| 2026-09-01 | development-management | Python/Windowsアプリをソース起動・手動EXEビルド・手動配布更新の3経路へ統一 | 管理文書をGitHub `main`で更新 |
| 2026-09-01 | development-management | ChatGPTをGitHub側の第一実装担当、CodexをWindows実機・ローカル環境作業の第一担当とする分業へ変更 | 管理文書をGitHub `main`で更新 |
| 2026-09-01 | beverage-inventory-ordering-system | 現行ブラウザ版を仕様正本としてPython/PySide6移行を開始。`python-desktop-migration` / Draft PR #2に候補版を隔離 | 最新実運用JSONで66/66商品一致。Windows実機、EXE、共有版は別ゲート |
| 2026-07-23 | menu-sheet-generator | `v1.0.0`初回正式リリース | タグ・Release公開、実機動作確認済み |
| 2026-07-21 | menu-sheet-generator | GitHub管理開始と正式ソース確定 | ビルド・全自動テスト・実プリンター確認完了 |
| 2026-07-21 | call-reception-assistant | 正式GitHubリポジトリ・管理文書作成 | プロジェクト化完了、アプリ未実装 |
| 2026-07-20 | beverage-inventory-ordering-system | 飲料発注システムを正式プロジェクト `apps/ordering/` へ移管 | JavaScript構文・静的ファイル確認 |
| 2026-07-20 | next-day-setup | ケーキ発注書の緊急用手動印刷を追加 | 自動テスト38件成功、実機未確認 |
