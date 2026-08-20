# `clinosim.modules.disease` — disease-protocol registry + severity + acuity constants

## Purpose

Owns the disease-protocol registry — one YAML file per disease under
[`reference_data/`](reference_data/), loaded through a validated
Pydantic `DiseaseProtocol` model — plus the canonical severity /
acuity / drug-vocabulary constants and helpers that the simulator
reads when it drives a patient through admission, daily rounds,
imaging, orders, and discharge. Adding a new disease is a YAML-only
edit; no engine code changes.

Despite the name, the registry covers every **admission / encounter
protocol**: internal diseases (pneumonia, HF, MI, stroke, DKA, …),
trauma (crush injury, MVA hand fracture, …), and occupational injury
(industrial burn, electrocution, fall from height). Short outpatient
/ ED-only protocols live in a sibling registry under
[`clinosim.modules.encounter`](../encounter/README.md).

## Scope

- **In scope**: `DiseaseProtocol` schema + child models
  (`HpiTemplate`, `PhysicalExamSystemFindings`,
  `PhysicalExamDayFindings`, `DischargeInstructions`, `NarrativeSpec`,
  `ImagingOrderSpec`, `DailyTrajectoryEntry`); the two loaders
  (per-disease and full-registry, both `@lru_cache`); severity
  distribution sampling with condition-based modifiers and minimum
  clamping; canonical severity category ↔ score mapping; canonical
  acuity-tier disease sets (`EMERGENCY_PRIORITY_DISEASES`,
  `CRITICAL_MONITORING_DISEASES`, `NEURO_LOC_MONITORING_DISEASES`);
  drug-block route + duration validation (Issue #455 / #437 family);
  chief-complaint / target-LOS / department localization helpers.
- **In scope (import-time validation)**: every YAML is round-tripped
  through Pydantic (`extra="forbid"`) and additional
  `_validate_drug_*` passes reject dose ↔ route contradictions
  (fallback-relative), invalid escalation `type` values, missing
  duration in long-interval doses, and localised-dose-key typos.
- **Out of scope**: the physiology-state update mechanics that read
  a protocol at simulation time
  ([`clinosim.modules.physiology`](../physiology/README.md)),
  clinical-course trajectory selection
  ([`clinosim.modules.clinical_course`](../clinical_course/README.md)),
  outpatient / ED short-protocol data
  ([`clinosim.modules.encounter`](../encounter/README.md)), narrative
  templating ([`clinosim.modules.document.narrative`](../document/narrative/README.md)),
  disease-driven encounter emission logic
  ([`clinosim.simulator`](../../simulator/)).

## Public API

`__init__.py` is empty; consumers import directly from the four
submodules:

```python
# Schema + loaders
from clinosim.modules.disease.protocol import (
    DiseaseProtocol,
    HpiTemplate,
    PhysicalExamSystemFindings,
    PhysicalExamDayFindings,
    DischargeInstructions,
    NarrativeSpec,
    ImagingOrderSpec,
    DailyTrajectoryEntry,
    load_disease_protocol,        # (disease_id) -> DiseaseProtocol  (lru_cache=64)
    load_all_disease_protocols,   # () -> dict[str, DiseaseProtocol]  (lru_cache=1)
    # Drug-vocabulary helpers
    DRUG_BLOCK_ROUTE_FALLBACKS,
    ROUTE_DOSE_TOKENS,
    dose_route_tokens,
    dose_contradicts_fallback,
    dose_names_long_interval,
)

# Severity model
from clinosim.modules.disease.severity import (
    SEVERITY_CATEGORIES,          # ("mild", "moderate", "severe")
    SEVERITY_SCORE_RANGES,        # canonical half-open ranges
    category_from_score,          # (score) -> "mild"|"moderate"|"severe"
    sample_severity_category,     # (dist, modifiers, minimum, person, rng)
    sample_severity,              # (protocol, person, rng) -> (category, score)
    EVALUABLE_CONDITIONS,
    RESERVED_INTRINSIC_CONDITIONS,
    KNOWN_MODIFIER_CONDITIONS,
)

# Acuity-tier canonical disease sets
from clinosim.modules.disease.acuity import (
    EMERGENCY_PRIORITY_DISEASES,      # Encounter.priority = "EM"
    CRITICAL_MONITORING_DISEASES,     # q1-2h vitals
    NEURO_LOC_MONITORING_DISEASES,    # LOC (AVPU) admission days 0-2
)

# Localization helpers (country → YAML key, chief complaint, department)
from clinosim.modules.disease.localization import (
    _country_to_yaml_key,
    target_los_config,
    _disease_chief_complaint,
    _disease_chief_complaint_ja,
    _disease_to_department,
)
```

`load_disease_protocol` returns the same cached instance across calls
(treat as read-only). `load_all_disease_protocols` is a one-shot
convenience; both raise `ValueError` / Pydantic `ValidationError` on
any schema or validation failure.

## Determinism

- Severity sampling (`sample_severity_category`, `sample_severity`)
  is deterministic in `rng`; the caller (`clinosim.modules.population`
  hospitalization gate + `clinosim.modules.patient.activator`) owns
  the seed derivation. No sub-seed offset is registered because this
  module is not an enricher — it is imported directly by whoever
  needs the sampler.
- Everything else (loaders, validators, drug-vocabulary helpers,
  acuity sets, localization) is pure.

## Dependencies

- `pydantic` — schema + `extra="forbid"` validation.
- `yaml` — YAML parser.
- `numpy` — `np.random.Generator` for severity sampling.
- `clinosim.modules._shared` — `normalize_probabilities`
  (`fallback="raise"`).
- No dependency on `clinosim.simulator` (strict one-way boundary —
  simulator reads disease, never the other way).

## Constants and configuration

- **Disease YAML registry**: [`reference_data/`](reference_data/) —
  32 files today (one per disease id; filename = disease_id +
  `.yaml`). Each carries country-specific epidemiology, severity
  distribution + modifiers, presenting symptoms, physiology impact,
  daily trajectory archetypes, complications, order protocols
  (labs / vitals / imaging / medications), differentials +
  likelihood ratios + code progressions, drug protocols per country
  × role (`first_line`, `alternative_penicillin_allergy`,
  `mrsa_coverage`, `escalation`, `post_op`, `discharge_oral`,
  `hyperkalemia_management`, `alternative_beta_blocker_contraindicated`,
  …), target LOS + discharge benchmarks.
- **Severity canonical model** (`severity.py`):
  - `SEVERITY_CATEGORIES = ("mild", "moderate", "severe")`.
  - `SEVERITY_SCORE_RANGES = {"mild": (0.0, 0.3), "moderate":
    (0.3, 0.7), "severe": (0.7, 1.0)}` — half-open (upper-inclusive
    on `severe`). `category_from_score` is exactly consistent so a
    uniform draw inside a range re-derives its category.
  - `EVALUABLE_CONDITIONS` — modifier conditions this module knows
    how to evaluate against a `person` (ICD-prefix membership +
    age-threshold set); `RESERVED_INTRINSIC_CONDITIONS` — modifier
    tokens intentionally left to the caller
    (e.g. `is_covid_variant_delta`); `KNOWN_MODIFIER_CONDITIONS =
    EVALUABLE_CONDITIONS | RESERVED_INTRINSIC_CONDITIONS`. YAML
    modifier keys outside this union raise at load time.
- **Acuity-tier canonical sets** (`acuity.py`, Issue #563):
  three overlapping `frozenset[str]` — presence of a disease id in
  one of these sets is a load-bearing clinical fact. Adding /
  removing an entry is a data-quality PR, not a refactor. The prior
  `subdural_hematoma` inconsistency (in `EMERGENCY_PRIORITY_DISEASES`
  but missing from `CRITICAL_MONITORING_DISEASES`) was the drift
  Issue #563 caught.
- **Drug-vocabulary helpers** (`protocol.py`, Issue #455 family):
  - `DRUG_BLOCK_ROUTE_FALLBACKS = {"discharge_oral": "PO",
    "escalation": "IV"}` — the two blocks whose readers substitute
    a default route when the entry omits `route`. Blocks with no
    substituting reader (`first_line`, `post_op`,
    `alternative_penicillin_allergy`, `mrsa_coverage`, …) are
    deliberately not validated to avoid failing the build on data
    that never reaches output.
  - `ROUTE_DOSE_TOKENS` — every route abbreviation the fallback
    check tokenises inside a free-text `dose`
    (`PO`, `IV`, `SC`, `IM`, `SL`, `PR`, `NG`, `TD`, `INH`, `NEB`).
    Word-boundary regex `_ROUTE_DOSE_RE` is load-bearing — a
    substring match false-positives on `PR` inside `PRN` and `NG`
    inside `remaining`.
  - `dose_contradicts_fallback(dose, fallback)` — returns True when
    the dose names routes AND the fallback is not among them.
  - Long-interval helper `dose_names_long_interval` — recognises
    `q<N><unit>` patterns beyond a threshold for
    `_validate_drug_block_duration_days`.

## Directory contents

```
clinosim/modules/disease/
  __init__.py                     empty
  protocol.py                     DiseaseProtocol + child models + loaders + drug validators
  severity.py                     severity categories / ranges / sampler / modifier evaluator
  acuity.py                       EMERGENCY_PRIORITY / CRITICAL_MONITORING / NEURO_LOC sets
  localization.py                 country → YAML key + chief complaint + department + target_los
  reference_data/
    <disease_id>.yaml             32 files (one per disease)
  SPEC.md                         extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`**. It is not an
enricher.

## Enricher wiring

Not applicable — this module is a data + helpers layer, not an
enricher. It is not registered with `register_builtin_enrichers` and
has no seed offset in `ENRICHER_SEED_OFFSETS`. Every consumer imports
what it needs directly.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) | Loads `load_all_disease_protocols()` once per run. |
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Reads `DiseaseProtocol` for admission orders, daily trajectory, drug protocols, target LOS; consults the acuity-tier sets to gate `Encounter.priority` and vitals sampling frequency. |
| Emergency / outpatient / daily loop | [`clinosim/simulator/{emergency,outpatient,daily_loop,vitals_pipeline}.py`](../../simulator/) | Same read pattern as inpatient at their respective encounter tiers. |
| Discharge gate + rx | [`clinosim/simulator/{discharge_gate,discharge_rx}.py`](../../simulator/) | Uses `DiseaseProtocol.discharge_criteria` + `discharge_oral` drug block. |
| Simulator helpers | [`clinosim/simulator/helpers.py`](../../simulator/helpers.py) | Re-exports `disease.localization` helpers for one deprecation cycle (Issue #544). |
| Narrative | [`clinosim/modules/document/narrative/{passes,template_generator}.py`](../document/narrative/) | Reads `DiseaseProtocol.narrative` templates + `HpiTemplate` + `DischargeInstructions`. |

## Testing

```bash
pytest tests/unit -k disease -q
```

Individual files:

- [`tests/unit/test_disease_yaml_drug_code_consistency.py`](../../../tests/unit/test_disease_yaml_drug_code_consistency.py)
  — every drug entry's code resolves in `clinosim/codes/`.
- [`tests/unit/test_disease_yaml_key_coverage.py`](../../../tests/unit/test_disease_yaml_key_coverage.py)
  — canonical key coverage across the 32 YAMLs.
- [`tests/unit/test_disease_protocol_extra_forbid.py`](../../../tests/unit/test_disease_protocol_extra_forbid.py)
  — Pydantic `extra="forbid"` guard on unknown keys.
- [`tests/unit/test_cli_test_disease_format.py`](../../../tests/unit/test_cli_test_disease_format.py)
  — CLI disease-format helper.
- [`tests/unit/modules/test_disease_acuity_sets.py`](../../../tests/unit/modules/test_disease_acuity_sets.py)
  — the three acuity sets stay consistent (Issue #563 guard).
- [`tests/unit/modules/disease/`](../../../tests/unit/modules/disease/)
  — module-scoped unit tests (severity sampler, drug validators, and
  localization helpers).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
