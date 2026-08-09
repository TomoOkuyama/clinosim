# `clinosim.modules.antibiotic` — empirical antibiotic dosing

## Purpose

Always-on Module (AD-55) that generates **empirical antibiotic
regimens** for HAI events per IDSA guidelines. Consumes
`extensions["hai"]` from `clinosim.modules.hai` and writes to three
downstream slots: `record.orders` (MedicationRequest),
`record.medication_administrations` (MAR), and
`extensions["antibiotic"]`.

## Scope

- **In scope**: empirical regimen materialisation for CLABSI, CAUTI,
  VAP (organism-agnostic first-line therapy per IDSA / ATS guidelines),
  MAR generation for each dose, cross-check with existing FHIR
  medication builder.
- **Out of scope**: culture-directed narrow-spectrum switch (Phase 3b-3
  follow-up), susceptibility (S / I / R) modelling (Phase 3b-2
  follow-up), decay / duration titration (Phase 3b-4), FHIR
  serialisation (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.antibiotic import (
    enrich_antibiotic,                 # AD-56 post_records enricher entry
    empirical_regimen_for_hai,         # (hai_type) -> AntibioticRegimen
)
```

The enricher is registered automatically at import time (POST_ENCOUNTER
stage, order 85, always-on).

## Regimens

| HAI type | Regimen | Duration | Reference |
|---|---|---|---|
| CLABSI | Vancomycin q12h + Piperacillin/Tazobactam q6h | 14 days | IDSA 2009 (Mermel LA et al., CID 49:1-45) |
| CAUTI | Ceftriaxone q24h | 7 days | IDSA 2009 (Hooton TM et al., CID 50:625-63) |
| VAP | Vancomycin q12h + Piperacillin/Tazobactam q6h | 7 days | IDSA/ATS 2016 (Kalil AC et al., CID 63:e61-e111) |

## Dependencies

- `clinosim.types.antibiotic` — `AntibioticRegimen`.
- `clinosim.types.encounter` — `Order`, `OrderType`,
  `MedicationAdministration`.
- `clinosim.types.hai` — `HAIEvent` (via `extensions["hai"]`).
- `clinosim.modules.hai` — `HAI_TYPES` (YAML cross-validation).
- `clinosim.modules.observation.microbiology` —
  `antibiotic_loinc_lookup()`, the single source of truth for antibiotic
  LOINC codes.
- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.simulator.helpers` (formerly `seeding`) —
  `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142`, `derive_sub_seed`.
- `clinosim.codes.data.{rxnorm,yj}` — drug display lookups.
- `clinosim.locale.{us,jp}.code_mapping_drug` — drug key → RxNorm / YJ.

## Constants and configuration

- `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142` (`"AB"`) — sub-seed
  offset per AD-16 determinism convention.
- Regimen definitions live inline in `engine.py`. Drug key → LOINC /
  RxNorm / YJ resolution goes through the shared code registry.
- `ABX_REGIMEN_ID_PREFIX` and `ABX_NARROW_SUFFIX` (short by design to
  stay under FHIR R4's 64-char MedicationRequest.id limit; see
  `tests/unit/test_antibiotic_id_length.py`).

## Directory contents

```
clinosim/modules/antibiotic/
  __init__.py       public API
  engine.py         pure functions (regimen selection, MAR expansion)
  enricher.py       AD-56 post_records enricher (enrich_antibiotic)
  audit.py          per-module audit spec
```

## Design principles

- **AD-55 always-on** (never gated by `enabled` flag) — clinically
  impossible to have HAI without antibiotic; matches device / hai
  cascade pattern.
- **AD-56** builder + enricher registry.
- **AD-16 deterministic** — per-patient sub-seed via `derive_sub_seed`.
- **AD-57 BNP-pattern surgical** — physiology state is not mutated;
  observation-time formula only.
- **AD-32 discipline** — future-onset HAI events are pre-skipped inside
  the enricher to prevent orphan Order / MAR after inpatient
  truncation.

## Testing

```bash
pytest tests/unit -k antibiotic -q
pytest tests/integration -k antibiotic -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
