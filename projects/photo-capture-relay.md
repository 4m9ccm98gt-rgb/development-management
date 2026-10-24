# photo-capture-relay

最終確認: 2026-10-24（JST）

## 正式ソース

`C:\Users\suisy\Documents\Development\repos\photo-capture-relay`（種別 `service`、既定ブランチ `main`）。
GitHub: `https://github.com/4m9ccm98gt-rgb/photo-capture-relay`（private）。2026-10-04 に初回commit `b28560c` を `main` へ push。

## 役割

スマホで撮った写真を、Google Apps Script Web App ＋ 非公開Drive一時受信箱経由でPCへ届け、
共有フォルダの `<保存先>\yyyy-MM-dd\`（送信日・日本時間）へ保存する。同名は `_2`, `_3`… で上書きしない。
方式・安全境界は俺伝（food-cost-calculation-system）の Google 4G/5G 受信をコピーして独立させたもの。俺伝repoは変更していない。

## 決定事項（2026-10-04 ユーザー回答）

- PC側は事務所の別PCでログオン時常駐（`INSTALL_TASK_CLICK_ME.cmd`、タスク名 `PhotoCaptureRelay`）。
- 保存先は共有フォルダ（UNC / NAS）。未接続時は取り込まず Drive に残す（72時間）。
- スマホの入口は俺伝と同じ48時間セッション。常駐側が残り24時間未満で自動更新し、QRページをローカルに出力。
- 状態管理は Drive ファイル説明欄のみ（スプレッドシートは使わない）。ack 後はゴミ箱へ（俺伝と同じ）。
- 設定は `%LOCALAPPDATA%\PhotoCaptureRelay\config\settings.json`。repoには `settings.example.json`（ダミー）のみ。

## 現在の状態（2026-10-24）

- **フロントPCで稼働中**。用途は外国人宿泊者の旅券画像の受け渡しのため、Googleドライブに画像を残さない方針（取込済みは ack で即時完全削除、未取込は `RETENTION_HOURS` = 72時間で完全削除）。
- **本番の Apps Script はバージョン5 = `67c79a7`**（`gas/Code.gs` は GitHub と SHA-256 一致を確認済み）。有効なデプロイは1つ（ID先頭 `AKfycbwxoic…`、フロントPCが使用、URL不変）。未使用だった旧デプロイ（ID先頭 `AKfycbx-9HaREm…`、バージョン1）はアーカイブ済み。
- 本番の `appsscript.json` は Drive 拡張サービス（v3）と webapp 設定（`executeAs` = `USER_DEPLOYING`、`access` = `ANYONE_ANONYMOUS`）を持つ。repo の `gas/appsscript.json` も同じ内容に揃えた（`b1a4327`）。
- repo `main` の最新は `b1a4327`（pytest 148件 PASS）。実装: `gas/`（完全削除・clientId 目印7日・手動 preview / purge）、PC側 `src/photo_capture_relay/`、本番セットアップ・診断・配布スクリプト。
- 2026-10-24 の本番作業（Apps Script エディタで手作業）: 上記の更新、`previewTrashedInboxFiles` で旧ゴミ箱 39件（acked 39 / pending 0 / 判別不能 0、親が確認できないもの 0）を確認、`purgeTrashedInboxFiles` で39件を完全削除（失敗0、ゴミ箱は空）。
  旧版が0件と表示したのは `DriveApp.searchFiles` の検索自体が原因で、ファイルの親情報は正常だった。
- 送信テスト: スマホ → フロントPC取込 → ack の後、写真が受信フォルダにもゴミ箱にも残らないことを確認済み。

## 未確認

- ack 後の再送が「受信済み」（clientId の目印）になる実機確認。
- 未取込写真の72時間後の完全削除（`cleanupExpired` の実動作）。
- スマホ実機の細部（HEIC・大きい写真・複数選択）、共有フォルダ上の連番 rename の長期運用。
- フロントPC側の配布版（exe）の版の記録（この記録では未確認）。

## 次の作業

1. 運用しながら上記の未確認を確認する。
2. repo側 `AI_HANDOFF.md` を現状に合わせる（デプロイ済みの記述）。
