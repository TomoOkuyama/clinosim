# `clinosim.modules.resuscitation`

The resuscitation attempt that ends the in-hospital death of a full-code patient (Issue #3483).

## Purpose

An in-hospital death of a patient whose code status is "For resuscitation" used to carry no record of a resuscitation: no procedure, no drug, no code event. The death summary therefore had to either assert a cardiopulmonary arrest without any attempt or say that none is documented. This module records the attempt.

## Scope

**In scope**: for a deceased inpatient or emergency record whose `code_status` is the full-code tier (`resuscitation_rules.yaml` `attempt_tier`), one CPR `ProcedureRecord` (`procedure_type: cpr`; CPT 92950 for US, K-code J046 非開胸的心マッサージ for JP) that ends at the death time (the encounter's discharge time), and the epinephrine `Order` and `MedicationAdministration` rows given during it. The record is complete in the CIF, so the FHIR Procedure / MedicationRequest / MedicationAdministration and the death summary read it through the existing paths.

**Not done**: a not-for-resuscitation (DNAR, DNAR + DNI, comfort care) or unknown code status gets no attempt; a patient who survives gets none. No intubation is added (the record has no advanced-airway or rhythm data to base one on; an airway the record already holds stays as recorded). A patient under `epinephrine.min_age` (18) gets the CPR record but no epinephrine, because the 1 mg dose is the adult dose and the paediatric weight-based dose was not read for this change.

## Rules (`reference_data/resuscitation_rules.yaml`)

| Rule | Value | Basis |
|---|---|---|
| Epinephrine dose and route | 1 mg IV | AHA 2020 Adult Cardiac Arrest Algorithm: "Epinephrine IV/IO dose: 1 mg every 3-5 minutes" |
| Interval | 4 minutes | Model choice inside the guideline's 3-5 minute range |
| First dose | 2 minutes after the start | Model choice (the guideline says "as soon as feasible" for a nonshockable rhythm) |
| Duration | 15-45 minutes, drawn per stay | Model choice; the guideline gives no duration. Capped by the length of the stay |

## Determinism

The duration is drawn from a per-stay sub-RNG seeded by `clinosim.seeding.resuscitation_seed(patient_id, encounter_id)` (SHA-256 of the ids), so no existing RNG stream is read or shifted. Everything else is a pure function of the death time and the YAML. The enricher runs at `POST_RECORDS` order 55, after `code_status` (50), and is idempotent.

## Public API

```python
from clinosim.modules.resuscitation.engine import load_rules, build_cpr_procedure, build_epinephrine
from clinosim.modules.resuscitation.enricher import enrich_resuscitation
```

## Dependencies

`clinosim.modules.code_status` (the tier and its SNOMED code), `clinosim.codes.procedures` (catalog entry `cpr`), `clinosim.modules.order.placed_order_mar.stable_nurse`, `clinosim.seeding`, pydantic (the rules YAML is validated at load).

## Constants and configuration

All values live in [`reference_data/resuscitation_rules.yaml`](reference_data/resuscitation_rules.yaml), loaded once by `load_rules()` and validated by a pydantic model: `attempt_tier` (the code-status tier an attempt is made for), `encounter_types` (`inpatient`, `emergency`), `procedure` (catalog type `cpr`), `duration_minutes` (`min` / `max`) and the `epinephrine` block (drug, dose, route, `min_age`, `interval_minutes`, `first_dose_offset_minutes`, `clinical_intent` per language). See the Rules table above for the values and their basis.

## Directory contents

```
clinosim/modules/resuscitation/
  __init__.py
  engine.py                          load_rules / attempt_status_code / is_resuscitation_order / attempt_minutes / build_cpr_procedure / build_epinephrine
  enricher.py                        enrich_resuscitation (POST_RECORDS)
  reference_data/
    resuscitation_rules.yaml         attempt tier, encounter types, CPR procedure type, duration range, epinephrine dose / route / interval
```

## Enricher wiring

Registered in [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py): `name="resuscitation"`, `stage=POST_RECORDS`, `order=55` (after `code_status` 50, before `care_level` 60), always on. The sub-seed is `clinosim.seeding.resuscitation_seed(patient_id, encounter_id)`; it is not an `ENRICHER_SEED_OFFSETS` entry.
