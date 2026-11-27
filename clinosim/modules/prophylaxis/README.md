# `clinosim.modules.prophylaxis`

Standard-of-care VTE (DVT) chemoprophylaxis for inpatient stays ≥ 48 h.

## Purpose

Real ward protocols require every inpatient staying ≥ 48 h to be
assessed for VTE prophylaxis; the standard-of-care regimen for the
non-contraindicated majority in the US is Enoxaparin 40 mg SC daily
(30 mg daily when the Cockcroft-Gault creatinine clearance is below
30 mL/min); in Japan enoxaparin is labelled only for orthopedic /
abdominal surgery, so a medical inpatient gets low-dose unfractionated
heparin (5,000 units SC every 12 hours). Prior to
this module, only 14/32 disease YAMLs listed DVT prophylaxis under
`supportive_orders:`, leaving ~40 % of IMP ≥ 48 h encounters without
prophylaxis (US p=2000 seed=500 baseline: 40/103 uncovered).

## Scope

**In scope**: DVT (VTE) chemoprophylaxis Order emission for IMP
encounters ≥ 48 h, plus its daily MedicationAdministration rows
(Issue #2607 — a dose at each of the regimen's `administration_hours`
from the order until discharge or until the order that replaces it, given by a ward nurse picked with
`order.placed_order_mar.stable_nurse`), with rule-based skip when the patient is below the
pediatric age ceiling (default 18), is already on therapeutic
anticoagulation (warfarin / DOAC / heparin drip), the admission dx is
active bleeding / recent hemorrhagic stroke / GI bleed / delivery /
active DVT-PE treatment, or Enoxaparin would form a major /
contraindicated pair with an active medication
(`drug_safety.check_candidate_against_active`, Issue #1087). A therapeutic
anticoagulant a complication started during the stay (order id with
`-COMPTX-`, Issue #3864) does not remove the prophylaxis given before it: the
prophylaxis ends at that order (and is not given when it was earlier); a stop
marker for the prophylaxis drug written by a bleeding complication cuts its
doses after the stay (`order.supersede.drop_doses_after_hold`).

**Out of scope (post-MVP)**:
- Stress-ulcer prophylaxis (PPI on ICU) — separate protocol.
- VAP bundle (head-of-bed elevation, chlorhexidine mouthcare) —
  belongs to nursing enricher.
- Mechanical prophylaxis (intermittent pneumatic compression) fallback
  for bleeding-contraindicated patients — deferred; current design
  simply skips.

## Public API

```python
from clinosim.modules.prophylaxis import (
    build_dvt_prophylaxis_orders,
    should_skip_dvt_prophylaxis,
)

# Skip-decision helper (pure function on patient / encounter state)
skip, reason = should_skip_dvt_prophylaxis(
    patient=patient_profile,
    encounter=encounter,
    admission_dx_code="J18.1",
    active_medications=["Warfarin 3mg PO daily"],
)
# → (True, "therapeutic_anticoagulant_active")

# Order builder for a CIF record
orders = build_dvt_prophylaxis_orders(record=cif_record, country="US")
# → [Order(order_id="ORD-<encounter_id>-DVT-01", display_name="Enoxaparin", ...)]
```

## Regimen by country and renal function (Issue #3449)

`dvt_prophylaxis.regimens` in the YAML holds one regimen per country (a
country without one uses `default_country`):

- **US**: Enoxaparin 40 mg SC once daily (Lovenox label, 2.2, medical patients
  during acute illness); **30 mg once daily while the Cockcroft-Gault CrCl is
  below 30 mL/min** (label 2.3 Table 1, 8.7). No adjustment at 30 mL/min or
  above.
- **JP**: Heparin 5,000 units SC every 12 hours (`q12h`, doses at 09:00 and
  21:00). Enoxaparin (クレキサン) is approved in Japan only for lower-limb
  orthopedic and high-risk abdominal surgery and is contraindicated at CrCl <
  30 mL/min (package insert 2.4, 4.), so it is not used for a medical
  inpatient; the unfractionated heparin insert indicates 血栓塞栓症の治療及び
  予防 and the JCS 2017 PTE/DVT guideline (3.4) gives 5,000 units every 8 or
  12 hours for any underlying disease. Surgical enoxaparin (2,000 IU twice
  daily) is not modelled: the order is placed 6 h after admission whatever
  the surgery time, while the label starts it 24-36 h after surgery.

The creatinine clearance (`renal_dose.crcl_cockcroft_gault`, terms in the
YAML `creatinine_clearance` block) uses the encounter's charted weight, the
age at admission and the latest creatinine at or before the order time (no
creatinine: the standard dose). The first later creatinine that puts the CrCl
below the threshold stops the order at its result time and places a new order
(`...-DVT-02`, `prior_order_id` set) with the reduced dose; the dose is reduced
once and stays reduced for the rest of the stay (a noisy later value does not
step it back up).

## Determinism

Pure YAML lookup + rule dispatch. No RNG consumption — the MAR
times are fixed (`daily_times`) and the giving nurse is a stable
function of the order id (`stable_nurse`). Given a fixed
(patient, encounter, admission_dx) tuple, the output is byte-identical
across runs.

## Dependencies

- `clinosim.types.encounter` (`Order` / `OrderType` / `OrderStatus` —
  the builder emits real `Order` dataclasses)
- `clinosim.modules.drug_safety.engine.check_candidate_against_active`
  (pair check against active medications; failures are swallowed so
  prophylaxis is never blocked by a drug_safety error)
- `clinosim.modules.order.placed_order_mar` — `daily_times`,
  `stable_nurse`, `administrations_for` (enricher MAR rows);
  `clinosim.modules.order.absolute_dose.is_continuous_infusion`
- `clinosim.codes.drugs.medication_matches`,
  `clinosim.datafiles.load_data_yaml`,
  `clinosim.locale.localized` (`language_slot`, `localized_field`)
- Third-party: pydantic (`_ProphylaxisRules`, `_SkipRule` validate the
  rules yaml at load).

## Constants and configuration

`reference_data/prophylaxis_rules.yaml`:
- `dvt_prophylaxis` block: LOS threshold, intent text, and per-country
  `regimens` (drug / dose / route / frequency / `administration_hours` (MAR
  dose times, Issue #2607) / optional `renal_adjustment`: `crcl_below_ml_min`
  and the reduced `dose_quantity`, Issue #3449)
- `creatinine_clearance` block: Cockcroft-Gault terms (age offset,
  denominator, female factor, creatinine unit)
- `skip_conditions` block: 5 rules (therapeutic AC / active bleed /
  perinatal delivery / active DVT-PE treatment / pediatric age gate)
  with drug needles, ICD prefixes, or `pediatric_age_ceiling` (18).
  The drug_safety pair check is code-only (no yaml block).

Schema-level guidance: every skip condition MUST document its clinical
rationale and MUST map to code in `engine.should_skip_dvt_prophylaxis`.
Adding a new skip condition is a two-step change (yaml + Python
dispatch) — the yaml alone does not activate a rule.

## Directory contents

```
clinosim/modules/prophylaxis/
├── __init__.py            # public API re-export
├── engine.py              # rule loader + skip dispatch + order builder
├── renal_dose.py          # Cockcroft-Gault, creatinine series, dose periods (pure)
├── enricher.py            # POST_ENCOUNTER order 75 entrypoint + daily MAR rows
├── reference_data/
│   └── prophylaxis_rules.yaml
├── README.md              # this file
└── README.ja.md
```

## Enricher wiring

Registered in `clinosim/simulator/enrichers.py` as:

- Stage: POST_ENCOUNTER
- Order: 75 (after `device` 70, before `hai` 80)
- Sub-seed: `0x5052` ("PR") is reserved in
  `clinosim/seeding.py::ENRICHER_SEED_OFFSETS`, but the enricher
  consumes no RNG and does not read it
- Enabled: always-on (matches DVT prophylaxis being universal standard-of-care)

## Output surfaces

- `record.orders` gets one appended `Order` dataclass per eligible
  encounter. The order flows through the standard FHIR
  `MedicationRequest` builder without any new adapter.
- `record.medication_administrations` gets the order's daily
  `MedicationAdministration` rows (status `given`, `administered_by`
  set), emitted as FHIR `MedicationAdministration`.

## Testing

Unit tests: `tests/unit/test_prophylaxis.py` covering
- Short-LOS / non-inpatient encounter → no order
- Therapeutic-AC patient → skipped with correct reason
- Active hemorrhage dx → skipped
- Delivery dx (O chapter / Z37 / Z38) → skipped
- Active DVT/PE dx → skipped (own therapy replaces prophylaxis)
- Pediatric (age < 18) admission → skipped (Issue #1276, #3082)
- Chronic aspirin / in-encounter NSAID → skipped via drug_safety pair (Issue #1087)
- Normal J18 pneumonia IMP ≥ 48 h → order emitted

`tests/unit/test_prophylaxis_renal_dose_3449.py` covers the Cockcroft-Gault
value, the US 40 mg / 30 mg doses by CrCl, the order split on a rising creatinine
(reduced once, kept when it recovers), MAR doses per order period, and the JP heparin regimen.

## Ownership

2026-09-04. Issue: #1071.

Japanese counterpart: [`README.ja.md`](README.ja.md).
