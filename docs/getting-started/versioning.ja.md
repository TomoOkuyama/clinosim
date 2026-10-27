# バージョニングとリリース

clinosim の SemVer scope は generic SemVer のモジュール境界ではなく
**CIF ↔ narrative-CIF 整合性** に anchoring している。正準ルールは
[`CHANGELOG.md`](../development/changelog.md) 冒頭「Versioning policy
(from v0.4.0 onward)」が持つ。要約:

- **MAJOR** — Python API 破壊 (import path、public 関数シグネチャ、
  scripted 利用者を壊す CLI オプション削除等)。
- **MINOR** — CIF ↔ narrative-CIF 整合性を破壊する変更
  (CIF schema 変更、narrative-CIF drift、CIF 構造 field を伴う新規
  resource type 等)。同 seed でも bite 単位で出力が変わり得る。
- **PATCH** — CIF ↔ narrative-CIF 整合性を保つ変更
  (FHIR-emit-only 修正、locale 表示訂正、CIF / narrative-CIF 構造
  field に触れないデータ品質訂正を含む)。

完全なポリシーと各リリースの判断理由は `CHANGELOG.md` を参照。

## リリース切り出し

Version は 1 箇所に集約: `clinosim/__init__.py::__version__`。
`pyproject.toml` は動的に読み込む (`[tool.hatch.version]`) ので、
PyPI メタデータ / `pip show clinosim` /
`import clinosim; print(clinosim.__version__)` は drift しない。

```bash
# 1. version を bump し changelog を更新
$EDITOR clinosim/__init__.py       # 例: __version__ = "0.3.0"
$EDITOR CHANGELOG.md               # [Unreleased] エントリを [0.3.0] - YYYY-MM-DD の下に移動

# 2. commit + tag
git add clinosim/__init__.py CHANGELOG.md
git commit -m "release: v0.3.0"
git tag -a v0.3.0 -m "clinosim v0.3.0"
git push origin master --tags

# 3. release ワークフローが自動発火:
#    - sdist + wheel をビルド
#    - twine でメタデータ check
#    - 4 データセットプリセットをビルド (us-100, us-1000, jp-100, jp-1000)
#    - wheel + sdist + データセット tarball 付きの GitHub Release を作成
```

リリースノートは `CHANGELOG.md` から自動抽出。

## Changelog

完全な履歴: [Changelog](../development/changelog.ja.md)。
