# Installation

## As a user (recommended)

Install the packaged version from PyPI:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install clinosim
clinosim --help
```

To track unreleased changes, install straight from GitHub:

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
- Main dependencies: numpy, scipy, pydantic, pyyaml, httpx, mpmath
- **JP generation (`--country JP`)** needs the JP-CLINS FHIR package
  (`clinical-information-sharing#1.13.0` + `jpfhir-terminology#2.2606.0`),
  either installed in the `fhir` CLI cache (`~/.fhir/packages/`) or pointed
  to by `CLINOSIM_JP_CLINS_PKG_DIR`. Without it a JP run exits with an
  error unless you pass `--allow-legacy` (or set
  `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG=1`), which emits legacy 5-digit
  JLAC10 codes that are not JP-CLINS compliant. See
  [JP-CLINS](../jp-clins.md).
- **Optional:**
    - Ollama for local LLM narrative generation
    - `pip install "clinosim[parquet]"` for CIF Parquet export
    - `pip install "clinosim[docs]"` to build this documentation site
      locally with `mkdocs serve`

## Sanity check

The dataset presets live in `datasets/` at the repository root, so
`clinosim dataset` needs a source checkout (developer install).

```bash
clinosim --help                                 # top-level CLI banner
clinosim dataset list                           # 4 shipped presets
clinosim dataset build jp-100 --output ./test   # ~30 s smoke build
```
