# Medication lifecycle — specification

Status: **normative**. Every change that places, holds, administers, stops, prescribes, renews or codes a medication follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`medication-lifecycle-spec.ja.md`](medication-lifecycle-spec.ja.md).

Related specs:
- How a drug is identified (`drug_ref`, `same_drug`, `has_drug`, `medication_matches`) and how its codes and names are resolved: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) §4.1 / §9.
- Random draws and RNG-neutral changes: [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md).

## 1. Principles

1. **One rule, one place.** Each decision about a medication is made by one function reading one data file, and every stage that needs the decision calls it: admission, the daily loop, the administration record (MAR), discharge, activation of home medications, the longitudinal history and FHIR export. No stage keeps its own copy.
2. **The record tells one story.** At most one active order per drug. An order that is replaced is stopped, and its administrations end there. An order of a finished stay is closed at discharge. Every administered order has its order, and every active order is administered or explains why not.
3. **Decided in the simulation, derived at export.** Order and administration facts are stored in CIF. State that depends on the snapshot or on later records — whether a take-home prescription is still active, which one replaced it — is computed at FHIR export (§6).
4. **Every rule has a guard.** Each rule names the test that enforces it; a rule without one is listed in §8.

## 2. Lifecycle

```
protocol / home medications ──► orders (admission, daily loop, enrichers)
        │                              │ drug-safety gate (§3)
        │                              ▼
        │                       administrations (MAR, §4)
        │                              │ supersede / discharge close (§5)
        ▼                              ▼
discharge prescription (§6) ──► home medications ──► next encounters, longitudinal history
                                       │
                                       ▼
                       FHIR MedicationRequest / MedicationAdministration (§6, §7)
```

## 3. Placing orders: safety gate and holds

| Rule | Canonical code | Guard |
|---|---|---|
| Every candidate medication order of the daily loop and of admission passes the drug-safety gate (contraindications, interactions, demographic gates) before it is placed. | `simulator/medication_pipeline.py::apply_drug_safety_gate_to_orders` (admission: `apply_drug_safety_gate_to_admission_orders`); rules in `modules/drug_safety/reference_data/contraindications.yaml` and `demographic_gates.yaml` | `tests/unit/modules/drug_safety/`, `tests/integration/test_drug_safety_gate_post_admission.py` |
| Hold rules come from one source at admission, administration and discharge: renal actions per drug, vital-sign hold parameters, the metformin renal threshold. | `medication_pipeline.py` (`renal_medication_rules`, `mar_vital_hold_reason`, `metformin_admission_hold_threshold`), `discharge_rx.py::renal_hold_drugs`; data `locale/shared/renal_medication_rules.yaml`, `chronic_medications.yaml` | `tests/unit/test_hold_rules_one_source_2296.py`, `tests/unit/test_medication_holds_acute_illness_1335.py` |
| A drug is decided on by its catalog identity, never by a substring of its name. | `clinosim/codes/drugs.py` (see the code-mapping spec) | `tests/unit/test_has_drug_logic_2377.py` |

## 4. Administrations

| Rule | Canonical code | Guard |
|---|---|---|
| Orders placed by the daily loop get their administrations in the loop, from the order's frequency and the patient's state (holds, refusals, PRN triggers). | `medication_pipeline.py::_generate_mar`, `generate_prn_administrations`, `prn_category` | `tests/unit/test_prn_from_state.py`, `tests/unit/test_prn_inhaler_cadence_1318.py` |
| Orders placed outside the loop (VTE prophylaxis enricher, delivery bundle) get administrations from one helper set that draws no RNG: fixed daily times and a nurse picked by a stable hash. | `modules/order/placed_order_mar.py` (`daily_times`, `stable_nurse`, `administrations_for`) | `tests/unit/modules/order/test_placed_order_mar_spec.py` |
| The FHIR timing of an order states its frequency once: ranges ("q4-6h") and PRN caps come from one resolver, and a frequency already in the dose text is not repeated. | `modules/output/fhir_r4/lib/dosage.py` (`resolve_timing_repeat`, `frequency_in_text`) | `tests/unit/output/test_prn_timing_2613.py` |

## 5. Stopping orders

| Rule | Canonical code | Guard |
|---|---|---|
| One active order per drug. A new order of the same drug, or of a drug of a class that replaces it (carbapenem switch, ...), stops the earlier one: status stopped, end time, no administrations after it, and the new order records it as its prior order. | `modules/order/supersede.py::supersede_orders`; rules in `modules/order/reference_data/medication_supersede.yaml` | `tests/unit/test_supersede_medication_orders_2615.py` |
| The medication orders of a finished stay are closed at its discharge (or death): completed when administered, stopped otherwise, with the end time. | `supersede.py::close_orders_at_discharge` | `tests/unit/test_close_orders_at_discharge_2606.py` |
| Both run in one POST_ENCOUNTER enricher, after every module that places orders. | `supersede.py::enrich_supersede_orders` | `tests/unit/test_supersede_medication_orders_2615.py` |

## 6. Discharge and home medications

| Rule | Canonical code | Guard |
|---|---|---|
| The discharge prescription is built from the protocol's discharge medications and the continued home medications, without the drugs held for renal function. | `simulator/discharge_rx.py::build_discharge_rx` | `tests/unit/test_build_discharge_rx_continue_at_discharge.py`, `tests/unit/test_discharge_rx_drug_safety_1334.py`, `tests/unit/test_discharge_oral_route_integrity.py` |
| Discharge, activation of home medications and the longitudinal history reconcile against one rule list: a second agent of a class a listed rule names is not added (one statin, one P2Y12 inhibitor, one anticoagulant, no ACE inhibitor with an ARB). | `modules/drug_safety/engine.py::discharge_reconciliation_rules`; callers `discharge_rx.py`, `modules/patient/activator.py`, `modules/longitudinal/engine.py` | `tests/unit/test_discharge_reconciliation_2713.py` |
| With an oral anticoagulant, dual antiplatelet therapy becomes the anticoagulant + clopidogrel and aspirin a short course, at discharge and at activation of home medications. | `discharge_rx.py::limit_triple_antithrombotic`; plan `contraindications.yaml` `triple_therapy_after_acs` | `tests/unit/test_limit_triple_therapy_2717.py` |
| A finite course (≤ 14 days) on the discharge prescription is not carried into the home medications. | `simulator/helpers.py` (`_ACUTE_COURSE_MAX_DAYS`) | none (§8) |
| The status of a take-home prescription (active, completed, stopped), its end date and the prescription it replaced are computed once, across all the patient's records and the snapshot, before the bundles are built. | `modules/order/prescription_supersede.py::prescription_closures`, passed as `BundleContext.rx_closures` | `tests/unit/test_prescription_renewal_2610.py` |

## 7. Product coding

| Rule | Canonical code | Guard |
|---|---|---|
| JP: the YJ product code is chosen by the order's route class from the drug catalog (`codes.yj` per route class). A drug with no product for the route goes to the eCS no-code slice. | `codes/drugs.py::jp_drug_code`, `jp_drug_code_table` | `tests/unit/test_jp_drug_codes_2347.py` |
| US: the RxNorm clinical drug (SCD) is chosen by drug, route class and dose (dose = 1-4 units of one strength); the ingredient code follows it. No SCD is stated when no single product fits the dose. | `codes/drugs.py::rxnorm_scd_code`, table `codes/data/rxnorm_scd.yaml` (generated by `scripts/refresh_rxnorm_scd.py`); applied by `fhir_r4/medications/medications.py::_apply_rxnorm_scd` | `tests/unit/codes/test_rxnorm_scd_2614.py` |

## 8. Gaps

| Gap | Where |
|---|---|
| The discharge carry-forward of finite courses keys on `duration_days` with a constant in Python and has no test of its own. | `simulator/helpers.py` |
