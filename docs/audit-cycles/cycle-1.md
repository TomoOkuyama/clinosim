# Cycle 1 — (not yet started, opens session 41)

**Status:** IN-PROGRESS — Global review + sampling phase
**Master HEAD at cycle start:** `615a4c28b6`
**Start date:** 2026-07-07 (session 40 tail, transitioning to cycle format)
**Population:** US 10000 + JP 10000
**Seed:** 42
**Output paths:** `/private/tmp/claude-818441110/-Users-tokuyama-workspace-clinosim/8cd1b570-652b-43c2-81ab-741830e596eb/scratchpad/cycle-1/{us,jp}`

## Generation command

```bash
python -m clinosim.simulator.cli generate --population 10000 --country US --seed 42 \
    --output <path>/us --format fhir-r4
python -m clinosim.simulator.cli generate --population 10000 --country JP --seed 42 \
    --output <path>/jp --format fhir-r4
```

## Issue list (target: 20 items) — LISTED 2026-07-07

Global US p=10000 + JP p=10000 review + random sampling (10 patients: 5 US + 5 JP).

| # | id | category | summary | offenders | impact |
|---|---|---|---|---|---|
| 1 | C1-01 | FHIR spec | Outpatient `AMB` encounters carry a `hospitalization` block; per FHIR R4 the block is for inpatient/ED context only | US 35986 / JP est. similar | Emits spec-inappropriate block on ~90% of encounters |
| 2 | C1-02 | FHIR spec | `Encounter.hospitalization.admitSource.coding` has code but no `display` | US 40830 (100%) | Interop degradation, display fallback needed |
| 3 | C1-03 | FHIR spec | `Encounter.hospitalization.dischargeDisposition.coding` has code but no `display` | US 40830 (100%) | Same as C1-02 |
| 4 | C1-04 | FHIR spec | `Encounter.hospitalization.dischargeDisposition` has empty `code` on some encounters | US 24 | Empty CodeableConcept, spec-violating |
| 5 | C1-05 | Clinical | `Encounter.type` is uniformly "Patient-initiated encounter" (SNOMED 270427003) for every AMB encounter — no diversity by department / visit reason | US 35986 (100% AMB) | Loss of clinical granularity |
| 6 | C1-06 | Reference integrity | `MedicationAdministration.request` field missing on 100% of records — no MAR→MR linkage | US 204001 (100%) | Fundamental order-to-administration audit trail broken |
| 7 | C1-07 | Reference integrity | All `MedicationRequest` records orphan (no MAR references them) — root cause identical to C1-06 | US 21820 (100%) | Same as C1-06 |
| 8 | C1-08 | Statistical / clinical | `MedicationRequest` per encounter very low (US 0.53, JP 0.19). Real EHR expected ~5-15/inpatient encounter | US 21820, JP 6014 | Missing chronic-med orders, admission orders, discharge orders |
| 9 | C1-09 | Statistical / realism | `Procedure` per encounter 0.028 US (1161 for 40k enc); real EHR expected 1-5/inpatient encounter | US 1161, JP 361 | Event density gap; session 40 memory `project_event_density_strategy.md` confirms |
| 10 | C1-10 | Statistical / realism | `ImagingStudy` per encounter 0.003 (107 for 40k enc); real EHR expected many more (multiple modalities per inpatient stay) | US 107, JP 104 | Imaging event density gap |
| 11 | C1-11 | Structural | `ClinicalImpression.summary` is empty on 100% of records | US 7261 (100%) | Missing key clinical-judgment field |
| 12 | C1-12 | Statistical | SDOH Observations (Occupation LOINC 11341-5, Tobacco 72166-2, Alcohol 11331-6) missing `effectiveDateTime` | US ~3853 SDOH obs | Observation without effective time = incomplete FHIR observation |
| 13 | C1-13 | Statistical | Microbiology susceptibility Observations (LOINC 18862-3 etc.) missing `effectiveDateTime` and `code.text` | US ~130+ sampled | Same as C1-12 |
| 14 | C1-14 | Structural | `CareTeam.status` is "inactive" for 40808/40832 encounters — CT status not derived from Encounter status/period correctly | US 40808 (99.9%) | Every finished encounter's CareTeam is marked inactive, but this is FHIR-inappropriate for active period reporting |
| 15 | C1-15 | Statistical / clinical | `CareTeam` has 1 participant (attending only) in 39665/40832 encounters; nurse added on 1167 (inpatient/ICU/rehab only per session 40 registry). No pharmacist/nutritionist/rehab even for inpatient | US 39665 solo, JP est similar | Under-populated CareTeam vs real multi-disciplinary practice |
| 16 | C1-16 | Clinical | All `ServiceRequest.intent` = "order" — real EHR has plan, original-order, instance-order variety (esp. for chronic-prescription plans) | US 100001 sampled (100%) | Loss of order-intent semantics |
| 17 | C1-17 | Clinical | All 960 `AllergyIntolerance` are `clinicalStatus:active` + `verificationStatus:confirmed` — no diversity (real practice: resolved, inactive, unconfirmed also exist) | US 960 (100%) | Over-simplified allergy state model |
| 18 | C1-18 | Statistical | JP Condition `problem-list-item` per encounter ~half of US (JP 1.20/enc, US 2.49/enc) with same population size and similar disease mix | JP 38416 vs US 101710 | Chronic condition emission difference between locales — likely a hidden branch |
| 19 | C1-19 | Statistical | All `Immunization.status` = "completed" — no "not-done" / "entered-in-error" — real practice has vaccine refusals, contraindicated, missed appointments | US 36945, JP 25390 (100%) | Reality gap |
| 20 | C1-20 | Realism | Patient count 6230 US / 4825 JP vs `--population 10000` argument — 38-52% of the population argument produced no patients | US 3770 / JP 5175 gap | Either intentional (family generation) or hidden silent-drop; needs clarification |

### Detection commands & samples

_(kept in scratchpad: `/private/tmp/claude-.../scratchpad/cycle-1/` NDJSON snapshots + inline python scans in this session's tool history)_

## Fix content (per issue)

_(populated during fix phase — one row per issue with commit hash + alternatives considered)_

## Verification result (recorded at cycle 2 opening)

_(populated when session ≥ 42 opens cycle 2 and re-runs generation)_

- Resolved: _(list)_
- Carried over to cycle 2: _(list)_
- Newly discovered during verification: _(list)_
