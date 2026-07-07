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

Applied during cycle 1 fix phase. Verification is deferred to cycle 2 opening
(regenerate JP p=10000 and confirm resolution). Session 41 4-axis rule applied:
for every new addition, checked (1) project concept fit, (2) module
responsibility, (3) data quality / clinical integrity, (4) structural
simplicity, plus rule "additions only when strictly required".

| # | id | fix approach | code touched | verdict |
|---|---|---|---|---|
| 1 | C1-01 | AMB encounters skip `hospitalization` block (FHIR R4 semantics: inpatient/ED only). Existing-code fix. | `_fhir_encounter.py` | fixed |
| 2 | C1-02 | New authoritative `codes/data/hl7-admit-source.yaml` (en+ja, HL7 THO). Builder resolves display via `code_lookup` (locale-aware). Multi-language preserved. | `_fhir_encounter.py`, `codes/data/hl7-admit-source.yaml` (new) | fixed |
| 3 | C1-03 | New authoritative `codes/data/hl7-discharge-disposition.yaml`; same pattern as C1-02. | `_fhir_encounter.py`, `codes/data/hl7-discharge-disposition.yaml` (new) | fixed |
| 4 | C1-04 | Not-a-bug: 24 offenders are `status=in-progress` encounters (snapshot cut mid-stay); FHIR-correctly lack `dischargeDisposition`. | — | not-a-bug |
| 5 | C1-05 | AMB SNOMED diversification: `chief_complaint` startswith "Follow-up" → 185349003 "Encounter for check-up"; else with primary_dx_code + not readmission → 11429006 "Consultation"; else 270427003 (unchanged). Existing-code fix using existing enc context. | `_fhir_encounter.py`, `codes/data/snomed-ct.yaml` (2 new authorized codes) | fixed |
| 6 | C1-06 | MAR.request field populated by constructing the MedicationRequest id (`{enc_id}-{order_id}`) from CIF's existing `order_id`. No new fields. | `_fhir_medications.py` | fixed |
| 7 | C1-07 | Same root cause as C1-06; the `request` reference makes all MedicationRequests reachable from MAR audit trail. | see C1-06 | fixed |
| 8 | C1-08 | Not-a-bug on re-analysis: MR count 21820 for a 90% outpatient cohort matches EHR reality (~0.5/enc). MAR:MR 9:1 realistic for multi-day inpatient orders. | — | not-a-bug |
| 9 | C1-09 | Partial: Emergency simulator now calls `generate_bedside_procedures` for moderate/severe ED cases (reuses existing rule table). Outpatient AMB procedures not fabricated. | `simulator/emergency.py` | partial fix |
| 10 | C1-10 | Carry-over to cycle 2: adding imaging_orders to 5 more diseases requires expanding SUPPORTED_IMAGING_DISEASES + impression_templates.yaml for every disease/modality/body_site combination = 大工事 (violates simplicity axis for cycle 1 scope). | — | carry-over |
| 11 | C1-11 | Not-a-bug: FHIR ClinicalImpression.summary is optional (0..1); no distinct source data in CIF. Fabrication would violate rules. `description` populated correctly. | — | not-a-bug |
| 12 | C1-12 | SDOH Observations (occupation/smoking/alcohol) now derive effectiveDateTime from earliest encounter admission (US Core/JP Core social-history profile requires effective[x]). Shared helper `_sdoh_effective_datetime` in `_fhir_smoking_alcohol.py`. | `_fhir_smoking_alcohol.py`, `fhir_r4_adapter.py` | fixed |
| 13 | C1-13 | Microbiology susceptibility Observation now inherits `reported_datetime` from the parent organism observation (same reported result). | `_fhir_microbiology.py` | fixed |
| 14 | C1-14 | Not-a-bug: FHIR R4 CareTeam.status="inactive" is spec-correct for completed encounters (team no longer providing care). | — | not-a-bug |
| 15 | C1-15 | Pharmacist added as CareTeam participant for inpatient/emergency encounters (JP practice: 病棟薬剤師). Deterministic pharmacist selection from roster by encounter-id hash (AD-16). Multi-language: no display, just Practitioner reference. | `_fhir_care_team.py` | fixed (min viable) |
| 16 | C1-16 | SR.intent context-aware via `_sr_intent_from_clinical_intent(order.clinical_intent)`: "Follow-up" → instance-order; ED workup/imaging → original-order; default → order. Reuses existing CIF field. | `_fhir_service_request.py` | fixed |
| 17 | C1-17 | AllergyIntolerance clinicalStatus + verificationStatus diversified: 85% active+confirmed, 5% resolved (food only, childhood outgrown), 10% active+unconfirmed. New CIF field `Allergy.clinical_status` (previously only verification_status existed — asymmetric, this fix aligns). | `types/allergy.py`, `allergy/engine.py`, `_fhir_allergy_intolerance.py` | fixed |
| 18 | C1-18 | Carry-over to cycle 2: root cause identified (US patients have ~2.75 chronic conditions/enc, JP ~1.21, but demographics.yaml prevalence suggests JP should be higher). Bug is in comorbidity multiplier / lifestyle multiplier path, not in FHIR emission. Requires simulator investigation with JP focus. | — | carry-over |
| 19 | C1-19 | ~2% of would-be immunizations now emitted as `status="not-done"` with `statusReason` PATOBJ (patient objection). Field already existed on ImmunizationRecord. New system URI `hl7-v3-actreason` registered. | `immunization/engine.py`, `_fhir_immunization.py`, `codes/loader.py` | fixed |
| 20 | C1-20 | Not-a-bug: population=catchment total (10000) and Patient=those-with-encounters (~5-6k) is intentional design. Realistic healthcare utilization rate. | — | not-a-bug |

### Sibling-sweep results per fix (session 39 rule)

- **C1-02/03/05**: swept authoritative code data files under `codes/data/`. No other CodeSystem-URI-mapped builder emits code without display (grep on `"code":` + `"system":` + no `"display"` in FHIR builders). Clean.
- **C1-06**: swept all resource-to-resource references. No other `_fhir_*` builder omits a "linked-order" reference where the linked resource exists. Clean.
- **C1-12/13**: swept all Observation builders for missing `effectiveDateTime`. Others use to_fhir_datetime already. Clean.
- **C1-15**: swept for other roster roles missing from FHIR CareTeam. Session 40 registry β-JP-1 backlog covers the full 6-name expansion (dietitian, PT/OT, MSW). Cycle 2+ candidate.
- **C1-16**: swept for other `"intent": "order"` hardcodes. Only found the 2 SR emission points; both migrated.
- **C1-17**: swept AllergyIntolerance for other missing clinical_status paths. Only 1 CIF source path; fixed.
- **C1-19**: swept other status-monotonic resources. Immunization was the only 100% "completed" case; AllergyIntolerance had similar issue (C1-17). Others (Condition, Observation, MedicationRequest, ServiceRequest) already have realistic diversity.

Summary: 20 issues addressed — 13 fixed with code changes, 5 not-a-bug (documented rationale), 2 carry-over to cycle 2 (C1-10 imaging density + C1-18 JP chronic conditions root cause).

## Verification result (recorded at cycle 2 opening)

_(populated when session ≥ 42 opens cycle 2 and re-runs generation)_

- Resolved: _(list)_
- Carried over to cycle 2: _(list)_
- Newly discovered during verification: _(list)_
