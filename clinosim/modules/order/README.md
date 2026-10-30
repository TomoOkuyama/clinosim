# `clinosim.modules.order` — order placement + panel grouping + treatment classifier

## Purpose

Owns every clinical-order construction concern that the simulator
uses to schedule labs, imaging, medications, and supportive
treatments across the encounter timeline. Wraps three related
responsibilities:

1. **Order placement** (`engine.py`) — admission + daily-lab +
   imaging order building, medication order enrichment (parses
   free-text dose into structured dose / route / frequency),
   result-time computation (STAT / routine base timing + shift +
   weekend modifiers + M/M/1-style hospital-state delays).
2. **Panel grouping** (`panel_grouping.py`) — the single edit point
   that classifies a list of lab specs into panels (ABG, CBC, BMP,
   LFT, Lipid, Coag, UA, Checkup) vs stand-alone tests, driven by
   `reference_data/lab_panel_groups.yaml`. Every lab-ordering call
   site MUST go through `classify_lab_specs` (see
   [`AGENTS.md`](../../../AGENTS.md) — this is the AD-59 sibling
   pattern for `derive_lab_values` flag helpers).
3. **Treatment classifier** (`treatment_classifier.py`) — the
   single keyword table that decides whether a supportive /
   treatment string becomes a `MEDICATION` / `PROCEDURE` /
   `THERAPY` `Order`. Fixes the J5 pattern where inpatient
   `supportive[]` and encounter `treatment[]` each had their own
   inline keyword table.

Also owns the module's own [`audit.py`](audit.py) — the third
per-module AD-60 audit plug-in (after HAI and antibiotic), with
canonical-constants cross-check, a synthetic-Order
`lift_firing_proof` for `_bb_service_requests`, and a
`basedon_coverage` clinical-axis gate that requires 100 % of LAB
Observations to carry `basedOn` pointing to an existing
ServiceRequest.

## Scope

- **In scope**: `place_admission_orders`, `place_daily_lab_orders`,
  `place_imaging_orders` (Tier 1 #2 imaging-chain DRY entry point);
  `enrich_medication_order` + `parse_dose_string`;
  `calculate_lab_result_time` (STAT / routine + night-shift
  deferral), `calculate_imaging_result_time` (scheduling + reporting
  delay), `calculate_result_time_from_state` (hospital-state-driven
  M/M/1 delay via `facility.HospitalState`; without a state it falls
  back to the imaging model for imaging orders and the lab model
  otherwise, #2202); `order_resource_type`
  (single mapping from an `Order` to its hospital-state resource key
  `"lab"` / `"ct"` / `"mri"` / `"xray"` / `"ultrasound"`, or `None`);
  `replay_order_to_state` (F4 cache-hit queue replay, used by
  `simulator/_dispatch.py`); `enrich_discontinue_flip`
  (`discontinue_flip.py`, the POST_ENCOUNTER enricher that flips the
  original order of a `DISCONTINUE: X` marker to `STOPPED`); `classify_lab_specs` + `load_panel_definitions` +
  `PANEL_PRIORITY_ORDER` (`("ABG", "CBC", "BMP", "LFT", "Lipid",
  "Coag", "UA", "Checkup")`); the three `classify_*` treatment
  classifiers.
- **Out of scope**: lab-value derivation itself
  ([`observation.engine.generate_lab_result`](../observation/README.md));
  physiology state that lab / imaging results depend on
  ([`physiology`](../physiology/README.md)); hospital state
  ([`facility.HospitalState`](../facility/README.md)); FHIR
  ServiceRequest emission
  ([`output/fhir_r4/labs/service_request.py`](../output/fhir_r4/labs/service_request.py));
  antibiotic-regimen construction
  ([`antibiotic`](../antibiotic/README.md)).

### Chemotherapy cycle order emission (v0.5 → v0.6.0)

For each `chemo_visit` LifeEvent (see
[`clinosim.modules.population`](../population/README.md)), the
outpatient encounter builder consumes the regimen definition from
[`clinosim/locale/shared/chemo_regimens.yaml`](../../locale/shared/chemo_regimens.yaml)
and emits — for every drug in the regimen's `cycle_orders` list — one
`MedicationRequest` **plus** one `MedicationAdministration`, both
sharing the same `order_id`. This is the Tier-3-A slice-2 shape:
paired Order + MAR per cycle-day-1 drug, rather than a single
chronic daily home medication. Oral daily chemo (Capecitabine,
Tamoxifen, Anastrozole, Bicalutamide) continues to flow through the
existing `chronic_medications.yaml` home-medication path — those
ARE daily home meds, not cycle drugs. The MRs / MARs carry
`intent="order"` / `status="completed"` on the day the
administration happens; a follow-up slice will expand multi-day
infusion drugs (FOLFOX's 46-h 5-FU) into per-day records.

## Public API

`__init__.py` re-exports the three panel-grouping symbols; every
other entry point is imported from its submodule:

```python
# Re-exported
from clinosim.modules.order import (
    PANEL_PRIORITY_ORDER,               # tuple[str, ...]
    classify_lab_specs,                 # (lab_specs, panels) -> (panel_groups, stand_alones)
    load_panel_definitions,             # () -> dict (@lru_cache=1)
)

# Order engine (imported directly by each simulator)
from clinosim.modules.order.engine import (
    place_admission_orders,             # (protocol, patient_id, encounter_id, admission_time, country, rng, ordered_by="", patient_age=None) -> list[Order]
    place_daily_lab_orders,             # (protocol, patient_id, encounter_id, day_number, order_time, lab_frequency_multiplier, rng, ordered_by="") -> list[Order]
    place_imaging_orders,               # (disease_protocol, encounter_id, patient_id, admission_dt, day_index, severity, rng, sequence_counter) -> list[Order]
    enrich_medication_order,            # (order, dose_str="") -> Order
    parse_dose_string,                  # (dose_str) -> dict
    calculate_lab_result_time,          # (order, rng) -> datetime
    calculate_imaging_result_time,      # (order, rng) -> datetime
    calculate_result_time_from_state,   # (order, hospital_state, hospital_ops, rng) -> datetime
    order_resource_type,                # (order) -> "lab" | "ct" | "mri" | "xray" | "ultrasound" | None
    replay_order_to_state,              # (order, hospital_state, hospital_ops) -> None
)

# Treatment classifier (single-source keyword tables)
from clinosim.modules.order.treatment_classifier import (
    classify_encounter_treatment,       # (display_name) -> OrderType
    classify_inpatient_supportive,      # (display_name, type_hint) -> OrderType
    classify_escalation_treatment,      # (esc_drug: object) -> OrderType
)

# POST_ENCOUNTER enricher (registered in simulator/enrichers.py)
from clinosim.modules.order.discontinue_flip import enrich_discontinue_flip  # (ctx) -> None
```

## Determinism

- **`panel_specimen_seed(parent_order_id)`** and
  **`individual_lab_seed(order_id)`** (both in
  [`clinosim/seeding.py`](../../seeding.py)) — AD-59 per-order sub
  seeds. Panel orders share one specimen, individual scalar orders
  get their own per-order seed. This module's ordering functions
  return `Order` objects with the ids that seed both helpers, so a
  new lab does not shift unrelated patients' streams.
- No sub-seed offset of this module's own in
  `ENRICHER_SEED_OFFSETS`; order construction is called imperatively
  by the encounter simulators, which pass their per-encounter RNG.
  The `discontinue_flip` enricher is RNG-free (it only mutates
  `record.orders` statuses).
- Panel-priority classification is deterministic (dict lookup with
  the pinned `PANEL_PRIORITY_ORDER` tuple).

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key` (engine) and
  `MED_STOP_ORDER_ID_MARKER` (`discontinue_flip.py`).
- `clinosim.modules.imaging.engine` — `load_modalities`,
  `load_body_sites`, `_resolve_imaging_procedure_code_key` for
  `place_imaging_orders`.
- `clinosim.simulator.enrichers` — `EnricherContext`
  (`discontinue_flip.py`).
- `clinosim.modules.order._imaging_result_timing`,
  `_lab_result_timing`, `_order_placement_timing`,
  `_state_delay_thresholds` — every timing / delay scalar (Issue
  #637 four-file sweep).
- `clinosim.codes.loader._load_system` — for `_code_in_data` panel
  validation (matches the sibling `hai/engine.py` pattern).
- `clinosim.audit.registry` (via `audit.py`) — AD-60 audit
  registration; `audit.py` also imports the ServiceRequest builder
  and constants from `output/fhir_r4/labs/service_request.py`.
- `clinosim.types.encounter` — `Order`, `OrderType`, `OrderStatus`.
- `numpy`, `yaml`.

## Constants and configuration

- **Panel priority** (`PANEL_PRIORITY_ORDER`, `panel_grouping.py`):
  `("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA", "Checkup")`.
  Order is load-bearing — HCO3 belongs to BOTH ABG and BMP, and the
  classifier assigns it to ABG first because ABG appears earlier.
- **Panel YAML**: [`reference_data/lab_panel_groups.yaml`](reference_data/lab_panel_groups.yaml)
  — moved from `output/reference_data/` because "panel" is
  fundamentally an ordering concept. Header comment enumerates the
  priority tuple and is cross-verified at import
  (`_validate_panel_definitions`).
- **Timing thresholds** (Issue #637 four-file sweep):
  - [`_lab_result_timing.py`](_lab_result_timing.py) — STAT vs
    routine base delay, night-shift deferral to next-morning
    behaviour, urgency multipliers.
  - [`_imaging_result_timing.py`](_imaging_result_timing.py) —
    scheduling delay (order → exam) + reporting delay separately.
  - [`_order_placement_timing.py`](_order_placement_timing.py) —
    per-order placement offset from encounter events.
  - [`_state_delay_thresholds.py`](_state_delay_thresholds.py) —
    hospital-state-driven delay for
    `calculate_result_time_from_state`.
- **Treatment classifier keywords** (`treatment_classifier.py`) —
  three keyword tuples (`PROCEDURE_KEYWORDS`,
  `PROTOCOL_TEXT_KEYWORDS`, `THERAPY_KEYWORDS`) plus two type-hint
  frozensets (`MEDICATION_TYPE_HINTS`, `CARE_PLAN_TYPE_HINTS`) that
  dispatch a display name to `MEDICATION`, `PROCEDURE`, `THERAPY`. Text-based substring
  matching so the same tables cover English encounter-YAML names
  and English disease-YAML detail strings. Localisation to JP is
  intentionally deferred to the FHIR builder.

## Directory contents

```
clinosim/modules/order/
  __init__.py                        re-exports the three panel symbols
  engine.py                          admission + daily + imaging order placement, result-time computation
  panel_grouping.py                  classify_lab_specs + load_panel_definitions + PANEL_PRIORITY_ORDER
  treatment_classifier.py            classify_{encounter,inpatient,escalation}_* keyword tables
  discontinue_flip.py                POST_ENCOUNTER enricher: DISCONTINUE marker → original order STOPPED (Issue #1346)
  audit.py                           AD-60 audit plug-in (per-module) — 7-check lift_firing_proof + basedon_coverage
  _lab_result_timing.py              STAT / routine / night-shift constants (Issue #637)
  _imaging_result_timing.py          scheduling + reporting delay constants (Issue #637)
  _order_placement_timing.py         placement offset constants (Issue #637)
  _state_delay_thresholds.py         hospital-state delay constants (Issue #637)
  reference_data/
    lab_panel_groups.yaml            panel → components + priority header
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `enricher.py`** — order placement is called
imperatively by every encounter simulator, not through
`register_builtin_enrichers`. The one exception is
`discontinue_flip.py` (see below).

## Enricher wiring

Order placement is not an enricher — it is called imperatively.
`discontinue_flip.enrich_discontinue_flip` IS registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) as
`discontinue_flip` (stage `POST_ENCOUNTER`, order `91`, always
enabled, no `ENRICHER_SEED_OFFSETS` entry because it draws no RNG).
The `audit.py` module is registered with the audit framework
(`register_audit_module`) at import time under the name
`order_service_request`, as the third AD-60 per-module plug-in.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Calls `place_admission_orders` (which classifies `supportive[]` via `classify_inpatient_supportive` internally) + `place_imaging_orders` + `enrich_medication_order`. |
| Emergency encounter | [`clinosim/simulator/emergency.py`](../../simulator/emergency.py) | `classify_encounter_treatment` for `treatment[]`, `enrich_medication_order`, `individual_lab_seed` for ED labs. |
| Outpatient encounter | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py) | `enrich_medication_order` (incl. chemo `cycle_orders`) + `individual_lab_seed`. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | `place_daily_lab_orders` + `place_imaging_orders`, plus `classify_encounter_treatment` / `classify_escalation_treatment` for treatment and escalation orders. |
| Unknown-condition walkthrough | [`clinosim/simulator/unknown_condition.py`](../../simulator/unknown_condition.py) | `calculate_result_time_from_state` for its lab results. |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) | Uses `panel_specimen_seed` + `individual_lab_seed` to sub-seed the observation engine, and `calculate_result_time_from_state` for result times. |
| F4 memo replay | [`clinosim/simulator/_dispatch.py`](../../simulator/_dispatch.py) | `replay_order_to_state` on the cache-hit path. |
| Medication pipeline | [`clinosim/simulator/medication_pipeline.py`](../../simulator/medication_pipeline.py) | Uses `enrich_medication_order` + `parse_dose_string` to build MedicationRequest/MedicationAdministration inputs. |
| FHIR ServiceRequest / DiagnosticReport builders | [`labs/service_request.py`](../output/fhir_r4/labs/service_request.py), [`labs/diagnostic_report.py`](../output/fhir_r4/labs/diagnostic_report.py) | Read `load_panel_definitions()` + each Order's `panel_key`; the SR builder owns the `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` constants that `audit.py` cross-verifies. |

## Testing

```bash
pytest tests/unit -k "order or panel_grouping or treatment_classifier" -q
pytest tests/integration -k "order or lab_pipeline" -q
clinosim audit run -d <cohort_dir> --module order_service_request   # AD-60 axis run
```

The `audit run --module order_service_request` command exercises the seven
`lift_firing_proof` equality checks + the `basedon_coverage`
clinical-axis gate documented in the [`audit.py`](audit.py) module
docstring; a green audit run is the load-bearing verification for
this module.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
