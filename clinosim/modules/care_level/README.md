# `clinosim.modules.care_level` — JP 要介護度 (long-term-care need level) assignment

## Purpose

Assigns a Japanese long-term-care-insurance certification level
(介護保険 認定区分 — `independent`, `support1`/`support2`,
`care1`…`care5`) to every patient in a JP cohort, deterministically per
person, and writes it to `CIFPatientRecord.care_level` (empty string
when the sampled level is `independent` or the patient is non-JP).
Downstream FHIR + CSV adapters read that field and emit a
social-history `Observation` and a `care_level.csv` row respectively.

The module is **JP-only**. On US or any other country the enricher
runs but always writes `""`, so no `Observation` is emitted and the
CSV column is empty.

## Scope

- **In scope**: age-driven sampling of one certification tier per
  patient from a weight table (`weights[age_band]`), using a
  patient-scoped sub-RNG that does not disturb the main simulation
  stream (AD-16).
- **Age drives the distribution**: certification rate is intentionally
  low under 65 (~2 %), rises to ~10 % at 65-74, ~30 % at 75-84, and
  ~60 % at 85+ — matching MHLW population statistics for the
  介護保険制度. Age is the *only* input; chronic-disease status and
  functional-assessment scores are not consulted.
- **Independent = empty**: the `independent` tier maps to the empty
  string, meaning no `Observation` and no CSV row. This mirrors real
  EHR practice where uncertified patients have no 認定区分 record.
- **Out of scope**: ADL / Barthel / functional-assessment scoring
  (that lives in [`clinosim.modules.nursing`](../nursing/README.md)),
  FHIR serialisation (in
  [`clinosim.modules.output`](../output/README.md)), the
  code-system's Japanese display text (in
  [`clinosim/codes/data/jp-care-level.yaml`](../../codes/data/jp-care-level.yaml)).

## Public API

`__init__.py` is empty; consumers import the two building blocks
directly:

```python
from clinosim.modules.care_level.engine import (
    assign_care_level,   # (age, country, rng) -> "" | care-level code
    load_reference,      # -> {levels, age_bands}
    load_rates,          # (country="JP") -> {age_band: [w0..w7]}
)
from clinosim.modules.care_level.enricher import enrich_care_level
```

`assign_care_level` returns `""` when `country` is not JP or the
sampled tier is `independent`; otherwise a `jp-care-level` code such
as `"support1"` or `"care3"`.

## Determinism

- Sub-seed offset `0x434C` (`"CL"`), registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["care_level"]`.
- Per-patient RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — same patient
  always samples the same tier across all their encounters, and the
  main patient RNG stream is not consumed.
- Contrast with `code_status`, which is encounter-scoped; care-level
  is a patient property (not an encounter property).

## Dependencies

- `clinosim.modules._shared` — `is_jp` (country gate),
  `normalize_probabilities` (weight normalisation with
  `fallback="raise"`), `get_attr_or_key` / `set_attr_or_key`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.codes` (indirect, via the FHIR builder) — LOINC and
  `jp-care-level` display lookup.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- [`reference_data/care_level.yaml`](reference_data/care_level.yaml)
  — country-neutral shape:
  - `levels: ["independent", "support1", "support2", "care1", "care2", "care3", "care4", "care5"]`
    (order matches the weight vectors in the locale rate tables).
  - `age_bands: ["0-64", "65-74", "75-84", "85-120"]`.
- [`clinosim/locale/jp/care_level_rates.yaml`](../../locale/jp/care_level_rates.yaml)
  — JP-only. Relative weights per age band over the 8-level vector.
  The engine normalises. Weights are the only country-varying input;
  add a new locale by adding a new YAML in
  `clinosim/locale/<country>/` and extending `load_rates` if that
  country has an analogous scheme.
- Custom code system:
  [`clinosim/codes/data/jp-care-level.yaml`](../../codes/data/jp-care-level.yaml)
  (source: MHLW 介護保険 区分). There is no international standard
  code for 要介護度, so `jp-care-level` is a local codeset used at
  emission time.

## Directory contents

```
clinosim/modules/care_level/
  __init__.py                   empty (see Public API note)
  engine.py                     load_reference / load_rates / assign_care_level
  enricher.py                   POST_RECORDS enrichment (patient-scoped sub-RNG)
  reference_data/
    care_level.yaml             levels + age bands (country-neutral)
```

The module has **no `audit.py`** — no `ModuleAuditSpec` is registered.
Verification lives in the unit + integration tests below.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) under
`register_builtin_enrichers`:

- `name="care_level"`, `stage=POST_RECORDS`, `order=60`,
  `enabled=lambda c: is_jp(getattr(c, "country", "US"))` — JP-gated at
  the registration level.
- Runs after `code_status` (order 50) and before the JP-only
  `sdoh` follow-ups (order 65+).

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`~L371`, `~L420`) | Writes `care_level.csv` from `record["care_level"]`. |
| FHIR `Observation` builder | [`clinosim/modules/output/fhir_r4/encounters/care_level.py`](../output/fhir_r4/encounters/care_level.py) (`_bb_care_level`) | Social-history `Observation` id `carelevel-{patient_id}`, `code` = LOINC 80391-6 (`text = "要介護度"` on JP), `valueCodeableConcept` = `jp-care-level` code. `effectiveDateTime` mirrors the SDOH pattern (earliest encounter admission). JP encounters carry `meta.profile = JP_Observation_Common`. Extracted from the former `_fhir_sdoh.py` by PR2 G2 (2026-06-24) for single-responsibility separation. |
| Enricher registry | [`clinosim/simulator/enrichers.py:201`](../../simulator/enrichers.py) | POST_RECORDS registration. |

## Testing

```bash
pytest tests/unit -k care_level -q         # engine
pytest tests/integration -k care_level -q  # enricher + FHIR emission
```

Individual files:

- [`tests/unit/test_care_level_engine.py`](../../../tests/unit/test_care_level_engine.py)
  — sampling + age-band selection + JP-only gate.
- [`tests/integration/test_care_level_enricher.py`](../../../tests/integration/test_care_level_enricher.py)
  — enricher patient-scope determinism, empty on non-JP.
- [`tests/integration/test_fhir_care_level.py`](../../../tests/integration/test_fhir_care_level.py)
  — `Observation` emission end-to-end.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
