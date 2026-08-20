# `clinosim.modules.code_status` — resuscitation-status (code-status) assignment

## Purpose

Assigns a resuscitation-status tier — Full Code, DNR, DNR + DNI, or
Comfort care — to serious encounters, deterministically per encounter,
and exposes it as `CIFPatientRecord.code_status` (SNOMED code string,
empty when no tier applies). Downstream FHIR + CSV adapters read that
field and emit a survey-category `Observation` and a `code_status.csv`
row respectively.

## Scope

- **In scope**: sampling one tier per qualifying encounter from
  country-specific (context × age-band) weight tables, using an
  encounter-scoped sub-RNG that does not disturb the main simulation
  stream (AD-16).
- **Assignment gate** (`enricher._qualifies`):
  - `encounter_type == "inpatient"` → always assigned.
  - `encounter_type == "emergency"` → only when the patient is
    `deceased` or `icu_transferred` (mirrors EHR practice — most ED
    encounters do not carry an explicit code-status note).
  - Other encounter types → no assignment (`code_status = ""`).
- **Context resolution**: `terminal` if the patient died, otherwise
  `icu` if the encounter escalated to ICU, otherwise `routine`. Older
  age bands and higher-severity contexts skew toward DNR / Comfort.
- **Out of scope**: DNR-driven changes to the care plan (would live in
  [`clinosim.modules.clinical_course`](../clinical_course/README.md)),
  FHIR `Consent` serialisation and multi-slot advance-directive
  documents (in [`clinosim.modules.output`](../output/README.md)).

## Public API

`__init__.py` is intentionally empty; consumers import the two
building blocks directly:

```python
from clinosim.modules.code_status.engine import (
    assign_code_status,   # (age, context, country, rng) -> SNOMED code str
    load_reference,       # -> {observable_snomed, age_bands, tiers}
    load_rates,           # (country) -> {context: {age_band: [w_full, w_dnr, w_dnr_dni, w_comfort]}}
)
from clinosim.modules.code_status.enricher import enrich_code_status
```

`assign_code_status` is deterministic for a given `rng`; the enricher
wraps it with the gate + sub-seed derivation described below.

## Determinism

- Sub-seed offset `0x4353` (`"CS"`), registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["code_status"]`.
- Per-encounter RNG: `derive_sub_seed(master_seed, offset, encounter_id)`
  — same encounter always samples the same tier, and the main patient
  RNG stream is not consumed.

## Dependencies

- `clinosim.modules._shared` — `is_us` / `is_jp` (country dispatch),
  `normalize_probabilities` (weight normalisation with `fallback="raise"`),
  `get_attr_or_key` / `set_attr_or_key` (dict-or-dataclass dual-access
  in the enricher).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.codes` (indirect, via the FHIR builder) — SNOMED display
  lookup for the emitted `Observation.code` + `valueCodeableConcept`.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- [`reference_data/code_status.yaml`](reference_data/code_status.yaml)
  — country-neutral. Declares:
  - `observable_snomed: "304251008"` — SNOMED CT observable
    "Resuscitation status".
  - `age_bands: ["0-49", "50-69", "70-84", "85-120"]`.
  - Four `tiers` with `{key, snomed, en, ja}`:
    - `full_code` — 304252001 ("For resuscitation")
    - `dnr` — 304253006 ("Not for resuscitation" / DNAR)
    - `dnr_dni` — **also 304253006**; SNOMED CT International has no
      distinct active concept for the DNR + DNI combination, so the
      tier label carries the DNI distinction while the code is shared.
    - `comfort` — 103735009 ("Comfort care / palliative"), marked
      `TODO: verify` pending re-check against a live SNOMED release.
  - Observable + resuscitation codes were $lookup-verified active
    against `tx.fhir.org` on 2026-06-22 (see file comment for the
    exact procedure).
- [`clinosim/locale/us/code_status_rates.yaml`](../../locale/us/code_status_rates.yaml)
  and [`clinosim/locale/jp/code_status_rates.yaml`](../../locale/jp/code_status_rates.yaml)
  — country-specific `weights[context][age_band] = [full, dnr, dnr_dni, comfort]`
  distributions summing to 1. `load_rates` returns `{}` for
  unsupported countries; the enricher treats an empty map as "no
  assignment", so a new country will not silently inherit US rates
  (2026-07-02 grand-design review contract).

## Directory contents

```
clinosim/modules/code_status/
  __init__.py                   empty (see Public API note)
  engine.py                     load_reference / load_rates / assign_code_status
  enricher.py                   POST_RECORDS enrichment (gate + sub-RNG)
  reference_data/
    code_status.yaml            country-neutral observable + tiers + age bands
```

The module has **no `audit.py`** — no `ModuleAuditSpec` is registered
today. Verification lives in the unit + integration tests below.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) under
`register_builtin_enrichers`:

- `name="code_status"`, `stage=POST_RECORDS`, `order=50`,
  `enabled=lambda c: True`.
- Runs after `family_history` (order 40) and before the JP-only
  `care_level` (order 60).

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`~L358`, `~L419`) | Writes `code_status.csv` from `record["code_status"]`. |
| FHIR `Observation` builder | [`clinosim/modules/output/fhir_r4/conditions/code_status.py`](../output/fhir_r4/conditions/code_status.py) (`_bb_code_status`) | Survey-category `Observation` id `codestatus-{enc_id}`, `code` = observable 304251008, `valueCodeableConcept` = tier SNOMED, `effectiveDateTime` = admission datetime. JP encounters additionally carry `meta.profile = JP_Observation_Common`. |
| Enricher registry | [`clinosim/simulator/enrichers.py:188`](../../simulator/enrichers.py) | POST_RECORDS registration. |

## Testing

```bash
pytest tests/unit -k code_status -q         # engine + data + codes + csv
pytest tests/integration -k code_status -q  # enricher + FHIR emission
```

Individual files:

- [`tests/unit/test_code_status_engine.py`](../../../tests/unit/test_code_status_engine.py)
  — sampling + age-band selection.
- [`tests/unit/test_code_status_data.py`](../../../tests/unit/test_code_status_data.py)
  — YAML shape.
- [`tests/unit/test_code_status_codes.py`](../../../tests/unit/test_code_status_codes.py)
  — SNOMED code authority + active-concept checks (PR #68).
- [`tests/unit/test_code_status_csv.py`](../../../tests/unit/test_code_status_csv.py)
  — CSV row emission.
- [`tests/integration/test_code_status_enricher.py`](../../../tests/integration/test_code_status_enricher.py)
  — enricher gate + sub-seed determinism.
- [`tests/integration/test_fhir_code_status.py`](../../../tests/integration/test_fhir_code_status.py)
  — Observation emission end-to-end.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
