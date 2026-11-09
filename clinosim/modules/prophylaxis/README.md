# `clinosim.modules.prophylaxis`

Standard-of-care VTE (DVT) chemoprophylaxis for inpatient stays ≥ 48 h.

## Purpose

Real ward protocols require every inpatient staying ≥ 48 h to be
assessed for VTE prophylaxis; the standard-of-care regimen for the
non-contraindicated majority is Enoxaparin 40 mg SC daily. Prior to
this module, only 14/32 disease YAMLs listed DVT prophylaxis under
`supportive_orders:`, leaving ~40 % of IMP ≥ 48 h encounters without
prophylaxis (US p=2000 seed=500 baseline: 40/103 uncovered).

## Scope

**In scope**: DVT (VTE) chemoprophylaxis Order emission for IMP
encounters ≥ 48 h, plus its daily MedicationAdministration rows
(Issue #2607 — one dose at `administration_hour` from the order until
discharge, given by a ward nurse picked with
`order.placed_order_mar.stable_nurse`), with rule-based skip when the patient is below the
pediatric age ceiling (default 18), is already on therapeutic
anticoagulation (warfarin / DOAC / heparin drip), the admission dx is
active bleeding / recent hemorrhagic stroke / GI bleed / delivery /
active DVT-PE treatment, or Enoxaparin would form a major /
contraindicated pair with an active medication
(`drug_safety.check_candidate_against_active`, Issue #1087).

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
orders = build_dvt_prophylaxis_orders(record=cif_record)
# → [Order(order_id="ORD-<encounter_id>-DVT-01", display_name="Enoxaparin", ...)]
```

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
- `dvt_prophylaxis` block: drug / dose / route / frequency / LOS
  threshold / `administration_hour` (MAR dose time, Issue #2607)
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
- Delivery dx (Z37/Z38) → skipped
- Active DVT/PE dx → skipped (own therapy replaces prophylaxis)
- Pediatric (age < 18) admission → skipped (Issue #1276, #3082)
- Chronic aspirin / in-encounter NSAID → skipped via drug_safety pair (Issue #1087)
- Normal J18 pneumonia IMP ≥ 48 h → order emitted

## Ownership

2026-09-04. Issue: #1071.

Japanese counterpart: [`README.ja.md`](README.ja.md).
