# `clinosim.modules.monitoring` — chronic-medication-driven monitoring labs

## Purpose

Injects the standard-of-care monitoring labs a chronic medication
requires (Warfarin → PT-INR is the canonical example) into a
patient's encounters at POST_RECORDS time, closing the gap Issue #736
opened and captured under META Issue #757. Before this module, the
simulator's lab sources were disease-YAML `laboratory` blocks,
per-encounter admission / discharge protocol, and antibiotic-driven
orders — none of them consulted `patient.current_medications`, so
a warfarin patient whose only encounter was outpatient HTN follow-up
got no PT-INR at all.

## Scope

- **In scope**: reading each patient's `current_medications` at
  POST_RECORDS time, case-insensitive substring matching against
  the drug + aliases in `medication_monitoring.yaml`, injecting one
  monitoring lab per eligible encounter (MVP scope — frequency /
  cadence scheduling is deferred to a follow-up PR under META #757),
  per-encounter dedup so disease-YAML flows that legitimately order
  the same analyte (INR under sepsis / PE / GI bleed) are respected
  and not double-emitted.
- **Out of scope**: chronic-medication attachment
  ([`clinosim.modules.patient`](../patient/README.md) activator);
  disease-YAML lab orders
  ([`clinosim.modules.order`](../order/README.md)); lab-value
  derivation itself
  ([`clinosim.modules.observation`](../observation/README.md));
  FHIR emission
  ([`clinosim.modules.output`](../output/README.md)); frequency
  scheduling (daily vs monthly, induction vs maintenance) —
  planned for META #757 pass 3+.

## Public API

The module's `__init__.py` carries only the package docstring;
consumers import from the submodules:

```python
from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import (
    load_medication_monitoring,      # () -> {drug_name: {aliases, monitoring: [...]}}
    match_drugs,                     # (current_medications) -> list[matched drug entry]
)
```

## Determinism

- Sub-seed offset `0x4D4D` (`"MM"`) — registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["medication_monitoring"]`.
- Per-patient sub-RNG via
  `derive_sub_seed(master_seed, offset, patient_id)` — master RNG
  untouched (matches the `care_level` / `family_history` pattern).
- Per-lab noise draws go through
  `individual_lab_seed(order_id)` from
  [`clinosim/seeding.py`](../../seeding.py) — the AD-59 per-order
  isolation used by `outpatient.py` and `inpatient.py` Pass 1.
- The synthetic order id is content-derived
  (`<encounter_id>-MED-MON-<idx>`) so it stays stable across
  repeated runs on the same seed.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.modules.observation.engine` — `canonical_lab_name`,
  `generate_lab_result`, `get_lab_unit`, `determine_flag` (the
  single lab-emission surface).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`,
  `individual_lab_seed`.
- `clinosim.types.encounter` — `EncounterType`, `Order`,
  `OrderResult`, `OrderStatus`.
- `yaml`, `numpy`.

## Constants and configuration

- [`reference_data/medication_monitoring.yaml`](reference_data/medication_monitoring.yaml)
  — drug → labs mapping. Each entry:
  ```yaml
  <Drug canonical name>:
    aliases:        [<optional case-insensitive substring matches>]
    monitoring:
      - lab:        <internal analyte name — matches observation engine>
        loinc:      "<LOINC code>"
        rationale:  "<one-sentence clinical justification>"
  ```
  Aliases are matched case-insensitively via substring, mirroring
  `physiology.engine._WARFARIN_NAMES` — so `"Warfarin 3mg PO"`,
  `"ワルファリン"`, and `"WARFARIN"` all match the Warfarin entry.
- Loader lives in [`mapping.py`](mapping.py) — intentionally
  cache-less (small file, called once per POST_RECORDS pass) and
  parsed into plain dicts (no Pydantic) to match the sibling
  `sdoh.load_social_history` loader style. Fail-loud on missing
  required keys so a YAML typo surfaces at load time rather than
  as a silent "drug never matched" downstream.

## Directory contents

```
clinosim/modules/monitoring/
  __init__.py                        package docstring only
  enricher.py                        enrich_medication_monitoring (POST_RECORDS)
  mapping.py                         load_medication_monitoring + match_drugs
  reference_data/
    medication_monitoring.yaml       drug → monitoring-labs mapping
```

The module has **no `engine.py`, no `audit.py`** — the enricher
entry point is in `enricher.py` and mapping helpers are in
`mapping.py`.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L213-231`):

- `name="medication_monitoring"`, `stage=POST_RECORDS`, `order=65`,
  `enabled=lambda c: True`.
- Runs after `care_level` (order=60) and before `health_checkup`
  (order=70) — after all other cross-record enrichers have
  populated the record shape but before the JP-only opt-in
  `health_checkup` encounter appends its own CHECKUP encounter.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:226`](../../simulator/enrichers.py) | POST_RECORDS order=65 registration. |
| Observation engine | [`clinosim/modules/observation/engine.py`](../observation/engine.py) | `generate_lab_result` + `determine_flag` + `get_lab_unit` produce the emitted lab value. |
| Downstream FHIR + CSV | (via generated `Order` / `OrderResult`) | The injected orders flow through the standard lab-emission path. |

## Testing

```bash
pytest tests/unit -k medication_monitoring -q
```

Individual files:

- [`tests/unit/test_medication_monitoring.py`](../../../tests/unit/test_medication_monitoring.py)
  — mapping load, drug matching (case + JA), per-encounter dedup,
  determinism.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
