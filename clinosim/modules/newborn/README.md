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
  "newborn_birth"`).
- **In this PR (N2 slice)**: Vitamin K prophylaxis
  (`MedicationAdministration`).
- **Reserved for follow-up PRs**: Apgar score at 1 min / 5 min
  (`Observation`, LOINC 9271-8 / 9274-2 — N4), AABR hearing screen
  (`Procedure` + `DiagnosticReport` — N5), tandem-MS metabolic mass
  screen (`ServiceRequest` + `Specimen` + `DiagnosticReport` — N6),
  bilirubin monitoring + CCHD SpO2 screen + US ophthalmic prophylaxis
  (N7).
- **Out of scope**: NICU pathology (Z38.0 well-newborn only), multiple
  births (Z37.2 / 3 / 4 / 5 — singletons only), home / birth-centre
  deliveries. All natural follow-ups but separate from the
  well-newborn-birth-admission axis this module owns.

## Public API

```python
from clinosim.modules.newborn import (
    load_newborn_config,             # locale schedule loader (cached)
    is_newborn_birth_record,         # firing-gate predicate
    build_vitamin_k_administrations, # pure event builder (per record + country)
    enrich_newborn,                  # POST_ENCOUNTER enricher entrypoint
)
```

## Enricher registration

Registered in `clinosim/simulator/enrichers.py` as
`POST_ENCOUNTER order=92`, always-on for JP and US locales:

- After `imaging` (90) / `triage` (93) so the module sees a fully-
  populated encounter.
- Before `document` (95) so any narrative that surfaces the Vitamin K
  administration finds the MAR entry already in place.

## Configuration

`reference_data/newborn_screening.yaml` — locale-specific protocol
parameters. Every clinically-meaningful constant lives here per repo
convention (`feedback_constants_live_in_external_config`); the engine
carries no hardcoded doses / days / drug names.

Current keys (this PR):

```yaml
vitamin_k:
  jp: {drug_name, dose, route, schedule_days, within_hours_of_birth, yj_code}
  us: {drug_name, dose, route, schedule_days, within_hours_of_birth, rxnorm_code}
```

Follow-up PRs stack sibling keys (`apgar`, `hearing_screen`,
`metabolic_screen`, `bilirubin`, `cchd_pulse_ox`, `ophthalmic`).

## Determinism

Every event this module emits is a deterministic function of the
birth-encounter admission datetime + the yaml schedule. No RNG
consumption — the schedule is fixed, and there is no coverage-miss /
declined path yet (the JP Vitamin K program has ~99.5 % uptake per
MHLW; modelling the miss rate is deferred until the coverage data is
in yaml).

## References

- JP MHLW 新生児 ビタミン K 欠乏性出血症予防 (2011 改訂, 3-dose oral
  schedule).
- AAP Guidelines for Perinatal Care 8th ed. (US Vitamin K 1 mg IM
  within 6 h of birth).
- FHIR R4 `MedicationAdministration` — the emit shape used by the
  existing `medications/` builder; no new resource shape introduced.
