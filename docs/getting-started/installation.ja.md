# インストール

## ユーザーとして (推奨)

PyPI からパッケージ版をインストール:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install clinosim
clinosim --help
```

未リリースの変更を追う場合は GitHub から直接インストール:

```bash
pip install "git+https://github.com/TomoOkuyama/clinosim.git@master"
clinosim --help
```

## 開発者として (dev deps 付き editable install)

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## 要件

- Python 3.11+
- 主要依存: numpy / scipy / pydantic / pyyaml / httpx / mpmath
- **JP 生成 (`--country JP`)** には JP-CLINS FHIR パッケージ
  (`clinical-information-sharing#1.13.0` + `jpfhir-terminology#2.2606.0`)
  が必要。`fhir` CLI キャッシュ (`~/.fhir/packages/`) に導入するか、
  `CLINOSIM_JP_CLINS_PKG_DIR` で指定する。無い場合、JP 実行は
  `--allow-legacy` (または `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG=1`) を
  渡さない限りエラー終了し、渡した場合は JP-CLINS 非準拠の旧 5 桁
  JLAC10 コードを出力する。[JP-CLINS](../jp-clins.ja.md) 参照。
- **オプション:**
    - ローカル LLM narrative 生成用 Ollama
    - CIF Parquet 出力: `pip install "clinosim[parquet]"`
    - `mkdocs serve` でこの文書サイトをローカルビルド:
      `pip install "clinosim[docs]"`

## Sanity check

データセットプリセットはリポジトリ直下の `datasets/` にあるため、
`clinosim dataset` にはソースチェックアウト (開発者インストール) が
必要。

```bash
clinosim --help                                 # トップレベル CLI バナー
clinosim dataset list                           # 同梱プリセット 4 件
clinosim dataset build jp-100 --output ./test   # ~30 秒の smoke ビルド
```
