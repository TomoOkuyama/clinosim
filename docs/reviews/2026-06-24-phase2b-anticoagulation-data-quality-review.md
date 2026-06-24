# Phase 2b Data Quality Review — `on_warfarin` Medication-Physiology Coupling

**Date**: 2026-06-24
**Branch**: `feat/phase2b-on-anticoagulation`
**Cohort**: US p=10,000 + JP p=5,000, seed=42, format=fhir-r4
**Audit script**: `scratchpad/phase2b_dqr/dqr_audit.py`
**Raw output**: `scratchpad/phase2b_dqr/dqr_results.txt`

**Result**: **ALL 3 AXES PASS** for both US and JP.

---

## Axis 1: Structural

### US (p=10,000)

| Metric | Value |
|---|---:|
| Total Observation resources | 3,407,516 |
| PT_INR observations (LOINC 6301-6) | 5,659 |
| referenceRange coverage | 5,659 / 5,659 (100.0%) |
| interpretation coverage | 5,659 / 5,659 (100.0%) |

### JP (p=5,000)

| Metric | Value |
|---|---:|
| Total Observation resources | 434,529 |
| PT_INR observations (JLAC10 2B030, unit `{INR}`) | 1,354 |
| referenceRange coverage | 1,354 / 1,354 (100.0%) |
| interpretation coverage | 1,354 / 1,354 (100.0%) |

**PASS**: All PT_INR observations carry referenceRange + interpretation per FHIR R5 Note 5 (consistency requirement). Code resolution intact (LOINC 6301-6 in US, JLAC10 2B030 in JP).

---

## Axis 2: Clinical Coherence

### US (p=10,000)

| Cohort | n | p10 | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|
| warfarin (chronic + in-hospital) | 515 | 1.50 | **2.70** | 3.10 | 3.90 |
| DOAC (apixaban / rivaroxaban / etc.) | 241 | 1.32 | **1.80** | 2.90 | 3.40 |
| no AC | 4,903 | 1.30 | **1.70** | 2.40 | 3.40 |

- warfarin patients (n=111 in MedReq), DOAC patients (n=143)
- **warfarin median 2.70 in therapeutic band [2.0, 3.0]** ✓
- **DOAC median 1.80 ≈ no-AC median 1.70 (delta 0.10)** ✓ — DOAC correctly NOT shifted, faithful to clinical practice of not monitoring INR for DOAC
- **warfarin shifted +1.00 above no-AC** ✓ — clear therapeutic effect

### JP (p=5,000)

| Cohort | n | p10 | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|
| warfarin | 141 | 2.10 | **3.00** | 3.50 | 3.90 |
| DOAC | 17 | 1.70 | **1.90** | 2.22 | 2.30 |
| no AC | 1,196 | 1.40 | **1.90** | 2.60 | 3.20 |

- warfarin patients (n=11 in MedReq), DOAC patients (n=9)
- **warfarin median 3.00 at therapeutic upper boundary** ✓
- **DOAC median 1.90 = no-AC median 1.90 (delta 0.00)** ✓
- **warfarin shifted +1.10 above no-AC** ✓

### Compound (warfarin + comorbidity) — visible in tail

US warfarin max = 3.90 (warfarin + cirrhosis or DIC → over-AC, clinically realistic bleeding risk). JP warfarin max = 3.90 mirror.

### PE/DVT/AF in-hospital ramp evidence

The warfarin INR cohort includes patients on chronic AC (AF I48 from existing chronic_medications.yaml) PLUS in-hospital warfarin orders ≥ 3 days old (PE/DVT/AF acute treatment.medications path, peeked from all_orders). The byte-diff (US p=2000, scratchpad/phase2b_byte_diff_results.md) confirmed 13 distinct encounters with PT_INR shifts in US, all warfarin-detected.

**PASS**: warfarin therapeutic + DOAC unchanged + warfarin shifted above no-AC. Clinically coherent.

---

## Axis 3: JP Language

### US

- **0 Observation lines contain Japanese characters** ✓
- US output is 100% English

### JP

- warfarin Japanese display "ワルファリン3mg" emitted: 14 MedRequests
- apixaban Japanese display "アピキサバン5mg" emitted: 8 MedRequests
- rivaroxaban Japanese display "リバーロキサバン15mg" emitted: 0 MedRequests (small cohort at p=5000; activator-draw artifact — not a defect)
- **PT_INR coding**: JLAC10 `urn:oid:1.2.392.200119.4.1005` code `2B030` display `プロトロンビン時間` — JCCLS-JSLM v137 standard, no LOINC duplication (intentional, JP convention)

**PASS**: JP Japanese localization intact for AC drug names + PT_INR display.

---

## Invariants

- **AD-16** (master RNG isolation): byte-diff p=2000 confirmed 8/9 NDJSON files sha256-identical between master and branch — cohort composition unchanged.
- **AD-57** (BNP-pattern surgical): `PhysiologicalState` untouched; PT_INR formula-only change. Verified by `test_pt_inr_off_warfarin_unchanged` unit test + structural identity of all non-Observation NDJSON.
- **AD-59** (per-order sub-rng): `individual_lab_seed` / `panel_specimen_seed` unchanged. No new RNG draw inside `derive_lab_values`. Verified by `test_pt_inr_distribution_deterministic_under_same_seed` + `test_pt_inr_distribution_deterministic_pe_cohort` (both PASS, same seed → byte-identical PT_INR distribution).

---

## Notes on findings

1. **DOAC patient INR distribution overlaps no-AC** — this is the **correct** behavior. Phase 2b intentionally does NOT detect DOAC because INR is not clinically monitored for DOAC (rivaroxaban has minor PT effect but is not used for therapeutic monitoring). The 0.10 / 0.00 delta confirms DOAC patients are scored exactly like non-AC patients.

2. **JP rivaroxaban = 0 MedRequests** at p=5000 — activator's independent-probability draw for I26/I82 didn't draw rivaroxaban in this JP cohort. Pre-existing limitation (Phase 2c backlog: activator AC-drug exclusivity). Not a Phase 2b defect.

3. **warfarin p10 = 1.50 (US)** — some warfarin patients are below therapeutic. This is realistic:
   - In-hospital warfarin order patients at day < 3 (still in loading phase, INR baseline)
   - Newly initiated chronic warfarin at very first encounter
   - These appear in the warfarin cohort because they have warfarin in `current_medications` or `medication_orders`, but the day-3 gate or low baseline keeps INR sub-therapeutic.

4. **warfarin max = 3.90** — compound over-AC patient (warfarin + cirrhosis or DIC). Clinically realistic — bleeding risk visible.

---

## Acceptance

All 3 axes PASS for both US and JP. Phase 2b ready for docs sync and PR.
