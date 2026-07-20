# beverage-inventory-ordering-system

## 概要

飲料在庫の入力、保存、要発注判定、飲料発注処理を管理する業務システムです。

1つの正式プロジェクト内に次の2機能を持ちます。

- 飲料在庫管理システム
- 飲料発注システム（開発中）

## 現在の状態

- 正式ソースは `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`。
- 飲料発注システムは独立プロジェクトにせず、同一リポジトリ内の `apps/ordering/` サブシステムとして管理する。
- 在庫管理システムはリポジトリ直下の現行構成を維持し、発注システムは開発中として段階的に統合する。
- 現行運用版から必要ファイルを正式ソースへコピー済み。
- コピー対象10ファイルは現行版とのハッシュ一致を確認済み。
- `README.md` と `.gitignore` を作成済み。
- `app.js` 構文確認、ブラウザ起動、保存メッセージ、JSON読込・復元、リロード後の復元を確認済み。
- 発注中数量を加味した要発注判定を確認済み。
- 現行運用版は変更・削除していない。
- GitHubリポジトリ `4m9ccm98gt-rgb/beverage-inventory-ordering-system` へ初回push済み。
- アプリ本体、初期マスタ、棚卸入力フォーマット、README、`docs/`、運用説明書はGitHubへ反映済み。
- ローカル`main`はGitHub `main`（`8d2ab9c`）へfast-forward済みで、`origin/main`と一致している。
- 同期後のGit状態はクリーン。`app.js`構文確認、ブラウザ起動、コンソールエラーがないことを確認済み。

## 正式ソース

`C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`

今後は、このフォルダのみを開発・修正・コミット対象とします。現行のCodex配下フォルダは参照専用として維持します。

## 移行済みファイル

- `index.html`
- `app.js`
- `styles.css`
- `default-drink-items.js`
- `default-recipes.js`
- `default-order-settings.js`
- `商品マスタひな形.xls`
- `棚卸入力_フォーマット.csv`
- `飲料在庫チェック_社内運用説明書.docx`
- `飲料在庫チェック_システム管理者向け解説.docx`
- `README.md`
- `.gitignore`

## Git管理から除外したもの

- `_不要ファイル退避_20260524` 配下
- `inventory-data.json`
- 旧CSV、旧bat、旧ps1
- バックアップxls
- 生成HTML、出力xlsx
- その他の運用データ・生成物

## 保存方式

- `localStorage`
  - `drinkInventorySettings`
  - `drinkInventorySettingsBackup`
- JSON保存・読込
  - `drink-inventory-data.json`
- HTTP起動時のみ `/api/data` へ保存・読込
- `sessionStorage`、IndexedDB、Cache APIは未使用

## 要発注判定

現在の考え方:

`棚卸し在庫 + 納品済み + 発注中 - 売上消費`

`getPendingFromOrderHistory()` と `alertRemaining = remaining + pending` で確認済みです。

## 現在の阻害要因

正式ソースの書き込みとGit同期を確認済みで、在庫管理側の継続開発を妨げる既知のGit阻害要因はありません。

飲料発注アプリは `apps/ordering/` へ移管済みです。Git管理対象には実業者名、実FAX番号、実発注履歴を含めず、開発用サンプルデータで起動できる状態にしています。

発注システムは開発中です。在庫管理側の商品マスタ、発注中数量、納品済み管理との統合は未完了です。

## 次にやること

1. `apps/ordering/` の発注システムと在庫管理側の商品マスタを比較し、共通化方針を決める。
2. 発注履歴を在庫管理側の `orderHistory` と統合する設計を行う。
3. 実業者名、実FAX番号、実発注履歴をGit管理しない安全な実運用データ投入手順を決める。
4. PC間共有保存、既存データ保護を含む段階的な統合手順を設計する。

## 未確認事項

- 実際のファイルダウンロード完了はブラウザ制御側では未確認。保存ボタン押下後のアプリ内メッセージは確認済み。
- 発注先URL `https://store.xorder.jp/mylist?sosId=1380377` は業務用URL。現在のGitHubリポジトリは非公開のため今回は維持する。公開へ変更する場合は事前に分離を検討する。
- 飲料発注システムの移管元単体タスクは、今回の移管をもって開発拠点としては終了。今後は正式ソースの `apps/ordering/` のみを変更する。

## 注意

- ブラウザ保存データを消失させない。
- 認証情報、実運用設定、業務データ、出力物をGit管理しない。
- 現行システムの業務ロジックを初回Git化と同時に変更しない。
- 現行運用版を削除・上書きしない。
- 実運用確認済みと未確認を分けて記録する。
