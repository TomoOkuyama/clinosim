# clinosim を PyPI に公開

release ワークフロー (`.github/workflows/release.yml`) は各
`v*.*.*` タグ push で発火し、wheel + sdist をビルドして GitHub
Release を作成し、同じジョブ内で wheel + sdist を PyPI にアップロード
します。

## PyPI Trusted Publishing (OIDC)

PyPI アップロードは Trusted Publishing を使います。GitHub OIDC で
ワークフローを直接 PyPI に対して認証するので、long-lived token を
リポジトリに保管しません。trusted publisher は
<https://pypi.org/manage/project/clinosim/settings/publishing/> に
以下で登録済み:

- PyPI Project name: `clinosim`
- Owner: `TomoOkuyama`
- Repository name: `clinosim`
- Workflow name: `release.yml`
- Environment name: `release`

`release.yml` では `release` ジョブが `release` environment で動作し
`id-token: write` を持ちます。アップロードは
`Publish to PyPI (Trusted Publishing / OIDC)` step
(`pypa/gh-action-pypi-publish@release/v1`、`packages-dir: dist/`) が
行います。ジョブの environment 名と PyPI 側の登録が一致しないと、PyPI
は token 交換を拒否します。

## リリースを切る

1. `clinosim/__init__.py::__version__` を bump (例: `0.2.0 → 0.3.0`)
2. `CHANGELOG.md` の `## [Unreleased]` 内容を新しい
   `## [X.Y.Z] - YYYY-MM-DD` 見出しの下に移動
3. `git commit -am "release: vX.Y.Z"` + master に push
4. `git tag -a vX.Y.Z -m "clinosim vX.Y.Z"` +
   `git push origin vX.Y.Z`
5. `release.yml` がタグ push で発火し以下を実行:
   - `tag == clinosim.__version__` を検証 (不一致は拒否)
   - sdist + wheel をビルドし `twine check`
   - データセットプリセット (us-100 / us-1000 / jp-100 / jp-1000) を
     `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG=1` でビルド (runner に JP-CLINS
     パッケージが無いため、JP プリセットは旧 5 桁 JLAC10 OID)
   - sdist / wheel / データセット tarball を添付し、CHANGELOG エントリ
     を notes として GitHub Release を公開
   - sdist + wheel を PyPI に公開 (データセット tarball は GitHub
     Release のみ)
   - `dist/*` を workflow artifact としてアップロード (90 日保持)

## Roll-forward-only

PyPI は同一バージョンの再公開を許可しません。バグ入りリリースが出
たら、patch バージョンを bump して再切り出し。同一バージョン番号を
削除+再アップロードしてはいけない。

## 関連ワークフロー

- `nightly.yml` — master に対する reproducibility gate。リリース
  切り出し前に手動実行 (`workflow_dispatch`) して、前回 nightly から
  の silent determinism drift を検出する。
- `jp-clins-lab-compliance-gate.yml` — JP-CLINS 不変条件 check。
  タグ push の前に release commit で green である必要あり。
