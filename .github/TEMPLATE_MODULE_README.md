# `clinosim.modules.<name>` — [one-line English description]

> **How to use this template.** Copy to
> `clinosim/modules/<name>/README.md` (+ a Japanese sibling
> `README.ja.md`), then fill in every placeholder in `<angle brackets>`
> and drop sections that genuinely do not apply (marked "(optional)"
> below). The canonical 11-section structure below is what
> `MODULES.md` promises to readers; every existing module README
> follows it. Working reference examples:
> - `clinosim/modules/allergy/README.md` — enricher module with
>   YAML-driven reference data and a POST_POPULATION wiring.
> - `clinosim/modules/hai/README.md` — enricher module with an AD-60
>   audit plug-in.
> - `clinosim/modules/sdoh/README.md` — data-only variant (no
>   enricher, no `ENRICHER_SEED_OFFSETS` entry).
> - `clinosim/modules/observation/README.md` — simulation-layer
>   module (multiple enricher entries, deep public API).

## Purpose

<2-3 sentences: what does this module own, what problem does it
solve, why is it a separate module. Name the CIF field(s) it writes
so a reader can grep for downstream consumers.>

## Scope

- **In scope**: <what this module is responsible for — constants,
  rates, data files, per-patient decisions. List the specific fields
  it writes on `PersonRecord` / `Encounter` / etc.>
- **Out of scope**: <adjacent responsibilities that live elsewhere.
  Link the sibling module(s) so a reader knows where to look —
  e.g. FHIR serialisation
  ([`output`](../output/README.md)), code-display lookups
  ([`codes`](../../codes/)), locale text
  ([`locale`](../../locale/README.md)).>

## Public API

`__init__.py` should re-export the module's stable surface (MOD-1).
Show the exact imports downstream code is expected to use, with a
one-line comment per symbol:

```python
from clinosim.modules.<name> import <Type1>, <Type2>
from clinosim.modules.<name>.engine import (
    <public_function>,       # <one-line role>
    <PUBLIC_CONSTANT>,       # <value + meaning>
)
```

Do NOT list internal helpers (leading underscore). If the module has
an audit plug-in, list its public constants here too — canonical
constants imported by `audit.py` are part of the public surface.

## Determinism

- **Sub-seed offset**: `<0xNNNN>` (`"XX"`) registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["<name>"]`. Follow the 16-bit hex-ASCII
  convention (e.g. `0x4142 == "AB"`). If the module is data-only
  (no enricher), delete the offset entry and note "no sub-seed —
  data-only variant" here.
- **Per-patient RNG**:
  `derive_sub_seed(master_seed, offset, person_id)` — same patient
  always samples the same decision, and the main population RNG
  stream is NOT consumed (AD-16).
- **Probability normalisation**: any YAML-sourced probability
  distribution goes through
  `normalize_probabilities(..., fallback="raise")` so a
  pre-normalisation drift raises rather than silently biasing the
  draw (PR #102 silent-no-op defense triplet).
- <Any status / secondary distributions drawn from the same
  per-patient stream — note the ordering so the reader can predict
  which decision consumes RNG steps in what order.>

## Dependencies

- `clinosim.modules._shared` — `<what you use>` (typically
  `normalize_probabilities` and/or `is_jp`).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.<name>` — `<Type1>`, `<Type2>`.
- `clinosim.codes.loader` — `<what you use>` (usually `_load_system`
  for import-time SNOMED / LOINC membership checks).
- `numpy` — `np.random.Generator`.
- `yaml` — YAML parser.
- <Sibling `clinosim.modules.*` imports, one per line, with the
  specific function or constant imported and the reason. Prefer
  keeping the graph shallow — each new inter-module edge should be
  justified in a code comment.>

Each module MAY depend only on what is listed here (`AGENTS.md`
"Module independence"). If you add a new import, add a row here in
the same PR.

## Constants and configuration

- **Module-level constants** (all in `engine.py`):
  - `<CONSTANT_NAME> = <value>` — <what it controls, why this value,
    which reference / benchmark it matches>.
- **Reference YAML**:
  [`reference_data/<file>.yaml`](reference_data/<file>.yaml) —
  <schema: required keys, cross-references to other yaml files,
  membership constraints validated at import time>.
- **Import-time validator** (`_validate_<name>`): rejects
  <enumerate the classes of drift it catches — orphan keys,
  key drift vs canonical constants, missing required entry fields,
  out-of-range probabilities, code memberships against
  `clinosim/codes/data/*.yaml`>. This is the PR-90 / PR-102
  silent-no-op defense layer for this module.

## Directory contents

```
clinosim/modules/<name>/
  __init__.py               re-exports the public API (MOD-1: never empty)
  engine.py                 loader / validator / <public functions>
  audit.py                  (optional) AD-60 audit plug-in
  reference_data/
    <file>.yaml             <schema summary>
  README.md                 this file
  README.ja.md              Japanese sibling
```

### Canonical module-head boilerplate

```python
from functools import lru_cache
from pathlib import Path

import yaml

# Add if you sample from a normalised distribution:
# from clinosim.modules._shared import normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"        # if you ship reference_data/
_LOCALE = _HERE.parents[1] / "locale"      # if you read from clinosim/locale/


def _validate(data: dict) -> None:
    """Fail-loud validator — raises on any orphan / drifted key.

    Example cross-check pattern (customise for your data):

        valid_keys = set(data.get("canonical_section") or {})
        for item_id, item in (data.get("items") or {}).items():
            ref_key = (item or {}).get("ref_field")
            if ref_key and ref_key not in valid_keys:
                raise ValueError(
                    f"<file>.yaml: item {item_id!r} references unknown key "
                    f"{ref_key!r}; expected one of {sorted(valid_keys)}"
                )
    """
    raise NotImplementedError(
        "Implement _validate: add canonical-constants cross-checks "
        "against your YAML keys. See docstring example. MUST raise "
        "ValueError on unknown keys (PR-90 silent-no-op defense)."
    )


@lru_cache(maxsize=1)                       # no-param loader → maxsize=1
def load_reference() -> dict:
    with open(_REF_DIR / "<file>.yaml") as f:
        data = yaml.safe_load(f) or {}
    _validate(data)                         # PR-90 defense: run at load time
    return data


@lru_cache(maxsize=2)                       # country-param loader → maxsize=2
def load_rates(country: str) -> dict:
    if str(country).upper() not in {"US", "JP"}:
        return {}                            # no-op for unsupported countries
    with open(_LOCALE / country.lower() / "rates.yaml") as f:
        return yaml.safe_load(f) or {}
```

**Locale loader variants.** Modules whose data covers both US and JP
use the `{}` no-op pattern above. Modules that always have data and
intentionally default unsupported countries to US use the
`key = "jp" if str(country).upper() == "JP" else "us"` variant (see
`code_status/engine.py`, `family_history/engine.py`,
`immunization/engine.py`). Pick based on data availability.

Cache-size convention (PR-A / PR-B1):
`load_X()` no-param → `maxsize=1`; `load_X(country)` → `maxsize=2`
(US + JP). Higher `maxsize` on a country-only loader is a review
smell — check `docs/CONTRIBUTING-modules.md` for the exact rule.

## Enricher wiring

**If this module registers an enricher**, describe the wiring; if
not, delete this section and say "no enricher — data-only variant"
in Purpose instead.

- Registered in
  [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
  under `register_builtin_enrichers`:
  - `name="<name>"`, `stage=<POST_POPULATION | POST_ENCOUNTER | POST_RECORDS>`,
    `order=<N>`, `enabled=<gate>`.
- **Stage rationale**: <why this stage — what upstream state it
  reads, what downstream consumers depend on it firing before them>.
- **Order rationale**: <why this order relative to sibling
  enrichers at the same stage — e.g. "runs after `device` so
  `record.icu_transferred` is populated">.

## Output surfaces (consumers)

Who reads what this module writes:

| Consumer | Where | Role |
|---|---|---|
| FHIR `<ResourceType>` builder | [`clinosim/modules/output/fhir_r4/<domain>/<file>.py`](../output/fhir_r4/<domain>/<file>.py) | <what it reads and emits> |
| <sibling module> | <path> | <what it reads> |
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) | Stage/order registration. |

Impact tier hint:
- **core** — main simulation loop or all encounters
- **medium** — specific feature (a single FHIR builder, a specific
  lab path, etc.)
- **guard** — test-only (no runtime impact)

Find fresh consumers with:

```bash
grep -rln "from clinosim.modules.<name>\b\|import clinosim.modules.<name>\b" clinosim/ tests/
```

Re-run whenever the public API changes.

## Testing

```bash
pytest tests/unit -k <name> -q                    # loader + validator + engine
pytest tests/unit/output -k fhir_<related> -q     # FHIR emission (if any)
```

Individual files worth naming here (add each test path when you add
its target):

- [`tests/unit/modules/<name>/test_engine.py`](../../../tests/unit/modules/<name>/test_engine.py)
  — determinism, gate rates, distribution shape.
- [`tests/unit/modules/<name>/test_<yaml>_yaml.py`](../../../tests/unit/modules/<name>/test_<yaml>_yaml.py)
  — validator coverage.
- [`tests/unit/output/test_fhir_<related>.py`](../../../tests/unit/output/test_fhir_<related>.py)
  — FHIR emission end-to-end (if this module surfaces a FHIR
  resource).
- [`tests/unit/modules/<name>/test_audit.py`](../../../tests/unit/modules/<name>/test_audit.py)
  — AD-60 audit plug-in coverage (if the module ships one).

Audit plug-in (AD-60): a module-specific verification plug-in lives
at `clinosim/modules/<name>/audit.py` and registers a
`ModuleAuditSpec`. Available checks:
`canonical_constants`, `yaml_keys_to_validate`,
`structural_obs_codes`, `clinical_acceptance`, `lift_firing_proof`.
See `clinosim/modules/hai/audit.py` for the canonical example. Run
with `clinosim audit run -d <cohort_dir> --module <name>`.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).

---

**Related documentation**

- [`AGENTS.md`](../../../AGENTS.md) — AI-agent conventions +
  invariants. `CLAUDE.md` is a thin pointer to this file.
- [`MODULES.md`](../../../MODULES.md) — module map that promises the
  canonical 11-section structure this template implements.
- [`SCENARIO_FLAGS.md`](../../../SCENARIO_FLAGS.md) — if this module
  handles a scenario or medication flag routed through
  `derive_lab_values`.
- [`docs/CONTRIBUTING-modules.md`](../../../docs/CONTRIBUTING-modules.md) —
  module-author playbook + PR verification guide + `@lru_cache`
  maxsize rules + probability-sampling convention.
- Applicable ADRs in
  [`docs/architecture/adr-history.md`](../../../docs/architecture/adr-history.md)
  (typically AD-16 determinism, AD-55 enricher patterns, AD-56
  registry, AD-59 per-order sub-rng, AD-60 audit; pick the ones
  that actually apply).
