# Agent Efficiency / CI Final Review — 2026-09-07

## 結論

Claude独立レビュー後の再検証と修正を完了した。

DevelopmentのT0〜T3リスク比例型フローと、Codexローカルfull regressionをGitHub Actionsへ移す方針は採用可能。
ただしCI代替は `AGENT_EFFICIENCY_POLICY.md` §4 / §9 のcoverage境界と、candidate SHAのgreen確認を満たす場合だけ成立する。

## 独立レビューから採用した修正

- T2/T3でCIをローカルfullの代替に使う場合、candidate SHAのCI green確認までterminal completionにしない。
- `CI確認予定` / `CI実行中` は途中状態とする。
- T2の固定文書コストを削るため、読む節を具体的に限定した。
- T1/T2境界で、共有utility等が2 hops以内に金額・在庫・数量・帳票・印刷・DB・業務日付へ流れる場合は最低T2とした。
- `【確立した事実】` が修正前targeted再現と矛盾する場合、その事実だけ再調査できる安全弁を追加した。
- green baselineが有効でも、自分の変更箇所のtargeted testは省略できないことを明文化した。
- CIでskip / 未カバーの領域にblast-radiusが触れる場合、CI-covered branchでもlocal / real checkを残す。
- 列挙型CIはdrift guard必須とし、新しいdeterministic test/harnessのworkflow追加漏れをgreenにしない。

## repo別の最終修正

### inventory-reconciliation-system / main

Candidate: `b715dbf1216e7ce51281689e34b5ec11a2ca786f`

- deterministic unittest 3 modulesを明示列挙。
- `test_*.py` のうちdeterministic testらしい新規fileを検出し、workflow列挙漏れならCIをfailさせるdrift guardを追加。
- shift-holiday local regressionを継続。
- live IMAP / browser / external-siteはCI外の実環境確認として維持。
- GitHub Actions `Inventory regression tests (Windows)` green確認済み。

Claude指摘 `IR-1`（`run_local_tests()` が失敗をraiseしない可能性）は現コードでは不採用。`run_local_tests()` は通常の `assert` を使い、失敗時は `AssertionError` により非0終了する。

### menu-sheet-generator / main

Candidate: `60bb973ba13bb47e7399d6cc3205ad56b3c32ef1`

- 2つの列挙harnessにdrift guardを追加。
- `MenuPrinterWpf.csproj` のRelease buildをCIへ追加し、harnessから参照されないUI等のcompile breakも検出する。
- PMS CSV aggregation / GDI pre-spool harnessを継続。
- GDI pre-spoolはrender/layoutまでで、spooler/driver/紙/物理出力は実プリンター確認と明記。
- GitHub Actions `Menu sheet regression (Windows)` green確認済み。

### qr-supply-ordering-system / main

Candidate: `acf3d67e761b70c76a49770a0002bf68f8b0cc07`

- repositoryのdeterministic pytest setを自動収集して実行。
- docs-only pushを除外、concurrencyで古いrunをcancel、pip cacheを追加。
- 実LAN、camera/QR scan、Windows firewall、populated production DB migration、multi-host運用はCI外と明記。
- DB migration/schema変更はtargeted migration dry-runを追加するルールをPolicyへ記載。
- GitHub Actions `QR supply pytest (Windows)` green確認済み。

Claudeの「18件では取込/DBがほぼ未検証」という評価はそのまま採用しない。現suiteにはxlsm/CSV取込、壊れたExcel、transaction rollback、missing unit、stable ID、gap非再利用、重複候補、concurrent ID allocation等が既にある。ただし実運用DB migration等はCI外として残す。

### food-cost-calculation-system / main

Candidate: `2bec8d54028a17961ff3a32f562c6ab7a30e3781`

- `requirements-dev.txt` に `Nuitka==4.2.1` を固定し、release dependencyを文書化可能な依存へ移した。
- CIはrepo-local `.venv` を作成し、`requirements-dev.txt` から依存を導入。
- pytest単体実行ではなく、Windows PowerShell 5.1で `build_release.ps1 -DryRun -AllowDirty` を **`-SkipValidation` なし** で実行する形へ変更。
- その正式validation gate内で pytest / compileall / `git diff --check` / distribution safety / BUILD_INFO生成を通す。
- 最終結果: **254 passed / 2 skipped**、formal validation dry-run成功。
- real Nuitka standalone/MSVC build、実Tesseract OCR、実HDD/利用PCはCI未カバーとPolicyへ明記。
- `tools/release/**`、build flags、dependency/build変更ではrelease前に正式手動build + launch確認を残す。

Claude指摘 `FC-3` の目的は採用したが、「pytest test内からvalidation付きDryRunを呼ぶ」案は採用しなかった。build script自身が `pytest -q` を実行するため、pytest内pytestの再帰構造を避け、GitHub Actionsの独立stepとしてformal validationを実行した。

Claude指摘 `FC-2`（CI Python 3.13 vs real dev 3.12）は、GitHub正本の `RUN_DEV.cmd` が `py -3` で3.12固定ではないため、その前提だけでは変更しない。現在はCI Python 3.13を維持する。

## 最終CI代替ルール

CIは「Codexローカルfullを省略するための代替」であり、「実環境確認の代替」ではない。

CI代替が成立する条件:

1. `AGENT_EFFICIENCY_POLICY.md` §9で現在branchがcovered。
2. 自分の変更のtargeted testを実施済み。
3. blast-radiusがCI skip / 未カバー領域に触れる場合、その領域のlocal / real checkを別途実施。
4. candidate SHAのCI greenを実際に確認済み。
5. 列挙型CIではdrift guardがgreen。

この条件を満たした場合、同じautomated full regressionをCodexローカルで重複実行しない。

## 残る意図的な非CI領域

- 実プリンター / printer driver / physical paper output
- 実共有サーバー / 複数PC
- live IMAP / Outlook / Thunderbird / browser / external site
- 実LAN / camera QR scan / Windows firewall
- populated production DB migration
- real Nuitka standalone / MSVC build
- 実Tesseract OCR
- 実HDD / 利用PC更新

これらは「未整備」ではなく、決定的CIへ安全に置けない実環境ゲート。変更が触れる場合だけWindows実機確認へ回す。

## 完了判定

Claude独立レビューで残ったHigh指摘（CI green completion loophole / 列挙型CI drift）は解消済み。
主要Medium指摘も、実物確認で妥当なものはPolicy・workflowへ反映した。

今後のCodex利用は、GitHub上で自動化可能なfull regressionではなく、上記の実環境ゲートとWindows固有問題へ優先配分する。
