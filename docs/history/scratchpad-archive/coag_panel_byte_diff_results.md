# Coag Panel PR — Byte-Diff Report

- master ref: `fbd80607`
- branch: `feat/coag-panel-physiology` HEAD
- p=2000, seed=42, both countries (US, JP)

## US (p=2000 seed=42)

### IDENTICAL invariant

| File | master | branch | match |
|------|--------|--------|-------|
| `Patient.ndjson` | `c6e2448d8ed678b3` | `c6e2448d8ed678b3` | OK |
| `Encounter.ndjson` | `c2e3379dcdef9905` | `c2e3379dcdef9905` | OK |
| `Condition.ndjson` | `4e9dd3c4dc125992` | `4e9dd3c4dc125992` | OK |
| `MedicationRequest.ndjson` | `72d7253b2498dae0` | `72d7253b2498dae0` | OK |
| `MedicationAdministration.ndjson` | `7a46b7ed622bb2b3` | `7a46b7ed622bb2b3` | OK |
| `Procedure.ndjson` | `ae2b0650f0588edb` | `ae2b0650f0588edb` | OK |
| `ImagingStudy.ndjson` | `MISSING` | `MISSING` | OK |
| `Immunization.ndjson` | `9d6fb2ac4bc0478f` | `9d6fb2ac4bc0478f` | OK |
| `FamilyMemberHistory.ndjson` | `3bd5ea303c256776` | `3bd5ea303c256776` | OK |

All IDENTICAL files match: **True**

### CHANGED files (expected — new APTT/PT/Fibrinogen + Coag DRs)

| File | master lines | branch lines | delta |
|------|--------------|--------------|-------|
| `Observation.ndjson` | 199381 | 199427 | +46 |
| `DiagnosticReport.ndjson` | 2618 | 2657 | +39 |

### New analyte emission counts (Observation)

| code | analyte | master | branch | delta |
|------|---------|--------|--------|-------|
| `14979-9` | APTT (US) | 0 | 40 | +40 |
| `5902-2` | PT (US, seconds) | 0 | 0 | +0 |
| `3255-7` | Fibrinogen (US) | 0 | 6 | +6 |

### Coag DR emission count (DiagnosticReport, LOINC 24373-3)

| `24373-3` (Coag panel) | master=0 | branch=39 | delta=+39 |


## JP (p=2000 seed=42)

### IDENTICAL invariant

| File | master | branch | match |
|------|--------|--------|-------|
| `Patient.ndjson` | `b5ddef86c6674cb5` | `b5ddef86c6674cb5` | OK |
| `Encounter.ndjson` | `411e1410b5cd4af4` | `411e1410b5cd4af4` | OK |
| `Condition.ndjson` | `dc9380408abf6bd7` | `dc9380408abf6bd7` | OK |
| `MedicationRequest.ndjson` | `6765240fb4b07fd2` | `6765240fb4b07fd2` | OK |
| `MedicationAdministration.ndjson` | `c8c95cc825285b34` | `c8c95cc825285b34` | OK |
| `Procedure.ndjson` | `cd6cc84d489c10f6` | `cd6cc84d489c10f6` | OK |
| `ImagingStudy.ndjson` | `MISSING` | `MISSING` | OK |
| `Immunization.ndjson` | `8182cb05f8d013ca` | `8182cb05f8d013ca` | OK |
| `FamilyMemberHistory.ndjson` | `34935467173d9a5f` | `34935467173d9a5f` | OK |

All IDENTICAL files match: **True**

### CHANGED files (expected — new APTT/PT/Fibrinogen + Coag DRs)

| File | master lines | branch lines | delta |
|------|--------------|--------------|-------|
| `Observation.ndjson` | 163635 | 163647 | +12 |
| `DiagnosticReport.ndjson` | 2234 | 2237 | +3 |

### New analyte emission counts (Observation)

| code | analyte | master | branch | delta |
|------|---------|--------|--------|-------|
| `2B020` | APTT (JP) | 0 | 3 | +3 |
| `2B030` | PT/PT_INR (JP) — analyte shared, count goes up | 617 | 617 | +0 |
| `2B100` | Fibrinogen (JP) | 0 | 9 | +9 |

### Coag DR emission count (DiagnosticReport, LOINC 24373-3)

| `24373-3` (Coag panel) | master=0 | branch=3 | delta=+3 |
