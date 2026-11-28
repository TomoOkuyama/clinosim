# Encounter lifecycle, snapshot and export — specification

Status: **normative**. Every change that creates or finishes an encounter, records a death, decides what a snapshot (`--end`) shows, or finishes a FHIR resource follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`encounter-lifecycle-and-export-spec.ja.md`](encounter-lifecycle-and-export-spec.ja.md).

Related specs: medication and lab state at export ([`medication-lifecycle-spec.md`](medication-lifecycle-spec.md) §6, [`lab-orders-and-results-spec.md`](lab-orders-and-results-spec.md) §4); random streams of the phases ([`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) §3); the AD-32 snapshot principle ([`implementation-rules.md`](implementation-rules.md) §2).

## 1. Principles

1. **One way to open and close an encounter.** Every encounter kind links its orders, sets its route fields and builds its diagnosis through the same helpers, so an ED visit, a clinic visit, an admission and a delivery have the same shape.
2. **One timeline.** The simulation runs one forward month loop; each person has at most one death, the earliest.
3. **The snapshot is applied at export.** CIF stores what happened. What a snapshot date shows — an admission still in progress, entries after the date dropped, coverage and prescriptions still active — is computed when FHIR is written, so one CIF can be exported at any snapshot.
4. **One finishing pass per resource.** Every FHIR resource, in the facility bundle and in every patient bundle, is finished by the same ordered passes (profiles, display stripping, identifiers, companion specimens), and every Condition starts from one skeleton.
5. **Every rule has a guard.** Each rule names the test that enforces it; a rule without one is listed in §6.

## 2. Encounters

| Rule | Canonical code | Guard |
|---|---|---|
| Every encounter simulator (ED, inpatient, outpatient, perinatal, unknown condition) builds its `ClinicalDiagnosis` through `encounter_diagnosis`, and links orders that have no encounter through `attach_orders`. A visit whose route is fixed by its kind (ED, outpatient, perinatal) sets admit source, disposition, priority and the admitting / discharging physician through `finalize_encounter`; an admission (inpatient, unknown condition) derives them from its admission route and discharge decision. | `simulator/encounter_setup.py` (`attach_orders`, `finalize_encounter`, `encounter_diagnosis`) | `tests/unit/test_encounter_setup.py`, `tests/unit/test_encounter_export_spec_guards.py` (`…builds_its_diagnosis_through_encounter_setup`, `…links_its_orders_through_encounter_setup`, `…clinical_diagnosis_is_constructed_only_in_encounter_setup`) |
| A procedure performed in an encounter lies inside its period. A clinic visit lasts until its last procedure ends (`extend_visit_to_procedures`); an admission holds its procedures between admission and discharge, and an ED visit places its procedures on its own workflow (arrival procedures with the triage vitals and IV access before the first IV drug order, fracture care after the imaging read) inside its stay (`fit_procedures_in_stay`). | `simulator/encounter_setup.py` (`extend_visit_to_procedures`, `fit_procedures_in_stay`), `simulator/ed_procedures.py::time_ed_procedures` | `tests/unit/simulator/test_procedures_in_encounter_2863.py` |
| An order is never dated before the start of its encounter (the ED arrival for a stay admitted through the ED). A placement time drawn as an anchor plus a normal offset is held at the window start after the draw, so the random stream does not change; `clamp_to_window` enforces it at generation, at the ED lab, imaging and treatment orders and at the admission work-up orders (Issue #3957). | `simulator/encounter_setup.py::clamp_to_window` | `tests/unit/test_orders_not_before_encounter_start_3957.py` |
| The simulation advances month by month in one loop: year boundary (population advance, healthcare calendar), monthly life events, ED slots (a slot that falls inside an inpatient stay is dropped, not deferred), then dispatch of the month's queued events in date order. | `simulator/phases/_forward_loop.py`, `simulator/phases/_ed_slot.py::dispatch_ed_slot` | `tests/unit/simulator/test_forward_loop_2169.py`, `tests/unit/simulator/test_ed_slot_inpatient_gate_3393.py` |
| A person's death is recorded once, through one method; the earliest recorded death wins (an in-hospital death replaces a later pre-sampled community death). A deceased inpatient or emergency record whose code status is the full-code tier gets one CPR procedure ending at the death time and the epinephrine given during it (a POST_RECORDS enricher, order 55, after `code_status`); a record that is not for resuscitation gets none (Issue #3483). | `types/population.py::PersonRecord.record_death`, `modules/resuscitation/enricher.py::enrich_resuscitation` | `tests/unit/test_death_record_2166.py`, `tests/unit/modules/resuscitation/test_resuscitation_3483.py` |

## 3. Snapshot at export

| Rule | Canonical code | Guard |
|---|---|---|
| An admission that crosses the snapshot is exported in progress (no `period.end`, no discharge disposition); entries dated after the snapshot are dropped, by calendar date, inclusive of the snapshot day. | `fhir_r4/builder.py` (`_reconcile_encounters_at_snapshot`, then `_drop_entries_after_snapshot`) | `tests/unit/output/test_fhir_after_snapshot_filter.py`, `tests/unit/output/test_fhir_encounter_hospitalization_941.py` |
| Coverage status is derived from its period and the snapshot. | `fhir_r4/demographics/patient.py::_derive_coverage_status` | `tests/unit/test_fhir_coverage.py`, `tests/unit/output/test_fhir_coverage_after_death_1278.py` |
| Take-home prescription state is computed across the patient's records before the bundles are built. | `order/prescription_supersede.py::prescription_closures` | see the medication spec |

## 4. FHIR finishing

| Rule | Canonical code | Guard |
|---|---|---|
| Every resource of the facility bundle and of every patient bundle is finished by one function, in a fixed order: JP Core / JP-CLINS or US Core profiles, JP observation categories, display stripping on English-only systems, eCS dosage fields, Observation identifiers, reference-range extension scrub, companion Specimen, ... The passes are called nowhere else in the builder. | `fhir_r4/builder.py::_finalize_resource` | `tests/unit/test_encounter_export_spec_guards.py::test_finishing_passes_run_only_in_finalize_resource` |
| Every Condition resource starts from one skeleton: identifier, JP Core profile and JP eCS diagnosis type on JP output, statuses, category, code, subject. | `fhir_r4/conditions/conditions.py::_condition_skeleton` | `tests/unit/test_encounter_export_spec_guards.py::test_condition_resources_start_from_the_skeleton` |
| A vital-sign Observation lies inside the Encounter it references: the per-field time offsets of a set (temperature +30 s, respiratory rate +60 s, SpO2 +5 s) never carry an Observation past the end of that Encounter (the end of the ED window for the ED bridge, the discharge time otherwise), and never move it earlier than the set itself (Issue #3959). | `fhir_r4/labs/observations.py::_shifted_vital_time`, `fhir_r4/lib/ed_reattribution.py::vital_sign_encounter_end` | `tests/unit/output/test_fhir_vitals_inside_short_visit_3959.py` |

## 5. Reading a cohort

| Rule | Canonical code | Guard |
|---|---|---|
| Eval and audit read an exported cohort through one NDJSON reader. | `audit/types.py::Cohort` | `tests/unit/test_audit_cohort_reader_2518.py` |

## 6. Gaps

| Gap | Where |
|---|---|
| Inpatient and unknown-condition admissions set their route fields in their own code, with no shared helper. | `simulator/inpatient.py`, `simulator/unknown_condition.py` |
