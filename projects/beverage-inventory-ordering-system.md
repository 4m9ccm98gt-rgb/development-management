# beverage-inventory-ordering-system

## 概要

飲料在庫の入力、保存、要発注判定、将来の発注処理を管理する業務システムです。

## 現在の状態

- 正式ソースは `C:\Users\suisy\Documents\Development\repos\beverage-inventory-ordering-system`。
- 現行運用版から必要ファイルを正式ソースへコピー済み。
- コピー対象10ファイルは現行版とのハッシュ一致を確認済み。
- `README.md` と `.gitignore` を作成済み。
- `app.js` 構文確認、ブラウザ起動、保存メッセージ、JSON読込・復元、リロード後の復元を確認済み。
- 発注中数量を加味した要発注判定を確認済み。
- 現行運用版は変更・削除していない。
- GitHubリポジトリ `4m9ccm98gt-rgb/beverage-inventory-ordering-system` は非公開で作成済みだが、まだ空。
- 初回コミット・pushは未実施。

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

Windows ACLは解消済みです。

ただし、現在のCodexセッションでは `.git` ディレクトリ作成がサンドボックスにより拒否され、`git init -b main` を実行できませんでした。ファイル編集は可能ですが、Git初期化だけ実行前に停止しています。

## 次にやること

1. Windows PowerShellまたはGit Bashで正式ソースへ移動する。
2. `git init -b main` を実行する。
3. `git add` 対象を確認する。
4. `git commit -m "Initial commit: formalize beverage inventory system"` を実行する。
5. `origin` にGitHubの非公開リポジトリを設定する。
6. `main` へ初回pushする。
7. push後、GitHub上のファイル一覧とローカルのGit状態を確認する。
8. その後、飲料発注システムの統合設計へ進む。

## 未確認事項

- 実際のファイルダウンロード完了はブラウザ制御側では未確認。保存ボタン押下後のアプリ内メッセージは確認済み。
- 発注先URL `https://store.xorder.jp/mylist?sosId=1380377` は業務用URL。現在のGitHubリポジトリは非公開のため今回は維持する。公開へ変更する場合は事前に分離を検討する。

## 注意

- ブラウザ保存データを消失させない。
- 認証情報、実運用設定、業務データ、出力物をGit管理しない。
- 現行システムの業務ロジックを初回Git化と同時に変更しない。
- 現行運用版を削除・上書きしない。
- 実運用確認済みと未確認を分けて記録する。
