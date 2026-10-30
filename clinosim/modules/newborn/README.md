# `clinosim.modules.newborn` — Newborn birth-admission clinical workup

## Purpose

Emits the clinical events every real neonatal chart carries during the
birth admission that no other module owns. Fills the gap between
`simulator/perinatal.py` (owns Encounter + Patient shells) and
`clinosim.modules.pediatric` (owns post-discharge well-child visits).

Filed under Issue #1252. The module-boundary rationale + why a
dedicated module beats folding into `perinatal.py` or `pediatric/` is
in the [#1252 design comment](https://github.com/TomoOkuyama/clinosim/issues/1252).

## Scope

- **In scope**: birth-admission clinical events that fire on the
  baby-side CIF record (`condition_event.condition_type ==
  "newborn_birth"`). All #1252 slices are implemented:
  - Vitamin K prophylaxis (`MedicationAdministration` — JP oral K2
    syrup on days 0 / 7 when inside the stay, US 1 mg IM — N2).
  - Shift-cadence vital signs from the newborn's `baseline_vitals`
    (`VitalSignRecord` — N3).
  - Apgar score at 1 min / 5 min (`Observation`, LOINC 9271-8 /
    9274-2 — N4).
  - AABR hearing screen (`Procedure`, SNOMED 232717001 — N5).
  - Tandem-MS metabolic mass screen (`Procedure`, SNOMED 405058008,
    plus `ServiceRequest` + `Specimen` + `Observation` +
    `DiagnosticReport` workflow — N6 / N6b).
  - Transcutaneous bilirubin, CCHD pulse-ox screen (`Observation`) and
    US erythromycin ophthalmic prophylaxis (`MedicationAdministration`;
    JP config declares no drug, so nothing is emitted) — N7.
- **Once-per-newborn dedup** (Issue #1736): siblings delivered by the
  same mother share `patient_id = "<mother_id>-BABY"`, so the hearing
  and metabolic screens are gated by a module-level
  `(patient_id, SNOMED)` tracker (`has_perinatal_baseline_emitted` /
  `mark_perinatal_baseline_emitted`), reset at the top of
  `clinosim.simulator.engine.run_beta` and by the autouse fixture in
  `tests/conftest.py`.
- **Out of scope**: NICU pathology (Z38.0 well-newborn only), multiple
  births (Z37.2 / 3 / 4 / 5 — singletons only), home / birth-centre
  deliveries, post-discharge doses (e.g. the JP 1-month Vitamin K dose).

## Public API

```python
from clinosim.modules.newborn import (
    load_newborn_config,               # locale schedule loader (cached)
    is_newborn_birth_record,           # firing-gate predicate
    build_vitamin_k_administrations,   # (record, country) -> list[MedicationAdministration]
    build_newborn_shift_vitals,        # (record) -> list[VitalSignRecord]
    build_apgar_scores,                # (record) -> list[dict]
    build_hearing_screen_procedure,    # (record) -> ProcedureRecord | None
    build_metabolic_screen_procedure,  # (record, country) -> ProcedureRecord | None
    build_bilirubin_observations,      # (record) -> list[dict]
    build_cchd_pulse_ox,               # (record) -> list[dict]
    build_ophthalmic_prophylaxis,      # (record, country) -> list[MedicationAdministration]
    PERINATAL_BASELINE_SNOMEDS,        # {"232717001", "405058008"}
    has_perinatal_baseline_emitted,
    mark_perinatal_baseline_emitted,
    reset_perinatal_baseline_tracker,
    enrich_newborn,                    # POST_ENCOUNTER enricher entrypoint
)
```

`engine.build_metabolic_screen_workflow_data` (not re-exported) builds
the ServiceRequest / Specimen / DiagnosticReport payload.

## Where outputs land

`enrich_newborn` appends to the newborn record:

- `medication_administrations` — Vitamin K + ophthalmic prophylaxis.
- `vital_signs` — shift vitals.
- `procedures` — hearing + metabolic screen `ProcedureRecord`s.
- `extensions["newborn"]` — `apgar`, `bilirubin`, `cchd_pulse_ox`,
  `metabolic_screen` payloads, rendered by the `_bb_newborn_*`
  bundle-builders in [`fhir_emit.py`](fhir_emit.py), which
  `clinosim/modules/output/fhir_r4/builder.py` imports.

## Enricher registration

Registered in `clinosim/simulator/enrichers.py` as
`POST_ENCOUNTER order=92`, always-on for JP and US locales:

- After `imaging` (90) so the module sees a fully-populated encounter.
- Before `triage` (93) and `document` (95), so any narrative that
  surfaces the Vitamin K administration finds the MAR entry already
  in place.

## Configuration

`reference_data/newborn_screening.yaml` — locale-specific protocol
parameters. Every clinically-meaningful constant lives here per repo
convention (constants live in yaml, not code); the engine
carries no hardcoded doses / days / drug names.

Top-level keys: `bilirubin`, `cchd_pulse_ox`, `ophthalmic_prophylaxis`,
`metabolic_screen`, `hearing_screen`, `apgar`, `shift_vitals`,
`vitamin_k`. The Vitamin K block, for example:

```yaml
vitamin_k:
  jp: {drug_name, dose, route, schedule_days, within_hours_of_birth, yj_code}
  us: {drug_name, dose, route, schedule_days, within_hours_of_birth, rxnorm_code}
```

## Determinism

No master-stream RNG is consumed. Vitamin K, ophthalmic prophylaxis
and shift vitals are deterministic functions of the birth-encounter
admission datetime, the newborn's `baseline_vitals` and the yaml
schedule. Apgar scores, hearing / metabolic screen outcomes,
bilirubin values and CCHD SpO2 values use a local
`np.random.default_rng` seeded from a SHA-256 of a fixed label plus
the newborn's patient id (e.g. `newborn-apgar|<pid>|…`,
`newborn-hearing-screen|<pid>`), so they are reproducible per patient
and independent of caller RNG. No `ENRICHER_SEED_OFFSETS` entry is
used. There is no Vitamin K coverage-miss / declined path yet.

## Testing

`tests/unit/modules/newborn/` — `test_vitamin_k.py`,
`test_shift_vitals.py`, `test_apgar.py`, `test_hearing_screen.py`,
`test_metabolic_screen.py`, `test_bilirubin_cchd_ophthalmic.py`,
`test_perinatal_baseline_dedup.py`; FHIR shape in
`tests/unit/output/test_newborn_metabolic_screen_fhir_shape.py`.

## References

- JP MHLW 新生児 ビタミン K 欠乏性出血症予防 (2011 改訂, 3-dose oral
  schedule).
- AAP Guidelines for Perinatal Care 8th ed. (US Vitamin K 1 mg IM
  within 6 h of birth).
- FHIR R4 `MedicationAdministration` — the emit shape used by the
  existing `medications/` builder for the MAR entries.

Japanese counterpart: [`README.ja.md`](README.ja.md).
