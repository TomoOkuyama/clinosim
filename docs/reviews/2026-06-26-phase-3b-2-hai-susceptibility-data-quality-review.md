# Phase 3b-2 HAI Culture Susceptibility — Data Quality Review

**Date**: 2026-06-26
**Branch**: feat/phase-3b-2-hai-susceptibility (HEAD: cc8bfa954)
**Spec**: docs/superpowers/specs/2026-06-26-phase-3b-2-hai-susceptibility-design.md
**Master baseline**: 6011b06e (post-PR-93/94/95)
**Verdict**: PASS

---

## 1. Test Suite

All tests pass on branch HEAD.

| Suite | Result | Count |
|---|---|---|
| `pytest -m "unit or integration"` | PASS | 787 passed, 3 skipped |
| `pytest -m e2e` | PASS | 39 passed |

---

## 2. Byte-diff (p=2000 US + p=1000 JP, seed=42)

Generated baseline on master `6011b06e` and PR branch at identical parameters.

### US (p=2000, seed=42)

| Artifact | Status | Notes |
|---|---|---|
| `Observation.ndjson` | DIFF (expected) | 10 `mb-sus-*` observations: Ciprofloxacin LOINC corrected 18879-7 → 18906-8 (Task 2 fix). Line count identical (195308). |
| `CIF/*.json` | DIFF (expected) | Timestamps only + same Ciprofloxacin LOINC fix in `antibiotic_loinc` field. No other structural changes. |
| `manifest.json` | DIFF (expected) | `transactionTime` timestamp only. |
| `AllergyIntolerance.ndjson` | IDENTICAL | AD-16 ✓ |
| `Condition.ndjson` | IDENTICAL | AD-16 ✓ |
| `Device.ndjson` | IDENTICAL | AD-16 ✓ |
| `DeviceUseStatement.ndjson` | IDENTICAL | AD-16 ✓ |
| `DiagnosticReport.ndjson` | IDENTICAL | AD-16 ✓ |
| `Encounter.ndjson` | IDENTICAL | AD-16 ✓ |
| `FamilyMemberHistory.ndjson` | IDENTICAL | AD-16 ✓ |
| `Immunization.ndjson` | IDENTICAL | AD-16 ✓ |
| `MedicationAdministration.ndjson` | IDENTICAL | AD-16 ✓ |
| `MedicationRequest.ndjson` | IDENTICAL | AD-16 ✓ |
| `Organization.ndjson` | IDENTICAL | AD-16 ✓ |
| `Patient.ndjson` | IDENTICAL | AD-16 ✓ |
| `Practitioner.ndjson` | IDENTICAL | AD-16 ✓ |
| `PractitionerRole.ndjson` | IDENTICAL | AD-16 ✓ |
| `Procedure.ndjson` | IDENTICAL | AD-16 ✓ |
| `Specimen.ndjson` | IDENTICAL | AD-16 ✓ |

### JP (p=1000, seed=42)

Same pattern as US: only `Observation.ndjson` (7 Ciprofloxacin LOINC corrections), `CIF/*.json` (timestamps + LOINC fix), and `manifest.json` (timestamp) differ. All 16 other NDJSON types: **IDENTICAL**.

### AD-16 Verdict

PASS. No cross-patient simulation state leaked. The only NDJSON difference is in `Observation.ndjson` — specifically the `code.coding[0].code` field on existing `mb-sus-*` community-microbiology susceptibility Observations for Ciprofloxacin. Same observation IDs, same patient/encounter assignments, same interpretation values. This is the intentional Task 2 LOINC code correction (18879-7 was Cefepime, not Ciprofloxacin; 18906-8 is the correct LOINC for Ciprofloxacin [Susceptibility]).

---

## 3. clinosim audit run

### Axis Summary

| Module | structural | jp_language | clinical | silent_no_op | Overall |
|---|---|---|---|---|---|
| antibiotic (US p=10k) | N/A | N/A | N/A | **PASS** | PASS |
| hai (US p=10k) | N/A | N/A | N/A | **PASS** | PASS |
| antibiotic (JP p=5k) | N/A | N/A | N/A | **PASS** | PASS |
| hai (JP p=5k) | N/A | N/A | N/A | **PASS** | PASS |

The structural / jp_language / clinical axes remain N/A per design (audit.py comment:
clinical R-rate enforcement deferred to PR3b-3 which will walk `Observation.ndjson` for
susceptibility LOINCs cohort-wide). The `silent_no_op` axis is the load-bearing
PR-90-class gate.

### silent_no_op Proof (both US + JP identical)

**antibiotic module**:
```
constants_pass_hai_empirical.yaml=ok
proof_eq_ext_antibiotic_count=1
proof_eq_ext_antibiotic_drug='ceftriaxone'
proof_eq_ext_antibiotic_duration_days=7
proof_eq_orders_medication_count=1
proof_eq_mar_count=7
proof_eq_mar_drug='Ceftriaxone'
proof_eq_mar_first_dt=datetime.datetime(2026, 1, 10, 8, 0)
proof_eq_mar_last_dt=datetime.datetime(2026, 1, 16, 8, 0)
proof_eq_clabsi_saureus_susceptibility_count=6
proof_eq_clabsi_saureus_vancomycin_is_S='S'
```

`proof_eq_clabsi_saureus_susceptibility_count=6` and `proof_eq_clabsi_saureus_vancomycin_is_S='S'`
are the antibiogram_firing_proof required by PR3b-2 (CLABSI S. aureus with 6 antibiotics tested,
Vancomycin always S — confirms the hai_antibiogram.yaml → ANTIBIOTIC_LOINC_LOOKUP →
FHIR Observation chain is firing and not silently no-op'd).

**hai module**:
```
constants_pass_hai_lab_lift.yaml=ok
proof_WBC_delta=2520.0
```

---

## 4. Clinical Realism (US p=10000, seed=42)

### Community Microbiology Cohort

| Metric | Value | Threshold | Verdict |
|---|---|---|---|
| Positive cultures | 374 | — | — |
| Empty susceptibility rate | 0.5% (2/374) | < 5% | **PASS** |

The 2 organisms without susceptibilities are E. faecalis (SNOMED 53326005), which is
intentionally excluded from the antibiogram panel in the community microbiology YAML
("routine S/I/R panel not applicable for our 8-abx scope").

### Community Antibiogram Rates (spot-check vs YAML priors)

| Organism | Antibiotic (LOINC) | Measured %R | YAML prior | Verdict |
|---|---|---|---|---|
| S. aureus (3092008) | Cefazolin 18866-4 (MRSA proxy) | 26.1% (6/23) | 30% | PASS (within ±1σ) |
| E. coli (112283007) | Ceftriaxone 18895-3 (ESBL proxy) | 14.4% (31/215) | 12% | PASS (within ±1σ) |

### HAI-Specific Susceptibility Cohort (US p=10000)

| Metric | Value | Notes |
|---|---|---|
| Total HAI events | 5 | 3 CAUTI + 2 VAP |
| HAI-linked cultures | 5 | All 5 HAI events have culture records |
| Cultures with S/I/R results | 3 | CAUTI/E.coli, VAP/S.aureus, VAP/K.pneumoniae |
| Cultures without S/I/R (intentional) | 2 | Both E. faecalis (CAUTI) — excluded per antibiogram design |
| Unintended empty susceptibilities | 0 | 0% |

HAI-specific NHSN acceptance band verification (MRSA rate, ESBL rate by cohort) is
deferred to PR3b-3 per design (`audit.py` comment). The sample size (5 events) is too
small for meaningful R-rate statistics. The `antibiogram_firing_proof` in the
`silent_no_op` axis (deterministic forced scenario) is the load-bearing verification
gate for PR3b-2.

---

## 5. JP Language Quality (JP p=5000, seed=42)

No new Japanese text fields added by PR3b-2. FHIR S/I/R `interpretation` values use
`v3-ObservationInterpretation` codes (S/I/R) with existing FHIR display logic.

JP cohort metrics:
- Positive cultures: 38, Empty susceptibilities: 0 (0.0%)
- HAI events: 0 (expected — low HAI rate in JP 5k cohort)
- JP regression: **N/A** (no new JP text paths introduced)

---

## 6. Summary

| Gate | Result | Notes |
|---|---|---|
| Tests (unit+integration+e2e) | **PASS** | 787+39 all green |
| AD-16 byte-diff | **PASS** | 16/16 non-Observation NDJSON types identical US+JP |
| Observation.ndjson diff | Expected | Ciprofloxacin LOINC correction only (Task 2) |
| clinosim audit run (US p=10k) | **PASS** | antibiogram_firing_proof emitted equality checks |
| clinosim audit run (JP p=5k) | **PASS** | Same proof checks |
| Empty susceptibility rate | **PASS** | 0.5% community, 0% HAI-intentional (< 5%) |
| Community antibiogram rates | **PASS** | S. aureus %MRSA 26.1%, E. coli %ESBL 14.4% |

**Ship-readiness verdict: PASS.**

Backlog:
- HAI-specific NHSN band enforcement (MRSA/ESBL % per cohort vs acceptance bands)
  deferred to PR3b-3 per `audit.py` design comment.
- `discontinuation_datetime` forward-compat field (Task 1) is serialized as `None` / not
  present in CIF output — will be populated by PR3b-3 narrow/de-escalation logic.
