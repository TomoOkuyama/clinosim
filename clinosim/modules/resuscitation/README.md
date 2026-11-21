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
from clinosim.modules.resuscitation import build_cpr_procedure, build_epinephrine, is_resuscitation_order, load_rules
from clinosim.modules.resuscitation.enricher import enrich_resuscitation
```

## Dependencies

`clinosim.modules.code_status` (the tier and its SNOMED code), `clinosim.codes.procedures` (catalog entry `cpr`), `clinosim.modules.order.placed_order_mar.stable_nurse`, `clinosim.seeding`, pydantic (the rules YAML is validated at load).
