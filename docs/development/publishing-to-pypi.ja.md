# clinosim を PyPI に公開

release ワークフロー (`.github/workflows/release.yml`) は各
`v*.*.*` タグ push で wheel + sdist をビルドし GitHub Release を
作成しますが、実際の PyPI アップロード step はメンテナが公開認証情報
を設定するまで意図的にコメントアウトされています。

サポートされる 2 経路 — 1 つを選び `release.yml` のインラインコメン
トに従って編集。

## Path A — PyPI Trusted Publisher (推奨、シークレット不要)

PyPI trusted publishing は GitHub OIDC でワークフローを直接 PyPI に
対して認証するので、long-lived token をリポジトリシークレットとして
保管する必要がありません。これは PyPI 推奨の最新経路。

### 初回設定 (メンテナ)

1. PyPI にパッケージ名を登録: <https://pypi.org/manage/projects/>
   → "Register a new project" → 名前 `clinosim`。初回のみ。
2. <https://pypi.org/manage/account/publishing/> で "Pending Trusted
   Publisher" を以下で追加:
   - PyPI Project name: `clinosim`
   - Owner: `TomoOkuyama`
   - Repository name: `clinosim`
   - Workflow name: `release.yml`
   - Environment name: 空欄 (必須承認 step を入れるなら `pypi`)
3. `.github/workflows/release.yml` を編集:
   - `permissions:` の下で `id-token: write` をアンコメント
   - ジョブ末尾の
     `- name: Publish to PyPI (trusted publishing)` step をアンコメント

### 検証

- pre-release タグ (例: `v0.2.0rc1`) を切って push、release job を確認
- 成功時に `pip install clinosim==0.2.0rc1` が動作するはず

## Path B — API token (シンプル、シークレット使用)

対象 org で trusted publishing が使用不可の場合、リポジトリシークレット
に保管した API token にフォールバック。

### 初回設定

1. PyPI でプロジェクト登録 (A step 1 と同じ)
2. `clinosim` プロジェクトのみに scope した API token を
   <https://pypi.org/manage/account/token/> で作成
3. Settings → Secrets and variables → Actions で `PYPI_API_TOKEN`
   としてリポジトリに追加
4. `.github/workflows/release.yml` を編集:
   `- name: Publish to PyPI (token)` step をアンコメント

## リリースを切る (両経路共通)

1. `clinosim/__init__.py::__version__` を bump (例: `0.2.0 → 0.3.0`)
2. `CHANGELOG.md` の `## [Unreleased]` 内容を新しい
   `## [X.Y.Z] - YYYY-MM-DD` 見出しの下に移動
3. `git commit -am "release: vX.Y.Z"` + master に push
4. `git tag -a vX.Y.Z -m "clinosim vX.Y.Z"` +
   `git push origin vX.Y.Z`
5. `release.yml` がタグ push で発火し以下を実行:
   - `tag == clinosim.__version__` を検証 (不一致は拒否)
   - sdist + wheel + データセットプリセット (us-100 / us-1000 /
     jp-100 / jp-1000) をビルド
   - アーティファクトと CHANGELOG エントリを notes として GitHub
     Release を公開
   - (上記 A または B 有効化後) PyPI に公開

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
