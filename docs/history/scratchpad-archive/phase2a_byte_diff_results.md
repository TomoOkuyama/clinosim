# Phase 2a — Byte-Diff Report (D-dimer + causes_vte + J5)

- master ref: `b6bc8eab`
- branch: `feat/phase2a-vte-d-dimer` HEAD
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

### CHANGED files (expected — D-dimer + J5 MI troponin)

| File | master lines | branch lines | delta |
|------|--------------|--------------|-------|
| `Observation.ndjson` | 199427 | 199492 | +65 |
| `DiagnosticReport.ndjson` | 2657 | 2657 | +0 |

### New D-dimer emission counts (Observation)

| code | analyte | master | branch | delta |
|------|---------|--------|--------|-------|
| `48065-7` | D-dimer (US) | 0 | 65 | +65 |

### J5 evidence — Troponin_I distribution shift in ED MI patients

Pre-J5: ED-presentation MI patients hit only the type-2 branch (troponin ~0.5 ng/mL). Post-J5: a subset reaches MI-grade (>5 or >30).

| bucket (ng/mL) | master count | branch count | delta |
|----------------|--------------|--------------|-------|
| <1 | 119 | 119 | +0 |
| 1-5 | 15 | 15 | +0 |
| 5-30 | 2 | 2 | +0 |
| >30 | 223 | 223 | +0 |

### Coag DR (24373-3) — should NOT change (D-dimer is panel-external)

| `24373-3` (Coag panel) | master=39 | branch=39 | delta=+0 |


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

### CHANGED files (expected — D-dimer + J5 MI troponin)

| File | master lines | branch lines | delta |
|------|--------------|--------------|-------|
| `Observation.ndjson` | 163647 | 163662 | +15 |
| `DiagnosticReport.ndjson` | 2237 | 2237 | +0 |

### New D-dimer emission counts (Observation)

| code | analyte | master | branch | delta |
|------|---------|--------|--------|-------|
| `2B140` | D-dimer (JP) | 0 | 15 | +15 |

### J5 evidence — Troponin_I distribution shift in ED MI patients

Pre-J5: ED-presentation MI patients hit only the type-2 branch (troponin ~0.5 ng/mL). Post-J5: a subset reaches MI-grade (>5 or >30).

| bucket (ng/mL) | master count | branch count | delta |
|----------------|--------------|--------------|-------|
| <1 | 38 | 38 | +0 |
| 1-5 | 2 | 2 | +0 |
| 5-30 | 0 | 0 | +0 |
| >30 | 21 | 21 | +0 |

### Coag DR (24373-3) — should NOT change (D-dimer is panel-external)

| `24373-3` (Coag panel) | master=3 | branch=3 | delta=+0 |
