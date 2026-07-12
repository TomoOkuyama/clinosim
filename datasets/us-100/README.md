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
pretty_name: clinosim US-100
size_categories:
  - n<1K
language:
  - en
---

# clinosim US-100

Synthetic US hospital EHR data for **100 patients** over **3 months**
(2026-01-01 → 2026-03-31), generated with
[clinosim](https://github.com/TomoOkuyama/clinosim) at seed 42.

Small enough (~2 MB) to build in under 30 s on a laptop, representative
enough for smoke tests, integration testing, teaching, and README-style
demos.

## Contents

Output layout is FHIR R4 Bulk Data Access — one NDJSON file per
`resourceType`:

```
us-100/
├── cif/                        # canonical intermediate format (structural + narrative)
└── fhir_r4/
    ├── Patient.ndjson
    ├── Encounter.ndjson
    ├── Condition.ndjson
    ├── Observation.ndjson       # labs + vitals
    ├── MedicationRequest.ndjson
    ├── MedicationAdministration.ndjson
    ├── DiagnosticReport.ndjson
    ├── Procedure.ndjson
    ├── AllergyIntolerance.ndjson
    ├── Immunization.ndjson
    ├── ImagingStudy.ndjson
    ├── DocumentReference.ndjson
    ├── ClinicalImpression.ndjson
    ├── Composition.ndjson
    ├── CareTeam.ndjson
    ├── Practitioner.ndjson
    ├── PractitionerRole.ndjson
    ├── Organization.ndjson
    ├── Location.ndjson
    └── manifest.json            # FHIR Bulk manifest (transactionTime — differs per build)
```

## Build parameters

| Field | Value |
|---|---|
| Country | US |
| Population | 100 |
| Seed | 42 |
| Start date | 2026-01-01 |
| End date | 2026-03-31 |
| Format | FHIR R4 Bulk NDJSON |

## How to build

```bash
pip install clinosim                                      # or: pip install -e ".[dev]" from source
clinosim dataset build us-100 --output ./us-100
```

Output is byte-identical to the pre-built tarball on the corresponding
GitHub Release (v0.3.0 onward), excluding wall-clock metadata in
`manifest.json` files. See
[Reproducibility](../../README.md#reproducibility).

## License

MIT (matches the clinosim project license). This dataset is fully
**synthetic** — no real patient data, PHI, or PII is involved.
**Not intended for clinical use.**

## Citation

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2026},
  url    = {https://github.com/TomoOkuyama/clinosim}
}
```

The Zenodo integration (`.zenodo.json` at repo root) mints a DOI on
every tagged release; cite that DOI for the specific clinosim version
you built the dataset with.
