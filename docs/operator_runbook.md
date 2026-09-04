# オペレーター用ランブック

この文書は、**開発ツール（Claude Code 等）が無い状態でも、日常の操作と困ったときの対応が
自分でできる**ようにするための手順書です。技術用語は最小限にしています。

前提のフォルダ:

- 正式なコード置き場: `C:\Users\suisy\Documents\Development\repos\`
- この知識ベース: `...\repos\development-management\`
- バックアップ: `C:\Users\suisy\DevDataBackups\` と `E:\DevDataBackups\`（外付け HDD）

---

## 1. 毎週やること

1. 外付け HDD（`E:`）をつなぐ。
2. `...\development-management\scripts\BACKUP_DEV_DATA_CLICK_ME.cmd` をダブルクリック。
   - `[DONE] Backup complete.` が出れば成功。
3. できれば `C:\Users\suisy\DevDataBackups\` の中の一番新しい `devdata-...` フォルダを、
   USB メモリなど**取り外せる媒体**にもコピーする（ランサムウェア・PC 故障対策）。
4. 月に1回くらい `...\development-management\scripts\DEV_DOCTOR_CLICK_ME.cmd` をダブルクリックし、
   一番下の `Summary` を見る。`ERROR` か `ACTION` があれば、`%USERPROFILE%\DEV_DOCTOR_report.txt`
   の中身をまるごと ChatGPT に貼って相談する。

---

## 2. 各システムの操作（ダブルクリックするファイル）

すべて対象リポジトリのフォルダ内にあります。

| システム | 開発版を起動 | 正式ビルド | 配布 |
|---|---|---|---|
| 俺伝（food-cost-calculation-system） | `RUN_DEV.cmd`（または `起動.bat`） | `BUILD_俺伝_CLICK_ME.cmd` | `UPDATE_HDD_CLICK_ME.cmd`（外付け HDD 経由） |
| 翌日準備（next-day-setup） | `RUN_DEV.cmd`（または `夕食料飲システムを起動.bat`） | `BUILD_EXE_CLICK_ME.cmd` | `UPDATE_SHARED_FOLDER.cmd`（共有フォルダ） |
| 在庫突合（inventory-reconciliation-system） | `RUN_DEV.cmd`（または `run_inventory_reconcile.bat`） | ― | 夜間自動実行は `run_inventory_reconcile_auto.bat`（タスクスケジューラ登録は `install_daily_inventory_task.bat`） |
| 飲料在庫（beverage-inventory-ordering-system） | `python_app\RUN_DEV.cmd` | `python_app\BUILD_EXE_CLICK_ME.cmd` | `python_app\UPDATE_SHARED_FOLDER.cmd` |
| QR物品発注（qr-supply-ordering-system） | `RUN_DEV.cmd` | ― | `DEPLOY.md` の手順（社内 LAN の 1 ホストで `RUN_DEV.cmd`） |
| 料理説明書（menu-sheet-generator、.NET製） | ― | `BUILD_RELEASE.cmd` | `UPDATE.cmd` |
| 調理場カレンダー（kitchen-calendar） | ― | ― | 翌日準備に統合済み。単体では使わない |
| 電話受付（call-reception-assistant） | ― | ― | アプリ本体は未実装 |
| 口コミ返信（hospitality-review-reply） | ― | ― | テンプレート集。アプリではない |

- `RUN_DEV.cmd` を初めて実行すると、必要な環境（`.venv`）と部品を自動で用意します（数分かかることがあります）。
- ビルド（`BUILD_...`）は「今のコードが未保存（未コミット）だと止まる」設計です（俺伝・beverage）。止まったら開発者/ChatGPT に相談。
- 配布（`UPDATE_...`）は業務データを消さない設計です。実行前に確認メッセージが出ます。
- 各システムの「ソース → ビルド入口 → 成果物 → 配布入口 → 配布先」の対応と、どこで安全に止まるかは
  [build_deploy_paths.md](build_deploy_paths.md) にまとめてあります（2026-09-04 に非本番環境で経路を実地確認済み）。

---

## 3. 困ったときの相談のしかた

**ChatGPT 等に、次のどれかをまるごと貼って相談してください。** 状況が伝わります。

| 症状 | 貼るもの |
|---|---|
| PC の調子が悪い / 何かが動かない | `DEV_DOCTOR_CLICK_ME.cmd` を実行 → `%USERPROFILE%\DEV_DOCTOR_report.txt` の全文 |
| GitHub のページで赤い × / 黄色い印が出た | その画面（Actions のログ）の文字。※この CI は「警告のみ」で、開発をブロックしません。放置しても壊れませんが、内容は確認を |
| アプリが起動しない / エラーが出た | ウィンドウに出た文字、`RUN_DEV.cmd` の黒い画面の文字 |
| バックアップから戻したい | [backup_restore.md](backup_restore.md) の手順。復元前に必ず現物を別名で退避 |
| 新しい PC で一から始めたい | [backup_restore.md](backup_restore.md) の「新 PC での復旧」。認証は下の **6. GitHub 認証** |
| GitHub に push できない / `gh` がエラー / DEV_DOCTOR に `gh auth failed` か `git push/pull auth failed` | 下の **6. GitHub 認証が切れたときの再設定** |

---

## 4. やってはいけないこと

- `C:\Users\suisy\Documents` にある**古いフォルダ**（`開発環境整備プロジェクト`、`kichen-calendar`、
  `ChatGPT\...` など）を**削除しない**。中身の確認結果は
  [pc_repo_audit.md](pc_repo_audit.md) にあり、判断が済むまで残します。
- `%LOCALAPPDATA%\FoodCostCalculation\` や `%LOCALAPPDATA%\SalesInventoryCheckTool\` の中の
  **DB・設定・認証情報ファイルを直接編集しない**。各アプリの設定画面から変更する。
- バックアップの中身（`DevDataBackups\...`）を **GitHub に上げない**（認証情報が入っています）。
- 「更新して」「実装して」と AI に頼むのは通常どおり可。ただし **タグ付け・本番反映・共有フォルダ更新・
  実データ更新**は、AI に「やっていい」と明示的に言うまで実行されません（安全側の既定）。

---

## 5. 用語ミニ辞典

| 言葉 | 意味 |
|---|---|
| リポジトリ / repo | 1つのシステムのコード置き場（フォルダ＋ GitHub の対） |
| ブランチ | 変更を隔離する「脇コピー」。`main` が正式版 |
| commit / push | 変更を記録（commit）し、GitHub へ送る（push）。push しないと GitHub 側から見えない |
| PR（プルリクエスト） | 脇コピーの変更を `main` に取り込む前のレビュー窓口 |
| CI | GitHub 上で自動で走るチェック。この構成では「警告のみ」で開発を止めない |
| `.venv` | Python アプリが使う部品一式の入れ物。`RUN_DEV.cmd` が自動で作る |
| DEV_DOCTOR | この PC 側の健康診断（`check_standards` は GitHub 側の点検） |
| `gh` | GitHub の公式コマンド。PR 作成・CI ログ確認・API に使う。`git` とは別の鍵を持つ |
| GCM（Git Credential Manager） | `git push` / `git pull` が GitHub にログインするための仕組み。鍵は Windows の「資格情報マネージャー」に入る |

---

## 6. GitHub 認証が切れたときの再設定

この PC は **2 つの別々の鍵**で GitHub とやり取りしています。片方を直しても、もう片方は直りません。

| 鍵 | 使うもの | 保存場所 | 切れると止まること | 無事なこと |
|---|---|---|---|---|
| `gh` の OAuth トークン | `gh pr` / `gh run` / `gh api` / `gh workflow`（PR 作成、CI ログ確認、API） | Windows 資格情報マネージャー `gh:github.com:...` | `gh` を使う操作すべて | `git push` / `git pull`、GitHub 上で動いている CI 自体 |
| `git`（GCM）の資格情報 | `git push` / `git pull` / `git fetch`（HTTPS） | Windows 資格情報マネージャー `git:https://github.com` | GitHub への push / pull / fetch | ローカルの commit・ブランチ操作、`gh` コマンド |

どちらも**有効期限の日付は表示されません**。切れる主な原因は、GitHub 側でアプリ連携を取り消した・
パスワードを変えた・セキュリティ上の理由で GitHub が無効化した、のいずれかです。
`DEV_DOCTOR_CLICK_ME.cmd` が両方を点検します（gh 側 = `[ERROR] gh auth failed`、git 側 = `[ACTION] git push/pull auth failed`）。
技術的な背景は [github_auth.md](github_auth.md)。

### 6-1. `gh`（GitHub CLI）の再ログイン

1. **開くもの**: スタートメニューで「PowerShell」を検索して **Windows PowerShell** を開く（管理者権限は不要）。
2. **入力するもの**: 次を打って Enter。

   ```
   gh auth login
   ```

3. **聞かれたこと**にキーボードの矢印キーと Enter で答える:
   - `What account do you want to log into?` → **GitHub.com**
   - `What is your preferred protocol for Git operations?` → **HTTPS**
   - `Authenticate Git with your GitHub credentials?` → **Yes**
   - `How would you like to authenticate GitHub CLI?` → **Login with a web browser**
   - 画面に **8 文字のワンタイムコード**（例 `ABCD-1234`）が出る。メモする。
4. **ブラウザで**: Enter を押すとブラウザが開く（開かなければ表示された URL を自分で開く）。
   - GitHub にログイン → メモしたコードを入力 → **Authorize github**（`repo` / `workflow` / `read:org` / `gist` の許可）をクリック。
5. **成功後に確認**: PowerShell に戻り、次を打つ。

   ```
   gh auth status
   ```

   `✓ Logged in to github.com account 4m9ccm98gt-rgb` と
   `Token scopes: 'gist', 'read:org', 'repo', 'workflow'` が出れば成功。
   `workflow` が無いときだけ、続けて `gh auth refresh -s workflow` を実行して手順 4 をもう一度。

### 6-2. `git push` / `git pull` の再ログイン（GCM）

**多くの場合、操作は不要です。** 資格情報が切れた状態で `git push` すると、GCM が自動でブラウザを開きます。
GitHub にログイン → **Authorize** で直ります。

自動で開かない・それでも失敗するとき:

1. **開くもの**: Windows PowerShell。
2. **入力するもの**: 古い資格情報を消す。

   ```
   git credential-manager github logout 4m9ccm98gt-rgb
   ```

3. どれか 1 つのリポジトリのフォルダへ移動して取得を試す（例: 知識ベース）。

   ```
   cd C:\Users\suisy\Documents\Development\repos\development-management
   git fetch
   ```

4. **ブラウザで**: GCM のウィンドウ／ブラウザが開く → GitHub にログイン → **Authorize Git Credential Manager**。
5. **成功後に確認**: 次がエラーなく行のリストを返せば成功。

   ```
   git ls-remote origin
   ```

   直らないとき: **コントロールパネル → 資格情報マネージャー → Windows 資格情報** で
   `git:https://github.com` を選んで「削除」→ もう一度手順 3 の `git fetch`。

### 6-3. 相談するとき

上記で直らない、または表示が手順と違うときは、`gh auth status` の全文（トークン値の行以外）と
`DEV_DOCTOR_report.txt` を ChatGPT 等に貼って相談する。**トークンそのものの文字列は貼らない。**
