# PR3b-3 narrow / de-escalation — Data Quality Review

**Date**: 2026-06-27
**Branch**: `feat/pr3b-3-narrow-de-escalation`
**Generation**: US p=10000 + JP p=5000, seed=42, `--format fhir-r4`, hospital `hospital_operations.yaml`
**Audit gate**: `clinosim audit run` 4-axis verdict
**Spec**: [`docs/superpowers/specs/2026-06-27-pr3b-3-narrow-de-escalation-design.md`](../superpowers/specs/2026-06-27-pr3b-3-narrow-de-escalation-design.md)
**Plan**: [`docs/superpowers/plans/2026-06-27-pr3b-3-narrow-de-escalation.md`](../superpowers/plans/2026-06-27-pr3b-3-narrow-de-escalation.md)

---

## Verdict

**Overall: WARN** (no FAIL; warnings are rare-event regime, mitigated by `silent_no_op` axis load-bearing PR-90-class equality_checks).

| Module | structural | jp_language | clinical | silent_no_op |
|---|---|---|---|---|
| antibiotic | N/A | PASS | WARN | **PASS** |
| hai | PASS | PASS | WARN | **PASS** |

The `silent_no_op` axis runs **17 equality_checks** (8 PR3b-1 + 3 PR3b-2 + **6 PR3b-3**), each verified against the production code path with hard equality. This is the load-bearing gate that closes the PR-90 silent-no-op class of bug — a green DQR with rare HAI events at population scale can be confounded, but the synthetic equality_checks fire deterministically against the real `enrich_antibiotic(ctx)` Pass 2 chain (cefazolin S → switch / vancomycin discontinuation_datetime / pip-tazo discontinuation_datetime / 1 narrowed regimen / drug=cefazolin / intent="narrowed").

---

## Generation summary

| Resource | US | JP |
|---|---:|---:|
| Patient | 10000 | 5000 |
| Device | 368 | 22 |
| HAI Condition (T80.211A / T83.511A / J95.851) | **4** | 0 |
| empirical abx MedicationRequest (`id: abx-hai-*`) | **7** | 0 |
| narrowed MedicationRequest (`id: *-narrowed`) | **2** | 0 |
| MedicationRequest `status="stopped"` | **3** | 0 |
| MedicationAdministration total | 626989 | 70855 |
| DiagnosticReport | 18191 | 4547 |

**JP has 0 HAI events** because of small ICU device cohort (n=22 vs US n=368) and shorter line-days at p=5000. At production scale JP would also produce HAI events; this run is rare-event by construction.

---

## PR3b-3 narrow chain firing analysis (US)

Counts:
- **HAI events**: 4 (3 CAUTI + 1 VAP per inferred mix; details below)
- **empirical regimens** (Pass 1): 7 abx-hai-* MedicationRequests, broken down as:
  - CAUTI ceftriaxone (1 drug × 3 events × 1 narrowed = 3 of the 7)
  - VAP vancomycin + piperacillin_tazobactam (2 drugs × 1 event = 2 of the 7)
  - Note: 7 = 3 (CAUTI) + 2 (VAP) + 2 (1 of the CAUTI narrowed to a new drug = 1 narrowed MedReq additionally counted)
- **narrow Pass 2 outcomes**:
  - 2 events fired SWITCH (2 narrowed MedicationRequest)
  - 1 event fired ELIMINATION OR (the third stopped count is the second SWITCH's empirical)
  - The `status="stopped"` count (3) - the `-narrowed` count (2) = 1 ELIMINATION event where empirical was discontinued without a new narrow regimen

Per-cohort observed values (US, from `clinical` axis info):
- `us/cauti/112283007_narrow_rate` = **0.667** (n=3 cohort — WARN, band [0.10, 0.30] not enforced)
- `us/vap/3092008_narrow_rate` = **1.0** (n=1 — WARN)
- `us/clabsi/3092008_narrow_n` = 0 (no S.aureus CLABSI in US run)
- `us/cauti/112283007_ceftriaxone_n` = 2 (R-rate gate WARN, n<30)
- `us/vap/3092008_cefazolin_n` = 1 (R-rate gate WARN, n<30)
- `us_hai_empty_susc_rate` = 0.333 (n=3 — WARN with new guard, below production-scale enforcement threshold)

---

## Axis verdicts

### Axis 1: structural — PASS

LOINC referenceRange + interpretation coverage 100% on numeric Observations (WBC, CRP, etc.). No regressions from PR3b-3 (PR3b-3 adds categorical S/I/R susceptibility observations whose structural correctness is verified by the silent_no_op `equality_checks` and tracked by the PR3b-2 `_ABX_LOINCS` design note).

### Axis 2: jp_language — PASS

- `us_non_ascii_display_violations=0` — no Japanese characters leaked into US output
- All JP labs (WBC + CRP) 100% localized

PR3b-3 introduces no new locale-specific display text; new `MedicationRequest.status="stopped"` value is FHIR-vocabulary (not localized text).

### Axis 3: clinical — WARN

All 11 warnings are **`n < 30` cohort-too-small** (rare-event regime at p=10000 + JP p=5000). No FAILs after the empty-rate WARN-guard fix.

Both Pass 2 new gates (`narrow_rate` + `hai_empty_susc_rate`) report the observed values in `result.info` even when below the enforcement threshold, so DQR visibility is preserved.

### Axis 4: silent_no_op — PASS

17 equality_checks all pass (full list in `audit_run.log`):
- 8 PR3b-1 (CAUTI ceftriaxone regimen)
- 3 PR3b-2 (CLABSI S.aureus susceptibility)
- **6 PR3b-3** (CLABSI MSSA → cefazolin switch + discontinuation_datetime + narrow regimen):
  - `proof_eq_pr3b3_narrow_target_drug='cefazolin'`
  - `proof_eq_pr3b3_empirical_vancomycin_discontinued_at=datetime.datetime(2026, 1, 12, 0, 0)`
  - `proof_eq_pr3b3_empirical_pip_tazo_discontinued_at=datetime.datetime(2026, 1, 12, 0, 0)`
  - `proof_eq_pr3b3_new_narrowed_regimen_count=1`
  - `proof_eq_pr3b3_new_narrowed_regimen_drug='cefazolin'`
  - `proof_eq_pr3b3_new_narrowed_regimen_intent='narrowed'`

Plus canonical-constants pass on `hai_empirical.yaml` and (via Task 5 ladder validation touch) `narrow_ladder.yaml`.

---

## FHIR diff vs PR3b-2 baseline

Bounded to:
- `MedicationRequest.ndjson` — 2 new `-narrowed`-suffixed resources + 3 resources with `status="stopped"` instead of `"active"`
- `MedicationAdministration.ndjson` — empirical MAR doses truncated past `discontinuation_datetime` + new narrow MAR doses added

No other resource type counts changed. byte-diff intentionally broken (new-feature PR).

---

## Test verification

Per CLAUDE.md PR-merge gate:
- **unit** (`tests/unit/test_narrow_ladder.py` + `test_narrow_engine.py`): **6 + 12 = 18 PASSED**
- **integration** (`tests/integration/test_narrow_enricher.py` + `test_antibiotic_audit.py` extension): **6 + 8 = 14 PASSED**
- **e2e** (`tests/e2e/`): **39 PASSED** (no NDJSON golden infrastructure exists; literal-assertion goldens unchanged)
- **clinosim audit run** (production gate): **WARN overall, no FAIL**, silent_no_op PASS
- Full suite (unit + integration + e2e): **5 pre-existing failures (audit registry `_reset_for_test` ordering on master), 983 passed, 4 skipped**

No PR3b-3 regression.

---

## 4-axis decision rationale

| Axis | Verdict | Reason |
|---|---|---|
| データ品質 | OK | New narrow regimens + status=stopped MedicationRequest emit correctly; rare-event regime makes population-scale verification small but firing path proven by silent_no_op axis |
| 臨床整合性 | OK | Pass 2 implements IDSA stewardship narrow / de-escalation faithfully; 3 outcomes (SWITCH / ELIMINATION / NO_CHANGE) match clinical reality; FHIR `MedicationRequest.status="stopped"` reflects real timeline |
| メンテ性 | OK | Same enricher 2-pass (1 module = 1 enricher convention preserved); new helpers in `engine.py` are pure functions; audit gates use existing `clinical_acceptance` metadata schema |
| コンセプト適切性 | OK | Forward-compat reserves (`intent="narrowed"`, `discontinuation_datetime`, `hai_event_id`) all load-bearing as designed; `OrderStatus.STOPPED` follows FHIR R4 status vocabulary |

---

## Out-of-scope items (deferred to subsequent PRs)

- **Per-organism filtering for empty-susc rate denominator** — current implementation counts all HAI cohort encounters; spec note in audit.py acknowledges panel-eligible filtering would require walking DiagnosticReport for organism (Phase 2 backlog)
- **PR3b-4 WBC/CRP decay** after antibiotic start_day
- **eGFR-based dose adjustment** for narrow target dose (current uses simplified `_narrow_dose_frequency` table)
- **Multi-drug narrow** (current: single target drug)

---

## Post-merge action

Per CLAUDE.md `feedback_iterative_adversarial_review`:
- After merge, run 4-stage adversarial review fan-out
- Fix PR for any Critical / Important findings
- Stop chain when Critical/Important = 0 + finding converging + remaining cosmetic-only + next-round expected size tiny
- Document convergence verdict in final fix PR body
