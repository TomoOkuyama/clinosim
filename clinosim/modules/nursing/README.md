# `clinosim.modules.nursing` — primary-nurse assignment + assessment scaffolding

## Purpose

Assigns a primary nurse to every inpatient / ICU / rehab-inpatient
encounter (POST_ENCOUNTER enricher, registered as
**`nursing_assignment`**), and publishes the reference scaffolding
(ADL categories, risk-assessment types, disease-specific nursing
focus) that future narrative and assessment work will consume.

**Naming disambiguation (AGENTS.md, AD-64).** The simulator has two
distinct enrichers whose names both start with "nursing":

- **`nursing_assignment`** — lives in THIS package
  (`clinosim.modules.nursing.engine.nursing_enricher`), POST_ENCOUNTER
  order=94, writes `EncounterRecord.primary_nurse_id`.
- **`nursing_flowsheets`** — lives in the observation package
  ([`clinosim.modules.observation.nursing_enricher`](../observation/README.md)),
  POST_RECORDS order=20, emits NEWS2 / GCS / Braden / Morse scores.

The two are always referenced with those disambiguating names in code
comments. This module scopes to the former.

## Scope

- **In scope**:
  - `nursing_enricher` — POST_ENCOUNTER assignment of
    `primary_nurse_id` on inpatient / ICU / rehab-inpatient encounters
    from the ctx `StaffRoster` (falls back to `""` if the ctx carries
    no roster or the roster has no nurses).
  - `assign_primary_nurse` — uniform sampling from
    `clinosim.modules.staff.engine.scoped_nurses(roster, ward=...,
    department=...)`: the nurses of the encounter's ward, else of its
    department, else every nurse (Issue #2700); caller owns the RNG
    seeding.
  - `load_nursing_assessment` — reference-data loader for
    `nursing_assessment.yaml`, validated against the
    `NursingAssessment` Pydantic model.
  - Public constants: `SUPPORTED_ADL_CATEGORIES` (5 ADL categories),
    `SUPPORTED_RISK_ASSESSMENTS` (3 risk-assessment types),
    `INPATIENT_ENCOUNTER_TYPES` (3 encounter types accepted by the
    enricher).
- **Out of scope**:
  - Nursing flowsheet observations (NEWS2 / GCS / Braden / Morse) —
    lives in [`clinosim.modules.observation`](../observation/README.md).
  - Nurse identity generation
    ([`clinosim.modules.staff`](../staff/README.md) owns the roster).
  - Nurse narrative documents
    ([`clinosim.modules.document.narrative`](../document/narrative/README.md)).
  - FHIR CareTeam / performer emission
    ([`clinosim.modules.output.fhir_r4`](../output/README.md)).

## Public API

```python
from clinosim.modules.nursing import (
    INPATIENT_ENCOUNTER_TYPES,   # frozenset {"inpatient", "icu", "rehab_inpatient"}
    SUPPORTED_ADL_CATEGORIES,    # frozenset {eating, bathing, dressing, toileting, mobility}
    SUPPORTED_RISK_ASSESSMENTS,  # frozenset {fall_risk, pressure_ulcer_risk, aspiration_risk}
    assign_primary_nurse,        # (encounter, roster|None, rng) -> staff_id (str, may be "")
    load_nursing_assessment,     # () -> dict (cached, NursingAssessment-validated)
)
```

The POST_ENCOUNTER entry point `nursing_enricher(ctx) -> None` is
defined in `engine.py` but is not re-exported; the simulator imports
it directly from
[`clinosim.modules.nursing.engine`](engine.py).

## Determinism

- Sub-seed offset `0x4E55` (`"NU"`), registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["nursing"]`.
- Per-encounter RNG in `nursing_enricher`:
  `derive_sub_seed(master_seed, offset, encounter_id)` — same
  encounter always draws the same nurse; the main simulation stream
  is not consumed (AD-16).
- `assign_primary_nurse` itself is pure and RNG-agnostic — the
  caller seeds.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.modules.staff.engine` — `scoped_nurses` (ward- /
  department-scoped nurse pool).
- `clinosim.determinism` — per-encounter RNG construction.
- `clinosim.datafiles` — `load_validated_yaml`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.staff` — `StaffRoster`.
- `numpy` — `np.random.Generator`.
- `pydantic` — `NursingAssessment` / `_NursingFocus` models.

## Constants and configuration

- Public frozensets (in `engine.py`):
  - `INPATIENT_ENCOUNTER_TYPES = {"inpatient", "icu", "rehab_inpatient"}`
    — encounter types the enricher accepts. Other types are skipped
    (no `primary_nurse_id` set).
  - `SUPPORTED_ADL_CATEGORIES = {"eating", "bathing", "dressing",
    "toileting", "mobility"}` — five Barthel-index categories.
  - `SUPPORTED_RISK_ASSESSMENTS = {"fall_risk", "pressure_ulcer_risk",
    "aspiration_risk"}` — three risk-assessment types.
- [`reference_data/nursing_assessment.yaml`](reference_data/nursing_assessment.yaml)
  — scaffolding read only via `load_nursing_assessment()`. Keys:
  - `adl_categories` — one entry per `SUPPORTED_ADL_CATEGORIES` key;
    value is the ordered list of possible ADL statuses.
  - `risk_assessments` — one entry per `SUPPORTED_RISK_ASSESSMENTS`
    key; value is the ordered list of possible risk statuses.
  - `disease_specific_nursing_focus` — `{disease_id: {focus,
    interventions: {<lang>: list[str]}}}` (nursing-focus text).
  - `baseline` — same `{focus, interventions}` shape, used as the
    fallback when no disease-specific entry matches.
- Load-time validation is the `NursingAssessment` Pydantic model
  (with `_NursingFocus` for `baseline` and each disease entry),
  applied by `load_validated_yaml`. It rejects an empty top-level,
  missing top-level keys, a focus without `focus` / `interventions`,
  `interventions` that does not map each language to a list, and
  `adl_categories` / `risk_assessments` keys that differ from
  `SUPPORTED_ADL_CATEGORIES` / `SUPPORTED_RISK_ASSESSMENTS` in either
  direction. Any drift raises at load time — the standard PR-90
  silent-no-op defense.
- **Scaffolding note**: `load_nursing_assessment` currently has no
  live consumers; the data is loaded only by its own unit tests.
  Downstream narrative work (β-JP-1) is the intended reader.

## Directory contents

```
clinosim/modules/nursing/
  __init__.py                     re-exports public constants + functions
  engine.py                       loader / validator / assign_primary_nurse /
                                  nursing_enricher (POST_ENCOUNTER)
  reference_data/
    nursing_assessment.yaml       ADL + risk + disease-focus scaffolding
```

The module has **no dedicated `enricher.py`** — the enricher entry
point lives in `engine.py`. There is **no `audit.py`** — no
`ModuleAuditSpec` is registered.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) under
`register_builtin_enrichers`:

- `name="nursing_assignment"`, `stage=POST_ENCOUNTER`, `order=94`,
  `enabled=lambda c: True`, `run=nursing_enricher`.
- Runs after `triage` (order 93) and before `document` (order 95).
- **The other nursing enricher — `nursing_flowsheets` — is registered
  in the same file as `name="nursing"`, `stage=POST_RECORDS`,
  `order=20`, sourced from
  [`clinosim.modules.observation.nursing_enricher`](../observation/README.md).**
  Do not conflate the two.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| FHIR `CareTeam` builder | [`clinosim/modules/output/fhir_r4/encounters/care_team.py`](../output/fhir_r4/encounters/care_team.py) | Emits `primary_nurse_id` as `CareTeam.participant[1].member` — only when non-empty (attending physician is participant[0]). |
| FHIR nursing flowsheet performer fallback | [`clinosim/modules/output/fhir_r4/procedures/nursing.py`](../output/fhir_r4/procedures/nursing.py) (`_bb_nursing_observations`) | RM-1: uses `primary_nurse_id` as the default `performer` on nursing survey Observations when no per-observation performer is set. |
| FHIR Practitioner emission | [`clinosim/modules/output/fhir_r4/lib/inline_bb.py`](../output/fhir_r4/lib/inline_bb.py) (`_bb_practitioners`) | RM-1: emits each encounter's `primary_nurse_id` as a `Practitioner` so the nursing-Observation performer reference resolves. |
| Enricher registry (`nursing_assignment`) | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) (`register_builtin_enrichers`) | POST_ENCOUNTER order=94 registration. |

## Testing

```bash
pytest tests/unit -k nursing -q         # constants, loader, validator, assign
pytest tests/integration -k nursing -q  # enricher + flowsheet FHIR emission
```

Individual files:

- [`tests/unit/test_nursing.py`](../../../tests/unit/test_nursing.py)
  — cross-package nursing unit tests.
- [`tests/unit/modules/nursing/test_engine.py`](../../../tests/unit/modules/nursing/test_engine.py)
  — `assign_primary_nurse` + constants + `nursing_enricher`
  determinism.
- [`tests/unit/modules/nursing/test_nursing_assessment_yaml.py`](../../../tests/unit/modules/nursing/test_nursing_assessment_yaml.py)
  — `NursingAssessment` validator coverage.
- [`tests/integration/test_nursing_enricher.py`](../../../tests/integration/test_nursing_enricher.py)
  — POST_ENCOUNTER enricher end-to-end.
- [`tests/integration/test_fhir_nursing.py`](../../../tests/integration/test_fhir_nursing.py)
  — FHIR flowsheet Observation emission (touches this module through
  the RM-1 performer fallback).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
