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
pretty_name: clinosim JP-100
size_categories:
  - n<1K
language:
  - ja
  - en
---

# clinosim JP-100

Synthetic Japanese hospital EHR data for **100 patients** over
**3 months** (2026-01-01 → 2026-03-31), generated with
[clinosim](https://github.com/TomoOkuyama/clinosim) at seed 42.

Ships JP-native features out of the box:

- **JP Core FHIR profile** compliance on 16 primary resource types
  (Patient / Condition / Encounter / Observation / MedicationRequest /
  DiagnosticReport / Procedure / Practitioner / …).
- **JLAC10** lab codes with **LOINC dual coding** (99.5% JLAC10
  coverage as of v0.2.0).
- **MHLW YJ** drug codes verified against the authoritative Excel
  master (12,410 rows).
- Japanese names / addresses (locale/jp/names.yaml + addresses.yaml).
- 保険者番号 / 被保険者番号 in FHIR Coverage (opt-in via
  `--jp-insurance`, default on for JP).

Small enough (~2 MB) to build in under 30 s on a laptop; representative
enough for JP-side smoke tests, teaching, and README demos.

## Contents

Output layout matches [`us-100`](../us-100/README.md#contents) — one
NDJSON per `resourceType` under `fhir_r4/`, plus the two-pass CIF
under `cif/`. Displays are in Japanese (`日本語`) throughout Condition,
DiagnosticReport, MedicationRequest, Immunization, and related
resources. Practitioner / Patient names use `family + given` order
per JP practice, with IDE (kanji) and SYL (kana) name variants.

## Build parameters

| Field | Value |
|---|---|
| Country | JP |
| Population | 100 |
| Seed | 42 |
| Start date | 2026-01-01 |
| End date | 2026-03-31 |
| Format | FHIR R4 Bulk NDJSON (with JP Core profiles) |

## How to build

```bash
pip install clinosim
clinosim dataset build jp-100 --output ./jp-100
```

## License

MIT. Fully **synthetic** — no real patient data. **Not intended for
clinical use.**

## Citation

See [`us-100/README.md#citation`](../us-100/README.md#citation).
