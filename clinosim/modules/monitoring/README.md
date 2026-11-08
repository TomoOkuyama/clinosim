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
  POST_RECORDS time, matching each medication to the rules in
  `medication_monitoring.yaml` by drug-catalog identity, injecting each
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

`__all__` (re-exported from `__init__.py`) is the chronic-visit lab-list
path:

```python
from clinosim.modules.monitoring import (
    load_medication_lab_mapping,     # () -> {rule: {drugs, classes, labs, per_visit_probability}} (lru_cache)
    monitoring_labs_for_patient,     # (current_medications, visit_key) -> list[str] lab names
)
```

The POST_RECORDS enricher path is reached through its submodules (not
re-exported):

```python
from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import (
    load_medication_monitoring,      # (path=None) -> {rule: {per_visit_probability, drugs, classes, monitoring: [...]}}
    match_drugs,                     # (current_medications, mapping) -> list[str] matched rule names
    matched_medication_names,        # (current_medications, mapping) -> {rule: (name_en, name_ja)}
    monitoring_lab_code,             # (lab) -> LOINC from locale/us/code_mapping_lab.yaml
)
```

Both paths read the same `medication_monitoring.yaml` (Issue #2786).
`monitoring_labs_for_patient` (in `engine.py`) is called from
`clinosim/simulator/phases/_healthcare_calendar.py` for each
`chronic_visit` event with `visit_key = "<patient_id>:<visit time>"`;
the returned labs are merged into the visit's `visit_labs`.

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
- Chronic-visit path: each rule's `per_visit_probability` gate is
  `determinism.sha_bernoulli(f"monitoring:{visit_key}:{rule}", p)` —
  draw-free, so it consumes neither the visit's `ev_rng` nor the
  enricher sub-seed, and adding a rule shifts no other draw.

## Dependencies

- `clinosim.determinism` — `sha_bernoulli` (chronic-visit gate) and
  the enricher's RNG construction.
- `clinosim.codes.drugs` — `medication_matches` (catalog-identity
  drug matching, Issue #2371), `drug_display`.
- `clinosim.datafiles` — `load_validated_yaml`.
- `clinosim.locale.loaders.demographics` — `load_code_mapping`
  (lab LOINC lookup).
- `clinosim.locale.i18n` — `t`; `clinosim.locale.localized` —
  `language_slot`, `localized_field`.
- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.modules.observation.engine` — `canonical_lab_name`,
  `generate_lab_result`, `get_lab_unit`, `is_qualitative_test`,
  `determine_flag` (the single lab-emission surface).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`,
  `individual_lab_seed`.
- `clinosim.types.encounter` — `EncounterType`, `Order`,
  `OrderResult`, `OrderStatus`.
- `pydantic`, `numpy`.

Callers: `clinosim/simulator/enrichers.py` (enricher registration) and
`clinosim/simulator/phases/_healthcare_calendar.py`
(`monitoring_labs_for_patient`).

## Constants and configuration

- [`reference_data/medication_monitoring.yaml`](reference_data/medication_monitoring.yaml)
  — the one drug → labs table for both paths, under a top-level
  `mappings:` key. Each entry:
  ```yaml
  mappings:
    <Rule label>:
      per_visit_probability: <0..1, chronic-visit gate (Issue #2786)>
      drugs:          [<catalog drug_id>, ...]       # drugs and/or classes (Issue #2371)
      classes:        [<catalog drug class>, ...]
      monitoring:
        - lab:             <internal analyte name — a key of locale/us/code_mapping_lab.yaml>
          interval_months: <int >= 1, minimum months between draws (Issue #2143)>
          rationale:
            en: "<one-sentence clinical justification>"
            ja: "<Japanese rationale>"
  ```
  A medication matches a rule by catalog identity
  (`codes.drugs.medication_matches`): its `drug_id`, or the drug its
  name resolves to through the catalog aliases, is in `drugs` or
  belongs to one of `classes` — so `"Warfarin 3mg PO"`,
  `"ワルファリン"` and `"Coumadin"` all match the Warfarin rule. The
  order code is not declared in the yaml: it is the lab's LOINC from
  `locale/us/code_mapping_lab.yaml` (Issue #2301).
- Loader lives in [`mapping.py`](mapping.py)
  (`load_medication_monitoring`) — cache-less (called once per
  POST_RECORDS pass), validated at load against the `extra="forbid"`
  Pydantic model `_MonitoringFile` (`_MonitoringRule`,
  `_MonitoringLab`, `_Rationale`) so a YAML typo, an unknown drug or
  class, or a lab with no code fails loud instead of surfacing as a
  silent "drug never matched" downstream.
  `engine.load_medication_lab_mapping` (cached) projects the same
  table into `{drugs, classes, labs, per_visit_probability}` for the
  chronic-visit path.

## Directory contents

```
clinosim/modules/monitoring/
  __init__.py                        re-exports load_medication_lab_mapping + monitoring_labs_for_patient
  engine.py                          load_medication_lab_mapping + monitoring_labs_for_patient (chronic-visit path)
  enricher.py                        enrich_medication_monitoring (POST_RECORDS)
  mapping.py                         _MonitoringFile model, load_medication_monitoring, match_drugs, matched_medication_names, monitoring_lab_code
  reference_data/
    medication_monitoring.yaml       drug → monitoring-labs table (both paths)
```

The module has **no `audit.py`**.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`register_builtin_enrichers`):

- `name="medication_monitoring"`, `stage=POST_RECORDS`, `order=65`,
  `enabled=lambda c: True`.
- Runs after `care_level` (order=60) and before `health_checkup`
  (order=70) — after all other cross-record enrichers have
  populated the record shape but before the JP-only opt-in
  `health_checkup` encounter appends its own CHECKUP encounter.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) (`register_builtin_enrichers`) | POST_RECORDS order=65 registration. |
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
