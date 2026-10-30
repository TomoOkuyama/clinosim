# `clinosim.dataset` — named-preset dataset builder

## Purpose

`clinosim.dataset` is a thin CLI wrapper that turns a named preset
(`jp-100`, `us-1000`, …) into the corresponding `clinosim simulate`
invocation (`simulate` is the canonical subcommand; `generate` remains
as a deprecation alias). It exists so users can run one short command
instead of remembering the six flags that make a given preset the
reproducible release it is.

Presets are the **versioned public API for dataset releases**. Adding
a new preset is how a maintainer declares a new officially-supported
combination of country / population / seed / date range / output
format.

## Scope

- **In scope**: preset discovery (`list_presets`), preset loading and
  validation (`load_preset`), the `DatasetPreset` value type, argv
  translation (`DatasetPreset.as_simulate_args`), the `clinosim
  dataset list` / `clinosim dataset build <name>` CLI subcommands.
- **Out of scope**: any generation capability of its own — the builder
  delegates to `clinosim generate` by rewriting `sys.argv` and
  invoking `clinosim.simulator.cli.main` in-process, so the generate
  code path stays single-sourced. Adding new simulation features
  never touches this package.

## Public API

```python
from clinosim.dataset import (
    DatasetPreset,          # frozen dataclass: name, description, country,
                            #   population, seed, start, end, format
                            #   + .as_simulate_args(output) -> list[str]
    list_presets,           # (presets_dir=None) -> list[str]
    load_preset,            # (name, presets_dir=None) -> DatasetPreset
    add_dataset_subparser,  # (argparse._SubParsersAction) -> None
    dispatch_dataset,       # (argparse.Namespace) -> int (process exit code)
)
```

CLI usage:

```bash
clinosim dataset list                       # show available presets
clinosim dataset build jp-100 -o ./jp-100   # build one preset
```

`add_dataset_subparser` is called from
`clinosim/simulator/cli.py::main` while it builds the argparse tree; `dispatch_dataset` is
called from the main CLI dispatch path when the user picks the
`dataset` subcommand.

## Determinism

Not applicable at package level. This package emits no records — it
only rewrites argv and delegates. Determinism of the built dataset is
inherited entirely from `clinosim.simulator` (AD-16): a given preset
(fixed country + population + seed + date range + format) produces a
byte-identical cohort on every run.

## Dependencies

- `pyyaml` for loading `datasets/<name>/spec.yaml`.
- `clinosim.simulator.cli.main` (imported lazily inside
  `dispatch_dataset` to avoid a circular import at CLI parse time).
- **No dependency on any `clinosim.modules.*` package.**

## Constants and configuration

- **Preset files** live at `<repo-root>/datasets/<name>/spec.yaml`.
  Each spec must declare 8 required keys (validated in `load_preset`):
  `name`, `description`, `country`, `population`, `seed`, `start`,
  `end`, `format`. A directory whose `spec.yaml` is missing any key
  raises `ValueError` at load time.
- **Directory name must match `name`** — a preset directory called
  `jp-100/` whose `spec.yaml` declares `name: jp-1000` is a
  configuration error and raises at load time.
- **Preset root discovery** — `_presets_dir()` returns
  `clinosim/dataset/presets` when it exists (built wheels copy the
  repo-root `datasets/` there via the pyproject `force-include`,
  #2204), else the repo-root `datasets/` of a source checkout. Both
  `list_presets` and `load_preset` accept a `presets_dir` override for
  tests.
- **Shipped presets** (as of writing): `jp-100`, `jp-1000`, `us-100`,
  `us-1000`. See [`datasets/README.md`](../../datasets/README.md) for
  the canonical list and per-preset descriptions.

## Directory contents

```
clinosim/dataset/
  __init__.py           entire package — DatasetPreset dataclass,
                        list_presets, load_preset, add_dataset_subparser,
                        dispatch_dataset (~190 lines)
```

Single-file package. Presets themselves live at `datasets/` in the
repo root, not inside `clinosim/`.

## Testing

```bash
pytest tests/unit -k dataset -q
```

Two test files reference `clinosim.dataset`. Coverage focuses on
preset YAML validation (`load_preset` error paths) and CLI wiring
(`add_dataset_subparser` registering the expected subcommands with
the expected required arguments).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
