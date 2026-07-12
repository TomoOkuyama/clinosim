---
license: mit
task_categories:
  - other
tags:
  - synthetic-ehr
  - fhir-r4
  - healthcare
  - clinical-data
  - medical-ai
pretty_name: clinosim US-1000
size_categories:
  - 1K<n<10K
language:
  - en
---

# clinosim US-1000

Synthetic US hospital EHR data for **1000 patients** over **6 months**
(2026-01-01 → 2026-06-30), generated with
[clinosim](https://github.com/TomoOkuyama/clinosim) at seed 42.

Sized for ML development: enough encounters to cover the disease
long tail (rare-event conditions like DKA, PE, cardiogenic shock,
delirium) without a multi-hour build. Approximately **30 MB** compressed
NDJSON.

## Contents

Output layout matches `us-100` — one NDJSON per `resourceType` under
`fhir_r4/`, plus the two-pass CIF under `cif/`.

Expected volumes at these parameters (approximate):

| Resource | Records |
|---|---:|
| Patient | ~1,000 |
| Encounter | ~5,000-6,000 |
| Condition | ~10,000 |
| Observation | ~200,000 (labs + vitals) |
| MedicationRequest | ~15,000 |
| MedicationAdministration | ~50,000 |
| DiagnosticReport | ~2,000 |

Actual counts depend on the population's disease distribution at seed 42
— rebuild for exact numbers.

## Build parameters

| Field | Value |
|---|---|
| Country | US |
| Population | 1000 |
| Seed | 42 |
| Start date | 2026-01-01 |
| End date | 2026-06-30 |
| Format | FHIR R4 Bulk NDJSON |

## How to build

```bash
pip install clinosim
clinosim dataset build us-1000 --output ./us-1000       # ~2-3 min on a laptop
```

## License

MIT. Fully synthetic — no real patient data. **Not intended for clinical use.**

## Citation

See [`us-100/README.md#citation`](../us-100/README.md#citation). Cite
the DOI minted by Zenodo on the corresponding clinosim release.
