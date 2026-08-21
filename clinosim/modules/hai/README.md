# `clinosim.modules.hai` — HAI onset sampling + culture + lab lift

## Purpose

Samples healthcare-associated infection (HAI) events — CLABSI,
CAUTI, VAP — per encounter based on CDC NHSN per-line-day risk
rates, writes the events into `record.extensions["hai"]`, generates
a companion `MicrobiologyResult` so the existing FHIR builder emits
the culture automatically, and lifts existing WBC + CRP observations
via a closed-form forward delta so lab values reflect the newly
introduced infection (Phase 3a).

Combined with [`clinosim.modules.device`](../device/README.md)
(POST_ENCOUNTER order=70, produces line-days),
[`clinosim.modules.antibiotic`](../antibiotic/README.md)
(POST_ENCOUNTER order=85, empirical regimen), and the observation
microbiology emitter, this module is the middle of the four-module
HAI cascade.

## Scope

- **In scope**: `sample_hai_onset` — CDC NHSN per-line-day risk
  sampling per HAI type on top of `extensions["device"]` line-days;
  `_sample_organism` — organism selection from
  `hai_organisms.yaml`; `_add_days` date helper;
  `apply_hai_lab_lift` — Phase 3a closed-form WBC + CRP forward
  delta with `_hai_lift_delta` mirroring the `derive_lab_values`
  CRP + WBC formula (state snapshot from
  `state_history[day_index + 1]`, then `round_to_precision` +
  `determine_flag` re-applied); six load-time YAML validators
  (`_validate_hai_organisms` / `_validate_hai_rates` /
  `_validate_hai_codes` / `_validate_hai_specimens` +
  `_validate_hai_antibiogram` in the antibiogram loader +
  `_validate_hai_lab_lift`); the `HAI_TYPES` canonical constant.
- **In scope (audit)**: [`audit.py`](audit.py) — the first per-module
  AD-60 audit plug-in. Registers a synthetic-CAUTI
  `lift_firing_proof` that reproduces the closed-form delta the
  runtime would produce (load-bearing verification PR-90 was
  missing) plus canonical-constants + structural-obs-codes checks
  and a clinical-acceptance cohort gate (CAUTI WBC delta ≥ 1500,
  CRP delta ≥ 25; CLABSI / VAP each ≥ 3000 / ≥ 50, small cohorts
  → WARN).
- **Out of scope**: device line-day generation
  ([`device`](../device/README.md)); empirical / narrowing
  antibiotic regimen construction
  ([`antibiotic`](../antibiotic/README.md)); FHIR
  `Observation` / `DiagnosticReport` emission for the culture
  ([`output/fhir_r4/labs/`](../output/fhir_r4/) —
  `_fhir_microbiology.py`); ServiceRequest emission
  ([`order`](../order/README.md)).

## Public API

```python
from clinosim.modules.hai import HAI_TYPES         # ("clabsi", "cauti", "vap")
from clinosim.modules.hai.engine import (
    sample_hai_onset,                              # (encounter, devices, rng) -> list[HAIEvent]
    load_hai_rates,                                # () -> dict (@lru_cache)
    load_hai_codes,                                # () -> dict (@lru_cache)
    load_hai_organisms,                            # () -> dict (@lru_cache)
    load_hai_specimens,                            # () -> dict (@lru_cache)
)
from clinosim.modules.hai.enricher import hai_enricher   # POST_ENCOUNTER entry
from clinosim.modules.hai.lab_lift import (
    apply_hai_lab_lift,                            # (record) -> None (mutates observations)
    _hai_lift_delta,                               # closed-form WBC / CRP delta
)
```

## Determinism

- Sub-seed offset `0x4841` (`"HA"`, PR-B) — registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["hai"]`.
- Per-patient sub-RNG via `derive_sub_seed(master_seed, offset,
  patient_id)` — main patient RNG untouched (AD-16).
- Lab lift is deterministic (closed-form delta, no rng draw); the
  state snapshot input is fully determined by the pre-lift state
  history, so applying / not applying the lift is byte-clean apart
  from the WBC / CRP observation values themselves.
- **Canonical `HAI_TYPES = ("clabsi", "cauti", "vap")`** — lowercase
  strings MUST be used everywhere. The prior UPPERCASE YAML keys +
  lowercase enricher writes silently no-op'd the entire Phase 3a
  lift in production (PR-90 lesson); a YAML integrity test plus
  this single source of truth prevents that class of regression.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`,
  `get_or_create_container`, `normalize_probabilities`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.modules.antibiotic` — `ANTIBIOTIC_LOINC_LOOKUP`
  (consumed by the enricher when writing the culture).
- `clinosim.modules.observation.engine` — `round_to_precision`,
  `determine_flag` (re-applied post-lift).
- `clinosim.audit.registry` (via `audit.py`) — AD-60 audit
  registration.
- `clinosim.types.encounter` — `Device`, `HAIEvent`,
  `MicrobiologyResult`.
- `numpy`, `yaml`.

## Constants and configuration

- **`HAI_TYPES`** — canonical lowercase tuple defined in
  `__init__.py` BEFORE any submodule import (avoids circular
  dependency with `enricher.py`).
- **Six YAML files** ([`reference_data/`](reference_data/)) with a
  6-layer per-validator sibling sweep (Issue #121-#122):
  - `hai_organisms.yaml` — organism SNOMED catalog per HAI type.
  - `hai_rates.yaml` — per-line-day HAI risk rates (CDC NHSN 2018-2020).
  - `hai_codes.yaml` — HAI condition codes (ICD-10 + SNOMED) per type.
  - `hai_specimens.yaml` — specimen type per HAI type.
  - `hai_antibiogram.yaml` — organism × antibiotic S/I/R rates
    (loaded by `antibiotic` module; validated 3-way against
    `HAI_TYPES` + `hai_organisms.yaml` + `ANTIBIOTIC_LOINC_LOOKUP`).
  - `hai_lab_lift.yaml` — per-HAI-type WBC + CRP delta parameters
    used by `_hai_lift_delta`.
- **7-layer system-level silent-no-op defense** (established through
  PR3b-3 / PR3b-5 chains): canonical URIs + ID prefixes + validator
  ordering + reverse-coverage (forward + staleness) +
  `HAI_EVENT_ID_SYSTEM` shared between writer + reader — see
  [`AGENTS.md`](../../../AGENTS.md) HAI-cascade section for the
  full 7-layer + per-validator 6-layer pattern.

## Directory contents

```
clinosim/modules/hai/
  __init__.py                    HAI_TYPES canonical constant + loader stub
  engine.py                      sample_hai_onset + loaders + validators + _sample_organism
  enricher.py                    POST_ENCOUNTER hai_enricher
  lab_lift.py                    apply_hai_lab_lift + _hai_lift_delta (Phase 3a)
  audit.py                       AD-60 audit plug-in (first per-Module) — lift_firing_proof
  reference_data/
    hai_organisms.yaml           organism SNOMED catalog
    hai_rates.yaml               per-line-day HAI risk rates
    hai_codes.yaml               HAI ICD + SNOMED codes per type
    hai_specimens.yaml           specimen type per HAI type
    hai_antibiogram.yaml         organism × antibiotic S/I/R
    hai_lab_lift.yaml            WBC + CRP delta parameters
```

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py):

- `name="hai"`, `stage=POST_ENCOUNTER`, `order=80`,
  `enabled=lambda c: True`. Runs AFTER `device` (order=70) so
  `extensions["device"]` is available.
- The `audit.py` module registers with the AD-60 audit framework at
  import time.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) | POST_ENCOUNTER order=80 registration. |
| Audit registry | [`clinosim/modules/hai/audit.py`](audit.py) | AD-60 audit plug-in — lift_firing_proof + canonical / structural / clinical checks. |
| Antibiotic enricher | [`clinosim/modules/antibiotic/enricher.py`](../antibiotic/enricher.py) | Reads `extensions["hai"]` for empirical regimen selection. |
| Observation microbiology emitter | [`clinosim/modules/observation/microbiology.py`](../observation/microbiology.py) | Emits `Observation.specimen.reference` and the `HAI_EVENT_ID_SYSTEM` identifier on HAI-derived cultures. |
| FHIR microbiology / diagnostic-report / servicerequest / document chain | integration tests (see below) | End-to-end HAI cascade emission. |

## Testing

```bash
pytest tests/unit -k "hai" -q
pytest tests/integration -k "hai" -q
clinosim audit run -d <cohort_dir> --module hai
```

Individual files:

- [`tests/unit/test_hai_yaml_validators.py`](../../../tests/unit/test_hai_yaml_validators.py)
  — the 6-layer per-validator sibling sweep.
- [`tests/unit/test_hai_engine.py`](../../../tests/unit/test_hai_engine.py)
  — `sample_hai_onset` + organism sampling.
- [`tests/unit/test_hai_enricher.py`](../../../tests/unit/test_hai_enricher.py)
  — POST_ENCOUNTER enricher determinism + `extensions["device"]`
  consumption.
- [`tests/unit/test_derive_lab_values_hai.py`](../../../tests/unit/test_derive_lab_values_hai.py)
  — lab-lift closed-form vs `derive_lab_values` parity.
- [`tests/unit/test_forced_scenario_hai.py`](../../../tests/unit/test_forced_scenario_hai.py)
  — `ForcedScenario.force_hai_event` deterministic injection.
- [`tests/unit/test_hai_codes_coverage.py`](../../../tests/unit/test_hai_codes_coverage.py)
  — ICD / SNOMED coverage.
- [`tests/integration/test_hai_susceptibility_chain.py`](../../../tests/integration/test_hai_susceptibility_chain.py)
  — PR3b-2 chain end-to-end.
- [`tests/integration/test_audit_hai_module.py`](../../../tests/integration/test_audit_hai_module.py)
  — AD-60 audit run integration.
- [`tests/integration/test_servicerequest_chain.py`](../../../tests/integration/test_servicerequest_chain.py),
  [`test_document_chain.py`](../../../tests/integration/test_document_chain.py)
  — cross-module emission.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
