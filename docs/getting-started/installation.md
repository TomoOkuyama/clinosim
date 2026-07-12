# Installation

## As a user (recommended)

Once released to PyPI, install the packaged version directly:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install clinosim                # (PyPI upload pending — see fallback below)
clinosim --help
```

**Pre-PyPI fallback** — install straight from GitHub:

```bash
pip install "git+https://github.com/TomoOkuyama/clinosim.git@master"
clinosim --help
```

## As a developer (editable install with dev deps)

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Requirements

- Python 3.11+
- Main dependencies: numpy, scipy, pydantic, pyyaml, httpx
- **Optional:**
    - Ollama for local LLM narrative generation
    - `pip install "clinosim[parquet]"` for CIF Parquet export
    - `pip install "clinosim[docs]"` to build this documentation site
      locally with `mkdocs serve`

## Sanity check

```bash
clinosim --help                                 # top-level CLI banner
clinosim dataset list                           # 4 shipped presets
clinosim dataset build jp-100 --output ./test   # ~30 s smoke build
```
