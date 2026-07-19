# 開発ルール

## 正式な知識ベース

- チャットだけに存在する決定事項を作らない。
- 運用・設計・ルール・重要な判断は `development-management` に必ず記録する。
- チャットの内容を唯一の情報源にしない。
- GitHub上の `development-management` を開発の正式な知識ベースとする。
- 判断の理由は `docs/decisions.md`、進行状況は `PROJECT_STATUS.md`、日々の作業は `DAILY_LOG.md` に反映する。

## ソースと作業場所

- 正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下のみとする。
- 旧フォルダは参照専用とし、新規開発、修正、ビルド、コミットに使用しない。
- 新しいチャットや別Codex環境では、最初に `development-management` を確認する。
- 作業開始時に対象リポジトリのブランチ、タグ、未コミット変更を確認する。

## 開発環境と検証

- 各プロジェクトはリポジトリ直下の `.venv` を使用する。
- 実装後は、構文確認、テスト、手動起動など変更に応じた動作確認をしてからコミットする。
- タグは安定版にのみ作成する。実運用未確認の変更へ安定版タグを付けない。
- コード変更時は、該当プロジェクトの README と `development-management/projects/*.md`、必要に応じて `PROJECT_STATUS.md` と `CHANGELOG.md` も更新する。
- 生成するPowerShellスクリプトは、利用環境に合わせWindows PowerShell 5.1互換の構文・文字コードとする。

## Git管理と情報保護

- 秘密情報、認証情報、実運用設定、顧客データ、業務データ、実行結果、キャッシュをGit管理しない。
- 設定例を共有する場合はダミー値を使った `*.example.*` とし、秘密情報を含めない。
- 未コミット変更はGitHubから確認できないため、作業中であることと確認状況を管理文書に明記する。

## ビルドと共有版更新

- 共有版更新は専用スクリプト `update_shared_folder.ps1`（通常はラッパーの `UPDATE_SHARED_FOLDER.cmd`）を使用する。
- `next-day-setup` の配布物 `dist\DinnerSystem\_internal` は完全同期し、古いランタイムやライブラリを残さない。
- 業務データ保護のため、共有フォルダ全体へ単純な `robocopy /MIR` を使用しない。
- 配布物と業務データを分離し、更新前後に業務データが保持されていることを確認する。
