# PR-A device module — 3-axis Data Quality Review

**Date**: 2026-06-24
**Master baseline**: `89969152`
**Branch**: `feat/device-module-pra`
**Cohort**: US p=10000 seed=42, JP p=5000 seed=42
**Audit script**: `scratchpad/device_dqr/dqr_audit.py`
**Gate**: 3-axis DQR (new feature PR, per `docs/CONTRIBUTING-modules.md` "PR 検証ガイド")

## Result: **OVERALL PASS** (3/3 axes × 2 countries)

```
=== Axis 1 (structural) — US ===
  Device.id unique: 353/353
  DUS.id unique:    353/353
  Device == DUS count: 353
  DUS refs all resolve
  display ≠ code: 100%
  status present: 100%
  Axis 1 US: PASS

=== Axis 2 (clinical) — US ===
  Device count: 353  DUS count: 353
  Distribution:
    SNOMED 52124006 = 125     (CVC)
    SNOMED 23973005 = 125     (Indwelling catheter)
    SNOMED 706172005 = 103    (Ventilator)
  Line-days (completed periods only):
    SNOMED 52124006: p50=6  p90=9  n=121
    SNOMED 23973005: p50=6  p90=9  n=121
    SNOMED 706172005: p50=6 p90=9  n=101
  Snapshot in-progress (no end): 10/353 = 2.8%
  Axis 2 US: PASS

=== Axis 3 (JP language) — US ===
  US has zero JP characters: PASS
  Axis 3 US: PASS

=== Axis 1 (structural) — JP ===
  Device.id unique: 20/20
  DUS.id unique:    20/20
  Device == DUS count: 20
  DUS refs all resolve
  display ≠ code: 100%
  status present: 100%
  Axis 1 JP: PASS

=== Axis 2 (clinical) — JP ===
  Device count: 20  DUS count: 20
  Distribution:
    SNOMED 52124006 = 7
    SNOMED 23973005 = 7
    SNOMED 706172005 = 6
  Line-days (completed periods only):
    SNOMED 52124006: p50=13 p90=24 n=7
    SNOMED 23973005: p50=13 p90=24 n=7
    SNOMED 706172005: p50=11 p90=21 n=6
  Snapshot in-progress (no end): 0/20 = 0.0%
  Axis 2 JP: PASS

=== Axis 3 (JP language) — JP ===
  JP Device displays 100% Japanese: PASS
  Axis 3 JP: PASS

OVERALL: PASS
```

## Axis 1 — structural (FHIR R4 + JP Core compliance)

Both countries pass all 6 structural checks:

| Check | US | JP |
|---|---|---|
| Device.id uniqueness | 353/353 ✓ | 20/20 ✓ |
| DeviceUseStatement.id uniqueness | 353/353 ✓ | 20/20 ✓ |
| Device == DUS count (1:1 invariant) | 353 = 353 ✓ | 20 = 20 ✓ |
| All DUS refs (device + encounter + patient) resolve | ✓ | ✓ |
| Device.type.coding[].display ≠ code (no display==code defect) | 100% | 100% |
| status field present on every resource | 100% | 100% |

Device ids follow `dev-{encounter_id}-{device_type}-{i}` per-encounter scope;
DUS ids follow `dus-{device_id}`. Both schemes guarantee global per-type
uniqueness even across readmissions because Encounter ids are
patient-cross-unique in clinosim.

## Axis 2 — clinical coherence

### Adoption distribution

- **US (n=353 devices, ICU subset of p=10000)**: 125 CVC + 125 catheter
  + 103 ventilator. Equal CVC and catheter counts confirm
  `severity_moderate_plus` indication triggers both simultaneously for
  every ICU inpatient (criteria intersection by design). Ventilator
  adoption rate ≈ 103/125 = 82% of CVC patients → reflects the
  `hypoxia` (perfusion_status < 0.4) and `high_respiratory_demand`
  (respiratory_fraction > 0.7) sub-cohort within ICU.
- **JP (n=20 devices, ICU subset of p=5000)**: 7 CVC + 7 catheter + 6
  ventilator. Smaller cohort; same proportional pattern.

### Line-days p50 / p90

| Country | SNOMED | Display | p50 | p90 | n |
|---|---|---|---|---|---|
| US | 52124006 | CVC | 6 | 9 | 121 |
| US | 23973005 | Catheter | 6 | 9 | 121 |
| US | 706172005 | Ventilator | 6 | 9 | 101 |
| JP | 52124006 | CVC | 13 | 24 | 7 |
| JP | 23973005 | Catheter | 13 | 24 | 7 |
| JP | 706172005 | Ventilator | 11 | 21 | 6 |

US p50 = 6 days reflects the inpatient encounter LOS (admission → discharge)
used as Phase 1 simplification for placement → removal periods. JP p50 = 13
days mirrors the longer JP-specific inpatient LOS distribution (JP healthcare
practice with extended observation periods). Both within plausible bands per
the implementation plan's clinical thresholds:

- CVC expected 2–30: actual 6–13 ✓
- Catheter expected 2–25: actual 6–13 ✓
- Ventilator expected 1–20: actual 6–11 ✓

### Snapshot in-progress rate

US 2.8% (10/353) DUS lack `timingPeriod.end`, JP 0.0% — matches AD-32
in-progress encounter baseline.

## Axis 3 — JP language quality

- **US output**: zero Japanese characters across Device + DUS NDJSON
  (regex match on JP Hiragana / Katakana / CJK Han) → US locale clean.
- **JP output**: 100% of Device.type.coding[].display + Device.type.text
  are Japanese (中心静脈カテーテル / 膀胱留置カテーテル / 人工呼吸器).
  All three derive from the verified `clinosim/codes/data/snomed-ct.yaml`
  entries.

## Phase 1 simplifications acknowledged (non-defects)

- **ICU sub-period as inpatient encounter LOS**: placement_date =
  admission, removal_date = discharge. Over-estimates true ICU
  line-days. Phase 2 HAI sampling rates will be calibrated to absorb this.
- **CVC + catheter always co-emit on ICU inpatient**: by design
  (both criteria = `severity_moderate_plus`). Phase 2-3 may refine CVC
  to vasopressor-use criterion if downstream analytics reports
  over-count.
- **Ventilator adoption ~82% of CVC**: the `hypoxia` proxy
  (perfusion_status < 0.4) is broader than true clinical ventilation
  need; Phase 2 may refine with explicit oxygen-saturation state if
  added to PhysiologicalState.

## Conclusion

PR-A satisfies the **goal-achievement gate**: FHIR R4 / JP Core
compliance + clinical coherence + JP language quality. All 3 axes ×
2 countries PASS. The supplementary byte-diff (Task 10) confirms zero
regression on pre-existing NDJSON. PR-A is ready to merge.

## Phase 2 (PR-B) preparation

The DQR cohort produced:
- US: 353 devices = 353 line-day records ready for CLABSI / CAUTI / VAP
  sampling
- JP: 20 devices = 20 line-day records (smaller cohort; useful for
  smoke testing the Phase 2 cross-module dependency)

Phase 2 PR-B brainstorming should start from these distributions when
calibrating HAI onset rates.
