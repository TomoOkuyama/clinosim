# バージョニングとリリース

clinosim は [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
に従います:

- **MAJOR** — 非互換な API / CIF / FHIR スキーマ変更。
- **MINOR** — 後方互換な機能追加 (新モジュール、新リソース型、追加
  locale サポート)。同 seed でもバイト単位で出力が変わり得る。
- **PATCH** — 後方互換なバグ修正 + CIF/FHIR スキーマを保つデータ
  品質訂正。**同 MINOR line 内の PATCH リリースでは、同 seed に対
  するバイト同一出力が hard guarantee。**

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
