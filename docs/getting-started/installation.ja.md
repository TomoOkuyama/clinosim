# インストール

## ユーザーとして (推奨)

PyPI 公開後は、パッケージ版を直接インストール:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install clinosim                # (PyPI アップロード準備中 — 下の代替参照)
clinosim --help
```

**PyPI 公開前の代替** — GitHub から直接インストール:

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
- 主要依存: numpy / scipy / pydantic / pyyaml / httpx
- **オプション:**
    - ローカル LLM narrative 生成用 Ollama
    - CIF Parquet 出力: `pip install "clinosim[parquet]"`
    - `mkdocs serve` でこの文書サイトをローカルビルド:
      `pip install "clinosim[docs]"`

## Sanity check

```bash
clinosim --help                                 # トップレベル CLI バナー
clinosim dataset list                           # 同梱プリセット 4 件
clinosim dataset build jp-100 --output ./test   # ~30 秒の smoke ビルド
```
