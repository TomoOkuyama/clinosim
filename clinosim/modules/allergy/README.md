# `clinosim.modules.allergy` — patient allergy sampling

## Purpose

Samples one allergy (or none) per patient during the POST_POPULATION
pass and writes it to `PersonRecord.allergies` as a list of `Allergy`
records with a nested `AllergyReaction`. Downstream FHIR
`AllergyIntolerance` emission reads the same field. The sampler is
deliberately two-stage — a patient-level 15 % overall gate followed
by a category-weighted single-allergen draw — to match the baseline
calibration reference the pre-refactor patient activator produced
(~15.3 % population-level prevalence).

## Scope

- **In scope**: patient-level overall allergy gate
  (`OVERALL_ALLERGY_PREVALENCE = 0.15`), category-weighted single
  allergen selection (`CATEGORY_WEIGHTS = {medication: 0.50,
  food: 0.25, environment: 0.25}`), uniform pick within category
  from `allergens.yaml`, per-allergy clinical / verification status
  sampling ("active + confirmed" majority, "active + unconfirmed"
  ~10 %, "resolved + confirmed" ~5 % restricted to food category).
- **In scope (validation)**: 6-layer import-time validator over
  `allergens.yaml` including `allergen_code` and every reaction's
  `manifestation_snomed` cross-checked against
  [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  membership via `_code_in_data`.
- **Out of scope**: multi-allergy per patient (single-allergy today,
  extension noted in code comments), drug-allergy interaction with
  prescribing ([`clinosim.modules.order`](../order/README.md)),
  FHIR serialisation
  ([`clinosim.modules.output`](../output/README.md)), reaction-event
  generation during a specific encounter, SNOMED display text
  ([`clinosim/codes/`](../../codes/)).

## Public API

`__init__.py` re-exports the two dataclasses only; consumers import
the enricher / loader entry points directly from `engine`:

```python
from clinosim.modules.allergy import Allergy, AllergyReaction
from clinosim.modules.allergy.engine import (
    allergy_enricher,                    # POST_POPULATION enricher entry
    load_allergens,                      # () -> {"medication": [...], "food": [...], "environment": [...]}
    SUPPORTED_ALLERGEN_CATEGORIES,       # frozenset {"medication", "food", "environment"}
    OVERALL_ALLERGY_PREVALENCE,          # 0.15
    CATEGORY_WEIGHTS,                    # {"medication": 0.50, "food": 0.25, "environment": 0.25}
    ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE, # 0.05
    ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE,   # 0.15
)
```

## Scope: AllergyIntolerance ≠ any allergic disease

The 15% overall gate models the fraction of patients with a **clinically
documented FHIR `AllergyIntolerance` record** — medication (Penicillin
/ Aspirin / Sulfa / etc.), severe food (peanut / shellfish / egg /
milk), or environmental (latex). Real-world benchmark:

| Reference | Rate | Scope |
|---|---|---|
| MHLW アレルギー疾患実態調査 2011 | 30-40% | ANY allergic disease incl. hay fever (J30) + food intolerance (K90.4) |
| Drug allergy documented alone | 5-10% | Medication-only, real EHR |
| Combined clinically documented `AllergyIntolerance` | 10-20% | Typical real hospital EHR |

**Do not compare the emitted rate against the 30-40% general "any
allergic disease" statistic** — that would be a scope mismatch. Hay
fever is emitted as `Condition` (ICD-10 `J30`), food intolerance as
`Condition` (`K90.4`), etc. `AllergyIntolerance` is the narrower "the
clinician wrote this on the allergy chart with a reaction" surface.

The 15% figure is a defensible middle ground within the 10-20% real
`AllergyIntolerance` documentation band, chosen to match the pre-refactor
patient activator baseline (~15.3%) so cohort determinism is preserved.

See [`scripts/audit_realworld_stats_jp.py`](../../../scripts/audit_realworld_stats_jp.py)
for the correct audit metric (this benchmark note is cross-referenced there).

## Determinism

- Sub-seed offset `0x414C` (`"AL"`), registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["allergy"]`.
- Per-patient RNG:
  `derive_sub_seed(master_seed, offset, person_id)` — same patient
  always samples the same allergy (or nothing), and the main
  population RNG stream is not consumed (AD-16).
- Category weights are normalised through
  `normalize_probabilities(..., fallback="raise")` so a YAML
  pre-normalisation drift raises rather than silently biasing the
  draw.
- Status draws (`clinical` / `verification`) come from the same
  per-patient RNG stream as the allergen selection, so status
  distribution is deterministic given the patient.

## Dependencies

- `clinosim.modules._shared` — `normalize_probabilities`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.allergy` — `Allergy`, `AllergyReaction`.
- `clinosim.codes.loader._load_system` (via `_code_in_data`) — direct
  SNOMED membership check during import-time validation.
- `numpy` — `np.random.Generator`.
- `yaml` — YAML parser.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- Module-level constants (all in `engine.py`):
  - `SUPPORTED_ALLERGEN_CATEGORIES` — frozenset of the three
    canonical categories; must match `allergens.yaml` keys exactly.
  - `OVERALL_ALLERGY_PREVALENCE = 0.15` — Step-4 calibrated gate
    rate.
  - `CATEGORY_WEIGHTS` — medication / food / environment
    distribution once the gate fires (relative weights, normalised
    at sample time).
  - `ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE = 0.05` — food-only bucket
    for `clinical="resolved" + verification="confirmed"` (models
    outgrown childhood food allergies).
  - `ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE = 0.15` — cumulative cutoff
    for `active + unconfirmed`; the remaining ~85 % becomes
    `active + confirmed`.
- [`reference_data/allergens.yaml`](reference_data/allergens.yaml)
  — one entry per allergen under `allergens.{medication, food,
  environment}`. Required fields per entry: `allergen_code` (SNOMED
  CT), `allergen_display_en`, `allergen_display_ja`,
  `prevalence.adult` (0..1 — documentation of the category-level
  reference rate, not the actual gate), `criticality`,
  `common_reactions[]` (each with `manifestation_snomed` and
  `severity`). Both `allergen_code` and every
  `common_reactions[].manifestation_snomed` are validated to exist
  in [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  at import time — an unknown code raises rather than falling
  through to the empty-display case (AD-30 chain, sibling of the
  `hai/engine.py:_code_in_data` pattern).
- 6-layer validator (`_validate_allergens`) rejects: (1) empty
  top-level, (2) missing / non-dict `allergens`, (3) key drift vs
  `SUPPORTED_ALLERGEN_CATEGORIES` (both directions), (4) empty
  per-category list, (5) missing required entry fields, (6)
  `prevalence.adult` out of range or the SNOMED cross-checks above.

## Directory contents

```
clinosim/modules/allergy/
  __init__.py                     re-exports Allergy + AllergyReaction
  engine.py                       validator / load_allergens / allergy_enricher
  reference_data/
    allergens.yaml                3-category allergen catalog + reactions
```

The module has **no `enricher.py`, no `audit.py`, no separate
`assign_*` function** — the enricher entry point is `allergy_enricher`
in `engine.py`.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L119-134`) under `register_builtin_enrichers`:

- `name="allergy"`, `stage=POST_POPULATION`, `order=10`,
  `enabled=lambda c: True`.
- Runs at POST_POPULATION order 10 (same order as identity) so
  allergies are available to every downstream enricher and
  simulation stage. Identity's gate is JP-only, so their execution
  is disjoint in practice.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| FHIR `AllergyIntolerance` builder | [`clinosim/modules/output/fhir_r4/conditions/allergy_intolerance.py`](../output/fhir_r4/conditions/allergy_intolerance.py) | Reads `record.allergies` and emits one `AllergyIntolerance` resource per entry. IDs follow the canonical `allergy-{patient_id}-{idx}` format owned by the builder (I-4 fix — the engine sets a placeholder `allergy_id="1"`). |
| Enricher registry | [`clinosim/simulator/enrichers.py:127`](../../simulator/enrichers.py) | POST_POPULATION order=10 registration. |

## Testing

```bash
pytest tests/unit -k allergy -q         # loader + validator + engine + types
pytest tests/unit -k fhir_allergy -q    # AllergyIntolerance emission
```

Individual files:

- [`tests/unit/test_types_allergy.py`](../../../tests/unit/test_types_allergy.py)
  — `Allergy` / `AllergyReaction` dataclass shape.
- [`tests/unit/modules/allergy/test_engine.py`](../../../tests/unit/modules/allergy/test_engine.py)
  — enricher determinism, gate rate, category distribution, status
  distribution.
- [`tests/unit/modules/allergy/test_allergens_yaml.py`](../../../tests/unit/modules/allergy/test_allergens_yaml.py)
  — 6-layer validator coverage.
- [`tests/unit/output/test_fhir_allergy_intolerance.py`](../../../tests/unit/output/test_fhir_allergy_intolerance.py)
  — `AllergyIntolerance` emission end-to-end.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
