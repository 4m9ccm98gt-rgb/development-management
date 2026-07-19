# next-day-setup 配布手順

## 原則

- 正式ソース `C:\Users\suisy\Documents\Development\repos\next-day-setup` からビルドする。
- リポジトリ直下の `.venv` を使用する。
- 実運用設定と業務データをGitやビルド成果物へ混入させない。

## 成果物

- 配布元: `dist\DinnerSystem`
- 実行ファイル: `dist\DinnerSystem\DinnerSystem.exe`
- ランタイム／依存ファイル: `dist\DinnerSystem\_internal`

## 更新手順

1. 構文確認、テスト、Python版の手動起動を行う。
2. 正式ソースからビルドする。
3. `DinnerSystem.exe` と `_internal` を含む成果物をローカルで起動確認する。
4. `update_shared_folder.ps1`（通常は `UPDATE_SHARED_FOLDER.cmd`）で共有版を更新する。
5. `_internal` だけは完全同期し、古いPythonランタイムやライブラリを残さない。
6. 共有フォルダにある業務データと実運用設定が保持されていることを確認する。
7. 共有版の起動、主要画面、印刷を実運用環境で確認する。

共有フォルダ全体に単純な `/MIR` を使用してはいけません。配布物と業務データで同期方針を分けます。

