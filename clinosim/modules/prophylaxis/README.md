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
encounters ≥ 48 h, with rule-based skip when patient is already on
therapeutic anticoagulation (warfarin / DOAC / heparin drip) or the
admission dx is active bleeding / recent hemorrhagic stroke / GI
bleed / delivery / active DVT-PE treatment.

**Out of scope (post-MVP)**:
- Stress-ulcer prophylaxis (PPI on ICU) — separate protocol.
- VAP bundle (head-of-bed elevation, chlorhexidine mouthcare) —
  belongs to nursing enricher.
- Mechanical prophylaxis (intermittent pneumatic compression) fallback
  for bleeding-contraindicated patients — deferred; current design
  simply skips.
- MedicationAdministration rows for the prophylaxis order — the
  MedicationRequest alone is the load-bearing FHIR signal; MAR
  generation runs through the existing daily-loop path when the sim
  detail level warrants it.

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
# → [{"order_id": "ORD-...-DVT-01", "display_name": "Enoxaparin", ...}]
```

## Determinism

Pure YAML lookup + rule dispatch. No RNG consumption. Given a fixed
(patient, encounter, admission_dx) tuple, the output is byte-identical
across runs.

## Dependencies

- `clinosim.types.encounter` (Order shape reference — but this module
  emits dict-shaped orders that the downstream Order dataclass constructor
  reads via `_shared.get_attr_or_key`)
- Third-party: PyYAML only.

## Constants and configuration

`reference_data/prophylaxis_rules.yaml`:
- `dvt_prophylaxis` block: drug / dose / route / frequency / LOS threshold
- `skip_conditions` block: 4 rules (therapeutic AC / active bleed /
  perinatal delivery / active DVT-PE treatment) with drug needles or
  ICD prefixes

Schema-level guidance: every skip condition MUST document its clinical
rationale and MUST map to code in `engine.should_skip_dvt_prophylaxis`.
Adding a new skip condition is a two-step change (yaml + Python
dispatch) — the yaml alone does not activate a rule.

## Directory contents

```
clinosim/modules/prophylaxis/
├── __init__.py            # public API re-export
├── engine.py              # rule loader + skip dispatch + order builder
├── enricher.py            # POST_ENCOUNTER order 75 entrypoint
├── reference_data/
│   └── prophylaxis_rules.yaml
└── README.md              # this file
```

## Enricher wiring

Registered in `clinosim/simulator/enrichers.py` as:

- Stage: POST_ENCOUNTER
- Order: 75 (after `device` 70, before `hai` 80)
- Sub-seed: `0x5052` ("PR") in `clinosim/seeding.py::ENRICHER_SEED_OFFSETS`
- Enabled: always-on (matches DVT prophylaxis being universal standard-of-care)

## Output surfaces

- `record.orders` gets one appended Order (dict-shaped) per eligible
  encounter. The order flows through the standard FHIR
  `MedicationRequest` builder without any new adapter.

## Testing

Unit tests: `tests/unit/test_prophylaxis.py` covering
- Short-LOS encounter → no order
- Therapeutic-AC patient → skipped with correct reason
- Active hemorrhage dx → skipped
- Delivery dx (Z37/Z38) → skipped
- Active DVT/PE dx → skipped (own therapy replaces prophylaxis)
- Normal J18 pneumonia IMP ≥ 48 h → order emitted

## Ownership

Session 99 (2026-09-04). Spec: session-99 conversation.
Issue: #1071.
