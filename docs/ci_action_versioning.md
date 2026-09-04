# 共通 CI アクションのバージョン運用

各アプリの `.github/workflows/standards.yml` は、`development-management` の
composite action `.github/actions/check-standards` を `uses:` で参照する。

## 参照は `@ci-v1` に固定する（`@main` にしない）

- `@main` を参照すると、`development-management` の `main` へ何か push しただけで
  全アプリの CI 挙動が即座に変わる（事故半径が広い）。
- そのため各アプリは **`@ci-v1`** タグを参照する。
  ```
  uses: 4m9ccm98gt-rgb/development-management/.github/actions/check-standards@ci-v1
  ```

## タグの意味

| タグ | 種類 | 意味 |
|---|---|---|
| `ci-v1.0.0` | 不変 | 初版（`c42b423`）。動かさない |
| `ci-v1.0.1` | 不変 | `knowledge` 種別追加（`40660b4`）。dogfood + hospitality-review-reply で確認 |
| `ci-v1` | 移動する | 「現在の安定版 v1系」。現在 `ci-v1.0.1`。検証済みの `ci-v1.x.x` へ張り替える |

### 更新履歴

- `ci-v1.0.0` (2026-09-04): 初版。dogfood + next-day-setup パイロット + 8repo 展開で確認。
- `ci-v1.0.1` (2026-09-04): `check_standards.py` に `knowledge` 種別を追加。`repo_types.toml` に `hospitality-review-reply = "knowledge"`。dogfood CI 成功 → hospitality CI で `@ci-v1` が `40660b4` を解決し `OK: 指摘なし` を確認 → `ci-v1` を移動。

`development-management` 自体の知識ベース版（`v1.0.0` 等）とは別系統。混同しない。

## 共通アクション（`scripts/check_standards.py` 含む）を変更するときの手順

必ず次の順で行う。途中で失敗したら `ci-v1` は動かさない。

1. **main**：`development-management` の `main` へ変更を push する。
2. **dogfood**：`development-management` 自身の CI（`standards-self.yml`、ローカルパス参照）が
   `success` であることを確認する。
3. **パイロット**：1つのアプリリポジトリの `standards.yml` を一時的にその変更の
   ブランチ／SHA へ向けたブランチを作り、push / PR で CI を回して意図どおりの
   結果（準拠 → success、既知の違反 → WARN 検出、warning-only で非ブロック）を確認する。
4. **成功確認**：上記がすべて緑であることを目視で確認する。
5. **ci-v1 更新**：新しい不変タグ（例 `ci-v1.0.1`）を打ち、`ci-v1` をそこへ移動して
   force push する。
   ```
   git tag -a ci-v1.0.1 -m "..." <SHA>
   git tag -f -a ci-v1 -m "move to ci-v1.0.1" <SHA>
   git push origin ci-v1.0.1
   git push -f origin ci-v1
   ```
6. 各アプリは `@ci-v1` のままで自動的に新実装を使う。個別変更は不要。

## 新しいアプリに CI を足すとき

`templates/ci/standards.yml` をそのまま `.github/workflows/standards.yml` として置く。
参照はすでに `@ci-v1`。
