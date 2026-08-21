# `clinosim.modules.triage` — ED triage sampling (JTAS / ESI)

## Purpose

Tier 1 #3 α-min-2 always-on AD-55 Module. On every ED (emergency)
encounter, samples a triage level (JTAS in JP / ESI in US), an
arrival mode (walk-in / ambulance / other), and an acuity score,
then writes the result to `EncounterRecord.triage_data`.
Non-emergency encounters are a no-op.

## Scope

- **In scope**: `triage_enricher` (POST_ENCOUNTER order=93,
  ED-only); `pick_triage_level(severity, level_system, rng)` —
  YAML weight table by (severity × system); `pick_arrival_mode(severity, rng)`;
  `load_triage_protocols()` YAML loader with 6-layer
  `_validate_triage_protocols` (silent-no-op defense).
- **Out of scope**: encounter routing / class emission (in
  [`clinosim.modules.encounter`](../encounter/README.md)), FHIR
  `Encounter.class` / `type` / `priority` emission (in
  [`clinosim.modules.output`](../output/README.md)), ED narrative
  document ([`clinosim.modules.document.narrative`](../document/narrative/README.md)
  — the ED_TRIAGE_NOTE stub is emitted by the
  [`document`](../document/README.md) module in a later
  POST_ENCOUNTER pass).

## Public API

```python
from clinosim.modules.triage import TriageData
from clinosim.modules.triage.engine import (
    triage_enricher,             # POST_ENCOUNTER enricher entry
    pick_triage_level,           # (severity, level_system, rng) -> str
    pick_arrival_mode,           # (severity, rng) -> str
    load_triage_protocols,       # () -> dict (@lru_cache, 6-layer validated)
)
```

## Determinism

- Sub-seed offset `0x5452` (`"TR"`, Tier 1 #3 α-min-2 PR1) —
  registered in [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["triage"]`.
- Per-encounter RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — main
  patient RNG untouched (AD-16).

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.triage` — `TriageData`.
- `clinosim.types.encounter` — `Encounter` (encounter_type gate).
- `yaml`, `numpy`.

## Constants and configuration

- [`reference_data/triage_protocols.yaml`](reference_data/triage_protocols.yaml)
  — per (level_system × severity) tier weights + arrival-mode
  probabilities. Import-time `_validate_triage_protocols` runs the
  standard 6-layer defense (empty top / missing keys / per-severity
  weights / forward+reverse coverage vs JTAS / ESI canonical
  levels / type checks).
- Level systems: `jtas` (JP), `esi` (US), dispatched via country
  at emit time.

## Directory contents

```
clinosim/modules/triage/
  __init__.py                        re-exports TriageData
  engine.py                          triage_enricher + pick_* helpers + loader + 6-layer validator
  audit.py                           AD-60 audit plug-in (triage-tier canonical constants + firing proof)
  reference_data/
    triage_protocols.yaml            per (system × severity) tier + arrival weights
```

The module has **no `enricher.py`** — the enricher entry point lives
in `engine.py` and is registered directly.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L303-316`):

- `name="triage"`, `stage=POST_ENCOUNTER`, `order=93`,
  `enabled=lambda c: True`.
- Runs before `nursing_assignment` (order=94) and `document`
  (order=95). ED-only inside the enricher body (non-ED encounters
  are skipped).
- The `audit.py` module registers with the AD-60 audit framework at
  import time (`register_audit_module`).

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:311`](../../simulator/enrichers.py) | POST_ENCOUNTER order=93 registration. |
| Audit registry | [`clinosim/modules/triage/audit.py`](audit.py) | AD-60 audit plug-in — canonical-constants cross-check + firing proof. |
| Document module | [`clinosim/modules/document/audit.py`](../document/audit.py) | Cross-references triage's canonical tier set. |
| FHIR encounter builder | [`clinosim/modules/output/fhir_r4/encounters/`](../output/fhir_r4/encounters/) | Reads `EncounterRecord.triage_data` for `Encounter.priority`. |

## Testing

```bash
pytest tests/unit -k triage -q
clinosim audit run -d <cohort_dir> --module triage
```

Individual files:

- [`tests/unit/modules/triage/test_engine.py`](../../../tests/unit/modules/triage/test_engine.py)
  — enricher gate, sampling determinism, ED-only behaviour.
- [`tests/unit/modules/triage/test_triage_protocols_yaml.py`](../../../tests/unit/modules/triage/test_triage_protocols_yaml.py)
  — 6-layer validator coverage.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
