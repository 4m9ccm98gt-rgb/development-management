# beverage-inventory-ordering-system

## 概要

飲料在庫の入力、保存、要発注判定、将来の発注処理を管理する業務システムです。

## 現在の状態

- 現行システムは `C:\Users\suisy\Documents\Codex\2026-05-21\files-mentioned-by-the-user-csv` 配下で運用中。
- ブラウザ保存を使用している。
- 発注中数量を加味した要発注判定まで実装済み。
- GitHubリポジトリ `4m9ccm98gt-rgb/beverage-inventory-ordering-system` は作成済みだが、現時点では空。
- 正式ソースへの移行、初回push、飲料発注システムの統合は未実施。

## 正式ソース予定地

`C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`

正式化後は、このフォルダのみを開発・修正・ビルド・コミットの対象とします。現行のCodex配下フォルダは移行確認後に参照専用とします。

## 現在の阻害要因

`C:\Users\suisy\Documents\Development\repos` に対し、Codex実行ユーザーグループ `CodexSandboxUsers` が `Modify` 権限を持っていません。

確認済みACL:

- `suisy`: `FullControl`
- `CodexSandboxUsers`: `ReadAndExecute`
- `CodexSandboxUsers`: `Modify` なし

このため、Codexから `Development\repos` 直下へ新規プロジェクトフォルダを作成できません。既存プロジェクトを編集できるのは、各プロジェクトフォルダに個別の `Modify` 権限が付いているためです。

これはWork、Codex、GitHubの不具合ではなくWindows ACLの問題です。

## 次にやること

1. Windows側で次のどちらかを実施する。
   - `Development\repos` に `CodexSandboxUsers` の `Modify` 権限を付与する。
   - 正式ソース予定フォルダを手動作成し、そのフォルダだけに `Modify` 権限を付与する。
2. 現行システムを正式ソース予定地へコピーする。
3. ファイル構成、保存データ、秘密情報、生成物を確認し、`.gitignore` を整備する。
4. READMEを作成し、現行機能、起動方法、データ保存方式、未実装事項を記載する。
5. ローカルGitとGitHubの空リポジトリを接続し、初回コミット・pushを行う。
6. 正式ソースからの動作確認後、現行Codex配下フォルダを参照専用とする。
7. その後、飲料発注システムの統合設計へ進む。

## 移行時の注意

- ブラウザ保存データを消失させない。
- 認証情報、実運用設定、業務データ、出力物をGit管理しない。
- 現行システムの業務ロジックを移行作業と同時に変更しない。
- 正式ソースでの動作確認が完了するまで、現行運用版を削除・上書きしない。
- 実運用確認済みと未確認を分けて記録する。
