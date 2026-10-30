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
  the drug + aliases in `medication_monitoring.yaml`, injecting each
  mapped monitoring lab into the record's target encounter (first
  outpatient encounter, else first encounter) unless the patient had
  that analyte drawn within the lab's `interval_months` (Issue #2143 —
  records are walked per patient in time order), per-encounter dedup so disease-YAML flows that legitimately order
  the same analyte (INR under sepsis / PE / GI bleed) are respected
  and not double-emitted.
- **Out of scope**: chronic-medication attachment
  ([`clinosim.modules.patient`](../patient/README.md) activator);
  disease-YAML lab orders
  ([`clinosim.modules.order`](../order/README.md)); lab-value
  derivation itself
  ([`clinosim.modules.observation`](../observation/README.md));
  FHIR emission
  ([`clinosim.modules.output`](../output/README.md)); induction vs
  maintenance cadence (only a fixed minimum `interval_months` per
  lab is modelled).

## Public API

The module has two independent paths:

```python
# 1. POST_RECORDS enricher path (medication_monitoring.yaml)
from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import (
    load_medication_monitoring,      # (path=None) -> {drug_name: {aliases, drug_ja, monitoring: [...]}}
    match_drugs,                     # (current_medications, mapping) -> list[str] canonical drug names
)

# 2. Chronic-visit lab-list path (med_lab_mapping.yaml), re-exported from __init__.py
from clinosim.modules.monitoring import (
    load_medication_lab_mapping,     # () -> {entry: {matches, labs, per_visit_probability}} (lru_cache)
    monitoring_labs_for_patient,     # (current_medications, rng) -> list[str] lab names
)
```

`monitoring_labs_for_patient` (in `engine.py`) is called from
`clinosim/simulator/phases/_healthcare_calendar.py` for each
`chronic_visit` event: the returned labs are merged into the visit's
`visit_labs`, each mapping entry gated by its `per_visit_probability`
on the visit's `ev_rng` (so it consumes the visit RNG stream, not the
enricher sub-seed).

## Determinism

- Sub-seed offset `0x4D4D` (`"MM"`) — registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["medication_monitoring"]`.
- Enricher path: per-patient sub-RNG via
  `derive_sub_seed(master_seed, offset, patient_id)` — master RNG
  untouched (matches the `care_level` / `family_history` pattern).
- Per-lab noise draws go through
  `individual_lab_seed(order_id)` from
  [`clinosim/seeding.py`](../../seeding.py) — the AD-59 per-order
  isolation used by `outpatient.py` and `inpatient.py` Pass 1.
- The synthetic order id is content-derived
  (`ORD-<encounter_id>-MED-MON-<NN>`) so it stays stable across
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

Callers: `clinosim/simulator/enrichers.py` (enricher registration) and
`clinosim/simulator/phases/_healthcare_calendar.py`
(`monitoring_labs_for_patient`).

## Constants and configuration

- [`reference_data/medication_monitoring.yaml`](reference_data/medication_monitoring.yaml)
  — drug → labs mapping for the enricher, under a top-level
  `mappings:` key. Each entry:
  ```yaml
  mappings:
    <Drug canonical name>:
      aliases:        [<optional case-insensitive substring matches>]
      drug_ja:        "<Japanese drug display>"            # optional (Issue #871)
      monitoring:
        - lab:             <internal analyte name — matches observation engine>
          interval_months: <int >= 1, minimum months between draws (Issue #2143)>
          loinc:           "<LOINC code>"
          rationale:       "<one-sentence clinical justification>"
          rationale_ja:    "<Japanese rationale>"          # optional (Issue #871)
  ```
  Aliases are matched case-insensitively via substring, mirroring
  `physiology.engine._WARFARIN_NAMES` — so `"Warfarin 3mg PO"`,
  `"ワルファリン"`, and `"WARFARIN"` all match the Warfarin entry.
- Loader lives in [`mapping.py`](mapping.py) — intentionally
  cache-less (small file, called once per POST_RECORDS pass) and
  parsed into plain dicts (no Pydantic) to match the sibling
  `sdoh.load_social_history` loader style. Fail-loud on missing
  required keys so a YAML typo surfaces at load time rather than
  as a silent "drug never matched" downstream (`lab`, `loinc` and an
  integer `interval_months >= 1` are required per monitoring row).
- [`reference_data/med_lab_mapping.yaml`](reference_data/med_lab_mapping.yaml)
  — chronic-visit mapping for `monitoring_labs_for_patient`, under a
  top-level `medication_lab_mapping:` key; each entry has `matches`
  (substring patterns over `drug_name` / `drug_name_ja`), `labs`
  (canonical analyte names) and `per_visit_probability`. Loaded by
  `engine.load_medication_lab_mapping` (cached, fail-loud).

## Directory contents

```
clinosim/modules/monitoring/
  __init__.py                        re-exports load_medication_lab_mapping + monitoring_labs_for_patient
  engine.py                          load_medication_lab_mapping + monitoring_labs_for_patient (chronic-visit path)
  enricher.py                        enrich_medication_monitoring (POST_RECORDS)
  mapping.py                         load_medication_monitoring + match_drugs
  reference_data/
    medication_monitoring.yaml       drug → monitoring-labs mapping (enricher)
    med_lab_mapping.yaml             medication → chronic-visit labs mapping (engine)
```

The module has **no `audit.py`**.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L288-308`):

- `name="medication_monitoring"`, `stage=POST_RECORDS`, `order=65`,
  `enabled=lambda c: True`.
- Runs after `care_level` (order=60) and before `health_checkup`
  (order=70) — after all other cross-record enrichers have
  populated the record shape but before the JP-only opt-in
  `health_checkup` encounter appends its own CHECKUP encounter.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:301`](../../simulator/enrichers.py) | POST_RECORDS order=65 registration. |
| Chronic-visit scheduler | [`clinosim/simulator/phases/_healthcare_calendar.py`](../../simulator/phases/_healthcare_calendar.py) | Calls `monitoring_labs_for_patient` per `chronic_visit` event. |
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
- [`tests/unit/test_monitoring_intervals.py`](../../../tests/unit/test_monitoring_intervals.py)
  — `interval_months` scheduling (Issue #2143).
- [`tests/unit/test_monitoring_doac.py`](../../../tests/unit/test_monitoring_doac.py)
  — DOAC → eGFR mapping.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
