# `clinosim.dataset` — named-preset dataset builder

## Purpose

`clinosim.dataset` is a thin CLI wrapper that turns a named preset (e.g.
`jp-100`, `us-1000`) into the corresponding `clinosim generate`
invocation. It exists so users can run one short command instead of
having to remember the six flags that make a given preset the
reproducible release it is.

Presets are the **versioned public API for dataset releases**. Adding a
new preset is how a maintainer declares a new officially-supported
combination of country / population / seed / date range / output format.

## Scope

- **In scope**: preset discovery (`list_presets`), preset loading and
  validation (`load_preset`), the `clinosim dataset build <name>` CLI
  subcommand.
- **Out of scope**: any generation capability of its own — the builder
  delegates to `clinosim generate` via the same `SimulatorConfig`
  pipeline. Adding new simulation features never touches this package.

## Public API

```python
from clinosim.dataset import (
    list_presets,           # () -> list[str]
    load_preset,            # (name) -> PresetSpec
    add_dataset_subparser,  # (argparse.ArgumentParser) -> None
    dispatch_dataset,       # (argparse.Namespace) -> int
)
```

CLI usage:

```bash
clinosim dataset list                     # show available presets
clinosim dataset build jp-100 --output ./jp-100-out
```

## Dependencies

- `pyyaml` for loading preset YAMLs.
- `clinosim.simulator` (via `clinosim generate`) for the actual run.
- No dependency on any `clinosim.modules.*` package.

## Constants and configuration

- Preset files live at `<repo-root>/datasets/<name>/spec.yaml`. Each
  spec declares:
  - `country`: `US` or `JP`
  - `population`: integer patient count
  - `seed`: integer RNG seed
  - `start` / `end`: ISO date range
  - `output_format`: `cif` / `fhir` / `csv` / combinations
- See [`datasets/README.md`](../../datasets/README.md) for the full
  list of shipped presets.

## Directory contents

```
clinosim/dataset/
  __init__.py           public API + CLI
```

Single-file package. The presets themselves live at `datasets/` in
the repo root, not inside `clinosim/`.

## Testing

```bash
pytest tests/unit -k dataset -q
```

Approximately 1 test file references `clinosim.dataset`. Coverage
focuses on preset-YAML validation.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
