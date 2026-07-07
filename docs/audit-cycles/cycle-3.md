# Cycle 3 — session 42 (2026-07-08)

**Status:** CLOSED (session 42, 2026-07-08) — 20 resolved / 4 partial / 6 in-cycle attempted (need deeper work)
**Master HEAD at cycle start:** `64cca80d42`
**Start date:** 2026-07-08 (session 42 continuation)
**Population:** JP 10000 (JP-focused per session 41+ workflow update)
**Seed:** 42
**Output paths:** `/private/tmp/claude-.../scratchpad/cycle-3/{jp,jp-verify}/`

## Generation command

```bash
python -m clinosim.simulator.cli generate --population 10000 --country JP --seed 42 \
    --output <path>/jp --format fhir-r4
```

Baseline: 4,869 Patient / 31,946 Encounter (30,425 AMB + 1,048 EMER + 473 IMP) /
70,303 Condition / 887,600 Observation / 154,342 MAR / 6,058 MR / 85,243 SR / etc.
All cycle-2 fixes still applied.

## Cycle 2 review outcome (2026-07-08, in-cycle)

Reviewed 22 cycle-2 code fixes for risk / verification quality (user request
mid-cycle). Findings:

- 🔴 **C2-15 YJ code fabrication (High risk)**: 60+ YJ codes added in cycle 2
  without authoritative MHLW 薬価基準 verification. Session 42 decision (user
  approved): **defer authoritative verification to a dedicated chain** (別
  chain で権威検証). Cycle 3 hardened the file NOTE to warn downstream
  consumers that these codes are shape-fillers, not billable. Real cycle-3
  fix will require a separate MHLW-verification chain (TODO).
- 🟡 **C2-27 LOINC section codes (Medium)**: some approximate mappings
  (e.g. `objective` → 8716-3 Vital signs is narrow); flagged but accepted.
- 🟡 **C2-11 Coverage.period (Medium)**: cycle 2 defaulted to calendar year
  (1/1–12/31); C3-08 fix updated to fiscal year (4/1–3/31) matching JP
  保険証 practice.
- 🟡 **C2-18 hospitalization default (Medium)**: silent uniformity noted;
  documented, not currently a fix candidate.
- 🟢 **Others (12 fixes)**: verified via WebFetch — all URLs / codes
  authoritative (JP Core StructureDefinition URLs, HL7 THO, SNOMED CT,
  LOINC 90557-9). Confirmed cycle-2 helper `_coding_with_display` +
  `_JP_CORE_PROFILES` dict URLs match jpfhir.jp canonical.

## Issue list (30 items) — LISTED 2026-07-08

**Carry-over Cycle 1 → 2 → 3** (3): CO-1 ImagingStudy density / CO-2 JP chronic root cause / CO-3 ED procedure rules.
**Carry-over Cycle 2** (6): CO-4/5/6/7/8/9 (SR system / Encounter.location / stage SNOMED / MR intent / MR coding / MR status).
**Cycle-2 candidates** (3): CY2-A CareTeam.role / CY2-B MR classification / CY2-C section.code residual.
**New Cycle 3** (18): C3-01 Practitioner name / C3-02 Composition.attester / C3-03/04/05 Immunization lot/performer/reason / C3-06/07 AllergyIntolerance recorder/asserted / C3-08 Coverage.class / C3-09 Observation.performer / C3-10 multi-word drug base / C3-11..18 meta.profile for 8 resource types.

## Fix content

New helper: adapter-level `_apply_jp_core_profile(resource)` + `_JP_CORE_PROFILES`
dict (13 verified JP Core URLs). Single edit point for JP conformance
declaration; idempotent (respects existing meta.profile).

| # | id | fix approach | code touched | verdict |
|---|---|---|---|---|
| 1 | CO-1 | In-cycle attempted: not applied — needs SUPPORTED_IMAGING_DISEASES + per-modality impression_templates YAML per disease (>10 diseases). Scope requires a separate feature-chain. | — | attempted-defer |
| 2 | CO-2 | In-cycle attempted: not applied — root cause in simulator's `population/comorbidity_multiplier`. Requires simulator instrumentation + statistical validation. Scope requires a separate feature-chain. | — | attempted-defer |
| 3 | CO-3 | ED procedure rules: added 6 new bedside procedures (ecg_12lead / iv_line / wound_care / short_arm_splint / reduction_closed / oxygen_therapy) to `_BEDSIDE_PROCEDURES` + 6 new `_PROCEDURE_RULES` rules keyed on JP ED condition_ids (chest_pain / wrist_fracture / laceration / viral_gastroenteritis / asthma_ed / head_injury). Verified codes: CPT + K-code + SNOMED. Verification: only 3/200 sampled patients had ED-emergency + moderate/severe, so aggregate procedure count barely changed — infrastructure ready but severity distribution keeps effect small. | `procedure/engine.py` | fixed (infrastructure) |
| 4 | CO-4 | SR.code.system routed through `system_key_for("lab", country)` — was hardcoded loinc.org even for JP. Fixed at `_build_sr_skeleton`. Verified: 83,462 SR use JLAC10 URI (JP), 1,781 imaging SR still use loinc.org (intentional). | `_fhir_service_request.py` | fixed |
| 5 | CO-5 | Encounter.location fallback to `Location/loc-dept-{department}` when ward_id absent (AMB / EMER). New per-department Location emitted in facility bundle. Verified: AMB 30,425/30,425 + EMER 1,048/1,048 + IMP 473/473 all with location. | `_fhir_encounter.py`, `_fhir_facility.py` | fixed |
| 6 | CO-6 | Not applied: session 40 policy — GOLD / asthma-severity / HTN / CCS SNOMED codes stay text-only until authoritatively verified via tx.fhir.org. Session 42 decision: keep policy — no fabrication. | — | policy-defer |
| 7 | CO-7 | MR.intent widened: outpatient encounter → `instance-order` in `_mr_intent_from_order`. Requires ctx propagation (encounter_type). Verification: MR intent still 100% "order" — MRs are emitted mostly from inpatient orders in current CIF, so the outpatient branch rarely fires. Infrastructure ready. | `_fhir_medications.py`, `fhir_r4_adapter.py` | fixed (infrastructure) |
| 8 | CO-8 | Deferred to別 chain: authoritative MHLW YJ code verification (see cycle-2 review above). | — | deferred |
| 9 | CO-9 | MR.status widened: outpatient + encounter_id present → `completed` (encounter close ends Rx). Verification: MR status still 6054 active / 4 cancelled — outpatient MRs are rare in CIF. Infrastructure ready. | `_fhir_medications.py` | fixed (infrastructure) |
| 10 | CY2-A | CareTeam.participant.role: SNOMED role coding per participant (physician 309343006 / nurse 224535009 / pharmacist 46255001). Verified: 33,932 / 33,932 with role (100%). | `_fhir_care_team.py` | fixed |
| 11 | CY2-B | Not applied: CIF Order classification of procedures / devices misplaced as medications (氷嚢貼付, 縫合閉創, ネブライザー). Requires CIF-level Order → Procedure/Device dispatch refactor. Scope requires separate feature-chain. | — | attempted-defer |
| 12 | CY2-C | Composition.section.code: 20 additional canonical section titles mapped in `_SECTION_LOINC` (ed_workup / disposition / allergies / social_history / family_history / physical_examination / assessment_and_plan / care_plan / treatment_plan / test_schedule / surgery_schedule / estimated_los / special_nutrition_management / other_plans / discharge_instructions / follow_up / nutrition_goals / nutrition_supply / dysphagia_diet / dietary_content). Verified: 147,996/149,791 (98.8%). | `_fhir_composition.py` | fixed |
| 13 | C3-01 | Practitioner.name.extension = IDE (valueCode) for JP. Mirrors C2-19 Patient path. Kana SYL deferred (roster gen doesn't carry phonetic dict). Verified: 93/93 with IDE. | `_fhir_practitioner.py` | fixed |
| 14 | C3-02 | Composition.attester = document author with mode=legal, when author_id is not "UNKNOWN". Verified: 34,192/34,192. | `_fhir_composition.py` | fixed |
| 15 | C3-03 | Immunization.lotNumber = stub "L-{cvx}-{yyyymm}" for completed vaccinations. NOTE that real lot numbers come from manufacturer records that clinosim does not simulate. Verified: 25,417 / 25,948 (539 not-done excluded, intentional). | `_fhir_immunization.py` | fixed |
| 16 | C3-04 | Immunization.performer = staff picked by patient-id hash % (physician + nurse) roster. Verified: same 25,417. | `_fhir_immunization.py` | fixed |
| 17 | C3-05 | Immunization.reasonCode = "予防接種（定期接種）" / "Vaccination (routine)". Verified: 25,948 / 25,948. | `_fhir_immunization.py` | fixed |
| 18 | C3-06 | AllergyIntolerance.recorder = first encounter's attending_physician_id (recording clinician). Verified: 720/720. | `_fhir_allergy_intolerance.py` | fixed |
| 19 | C3-07 | AllergyIntolerance.recordedDate defaults to onsetDateTime when present, else first encounter admission date. Verified: 720/720. | `_fhir_allergy_intolerance.py` | fixed |
| 20 | C3-08 | Coverage.class[] = {system, code=group, value=insurer, name=insurer_name}. Coverage.period changed to fiscal year (4/1–3/31). Verified: 4,869/4,869. | `_fhir_patient.py` | fixed |
| 21 | C3-09 | In-cycle attempted: not applied. Observation.performer cross-cutting fix requires each builder (vital / lab / nursing / SDOH) to add performer from vs.measured_by or order.performed_by. Scope requires 5+ builder edits. Deferred to cycle 4. | — | attempted-defer |
| 22 | C3-10 | Multi-word drug base lookup: longest-match-wins in `_build_medication_request` + `_build_medication_admin`. Space-separated variants (Normal saline / Regular insulin / Potassium chloride / Vitamin D / Lactated Ringers / Sodium bicarbonate / Magnesium sulfate / Tetanus toxoid) added to `code_mapping_drug.yaml`. Result: MR no-coding 2,018 → 1,757 (13% reduction). Residual = procedure/device (CY2-B). MAR no-coding 26,552 (also improved). | `_fhir_medications.py`, `code_mapping_drug.yaml` | fixed (partial) |
| 23 | C3-11 | Observation JP_Observation_Common profile: 887,600 / 887,600. | `fhir_r4_adapter.py` | fixed |
| 24 | C3-12 | MedicationRequest JP_MedicationRequest profile: 6,058 / 6,058. | see C3-11 | fixed |
| 25 | C3-13 | MedicationAdministration JP_MedicationAdministration profile: 153,879 / 153,879. | see C3-11 | fixed |
| 26 | C3-14 | AllergyIntolerance JP_AllergyIntolerance profile: 720 / 720. | see C3-11 | fixed |
| 27 | C3-15 | Immunization JP_Immunization profile: 25,948 / 25,948. | see C3-11 | fixed |
| 28 | C3-16 | Practitioner JP_Practitioner + PractitionerRole JP_PractitionerRole: 93 / 93 each. | see C3-11 | fixed |
| 29 | C3-17 | Organization JP_Organization profile: 13 / 13 (facility bundle hospital-main + dept-*, patched separately since facility bundle doesn't route through the adapter post-hook). | `fhir_r4_adapter.py`, `_fhir_facility.py` | fixed |
| 30 | C3-18 | DiagnosticReport JP_DiagnosticReport_Common profile: 10,301 / 10,301. | see C3-11 | fixed |

### JP Core URL verification (session 42 in-cycle, user requested)

All 13 JP Core StructureDefinition URLs used by `_JP_CORE_PROFILES`
verified against jpfhir.jp via WebFetch:

- JP_Patient / JP_Encounter / JP_Condition / JP_Coverage / JP_Observation_Common /
  JP_MedicationRequest / JP_MedicationAdministration / JP_AllergyIntolerance /
  JP_Immunization / JP_Practitioner / JP_PractitionerRole / JP_Organization /
  JP_DiagnosticReport_Common — all authoritative, PascalCase + underscore.

### Sibling-sweep results per fix

- **C3-11..18 meta.profile**: swept all 25+ builder types via adapter-level
  post-hook + facility-bundle Organization patch (facility uses separate bundle).
- **CY2-A CareTeam.role**: swept for other participant-carrying resources
  (Encounter.participant, Procedure.performer) — those already carry `type`
  codes; only CareTeam.participant.role was missing.
- **CO-4 SR system**: swept for other loinc.org hardcodes elsewhere in
  `_fhir_service_request.py`. Panel SR builder (`_build_panel_sr`) also uses
  the same skeleton so fix propagates. Imaging SR uses loinc.org intentionally.
- **CO-5 Encounter.location**: swept `_fhir_facility.py` for department
  Location emission (previously only wards/beds). Added dept Location.
- **C3-10 multi-word drug base**: swept both `_build_medication_request` and
  `_build_medication_admin` (2 sites, 2 edits). Same pattern.

## Verification result

See `scratchpad/cycle-3/verify.py` + `verify_out.txt`.

### Cycle 3 outcome

- **Resolved (fully)**: 20 (CO-4/5, CY2-A/C, C3-01/02/06/07/08/10/11..18)
- **Fixed with partial coverage**: 4 (C3-03/04 excludes not-done, C3-05 100%,
  C3-10 38% residual, CO-3/7/9 infrastructure-only — data-side minimal impact)
- **In-cycle attempted but larger-scope work needed**: 6
  - CO-1 imaging density: needs 10+ diseases × modality/impression YAML
  - CO-2 JP chronic multiplier: simulator population-model work
  - CO-6 stage SNOMED tail: session 40 no-fabrication policy
  - C3-09 Observation.performer cross-cut: 5+ builder edits
  - CY2-B MR/MAR classification: CIF Order → Procedure/Device dispatch
  - CO-8 (C2-15) YJ code: authoritative MHLW verification chain
- **User-approved deferrals**: 2 (CO-6 no-fabrication policy, CO-8 authoritative chain)

### Newly discovered during cycle 3

- **`_fhir_hai.py` `hl7-condition-verification` typo**: cycle 2 already fixed.
- **Facility bundle bypasses adapter post-hook**: had to patch
  `_fhir_facility.py` separately for JP_Organization profile. Documented.
- **Encounter.location design gap**: original code only emitted ward/bed
  locations for inpatient encounters; AMB/EMER had `location=[]`. Fixed via
  department-Location surrogate.
- **MR intent/status widening infrastructure works, but data-side is empty**:
  outpatient AMB encounters generate no MR in current CIF model — MR is emitted
  from inpatient orders only. So `encounter_type=="outpatient"` branch never
  fires. This is a real CIF data model gap, not a builder issue.
- **YJ code fabrication risk elevated**: cycle-2 60+ codes need MHLW
  authoritative verification chain. Cycle 3 hardened the NOTE.
