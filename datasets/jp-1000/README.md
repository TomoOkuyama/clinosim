---
license: mit
task_categories:
  - other
tags:
  - synthetic-ehr
  - fhir-r4
  - jp-core
  - healthcare
  - clinical-data
  - medical-ai
pretty_name: clinosim JP-1000
size_categories:
  - 1K<n<10K
language:
  - ja
  - en
---

# clinosim JP-1000

Synthetic Japanese hospital EHR data for **1000 patients** over
**6 months** (2026-01-01 → 2026-06-30), generated with
[clinosim](https://github.com/TomoOkuyama/clinosim) at seed 42.

Sized for ML development on Japanese clinical data with JP Core
profile compliance. Same JP-native feature set as
[`jp-100`](../jp-100/README.md#clinosim-jp-100) — JLAC10 + LOINC dual
coding, MHLW YJ drug codes, JP names / addresses / insurance — scaled
to a cohort that hits the JP disease long tail. Approximately **30 MB**
compressed NDJSON.

## Contents

Layout matches [`us-100`](../us-100/README.md#contents); displays are
Japanese throughout Condition / DiagnosticReport / MedicationRequest /
Immunization / …

Expected volumes at these parameters (approximate):

| Resource | Records |
|---|---:|
| Patient | ~1,000 |
| Encounter | ~5,000 |
| Condition | ~10,000 |
| Observation | ~150,000 |
| MedicationRequest | ~15,000 |
| MedicationAdministration | ~45,000 |
| DiagnosticReport | ~2,000 |
| Coverage | ~1,000 (opt-in JP insurance emission) |

Actual counts depend on the population's disease distribution at seed
42 — rebuild for exact numbers.

## Build parameters

| Field | Value |
|---|---|
| Country | JP |
| Population | 1000 |
| Seed | 42 |
| Start date | 2026-01-01 |
| End date | 2026-06-30 |
| Format | FHIR R4 Bulk NDJSON (with JP Core profiles) |

## How to build

```bash
pip install clinosim
clinosim dataset build jp-1000 --output ./jp-1000       # ~2-3 min on a laptop
```

## License

MIT. Fully **synthetic** — no real patient data. **Not intended for
clinical use.**

## Citation

See [`us-100/README.md#citation`](../us-100/README.md#citation).
