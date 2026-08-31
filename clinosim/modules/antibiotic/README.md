# `clinosim.modules.antibiotic` — HAI empirical + narrow antibiotic regimens

## Purpose

Third module in the always-on HAI cascade
([`device`](../device/README.md) → [`hai`](../hai/README.md) → this
module → observation microbiology emitter). Consumes
`extensions["hai"]` and, for each HAI event whose onset is on / before
the snapshot, materialises the IDSA 2009 / 2016 empirical regimen
plus (PR3b-3 Pass 2) the S/I/R-driven narrow / de-escalation
regimen. Every regimen becomes one `Order(MEDICATION)` +
N `MedicationAdministration` records that the existing
`fhir_r4/medications/medications.py` builder emits without a new builder.

## Scope

- **In scope**: `ANTIBIOTIC_DRUGS` canonical drug-key dict (single
  source of truth for antibiotic names — YAML loaders validate
  drug_key strings against it at import); `load_hai_empirical` +
  `load_narrow_ladder` (both YAML-loader with per-validator
  6-layer defense); `build_regimens` + `generate_mar_doses`;
  `_drug_slug` + `_check_fhir_id_length` (FHIR id-length guard —
  Issue-tracked contract that FHIR ids stay under `id` cardinality
  limits); the POST_ENCOUNTER `enrich_antibiotic` enricher with
  same-enricher Pass 2 for S/I/R-driven narrowing (`NarrowOutcome`
  enum + `select_narrow_target` + `narrow_outcome` +
  `narrow_duration_days`); AD-32 future-onset skip
  (pre-skips HAI events that would be truncated post-POST_ENCOUNTER,
  preventing orphan Order/MAR).
- **In scope (audit)**: [`audit.py`](audit.py) — second per-module
  AD-60 audit plug-in. lift_firing_proof exercises
  `enrich_antibiotic` on a synthetic CAUTI HAIEvent (expects 1
  regimen with `drug_key="ceftriaxone"` + `duration_days=7`, one
  MEDICATION Order, seven MAR entries); PR3b-2 extension adds an
  `antibiogram_firing_proof` (synthetic CLABSI + S. aureus HAIEvent
  → 6 susceptibility rows with vancomycin always-S sentinel and a
  cefazolin non-degenerate probe).
- **Out of scope**: HAI event sampling
  ([`hai`](../hai/README.md)); microbiology culture emission
  ([`observation.microbiology`](../observation/microbiology.py));
  FHIR MedicationRequest / MedicationAdministration serialisation
  ([`output/fhir_r4/medications/`](../output/fhir_r4/medications/README.md));
  narrow-target dose / frequency defaults themselves — those live
  in [`_narrow_dose_defaults.py`](_narrow_dose_defaults.py).

## Public API

```python
from clinosim.modules.antibiotic import (
    ANTIBIOTIC_DRUGS,                    # canonical {drug_key: {"name": display}}
    ANTIBIOTIC_LOINC_LOOKUP,             # re-exported from observation.microbiology
)
from clinosim.modules.antibiotic.engine import (
    FREQ_PER_DAY,                        # dose-frequency → doses/day table
    load_hai_empirical,                  # () -> dict[hai_type, regimen] (@lru_cache)
    load_narrow_ladder,                  # () -> dict[hai_type, {organism_snomed: [drug_key, ...]}] (@lru_cache)
    build_regimens,                      # (hai_event, empirical_map, patient_id) -> list[AntibioticRegimen]
    generate_mar_doses,                  # (regimen, admission_time) -> list[MedicationAdministration]
    NarrowOutcome,                       # Enum {SWITCH, ELIMINATION, NO_CHANGE}
    select_narrow_target,                # (hai_type, organism_snomed, susceptibilities) -> drug_key | None
    narrow_outcome,                      # (empirical, target) -> NarrowOutcome
    narrow_duration_days,                # (hai_type, drug_key) -> int
)
from clinosim.modules.antibiotic.enricher import enrich_antibiotic  # POST_ENCOUNTER entry
```

## Determinism

- Sub-seed offset `0x4142` (`"AB"`, PR3b-1) — registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["antibiotic"]`.
- PR3b-3 narrowing has **no new RNG** — `select_narrow_target` is
  pure over already-determined susceptibilities from the microbiology
  layer.
- AD-32 future-onset skip: HAI events with onset after the snapshot
  are pre-skipped so the antibiotic emit does not create orphan
  orders when the HAI truncation runs post-POST_ENCOUNTER.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.modules.observation.microbiology` —
  `antibiotic_loinc_lookup` (re-exported as
  `ANTIBIOTIC_LOINC_LOOKUP`).
- `clinosim.modules.antibiotic._narrow_dose_defaults` — per-drug
  narrow-target dose + frequency defaults.
- `clinosim.audit.registry` (via `audit.py`) — AD-60 audit
  registration.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`.
- `clinosim.types.encounter` — `AntibioticRegimen`,
  `MedicationAdministration`, `Order`, `OrderType`, `OrderStatus`,
  plus the microbiology types.
- `numpy`, `yaml`.

## Constants and configuration

- **`ANTIBIOTIC_DRUGS`** (`__init__.py`) — canonical drug-key dict.
  Keys are lowercase snake_case (`vancomycin`, `piperacillin_tazobactam`,
  `ceftriaxone`, `ampicillin`, `cefazolin`, `gentamicin`,
  `meropenem`, `ciprofloxacin`, `trimethoprim_sulfamethoxazole`,
  `cefepime`, …) matching the microbiology antibiotics section +
  `ANTIBIOTIC_LOINC_LOOKUP`. The YAML loaders validate every
  `drug_key` string against this dict at import (PR-90 lesson).
- **`FREQ_PER_DAY`** (`engine.py`) — dose frequency string →
  doses/day (`"q24h" → 1`, `"q12h" → 2`, `"q8h" → 3`, `"q6h" → 4`)
  consumed by `generate_mar_doses`.
- **Reference YAMLs**:
  - [`reference_data/hai_empirical.yaml`](reference_data/hai_empirical.yaml)
    — IDSA 2009/2016 empirical regimen per HAI type. Loader
    `_validate_hai_empirical` cross-validates every drug_key against
    `ANTIBIOTIC_DRUGS` (3-way with `HAI_TYPES` +
    `ANTIBIOTIC_LOINC_LOOKUP`).
  - [`reference_data/narrow_ladder.yaml`](reference_data/narrow_ladder.yaml)
    — per (HAI type, organism SNOMED) narrow target ladder. Loader
    `_validate_narrow_ladder` cross-validates 3-way against
    `HAI_TYPES` + `hai_antibiogram.yaml` + `ANTIBIOTIC_DRUGS`.
- **Narrow-target dose defaults** ([`_narrow_dose_defaults.py`](_narrow_dose_defaults.py),
  Issue #637) — per-drug (dose_string, frequency) pair returned by
  `_narrow_dose_frequency` in the enricher.
- **FHIR ID prefixes** (`engine.py`) — `ABX_REGIMEN_ID_PREFIX`,
  `ABX_ORDER_REQ_PREFIX`, `ABX_ORDER_ID_PREFIX`, `ABX_NARROW_SUFFIX`.
  `_check_fhir_id_length` enforces the FHIR `id` cardinality limit
  at every emission site (Issue-tracked; `_DRUG_SLUG_OVERRIDES`
  handles the drug names that would otherwise blow the length
  budget).
- **`AntibioticRegimen.discontinuation_datetime`** — forward-compat
  slot populated by PR3b-3 narrowing (`intent="narrowed"` regimens
  set `discontinuation_datetime = reported_datetime` on displaced
  empirical entries; downstream `_map_order_status_to_fhir` in the
  medications builder maps that to `MedicationRequest.status="stopped"`).

## Directory contents

```
clinosim/modules/antibiotic/
  __init__.py                        ANTIBIOTIC_DRUGS + ANTIBIOTIC_LOINC_LOOKUP re-export
  engine.py                          build_regimens + generate_mar_doses + narrow_* helpers + loaders + validators
  enricher.py                        POST_ENCOUNTER enrich_antibiotic (Pass 1 empirical + Pass 2 narrowing)
  audit.py                           AD-60 audit plug-in (second per-Module) — lift_firing_proof + antibiogram_firing_proof
  _narrow_dose_defaults.py           narrow-target dose + frequency defaults (Issue #637)
  reference_data/
    hai_empirical.yaml               IDSA empirical regimen per HAI type
    narrow_ladder.yaml               per (HAI type × organism) narrow ladder
```

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py):

- `name="antibiotic"`, `stage=POST_ENCOUNTER`, `order=85`,
  `enabled=lambda c: True`. Runs AFTER `hai` (order=80) so
  `extensions["hai"]` is populated.
- The `audit.py` module registers with the AD-60 audit framework at
  import time.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) | POST_ENCOUNTER order=85 registration. |
| Audit registry | [`clinosim/modules/antibiotic/audit.py`](audit.py) | AD-60 audit plug-in. |
| HAI enricher | [`clinosim/modules/hai/enricher.py`](../hai/enricher.py) | Cross-imports `ANTIBIOTIC_LOINC_LOOKUP`. |
| FHIR medications builder | [`clinosim/modules/output/fhir_r4/medications/`](../output/fhir_r4/medications/README.md) | Emits `MedicationRequest` + `MedicationAdministration` from the appended `Order` + MAR records (`status="stopped"` on discontinued empirical). |

## Testing

```bash
pytest tests/unit -k antibiotic -q
pytest tests/integration -k "antibiotic" -q
clinosim audit run -d <cohort_dir> --module antibiotic
```

Individual files:

- [`tests/unit/test_antibiotic_code_lookup.py`](../../../tests/unit/test_antibiotic_code_lookup.py)
  — `ANTIBIOTIC_LOINC_LOOKUP` coverage.
- [`tests/unit/test_antibiotic_engine.py`](../../../tests/unit/test_antibiotic_engine.py)
  — `build_regimens` + narrow-selection helpers.
- [`tests/unit/test_antibiotic_enricher_unit.py`](../../../tests/unit/test_antibiotic_enricher_unit.py)
  — enricher Pass 1 + Pass 2 unit.
- [`tests/unit/test_antibiotic_types.py`](../../../tests/unit/test_antibiotic_types.py),
  [`tests/unit/types/test_antibiotic_discontinuation.py`](../../../tests/unit/types/test_antibiotic_discontinuation.py)
  — dataclass shape (incl. `discontinuation_datetime` slot).
- [`tests/unit/test_antibiotic_id_length.py`](../../../tests/unit/test_antibiotic_id_length.py)
  — `_check_fhir_id_length` guard.
- [`tests/unit/test_antibiotic_yaml_loader.py`](../../../tests/unit/test_antibiotic_yaml_loader.py)
  — 6-layer loader validators.
- [`tests/unit/modules/antibiotic/`](../../../tests/unit/modules/antibiotic/)
  — module-scoped unit tests.
- [`tests/integration/test_antibiotic_forced_e2e.py`](../../../tests/integration/test_antibiotic_forced_e2e.py),
  [`test_antibiotic_audit.py`](../../../tests/integration/test_antibiotic_audit.py)
  — end-to-end + AD-60 audit run.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
