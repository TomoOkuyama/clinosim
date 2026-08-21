# `clinosim.modules.observation` — lab results, nursing flowsheets, microbiology

## Purpose

Owns three related emission-layer concerns for observed clinical data:

1. **Lab-value engine** (`engine.py`) — canonical lab naming +
   panel decomposition (`lab_aliases.yaml`, `lab_panels.yaml`),
   sex-banded reference ranges, physiologic clamping,
   noise / variability injection, precision rounding, and reference-
   range flag assignment. `generate_lab_result` is the single
   emission point every simulator uses to write a lab
   `OrderResult`.
2. **Nursing flowsheet observations** (`nursing.py` +
   `nursing_enricher.py`) — NEWS2 / GCS / Braden pressure-ulcer /
   Morse fall-risk score computation from vital + ADL data, plus
   the POST_RECORDS `enrich_nursing` enricher registered under
   `name="nursing"` in `simulator/enrichers.py`. (Distinct from the
   `nursing_assignment` enricher owned by
   [`clinosim.modules.nursing`](../nursing/README.md), which
   assigns `primary_nurse_id`.)
3. **Microbiology cultures + susceptibility** (`microbiology.py`) —
   deterministic culture organism sampling, S/I/R susceptibility
   generation from the antibiogram, HAI-event backref via
   `hai_event_id` (PR3b-2 chain).

Companion threshold files (`fluid_balance.py`, `oxygenation.py`,
`pre_analytical.py`, `vitals_thresholds.py`,
`_nursing_score_thresholds.py`, `_variability_defaults.py`) lift
every previously-inline scalar so a single edit propagates.

## Scope

- **In scope**: `canonical_lab_name` + `lab_panel_components`
  (single edit points for lab-alias resolution and panel expansion);
  `generate_lab_result` (baseline + noise + clamp + rounding +
  reference-range flag); `apply_realistic_variability`,
  `clamp_to_physiologic_limits`, `round_to_precision`,
  `determine_flag`, `_generate_qualitative_result`,
  `_reference_ranges_by_sex`; `get_lab_unit`;
  `compute_news2` / `compute_gcs` / `compute_braden` /
  `compute_morse_fall_risk` (nursing scores);
  `enrich_nursing` POST_RECORDS enricher (fills NEWS2/GCS on each
  vital, generates daily Braden/Morse);
  `has_microbiology(disease_id)` + `generate_microbiology(...)` +
  `antibiotic_loinc_lookup()`; four threshold sub-modules with
  clinical citations.
- **Out of scope**: physiology state that drives lab values
  ([`physiology`](../physiology/README.md)); order placement
  ([`order`](../order/README.md)); vitals / imaging derivation
  (drivers in [`physiology`](../physiology/README.md) +
  `simulator/vitals_pipeline.py`); FHIR emission
  ([`output`](../output/README.md)); microbiology antibiotic
  regimen selection ([`antibiotic`](../antibiotic/README.md)).

## Public API

`__init__.py` is empty; consumers import from the four submodules
directly:

```python
# Lab engine
from clinosim.modules.observation.engine import (
    canonical_lab_name,                  # (name) -> canonical str
    lab_panel_components,                # (panel_name) -> list[str]
    get_lab_unit,                        # (lab_name) -> unit str
    clamp_to_physiologic_limits,         # (lab_name, value) -> float
    apply_realistic_variability,         # (lab_name, value, rng) -> float
    round_to_precision,                  # (lab_name, value) -> float
    generate_lab_result,                 # (lab_name, state, patient, rng, **flags) -> OrderResult
    determine_flag,                      # (lab_name, value, sex, country) -> "L" | "H" | ""
)

# Nursing flowsheet
from clinosim.modules.observation.nursing import (
    compute_news2,                       # (vs: dict) -> int
    compute_gcs,                         # (consciousness_level, perfusion_status, rng) -> int
    compute_braden,                      # (adl, consciousness_level, volume_status, rng) -> dict
    compute_morse_fall_risk,             # (…) -> dict
)
from clinosim.modules.observation.nursing_enricher import enrich_nursing

# Microbiology
from clinosim.modules.observation.microbiology import (
    has_microbiology,                    # (disease_id) -> bool
    generate_microbiology,               # (…) -> list[MicrobiologyResult]
    antibiotic_loinc_lookup,             # () -> dict[antibiotic_key, LOINC code]
)
```

## Determinism

- Sub-seed offset `0x4E55` (`"NU"`) is registered in
  [`clinosim/seeding.py`](../../seeding.py) as
  `ENRICHER_SEED_OFFSETS["nursing"]` and shared between this
  module's `enrich_nursing` (POST_RECORDS order=20, registered as
  `name="nursing"`) and the primary-nurse enricher in
  [`clinosim.modules.nursing`](../nursing/README.md)
  (POST_ENCOUNTER order=94, registered as `name="nursing_assignment"`).
  The two enrichers run in different stages, so the shared offset
  does not conflict.
- Microbiology sampling uses an **encounter-scoped** sub-seed
  derived per `hai_event_id` / encounter, so `generate_microbiology`
  can be extended with new organisms without shifting unrelated
  patients' streams (PR3b-2 pattern).
- Lab-result variability is called with a **per-order** RNG
  (`simulator/seeding.py:panel_specimen_seed` /
  `individual_lab_seed` — AD-59), not the patient master RNG, so
  YAML edits adding a new analyte are byte-clean for unrelated
  patients.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`, `set_attr_or_key`,
  `is_jp`, `is_us`, `normalize_probabilities`.
- `clinosim.modules.observation.{fluid_balance,oxygenation,pre_analytical,vitals_thresholds,_nursing_score_thresholds,_variability_defaults}`
  — every clamp / noise / trigger threshold used by the three
  engines above (Issue #561 + #637 sweeps).
- `clinosim.locale.loader` — sex-banded reference-range YAMLs
  (`reference_range_lab.yaml`) and lab code mapping
  (`code_mapping_lab.yaml`).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.encounter` — `OrderResult`, `MicrobiologyResult`.
- `clinosim.types.clinical` — `PhysiologicalState` (input for lab
  derivation).
- `yaml`, `numpy`.

## Constants and configuration

- **Reference data** ([`reference_data/`](reference_data/)):
  - `lab_aliases.yaml` — canonical lab-name resolution
    (`canonical_lab_name`).
  - `lab_panels.yaml` — panel → component-lab lists
    (`lab_panel_components`).
  - `microbiology.yaml` — culture organism catalog + susceptibility
    distributions + `antibiotic_loinc_lookup` source. Validated at
    import via `_validate_microbiology` with 7 cross-references
    against `HAI_TYPES` / `ANTIBIOTIC_DRUGS` / SNOMED / LOINC
    canonical sets (PR-A pattern).
  - `nursing_scores.yaml` — authoritative published-instrument
    bands for NEWS2, GCS, Braden, Morse (loaded by `_scores`,
    consumed by the `compute_*` functions).
- **Threshold sub-modules**:
  - [`fluid_balance.py`](fluid_balance.py) (Issue #561) — daily
    intake / output balance thresholds: aggressive-IV / maintenance
    / restrictive regimen means + SDs, anuria floor for urine-output
    sampling.
  - [`oxygenation.py`](oxygenation.py) (Issue #561) — SpO₂ trigger
    thresholds for oxygen-therapy escalation
    (`SPO2_HYPOXEMIA_TRIGGER = 92 %`,
    `SPO2_SEVERE_HYPOXEMIA = 88 %`).
  - [`pre_analytical.py`](pre_analytical.py) (Issue #561) —
    specimen-rejection / hemolysis / technician-error rates lifted
    from two sites in `inpatient.py` so a tuning change propagates.
  - [`vitals_thresholds.py`](vitals_thresholds.py) — per-vital
    physiologic min / max clamps and reference bands.
  - [`_nursing_score_thresholds.py`](_nursing_score_thresholds.py)
    — score-band boundaries for the compute_* functions.
  - [`_variability_defaults.py`](_variability_defaults.py) —
    per-analyte default variability SDs when the reference YAML
    lacks a specific entry.

## Directory contents

```
clinosim/modules/observation/
  __init__.py                        empty
  engine.py                          lab canonicalisation + result generation
  nursing.py                         NEWS2 / GCS / Braden / Morse compute_* functions
  nursing_enricher.py                POST_RECORDS enricher (enrich_nursing)
  microbiology.py                    culture + susceptibility + antibiogram
  fluid_balance.py                   IV regimen + urine-output thresholds (Issue #561)
  oxygenation.py                     SpO₂ escalation triggers (Issue #561)
  pre_analytical.py                  specimen-error rates (Issue #561)
  vitals_thresholds.py               per-vital clamps + bands
  _nursing_score_thresholds.py       score-band boundaries (Issue #637)
  _variability_defaults.py           default variability SDs (Issue #637)
  reference_data/
    lab_aliases.yaml                 canonical lab-name aliases
    lab_panels.yaml                  panel → components
    microbiology.yaml                organism + susceptibility catalog
    nursing_scores.yaml              NEWS2 / GCS / Braden / Morse bands
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `audit.py`** — verification is import-time
(`_validate_microbiology`) plus the tests below.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py):

- **`nursing`** — `stage=POST_RECORDS`, `order=20`, always-on. Entry
  point: `clinosim.modules.observation.nursing_enricher.enrich_nursing`.
  Fills NEWS2 + GCS on every vital record; generates daily Braden +
  Morse risk assessments.

The `nursing_assignment` enricher registered by
[`clinosim.modules.nursing`](../nursing/README.md) (POST_ENCOUNTER
order=94) is a distinct enricher; both share the `0x4E55` sub-seed
offset but run in different stages so there is no conflict.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:148`](../../simulator/enrichers.py) | POST_RECORDS `nursing` registration. |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) | Calls `generate_lab_result` per placed lab order. |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | Consumes `fluid_balance.py` + `oxygenation.py` thresholds. |
| Inpatient / outpatient / emergency / daily_loop / unknown_condition | [`clinosim/simulator/*.py`](../../simulator/) | Consumes lab canonicalisation, nursing compute_*, and microbiology helpers. |
| Order module | [`clinosim/modules/order/panel_grouping.py`](../order/panel_grouping.py) | Consumes `lab_panel_components` to expand panel orders. |
| HAI lab lift | [`clinosim/modules/hai/lab_lift.py`](../hai/lab_lift.py) | Reads lab result WBC / CRP fields after `enrich_nursing`. |
| Monitoring enricher | [`clinosim/modules/monitoring/enricher.py`](../monitoring/enricher.py) | Consumes lab result flags for chronic-medication monitoring. |
| Antibiotic module | [`clinosim/modules/antibiotic/__init__.py`](../antibiotic/__init__.py) | Consumes `antibiotic_loinc_lookup` for regimen coding. |

## Testing

```bash
pytest tests/unit -k "observation or nursing or microbiology" -q
```

Coverage cluster: multiple test files exercise the lab flag rules,
nursing scores, microbiology YAML validation, and pre-analytical
error rates — search `tests/unit -k` with any of the module names
above for the specific file.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
