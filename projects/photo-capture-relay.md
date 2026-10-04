# photo-capture-relay

最終確認: 2026-10-04（JST）

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

## 現在の状態

- 実装済み: `gas/`、PC側 `src/photo_capture_relay/`、`RUN_DEV.cmd`、`SHOW_CAPTURE_LINK_CLICK_ME.cmd`、
  `INSTALL_TASK_CLICK_ME.cmd` / `UNINSTALL_TASK_CLICK_ME.cmd`、README / docs / AI_HANDOFF。
- pytest 52件（Google通信モック）PASS。`RUN_DEV.cmd check` を一時 LOCALAPPDATA で起動確認。

## 未確認

- Apps Script 実デプロイ（ユーザー作業）と実URLでの往復。
- スマホ実機（カメラ直接起動・複数選択・HEIC・大きい写真）。
- 事務所PCでのタスク登録（非管理者）、ログオン直後の共有フォルダ接続、SMB / NAS 上の連番 rename。

## 次の作業

1. ユーザーが README の手順で Apps Script をデプロイし、開発PCで `RUN_DEV.cmd once` の実往復を確認する。
2. スマホ実機で送信・失敗時の再送を確認する。
3. 事務所PCへ配置し、タスク登録・共有フォルダ保存を確認する。
4. repo側 `AI_HANDOFF.md` の「GitHub 未作成」記載を現状へ更新する（初回commit時点の記述のまま）。
