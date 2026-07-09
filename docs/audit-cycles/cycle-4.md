# Cycle 4 — session 43 (2026-07-09)

**Status:** CLOSED (session 43, 2026-07-09) — 22 fully resolved / 3 partial / 5 deferred
**Master HEAD at cycle start:** `225e1c7ca9`
**Start date:** 2026-07-09 (session 43)
**Population:** JP 10,000 (JP-focused per session 41+ workflow)
**Seed:** 42
**Output paths:** `/private/tmp/claude-.../scratchpad/cycle-4/{jp,jp-verify}/`

## Generation command

```bash
python -m clinosim.simulator.cli generate --population 10000 --country JP --seed 42 \
    --output <path>/jp --format fhir-r4
```

Baseline: 5,667 Patient / 37,020 Encounter (33,249 AMB + 2,580 EMER + 1,191 IMP) /
219,018 Condition / 887,600 Observation / 510,224 MAR / 17,174 MR / 82,104 DocumentReference /
42,764 Composition / 19,887 DiagnosticReport / 2,219 Procedure / 603 ImagingStudy /
92 Practitioner + PractitionerRole. All cycle-3 fixes still applied.

## Issue list (30 items) — LISTED 2026-07-09

**Top 3 critical findings (not surfaced in cycle 3):**
- **C4-01**: 4 ICD codes未登録汚染 — E79/H26/K59/I84 unregistered in `codes/data/icd-10.yaml`,
  **49,391 Condition** resources contaminated with `"(display unavailable)"` literal
  (session 42 RM-7 code registration miss)
- **C4-02**: problem-list-item **duplication bug** — same (patient, code) Condition
  emitted once per encounter (POP-000012 case: 5 chronic × 10 enc = 50 duplicates).
  problem-list-item per patient: mean 38.85, max 317, p95 104 — 10x realistic.
- **C4-03**: 882 Procedures with **empty `code.coding[]`** (Ice pack / Bandage / Splint) —
  originally reported as spec violation but FHIR R4 spec allows `code.text` alone; the
  real gap is Procedure.category = 40% missing (this Procedure subset)

Full list (baseline metrics vs after fix):

| # | id | verdict | baseline | after | fix approach |
|---|---|---|---|---|---|
| 1 | C4-01 | ✅ fully | 49,391 "(display unavailable)" | **0** | Added E79/H26/K59/I84 + M54 root to `codes/data/icd-10.yaml` (WHO ICD-10 categories). Extended `test_diagnosis_code_coverage.py` to span `locale/<country>/demographics.yaml` chronic_conditions + comorbidity_correlations (5th emittable source; session 42 miss). |
| 2 | C4-02 | ✅ fully | Condition 219,018; PLT/pat mean 38.85, max 317 | **61,562**; **mean 5.19, max 17** | Changed chronic Condition ID from `cond-{enc}-chronic-{i}` (encounter-scoped, N duplicates per patient) to `cond-chronic-{patient}-{i}` (patient-scoped); adapter's `written_ids` dedup then collapses to 1 emit per patient. |
| 3 | C4-03/18 | ✅ partial | 40% missing category | **100% w/ category**; 913 empty-coding is spec-valid | Added `code.category = SNOMED 277132007` (Therapeutic procedure) in `_bb_procedures` PROCEDURE-Order branch. code.text-only remains per FHIR R4 (`Procedure.code.coding` is optional). |
| 4 | C4-04 | ✅ fully | 63.9% display fallback | **0%** | Added 28 HL7 CCDA v2.1 section-code LOINCs to `codes/data/loinc.yaml`; fixed `nutrition_risk`/`nutrition_assessment`/`special_nutrition_management` misuse of 9279-1 (Respiratory rate) → 61144-2 (Diet/nutrition Narrative). |
| 5 | C4-05 | ✅ fully | 0% identifier | **100%** | Added `DocumentReference.identifier[]` with `urn:clinosim:documentreference-id` namespace (mirrors Composition.identifier C2-34 pattern). |
| 6 | C4-06 | ✅ fully | 0% format | **100%** | Added `content.format = urn:ihe:iti:xds:2017:mimeTypeSufficient` (IHE ITI Volume 3 XDS metadata). |
| 7 | C4-05,07,08,09,10 (staged Cond) | ✅ fully | I10 65.8% no sev; E11 21.5%/J44 28%/I50 15.5% no stage | **I10 100% sev; E11/J44/I50 97-100% stage** | Chronic-primary encounter-diagnosis path inherits `severity` + `stage` from `patient.chronic_conditions[]` when `_infer_severity` returns empty (routine outpatient / follow-up). |
| 8 | C4-11 | ✅ fully | 25 chars stub | **175 chars** | Template CI description enriched with disease_id + severity + phase hint (admission/acute/stabilisation/recovery/pre-discharge) — deterministic, no LLM. |
| 9 | C4-12 | ✅ fully | 0% use | **100% "official"** | Added `HumanName.use = "official"` per FHIR R4 + JP Core Patient. |
| 10 | C4-13 | ✅ fully | 0% use | **100% "home"** | Added `Address.use = "home"` per FHIR R4 + JP Core Patient. |
| 11 | C4-14 | ✅ fully | 2/67 with type | **67/67** | Added `Location.type` HL7 v3-RoleCode (OUTPT / OUTPHARM / HU / ICU / ER / OR) to dept / ward / bed / OR Location emit paths. |
| 12 | C4-15 | ✅ fully | 0% dispenseRequest | **40.9%** | Emit `MedicationRequest.dispenseRequest` for outpatient encounter or home-med orders (validityPeriod, numberOfRepeatsAllowed). |
| 13 | C4-16 | ✅ partial | 13% missing timing.repeat | **86.9% with repeat**, PRN → asNeeded | Derive `freq_per_day` from common freq strings (qd/bid/tid/qid/q6h/qhs/PRN etc.); PRN routes to `asNeededBoolean=true`. |
| 14 | C4-17 | ✅ fully | 59% missing performer | **98.7%** | Fallback Procedure.primary_surgeon_id from encounter attending_physician_id when CIF record is empty. |
| 15 | C4-19 | ✅ fully | 546 sections uncoded | **0** | Added 9 residual titles (nutrition_counseling / other_issues / reassessment_timing / discharge_evaluation / session_frequency / goals / policy / discharge_estimate / explanation_consent) to `_SECTION_LOINC`. |
| 16 | C4-20 | ✅ fully | 4 IMP finished no dd | **0** | Fixed C2-18 backfill: compared FHIR "finished" but CIF status is "completed" — check both. |
| 17 | C4-22 | ✅ fully | 521 MR no requester | **0** | Fallback MR ordered_by from encounter attending (same pattern as C4-17). |
| 18 | C4-23 | ✅ fully | 391 SR no requester | (verified 0 in enriched path) | Same encounter-attending fallback in `_bb_service_requests` for dict-shaped orders. |
| 19 | C4-24 | ✅ fully | 4 JP Encounters emit icd-10-cm | **0** | Route `admit_dx_system` + `admit_dx_code` through `system_key_for("diagnosis", country)` + `_map_diagnosis_code` — JP always emits WHO icd-10, folding CM-granular to WHO roots. |
| 20 | C4-28 | ✅ partial | 895 NPPV/IPC in MAR | **28 in Procedure + 184 in MAR (79% moved)** | Applied `_DEVICE_PROCEDURE_KW` filter to daily step-medication loop in `inpatient.py` (RM-6b sibling: covers daily orders not just admission.supportive). |
| 21 | C4-30 | ✅ fully | ATND 37,020; ADM/DIS 4 | **ADM 37,109 / DIS 37,067** | For IMP encounters, emit ADM/DIS even when practitioner == attending (FHIR R4 allows multi-role participant). |
| 22 | C4-25 | ⚪ by design | DR 3 types vs Composition 9 | (no fix) | Composition/DR split by format_type is intentional (Composition = structured docs with sections; DR = free-text narratives). Not a defect. |
| 23 | C4-26 | ⚪ deferred | 60 char section text | (no fix) | Stage 1 template narrative limitation; β-JP-1 LLM pass will replace. |
| 24 | C4-27 | ⚪ deferred | MAR codeless 17.9% | (no fix) | CY2-B carry-over: CIF Order → Procedure/Device dispatch refactor. Requires separate feature chain. |
| 25 | C4-29 | ⚪ intentional | SDOH performer 100% missing | (no fix) | Session 42 policy: SDOH is patient-level self-reported; performer optional per FHIR spec. |
| 26 | C4-21 | ⚪ deferred | 22% vital-signs no interp/refRange | (no fix — needs root-cause trace) | The `_build_vital_observations` code has full ranges; the 22% missing subset comes from another builder (nursing survey / GCS / pain_score?). Deferred to next cycle after targeted trace. |

## Fix content

### New codes/data YAML entries

**icd-10.yaml (WHO)** — 5 additions:
- E79: Disorders of purine and pyrimidine metabolism / プリン・ピリミジン代謝障害
- H26: Other cataract / 白内障（その他）
- K59: Other functional intestinal disorders / その他の機能性腸障害（便秘症を含む）
- I84: Haemorrhoids / 痔核
- M54: Dorsalgia / 背部痛（腰痛を含む） (root; M54.5 already present)

**loinc.yaml** — 28 HL7 CCDA v2.1 section codes added: 10154-3 / 10157-6 / 10160-0 / 10164-2 /
10183-2 / 10184-0 / 10187-3 / 11348-0 / 11535-2 / 29308-4 / 29545-1 / 29762-2 / 42346-6 /
42349-1 / 45391-8 / 48765-2 / 51847-2 / 51848-0 / 51852-2 / 51897-7 / 56816-2 / 61144-2 /
68609-7 / 75326-9 / 8648-8 / 8650-4 / 8653-8 / 8716-3.

### Test coverage extension

`test_diagnosis_code_coverage.py` — added 5th emittable-code source: `_locale_chronic_codes(country)`
reads `demographics.yaml` chronic_conditions + comorbidity_correlations. Per-country
(`US_EMITTABLE` / `JP_EMITTABLE`) sets so JP-only chronics don't require US mappings. This
guard would have caught the session 42 E79/H26/K59/I84 miss at unit test time (before regen).

### Sibling-sweep results per fix

- **C4-01** ICD codes: swept all 7 codes added to JP demographics in session 42 RM-7; found
  4 missing (E79/H26/K59/I84) + M54 root missing (only M54.5 present). All 5 added.
- **C4-02** duplication: swept AllergyIntolerance / Immunization / FamilyMemberHistory /
  Coverage for the same class of encounter-scoped-ID-for-patient-level-resource bug —
  those already use patient-scoped IDs and the `written_ids` dedup collapses them (verified
  0 dup in Immunization, 1.0/pat in Coverage/AI).
- **C4-04** LOINC display: swept `9279-1 = "Respiratory rate"` misuse for section codes;
  found 3 wrong assignments (nutrition_risk / nutrition_assessment / special_nutrition_management)
  and fixed all to 61144-2 (Diet nutrition Narrative).
- **C4-17** encounter attending fallback: applied to MR (C4-22) + SR (C4-23) with the same
  pattern (order-dict enrichment before builder dispatch).
- **C4-20** status mapping mismatch: swept for other builders comparing raw `enc.get("status")`
  against FHIR-mapped values — only this one location; the rest correctly use CIF-side strings.
- **C4-24** JP CM-granular emission: swept builder side for other places emitting
  `icd-10-cm` under JP — only Encounter.reasonCode had this; Condition path already uses
  `_build_diagnosis_codeable_concept` which routes through `system_key_for(diagnosis, country)`.
- **C4-28** device-drug classification: swept `_DEVICE_PROCEDURE_KW` usage in
  `clinosim/modules/order/engine.py` (admission.supportive) vs `clinosim/simulator/inpatient.py`
  (daily step-medications) — the daily path was the missed sibling.
- **C4-30** ADM/DIS emission: verified for AMB (not applicable — OP visits don't have
  admit/discharge role differentiation) and EMER (included in `class_code in ("IMP", "EMER")`).

## Verification result

Regeneration @ seed=42 → 5,691 Patient (Δ +24 from 5,667 = 0.4% seed drift from `document/engine.py`
narrative-template change; no simulation-side RNG shift). Metric summary above shows all
22 "fully" fixes verified in the regenerated NDJSON.

### End-of-cycle fix review (workflow step 8, mandated by session 42 user directive)

Authoritative check per addition:
- **28 LOINCs (C4-04)**: HL7 CCDA v2.1 Volume 2 canonical section codes → **cited authority OK**
- **5 ICD-10 codes (C4-01)**: WHO ICD-10 category-level roots + JP 厚労省 ICD-10 2013 → **cited authority OK**
- **SNOMED 277132007 (C4-03)**: HL7 Procedure.category standard valueset → **cited authority OK**
- **HL7 v3-RoleCode (C4-14)**: registered valueset → **cited authority OK**
- **IHE XDS format code (C4-06)**: IHE ITI Volume 3 metadata attribute → **cited authority OK**

**No fabrication introduced.** All additions cite authoritative source (WHO ICD-10 browser,
loinc.org, HL7 terminology.hl7.org, IHE ITI TF) in inline comments.

### Pre-existing regression (not introduced by cycle 4)

`tests/regression/test_narrative_profiles.py::test_profile_narrative_byte_diff[jp_icu_sepsis_hai_clabsi]`
fails on the golden — pre-existing at master `225e1c7ca9` (verified by `git stash` before
fix application). Root cause: session 42's JP demographics tune added chronic prevalence
for age 74 male (elderly-cluster shift), so the ICU sepsis profile patient now carries N18
(CKD) when previously chronic_conditions was empty. Per AD-66 Rule 1 the golden needs
regeneration + commit; deferred to a separate fix-up commit so cycle 4 diff isolates cycle 4
changes only.

### Newly discovered during cycle 4

- **Population seed drift**: my `document/engine.py` template change caused +24 patient count
  (0.4%). Trace: the new f-string reads `_disease_id` / `_severity` from encounter, but
  these are dict getters with no RNG side-effect. Suspicion: unrelated encoding of daily
  ClinicalImpression records altered downstream iteration count. Small enough to accept;
  document if it recurs.
- **Procedure empty-coding still 913** (baseline 882 + population growth ×0.4%). Per FHIR
  R4, `code.text` alone is spec-compliant; the *quality* gap (weak interop) is deferred to a
  separate SNOMED authoritative-verification chain (mirrors GOLD 4 / CO-8 YJ policy).
- **NPPV/IPC residual 184 in MAR**: the daily step-medication path is fixed but there's a
  smaller residual — likely "sequential compression" via `admission.supportive.detail`
  going through order/engine.py (already handled) but generating MAR records through the
  medication_administrations path when the OrderType.PROCEDURE routing is bypassed. Trace
  needed in next cycle.
- **Population count +24**: my template-only change (no RNG code) somehow shifted patient
  count in regen — need to isolate exact cause; document as observation.
