# AI Memory

この文書は、`development-management` と管理対象プロジェクトに固有のルールを記録します。AIの一般的な役割、思考順序、Codexとの役割分担、回答形式は [AI_OPERATING_MANUAL.md](AI_OPERATING_MANUAL.md) に記録します。

## GitHubプロジェクト開始時の必須手順

新規チャットで GitHub リポジトリをプロジェクトとして開いた場合は、ルートの `AGENTS.md` と `DEVELOPMENT_RULES.md` に定めた「GitHubプロジェクト初期確認ルール」を標準手順として適用する。GitHub 取得内容のみを使い、旧ローカルフォルダを参照せず、コードを変更する前に必要ファイル、アプリ起動、ブラウザコンソールを確認する。正常起動した GitHub 上の状態を正本とし、問題があれば修正せず原因と対応案を報告して指示を待つ。

## 正式ソース

- 正式ソース以外は変更しない。
- 管理対象プロジェクトの正式ソースは `C:\Users\suisy\Documents\Development\repos` 配下とする。
- 旧フォルダは参照専用とし、新規開発、修正、ビルド、コミットに使用しない。
- 対象リポジトリを確認するときは、READMEだけでなく、現在のブランチ、最新タグ、最新コミット、未コミット変更も確認する。
- GitHub、実運用版、デモ機版の対応状況は [VERSION_MATRIX.md](VERSION_MATRIX.md) で確認する。

## 変更時の保護ルール

- 調査依頼では、コード、設定、業務データ、外部サービスの状態を変更しない。
- 不明なファイル、設定、データを推測で削除しない。
- 業務ロジックを明示的な合意なく変更しない。
- 既存の未コミット変更はユーザーの作業として維持し、上書き、破棄、巻き戻しをしない。
- 実運用設定、秘密情報、認証情報、顧客データ、業務データをGit管理しない。
- コミット、タグ、pushはユーザーから明示的な指示があるまで行わない。

## development-managementへの記録

- 重要な設計判断は [docs/decisions.md](docs/decisions.md) に記録する。
- 進行状況と次の作業は [PROJECT_STATUS.md](PROJECT_STATUS.md) と対象の `projects/*.md` に記録する。
- 再発防止に使える知見は [LESSONS_LEARNED.md](LESSONS_LEARNED.md) に記録する。
- 変更履歴は [CHANGELOG.md](CHANGELOG.md) に記録する。
- コードを変更した場合は、対象リポジトリのREADMEも更新する。
- 推測と確認済み事実を分け、未確認事項は「未確認」と明記する。

## 作業完了時のプロジェクト固有報告

- 変更した内容とファイル
- 実施した確認と結果
- 実運用で未確認の項目
- 既存変更を含む現在のGit差分
- `development-management` へ記録した判断・進行状況
- コミット、push、タグの実施有無
