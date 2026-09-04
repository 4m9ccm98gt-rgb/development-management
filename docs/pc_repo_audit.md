# PC 全体 リポジトリ／クローン監査（2026-09-04）

Windows PC 上の全 git リポジトリを探索し「正規 / 旧 / 不明」に分類した。
**この監査では何も削除していない。** 未 push / 未コミット作業を発見しても、
内容を確認しただけで main へは入れていない。

探索範囲: `C:\Users\suisy` 配下（`AppData` / `node_modules` / `.venv` 除外）。
ドライブ: `C:`（作業用）、`D:`（リムーバブル・メディアなし）、`E:` `WE-Elements`（俺伝配布用外付けHDD）。

## 正規（canonical）

`C:\Users\suisy\Documents\Development\repos\` 配下の9リポジトリ。すべて GitHub
`4m9ccm98gt-rgb/<name>` と対応し、同期済み。

`beverage-inventory-ordering-system` / `call-reception-assistant` /
`development-management` / `food-cost-calculation-system` /
`inventory-reconciliation-system` / `kitchen-calendar` / `menu-sheet-generator` /
`next-day-setup` / `qr-supply-ordering-system`

## 旧・要確認（未 push 作業あり）

### A. `C:\Users\suisy\Documents\開発環境整備プロジェクト`（development-management の旧 clone）

- 対応 GitHub: `4m9ccm98gt-rgb/development-management`
- コミット履歴は正規リポジトリの祖先。**失われたコミットは無い。**
- ただし**未コミット編集が15件、GitHub 未反映**：
  - 新規: `BUSINESS_MODEL.md`（共通業務モデル／タスクモデルの設計文書。正規リポジトリに存在しない）
  - 新規: `projects/food-cost-calculation-system.md`、`projects/qr-supply-ordering-system.md`（正規リポジトリの `projects/` に無いプロジェクト文書）
  - 変更: `AI_OPERATING_MANUAL.md`(+86)、`docs/decisions.md`(+43)、`DAILY_LOG.md`(+68)、`VERSION_MATRIX.md`(+38)、`CHANGELOG.md`(+18)、`REPOSITORIES.md`(+17)、`AI_STARTUP.md` / `AI_CHECKLIST.md` / `PROMPT_PRINCIPLES.md` / `LESSONS_LEARNED.md` / `PROJECT_STATUS.md` / `projects/next-day-setup.md`
- **判断待ち**：これらの文書編集を正規リポジトリへ取り込むか。内容を1件ずつ確認し、
  現行の正規版と突き合わせてから決める（そのまま main へ入れない）。

### B. `C:\Users\suisy\Documents\kichen-calendar`（"kitchen" の綴り違い、kitchen-calendar の旧 clone）

- 対応 GitHub: `4m9ccm98gt-rgb/kitchen-calendar`（`repo_types.toml` では `archived`）
- コミット履歴は `e7ba6af Implement Phase 1 kitchen calendar`（GitHub の kitchen-calendar より古い）。
- **未コミット作業が大量（24件）、GitHub 未反映**：`kitchen_calendar/ui.py`(+434) / `models.py`(+90) / `pms_csv.py`(+29)、新規モジュール約10本（`calendar_cell` `daily_detail` `nds_holidays` `pdf_export` `print_model` `rice_settings` 等）、新規テスト6本、`requirements.txt`、起動 `.bat`。
- **比較結果**：これらのモジュールは `next-day-setup/dinner_system/kitchen_calendar/` に
  すべて存在し、NDS 側の方が新しく大きい（例 `ui.py` 666 行 vs 472 行）。NDS には
  さらに `a3_worksheet` `bulk_pdf` `image_export` `nds_adapter` もある。
- **見立て**：この作業は NDS への調理場カレンダー統合の **前段階版で、統合先で継続開発されて
  現在は上位互換になっている可能性が高い**。ただし旧 clone 固有の差分が無いかは全ファイル
  比較していない。
- **判断待ち**：NDS 側に無い固有の変更が無いことを確認できれば、この clone は参照／保管
  扱いでよい（削除しない）。

### C. `C:\Users\suisy\Documents\ChatGPT\food-cost-calculation-system`（旧・食材原価アプリの作業コピー）

- 対応 GitHub: なし（`git init` のみ、コミット無し、全ファイル untracked、ブランチ `master`）
- `src/` `tests/` `docs/` `pyproject.toml` `run_app.ps1` `google_apps_script/` 等、食材原価アプリの一式がある。
- 公式 `food-cost-calculation-system` リポジトリが存在し継続開発されているため、**初期の作業コピーで上位互換に置き換わっている可能性が高い**。
- **判断待ち**：公式リポジトリの `src/` と内容比較し、固有のものが無ければ保管扱い。

## 旧・同期済み（リスク低）

| パス | 対応 GitHub | 状態 |
|---|---|---|
| `Documents\在庫突合システム作成` | inventory-reconciliation-system | tracked は origin/main 一致。untracked は `GITHUB_UPLOAD.md` / `upload_to_github.bat` / `.ps1`（一度きりのアップロード補助）のみ |
| `Documents\inventory-reconciliation-system` | （remote 無し） | clean |
| `Documents\inventory-ordering-system`（+ `worktree/`） | （remote 無し） | clean。旧・発注系プロトタイプと思われる |
| `Documents\kichen-calendar\.reference-next-day` | next-day-setup | 参照コピー、clean、同期済み |
| `Documents\kichen-calendar\tmp\fresh-clone-20260806-201441` | kitchen-calendar | 一時 clone、detached、clean |
| `Documents\Call Reception Assistant` | （remote 無し） | コミット無しの空 stub |

## 不明・scratch（リスク低）

- `Documents\Codex\` および `Documents\Codex\2026-05-21 … 2026-07-15\**`（8 リポジトリ）:
  Codex CLI のセッション作業ディレクトリ（`files-mentioned-by-the-user-*` / `MenuPrinterWpf` /
  `fax` / `new-chat` / `pc-python-github-codex`）。remote 無し、clean。使い捨てと思われる。

## 管理対象外の実リポジトリ（要判断）

### `C:\Users\suisy\Documents\hospitality-review-reply`

- 対応 GitHub: `4m9ccm98gt-rgb/hospitality-review-reply`（**実在する GitHub リポジトリ**）
- `main`、clean、GitHub と同期済み。
- **管理9リポジトリに含まれていない**（`repo_types.toml` 未登録、正規パス `Development\repos` 配下に無い、CI 無し）。
- **判断待ち**：(a) 管理対象へ昇格（正規パスへ clone、`repo_types.toml` 登録、CI 追加）か、
  (b) 明示的に管理対象外とするか。

## 比較・救出の結果（2026-09-04）

### #1 `開発環境整備プロジェクト`（dev-mgmt 旧 clone）— 救出済み（レビュー用ブランチ）

15件の未 push 编集を canonical の現状と1件ずつ比較・分類。canonical は上書きせず、
取り込み候補のみ `recovery/from-old-clone-docs` ブランチ（Draft PR）に追記。分類詳細は
[recovery_from_old_clone.md](recovery_from_old_clone.md)。救出候補：`BUSINESS_MODEL.md`、
`projects/food-cost-*.md` / `projects/qr-supply-*.md`、フェーズ規律フレームワーク、
未反映だった5設計判断。旧・不要（ログ churn）と旧・要最新化（VERSION_MATRIX / REPOSITORIES）は未適用。
秘密情報・認証情報・顧客情報・実 FAX / 業者名は含まれない。→ **旧 clone は削除せず保管。**

### #2 `kichen-calendar`（綴り違い、kitchen-calendar 旧 clone）— superseded、固有差分なし

- ローカル専用コミットなし。24件の未コミットは標準スタンドアロン版の作業。
- 全モジュールが `next-day-setup/dinner_system/kitchen_calendar/` に存在し、NDS 側の方が新しく大きい（`ui.py` 666 vs 472 行など）。テストは NDS 10本 vs 旧 6本で NDS が上位集合。
- 旧 clone 固有のモジュール（`master.py` の JSON ローダ、`pms_csv.py` の直接パーサ、`nds_holidays.py` の跨 repo import、`__main__.py`）は、統合時に NDS 共有版（`nds_adapter.py` + NDS の `pms_import` + サブウィンドウ起動）へ**置き換えられたスタンドアロン用の配線**であり、失われた機能ではない。
- `config/rice_settings.json` は NDS の `kitchen_calendar_rice_settings.json` に相当。
- **結論：NDS へ統合済み・旧 clone は superseded。固有の機能／ロジック／テスト／設定／文書は見つからなかった**（全モジュールの完全な意味的 diff は未実施だが、NDS 版は一貫して上位）。→ **削除せず保管扱い。**

### #3 `ChatGPT\food-cost-calculation-system`（git init のみ・commit なし）— obsolete、固有差分なし

- git 履歴なし。`src/` の全ファイルが公式 `food-cost-calculation-system` に存在（欠落ゼロ）。
- 差分のある全ファイルが公式版より小さい（`database.py` 310 vs 1022 行、`ui.py` 567 vs 1838 行など）。一部は完全一致。
- **結論：初期作業コピー・obsolete。公式側に無い固有作業は見つからなかった。**→ **削除せず保管扱い。**

### #4 `hospitality-review-reply` — 管理対象へ追加（knowledge repository）

- private、`main`、GitHub と同期（`Documents\hospitality-review-reply` の旧 clone は behind 5 だったため、正規パスへ新規 clone）。
- `README.md` / `AI_HANDOFF.md` あり（`AGENTS.md` は無し＝任意フォローアップ）。tracked ファイルに秘密パターンなし。
- **アプリではなくテンプレート/知識 repo** のため、`repo_types.toml` に `knowledge` 種別を新設して登録。`check_standards.py` は `knowledge` に実行・ビルド標準を課さず、秘密情報チェックのみ行う。CI（warning-only）も追加。
- README の管理対象一覧に「knowledge repository / runtime 標準対象外」と明記。

## 未対応（ユーザー判断）

- `recovery/from-old-clone-docs`（Draft PR）のレビューと、正本への取り込み範囲の決定。
- `VERSION_MATRIX.md` / `REPOSITORIES.md` へ food-cost / qr-supply / hospitality-review-reply を**現在の実態で**追記。
- いずれの旧 clone も、上記判断が済むまで削除しない。
