# `clinosim.modules.family_history` — first-degree family-history synthesis

## Purpose

Synthesises a patient's first-degree family — mother, father, and 0-2
siblings — and assigns disease codes to each relative using
locale-specific base prevalence lifted by a per-disease heritability
factor when the patient carries the same code. Writes the resulting
list to `CIFPatientRecord.family_history`, from which downstream FHIR
and CSV adapters emit `FamilyMemberHistory` resources and a
`family_history.csv` file.

## Scope

- **In scope**: mother + father + 0-2 siblings per patient, with per-
  relative age derived from the patient's age (parents older by a
  configurable offset, siblings ± an offset), parent-deceased sampling
  that rises with age, and per-disease sampling using
  `base_prevalence(disease, relative_sex, relative_age_band) ×
  heritability(disease)` when the patient carries the code.
- **Diseases modelled**: cardiovascular / metabolic
  (`E11` diabetes, `I10` hypertension, `I25` ischaemic heart disease,
  `I63` / `I64` stroke, `E78` dyslipidaemia) and major cancers
  (`C50` breast, `C18` colon, `C34` lung, `C61` prostate). ICD-10 base
  codes only; downstream lookup resolves display text.
- **Sex restrictions**: prostate on male relatives only, breast cancer
  on female relatives only (enforced by the per-condition `sex` field
  in the reference YAML).
- **Out of scope**: propagating family-history back into the patient's
  own disease sampling (a Phase 2+ concern that would live in
  [`clinosim.modules.population`](../population/README.md) risk-factor
  logic), FHIR / CSV serialisation
  ([`clinosim.modules.output`](../output/README.md)), display text
  for ICD-10 or HL7 v3-RoleCode (in
  [`clinosim/codes/`](../../codes/)).

## Public API

`__init__.py` is empty; consumers import the two building blocks
directly:

```python
from clinosim.modules.family_history.engine import (
    generate_family_history,     # (patient_age, patient_conditions, country, rng)
                                 #   -> list[FamilyMemberHistoryRecord]
    load_reference,              # -> country-neutral biology (relationships / heritability / offsets)
    load_prevalence,             # (country) -> {icd_code: {age_band: {sex: rate}}}
    SIBLING_COUNT_OPTIONS,       # (0, 1, 2)
    SIBLING_SEX_MALE_PROBABILITY, # 0.5
)
from clinosim.modules.family_history.enricher import enrich_family_history
```

`generate_family_history` accepts `patient_conditions` as `str`,
`dict` (`{"code": ...}`), or object (`.code`) — the engine extracts
the ICD base by uppercase-splitting on `.`. Deterministic for a given
`rng`.

## Determinism

- Sub-seed offset `0x4648` (`"FH"`), registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["family_history"]`.
- Per-patient RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — same patient
  always synthesises the same family across all their encounters, and
  the main patient RNG stream is not consumed.

## Dependencies

- `clinosim.modules._shared` — `is_us` / `is_jp`,
  `normalize_probabilities` (`fallback="raise"`),
  `get_attr_or_key` / `set_attr_or_key`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.family_history` — `FamilyMemberHistoryRecord`.
- `clinosim.codes` (indirect, via the FHIR builder) — ICD-10 and
  HL7 v3-RoleCode display lookup.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- [`reference_data/family_history.yaml`](reference_data/family_history.yaml)
  — country-neutral biology:
  - `relationships` — v3-RoleCode entries for `MTH`, `FTH`, `NSIB`
    with per-code EN + JA display. **The JA canonical display strings
    are code-by-code** (`"母"` for MTH, `"父"` for FTH, `"natural
    sibling"` / `"実兄弟姉妹"` for NSIB) and MUST NOT be inferred
    from a sibling code — see the file header comment (Issue #369
    v23 regression) for the exact drift that broke PR #372.
  - `conditions` — per-ICD `{sex, heritability}`.
  - `sibling_count_weights` — 3-element weight for
    `SIBLING_COUNT_OPTIONS = (0, 1, 2)`.
  - `parent_age_offset` / `sibling_age_offset` — `{min, max}` ranges
    used with `rng.integers`.
  - `parent_deceased_base_age` / `parent_deceased_span` /
    `parent_deceased_max` — parent-deceased probability formula.
- [`clinosim/locale/us/family_history_prevalence.yaml`](../../locale/us/family_history_prevalence.yaml)
  and [`clinosim/locale/jp/family_history_prevalence.yaml`](../../locale/jp/family_history_prevalence.yaml)
  — `{icd_code: {age_band: {female: rate, male: rate}}}`. `load_prevalence`
  returns `{}` for unsupported countries (2026-07-02 grand-design
  contract) — the engine treats an empty map as "everyone unaffected".
- Module-level constants (in `engine.py`):
  - `SIBLING_COUNT_OPTIONS = (0, 1, 2)` — matches OECD 2020 average
    children-per-household for US + JP.
  - `SIBLING_SEX_MALE_PROBABILITY = 0.5` — matches the observed
    newborn sex-ratio-at-birth to two decimal places.

## Directory contents

```
clinosim/modules/family_history/
  __init__.py                     empty (see Public API note)
  engine.py                       generate_family_history + sampling helpers
  enricher.py                     POST_RECORDS enrichment (patient-scoped sub-RNG)
  reference_data/
    family_history.yaml           country-neutral biology
```

The module has **no `audit.py`** — no `ModuleAuditSpec` is registered.
Verification lives in the unit + integration tests below.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) under
`register_builtin_enrichers`:

- `name="family_history"`, `stage=POST_RECORDS`, `order=40`,
  `enabled=lambda c: True`.
- Runs after `immunization` (order 30) and before `code_status`
  (order 50).

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`~L341`, `~L418`) | Writes `family_history.csv` from `record["family_history"]` (patient-unique). |
| FHIR `FamilyMemberHistory` builder | [`clinosim/modules/output/fhir_r4/demographics/family_history.py`](../output/fhir_r4/demographics/family_history.py) | Emits one `FamilyMemberHistory` per relative; ids are `fmh-{patient_id}-NN` for write-time de-dup. |
| Enricher registry | [`clinosim/simulator/enrichers.py:175`](../../simulator/enrichers.py) | POST_RECORDS registration. |

## Testing

```bash
pytest tests/unit -k family_history -q         # engine, data, codes, csv, relationship
pytest tests/integration -k family_history -q  # enricher + FHIR emission
```

Individual files:

- [`tests/unit/test_family_history_engine.py`](../../../tests/unit/test_family_history_engine.py)
  — sampling determinism + sex/age filters.
- [`tests/unit/test_family_history_data.py`](../../../tests/unit/test_family_history_data.py)
  — reference YAML shape.
- [`tests/unit/test_family_history_codes.py`](../../../tests/unit/test_family_history_codes.py)
  — ICD-10 and v3-RoleCode authority checks.
- [`tests/unit/test_family_history_csv.py`](../../../tests/unit/test_family_history_csv.py)
  — CSV row emission.
- [`tests/unit/test_fhir_family_history_code_resolution.py`](../../../tests/unit/test_fhir_family_history_code_resolution.py)
  — code → display resolution in the FHIR builder.
- [`tests/unit/output/test_fhir_family_history_relationship.py`](../../../tests/unit/output/test_fhir_family_history_relationship.py)
  — per-code EN/JA display integrity (Issue #369 guard).
- [`tests/integration/test_family_history_enricher.py`](../../../tests/integration/test_family_history_enricher.py)
  — enricher determinism + heritability boost.
- [`tests/integration/test_fhir_family_history.py`](../../../tests/integration/test_fhir_family_history.py)
  — `FamilyMemberHistory` emission end-to-end.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
