# リポジトリ一覧

最終更新: 2026-09-04（JST）

正式ソースはすべて `C:\Users\suisy\Documents\Development\repos\<name>` 配下。
GitHub は `https://github.com/4m9ccm98gt-rgb/<name>`（すべて private）。
種別の唯一の正は [scripts/repo_types.toml](scripts/repo_types.toml)。

## 管理対象（10）

| リポジトリ | 種別 | 既定ブランチ | GitHub 既定ブランチ HEAD（2026-09-04） | タグ | 備考 |
|---|---|---|---|---|---|
| next-day-setup | desktop | `main` | `1b048f4` | `v1.2.1` | 翌日準備。実運用中。3経路完備。 |
| inventory-reconciliation-system | service | `main` | `fd2de21` | `v2.0.0` | 販売在庫突合。夜間自動実行。 |
| beverage-inventory-ordering-system | desktop | `main` | `main` = `7af032d` | なし | 移行作業は `python-desktop-migration`（`e458476`、upstream と同期）。Draft PR #2。能力ベース運用の起点。 |
| food-cost-calculation-system | desktop | **`codex/bootstrap-invoice-reading`** | `1940db0` | なし | 俺伝。`main` ブランチは無い。Nuitka + 外付け HDD 配布。既定ブランチの `main` 化は M3。 |
| menu-sheet-generator | desktop | `main` | `fa4fdf7` | `v1.0.0` | 料理説明書。.NET / WPF。GitHub Release 公開済み。 |
| qr-supply-ordering-system | web | `main` | `790fff5` | なし | QR 物品発注。社内 LAN の 1 ホストで Flask 常駐。`DEPLOY.md`。 |
| call-reception-assistant | desktop | `main` | `ae78cf5` | なし | 電話受付。**アプリ本体は未実装**。無課金・ローカル完結の初期試作方針。 |
| kitchen-calendar | archived | `main` | `2362043` | なし | 調理場カレンダー。next-day-setup へ統合済み。**今後開発しない**。 |
| hospitality-review-reply | knowledge | `main` | `f6e1e74` | なし | 旅館口コミ返信のテンプレート／知識 repo。アプリではない。CI は warning-only、実行・ビルド標準は課さない。 |
| development-management | — | `main` | `d45c0c9` | `ci-v1`（moving）/ `ci-v1.0.x`（固定） | 本知識ベース。共通 CI アクション（`.github/actions/check-standards`）を各 repo が `@ci-v1` で参照。 |

- HEAD 値は 2026-09-04 時点。最新は各リポジトリで `git -C <path> log -1` により確認する。
- 「既定ブランチ」はそのリポジトリで作業の基準になるブランチ。beverage は移行が終わるまで
  `python-desktop-migration`、俺伝は `codex/bootstrap-invoice-reading`。
- CI（GitHub Actions）は全 repo で warning-only（`strict: false`）。開発をブロックしない。

## 旧フォルダ・管理対象外の clone

`Development\repos` 配下以外の git リポジトリは参照専用。新規開発、修正、ビルド、コミットの
起点にしない。旧フォルダで見つけた修正は正式ソースへ内容を移してから検証する。
PC 全体の監査結果と各旧 clone の分類（救出済み／superseded／obsolete）は
[docs/pc_repo_audit.md](docs/pc_repo_audit.md) を参照。

- `C:\Users\suisy\Documents\開発環境整備プロジェクト` — development-management の旧 clone。
  未 push 編集の取り込み候補は `recovery/from-old-clone-docs`（Draft PR）に隔離済み。削除しない。
- `C:\Users\suisy\Documents\kichen-calendar`（綴り違い） — kitchen-calendar の旧 clone。superseded。削除しない。
- `C:\Users\suisy\Documents\ChatGPT\food-cost-calculation-system` — 俺伝の初期作業コピー。obsolete。削除しない。
- `C:\Users\suisy\Documents\hospitality-review-reply` — 旧 clone（behind）。正規パスへ新規 clone 済み。
- `C:\Users\suisy\Documents\Call Reception Assistant` — 正式ソースではない。`call-reception-assistant` の変更先に使わない。
