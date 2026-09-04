# System Overview

最終更新: 2026-09-04（JST）

## 全体構成

```text
                    正式な開発知識ベース（司令塔）
        ┌──────────────────────────────────────────────┐
        │ development-management                        │
        │ ・設計判断／開発ルール／進行状況              │
        │ ・AI 引き継ぎ／障害知見                       │
        │ ・標準（CAPABILITIES / repo_types /           │
        │   templates / check_standards / DEV_DOCTOR）  │
        │ ※業務コード本体は置かない                     │
        └───────────────┬──────────────────────────────┘
                        │ 状況・判断・知見を記録
   ┌────────────────────┼───────────────────────────────────────────┐
   │ desktop（GUI + EXE ビルド + 配布）                              │
   │  next-day-setup        翌日準備／席割・帳票・印刷／共有フォルダ配布 │
   │  food-cost-calculation-system（俺伝）  食材原価／Nuitka／外付けHDD配布 │
   │  menu-sheet-generator  お品書き印刷（.NET/WPF）／共有フォルダ配布   │
   │  beverage-inventory-ordering-system  飲料在庫・発注／Python移行中  │
   │  call-reception-assistant  電話受付（未実装・設計前）             │
   ├────────────────────────────────────────────────────────────────┤
   │ service（常駐・自動実行）                                        │
   │  inventory-reconciliation-system  販売在庫突合／夜間自動実行／警告メール │
   ├────────────────────────────────────────────────────────────────┤
   │ web（LAN サーバー）                                              │
   │  qr-supply-ordering-system  QR 物品発注／社内 LAN の 1 ホストで Flask │
   ├────────────────────────────────────────────────────────────────┤
   │ knowledge / archived                                            │
   │  hospitality-review-reply  口コミ返信テンプレート（アプリではない） │
   │  kitchen-calendar  next-day-setup へ統合済み（開発しない）        │
   └────────────────────────────────────────────────────────────────┘
                        │ 正式参照
                  ┌─────▼──────────┐
                  │ Google Sheets  │  シフト／休館日（next-day-setup /
                  │                │  inventory-reconciliation-system）
                  └────────────────┘
```

## 役割分担

| リポジトリ | 種別 | 管理するもの | 管理しないもの |
|---|---|---|---|
| development-management | — | 設計判断、ルール、現在地、引き継ぎ、教訓、横断標準 | 業務コード、実運用設定、業務データ |
| next-day-setup | desktop | 翌日準備、席割・担当割、帳票・印刷、共有版配布、調理場カレンダー統合分 | 販売在庫照合 |
| inventory-reconciliation-system | service | 販売在庫照合、休館日判定、夜間実行、警告メール | 印刷プラットフォーム |
| food-cost-calculation-system（俺伝） | desktop | 食材原価計算、請求書読み取り、Nuitka ビルド、外付け HDD 配布 | 実請求書画像、認証情報、food_cost.db 実データ |
| menu-sheet-generator | desktop | お品書き印刷（日本語・英語・従業員用）、PMS CSV 集計、共有フォルダ配布 | 実運用データ、配布先実パス |
| beverage-inventory-ordering-system | desktop | 飲料在庫管理、飲料発注サブシステム（`apps/ordering/`）、Python/PySide6 移行 | 実業者名、実 FAX 番号、実発注履歴 |
| qr-supply-ordering-system | web | QR 生成、物品発注 Web アプリ、LAN 運用手順 | 実発注データ、SECRET_KEY、DB 実体 |
| call-reception-assistant | desktop | 対話受付の設計・初期試作方針 | 電話回線、PMS 自動入力、実在庫変更（すべて対象外） |
| hospitality-review-reply | knowledge | 旅館口コミ返信のテンプレート・知識 | 実行・ビルド標準（課さない）、実顧客レビュー |
| kitchen-calendar | archived | （なし。統合済み） | すべて |

## 開発情報の流れ

1. 各業務リポジトリの正式ソース（`Development\repos\<name>`）で調査・実装・検証する。
2. コードの詳細は対象リポジトリへ記録する。
3. プロジェクト横断の現在地、重要判断、ルール、教訓を `development-management` へ記録する。
4. 新しいセッションは `development-management` の [AI_STARTUP.md](AI_STARTUP.md) →
   [PROJECT_STATUS.md](PROJECT_STATUS.md) の順で状況を把握してから作業を再開する。
