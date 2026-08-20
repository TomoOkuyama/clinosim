# `clinosim.modules.sdoh` — SDOH social-history reference data

## Purpose

Provides the enum → SNOMED + LOINC reference mapping for the social
determinants of health (SDOH) attributes the simulator populates on
`PatientProfile` during activation — currently `smoking_status`
(US Core LOINC 72166-2) and `alcohol_use` (LOINC 11331-6). Downstream
FHIR builders read this data to emit `Observation` resources under
category `social-history`.

The module is a **data-only variant** (see the "Data-only module
variant" section of [`docs/CONTRIBUTING-modules.md`](../../../docs/CONTRIBUTING-modules.md)):
no `enricher.py`, no `assign_*` function, no random-generator use.
Attribute assignment happens at patient activation via
`patient/activator.py` reading `locale/{us,jp}/demographics.yaml`.

## Scope

- **In scope**: publishing the SNOMED code → enum key mapping for
  smoking + alcohol tiers and the LOINC observation code for each
  topic, keyed by SDOH topic and enum value.
- **Out of scope**: patient-level assignment of `smoking_status` /
  `alcohol_use` (lives in
  [`clinosim.modules.patient`](../patient/README.md) activator +
  [`clinosim/locale/{us,jp}/demographics.yaml`](../../locale/)),
  FHIR `Observation` emission (in
  [`clinosim.modules.output.fhir_r4.demographics.smoking_alcohol`](../output/fhir_r4/demographics/smoking_alcohol.py)),
  SNOMED display text (in [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)),
  future SDOH topics not yet in `PatientProfile` (occupation,
  education, housing, food insecurity — see "Extending" below).

## Public API

```python
from clinosim.modules.sdoh import load_social_history

data = load_social_history()
# data["smoking_status"]["loinc"]                    -> "72166-2"
# data["smoking_status"]["category"]                 -> "social-history"
# data["smoking_status"]["values"]["never"]["snomed"] -> "266919005"
```

`load_social_history` is `@lru_cache(maxsize=1)`, so repeated calls
are free. It is the module's only public export (re-exported through
`__init__.py`).

## Dependencies

- `yaml` — YAML parser for the reference file.
- `clinosim.codes` (indirect, via the FHIR builder) — SNOMED display
  lookup at emission time.
- No dependency on any other `clinosim.modules.*`, no locale, no
  types.

## Constants and configuration

- [`reference_data/social_history.yaml`](reference_data/social_history.yaml)
  — country-neutral. Two topics currently:
  - `smoking_status` — LOINC `72166-2`, category `social-history`,
    three enum values: `never` (SNOMED 266919005), `former`
    (8517006), `current` (449868002). US Core profile
    `us-core-smokingstatus`.
  - `alcohol_use` — LOINC `11331-6`, category `social-history`,
    three enum values: `none` (SNOMED 105542008), `social`
    (28127009), `heavy` (86933000). HL7 social-history pattern
    (no US Core profile).
- All 6 SNOMED codes are cross-checked against
  [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  (both `en` and `ja` displays present) — verified by PR #68 SNOMED
  CT authority crosswalk.

## Directory contents

```
clinosim/modules/sdoh/
  __init__.py                     re-exports load_social_history
  engine.py                       load_social_history (single loader)
  reference_data/
    social_history.yaml           smoking + alcohol enum → SNOMED + LOINC
```

The module has **no `enricher.py`, no `audit.py`, and no seed
offset** in `ENRICHER_SEED_OFFSETS`. It is not registered with
`register_builtin_enrichers`. Verification lives in the unit +
integration tests below.

## Extending

New SDOH data belongs here when it fits the "simple enum attribute
resolved at output time" shape:

1. If `PatientProfile` already carries the attribute
   (like `smoking_status`), add a new topic key to
   `reference_data/social_history.yaml` (or a sibling
   `reference_data/<topic>.yaml`), then a FHIR builder in
   `clinosim/modules/output/fhir_r4/demographics/`.
2. If assignment requires computation (for example
   `food_insecurity` from address + income), a standalone module
   under `clinosim/modules/<theme>/` is the right home (full
   engine + enricher setup). Do NOT bolt computation into `sdoh`.

The 要介護度 (care_level) FHIR emission previously lived under
`_fhir_sdoh.py` alongside smoking/alcohol; it was split out to its
own module in PR2 G2 (2026-06-24) for single-responsibility
separation, so a comparable independent module is the pattern for
non-trivial SDOH work.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| FHIR `Observation` builders | [`clinosim/modules/output/fhir_r4/demographics/smoking_alcohol.py`](../output/fhir_r4/demographics/smoking_alcohol.py) | Reads `load_social_history()`, emits two social-history `Observation` resources (smoking + alcohol) with the LOINC observation code and the SNOMED `valueCodeableConcept` per enum. |

There is no CSV column dedicated to SDOH; smoking / alcohol travel
inside the patient CSV row.

## Testing

```bash
pytest tests/unit -k sdoh -q          # loader + codes + csv
pytest tests/integration -k sdoh -q   # FHIR emission
```

Individual files:

- [`tests/unit/test_sdoh_engine.py`](../../../tests/unit/test_sdoh_engine.py)
  — loader shape + caching.
- [`tests/unit/test_sdoh_codes.py`](../../../tests/unit/test_sdoh_codes.py)
  — SNOMED code authority + active-concept checks (PR #68 + PR2
  update).
- [`tests/unit/test_sdoh_csv.py`](../../../tests/unit/test_sdoh_csv.py)
  — smoking / alcohol columns in the patient CSV row.
- [`tests/integration/test_fhir_sdoh.py`](../../../tests/integration/test_fhir_sdoh.py)
  — `Observation` emission end-to-end.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
