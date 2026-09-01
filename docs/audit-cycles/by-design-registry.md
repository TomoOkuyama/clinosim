# By-Design Registry — Audit-Cycle Detection Exclusions

This document is a machine-readable registry recording observations from
past audit cycles that were confirmed as **"looks like a bug, but is
actually as specified" (by-design)**. It is the primary reference used to
avoid re-raising the same observation as an issue in subsequent audit
cycles, and **consulting it BEFORE listing an item in `cycle-N.md` is
mandatory**.

## How to use it (audit-role instructions)

1. When you detect an `N/total = X%` shaped missing / uncoded / unpopulated
   observation during audit, first search for an entry in this document.
2. If the observation matches an entry's `Signature`, do not register it as
   an issue. Note one line in `cycle-N.md` — `By-design confirmed (see
   by-design-registry.md#<slug>)` — to preserve the record of the full scan.
3. If the observation does NOT match the entry `Signature` but is in the
   same subject area, consider updating this registry entry or adding a
   new one. Changing a by-design determination requires **a PR that
   explicitly states the reason (Signature change / new clinical
   requirement / etc.) with a back-link to the original session PR** —
   this prevents silent drift.
4. This registry has a different role from the "resolved" items in
   `docs/design-notes/2026-07-06-fix-point-registry.md` added from
   session 43 onward:
   - fix-point-registry = ledger of past bug fixes (history)
   - by-design-registry = exclusion list of current by-design observations
     (current spec)

## Entry format

Each entry has six fields:

```yaml
- id: <short-kebab-case-slug>
  observation: <what is visible at audit time: "X ndjson has N missing Y">
  by_design_reason: <why this is not a bug (reference to spec / clinical practice / AD-XX)>
  signature: <pattern that mechanically decides this observation (regex / count comparison / etc.)>
  established_session: <session N, YYYY-MM-DD>
  established_pr: <commit / PR ref>
  revalidation_check: <a quick check to confirm next time that this is still by-design>
```

---

## Entries

### snapshot-truncated-in-progress-encounter-length

- **id**: `snapshot-truncated-in-progress-encounter-length`
- **observation**: One or more entries in `Encounter.ndjson` are missing the `length` field.
- **by_design_reason**: AD-32 snapshot semantics. An admission that runs past `--end` becomes `status = "in-progress"` with `discharge_datetime = None`, so ISO 8601 `length` cannot be computed and is intentionally omitted. FHIR R4 `Encounter.length` has cardinality 0..1, so omission on an in-progress encounter is spec-conformant.
- **signature**: `sum(1 for e in encounters if "length" not in e and e.get("status") == "in-progress")` **equals the total count of missing length**. If any `status != "in-progress"` encounters are missing length, they are out of scope for this registry = a real bug.
- **established_session**: session 44, 2026-07-11 (Chain 1 verify)
- **established_pr**: `2dcde6497d` chain 1 wrap
- **revalidation_check**: Confirm on JP p=200 seed=42 that every `Encounter.length missing` case has `status = in-progress`.

### inpatient-mr-substitution-omitted

- **id**: `inpatient-mr-substitution-omitted`
- **observation**: Some fraction (roughly 45–55%) of `MedicationRequest.ndjson` records are missing `substitution.allowedBoolean`.
- **by_design_reason**: JP inpatient dispensing practice = brand-specified, generic substitution not allowed. `fhir_r4/medications/medications.py` only emits `substitution` for `intent == "instance-order"` (chronic outpatient prescriptions); it intentionally omits it for `intent == "order"` (inpatient orders). FHIR R4 `MedicationRequest.substitution` has cardinality 0..1.
- **signature**: Aggregate the `intent` field of missing-substitution MRs; **all must be `"order"`** (equivalently, every MR with `intent == "instance-order"` has substitution attached, 100%).
- **established_session**: session 44, 2026-07-11 (Chain 1 verify)
- **established_pr**: `2dcde6497d`
- **revalidation_check**: 0 MRs with `intent == "instance-order"` missing substitution; 0 MRs with `intent == "order"` carrying substitution.

### coverage-class-plan-omitted-for-late-elderly-insurer

- **id**: `coverage-class-plan-omitted-for-late-elderly-insurer`
- **observation**: Some fraction (roughly 15–25%) of `Coverage.ndjson` records lack an entry with `class[].type.coding[].code == "plan"`.
- **by_design_reason**: JP late-elderly medical care insurers (後期高齢者医療広域連合, age ≥ 75) only have an insurer number (group) and **do not have a symbol (plan)** by statutory design. `fhir_r4/demographics/patient.py:170-200` emits the plan entry only when `symbol` is truthy, so late-elderly Coverage records have no plan.
- **signature**: Extract all Coverage records missing plan; every one must have `payor` / `class[0].name` containing "後期高齢者医療広域連合". Missing plan on any other insurer type is out of scope for this registry.
- **established_session**: session 44, 2026-07-11 (Chain 1 verify)
- **established_pr**: `2dcde6497d`
- **revalidation_check**: `class[0].name` of every plan-missing Coverage matches the "〇〇後期高齢者医療広域連合" pattern.

### fmh-onsetstring-omitted-for-healthy-relatives

- **id**: `fmh-onsetstring-omitted-for-healthy-relatives`
- **observation**: Some fraction (roughly 15–20%) of `FamilyMemberHistory.ndjson` records are missing `condition[].onsetString`.
- **by_design_reason**: `fhir_r4/demographics/family_history.py:81-91` does not emit `condition[]` when the relative's `condition_codes` is empty, so there is no target to attach onsetString to. Healthy relatives (no disease history) = clinically realistic. FHIR R4 `FamilyMemberHistory.condition` has cardinality 0..*.
- **signature**: For every FMH missing onsetString, `"condition" not in resource` (i.e., the condition array does not exist at all). If the condition array is present but onsetString is missing, that is a real bug (out of scope for this registry).
- **established_session**: session 44, 2026-07-11 (Chain 2 verify)
- **established_pr**: `1481306d2f`
- **revalidation_check**: Confirm `"condition" not in resource` for every FMH missing onsetString.

### co8-non-jp-marketed-drugs

- **id**: `co8-non-jp-marketed-drugs`
- **observation**: Some `MedicationRequest.ndjson` records lack a YJ code (text-only).
- **by_design_reason**: The drug is not listed in the Japanese pharmaceutical pricing standard (imported / OTC / withdrawn / ophthalmic-drop or other overseas generic-name prescription). Under the no-fabrication policy (established session 40), drugs whose authoritative code has not been verified do not carry an emitted code.
- **signature**: The drug name (base name or normalized form of medicationCodeableConcept.text) of an uncoded MR must be in the following whitelist:
  - "シクロベンザプリン" / "Cyclobenzaprine"
  - "フェナゾピリジン" / "Phenazopyridine"
  - "メクリジン" / "Meclizine"  (added session 44 cycle 6 — antihistamine, not listed in JP pricing standard)
  - "ニトロフラントイン" / "Nitrofurantoin"  (added session 44 cycle 6 — UTI, not listed in JP)
  - "プロパラカイン" / "Proparacaine"  (added session 44 cycle 6 — ophthalmic surface anesthetic, not listed in JP)
  - "オフロキサシン点眼" / "Ofloxacin ophthalmic"  (added session 44 cycle 6 — ophthalmic, no individual code)
  - "オキシメタゾリン" / "Oxymetazoline"  (added session 44 cycle 6 — nasal spray OTC)
  - "テルリプレシン" / "Terlipressin"  (added session 44 cycle 7 residual sweep — not listed in JP pricing standard)
  - "シクロペントラート" / "Cyclopentolate"  (added session 44 cycle 7 residual sweep — ophthalmic, no individual code)
  An uncoded MR for any other drug is a real bug (an MHLW lookup must be added).
- **established_session**: session 44, 2026-07-11 (Chain 4 CO-8) — 5 items added in cycle 6 (session 44 continuation)
- **established_pr**: `2c5e79b974` + cycle 6 close
- **revalidation_check**: Confirm every uncoded MR's text is a subset of the whitelist above. Update the registry if the set grows or shrinks.

### hba1c-value-as-stage-text

- **id**: `hba1c-value-as-stage-text`
- **observation**: For diabetes (E11 / E10) in `Condition.ndjson`, `stage.summary.text` uses the `"HbA1c X.Y%"` form (e.g., `"HbA1c 7.5%"`) and has no `coding`.
- **by_design_reason**: The HbA1c value itself is the "stage" description, but this is **not a standardized stage system** like CKD Gx or NYHA I-IV. A value-based concept such as "HbA1c 7.5%" does not exist in SNOMED CT. Keeping the value as text is more meaningful.
- **signature**: The `text` of any stage.summary missing coding must match the regex `HbA1c \d+\.\d+%`. Missing coding on any other pattern (CKD / NYHA / GOLD / CCS / asthma / HTN Stage) is a real bug.
- **established_session**: session 44, 2026-07-11 (Chain 4 CO-6 verify)
- **established_pr**: `69f4cae082`
- **revalidation_check**: Confirm every stage.summary missing coding matches the `HbA1c \d+\.\d+%` regex.

### snapshot-in-progress-clinical-impression-status

- **id**: `snapshot-in-progress-clinical-impression-status`
- **observation**: One or more `ClinicalImpression.ndjson` records have `status = "in-progress"` (a test expects `"completed"`).
- **by_design_reason**: A patient whose enclosing encounter is truncated to in-progress by the AD-32 snapshot cutoff. ClinicalImpression status follows the encounter status = in-progress, which is spec-conformant (both are valid `EventStatus` codes). The existing unit test `test_jp_clinical_impression_structural_fields_present` strictly requires `status == "completed"` and does not account for snapshot behavior = a pre-existing test-side gap (confirmed in session 44).
- **signature**: Every CI with `status = "in-progress"` has an associated `encounter.status` that is also `in-progress`.
- **established_session**: session 44, 2026-07-11
- **established_pr**: `544fd40d18` (observed in session 43 wrap / not yet formalized)
- **revalidation_check**: Confirm that every in-progress CI's encounter is also in-progress. Future plan: relax the test to be snapshot-aware (see FHIR completeness registry).

### snapshot-in-progress-encounter-discharge-disposition-omitted

- **id**: `snapshot-in-progress-encounter-discharge-disposition-omitted`
- **observation**: Some `Encounter.ndjson` records lack `hospitalization.dischargeDisposition` (24 observed in the cycle 1 audit).
- **by_design_reason**: AD-32 snapshot semantics. An in-progress encounter has not been discharged, so disposition is undetermined = spec-conformant. Confirmed at C1-04 (cycle 1).
- **signature**: Every Encounter missing `dischargeDisposition` has `status == "in-progress"` and `discharge_datetime == null`.
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close (session 41)
- **revalidation_check**: Every Encounter missing dischargeDisposition is in-progress.

### realistic-mr-mar-ratio-for-outpatient-heavy-cohort

- **id**: `realistic-mr-mar-ratio-for-outpatient-heavy-cohort`
- **observation**: MR count looks lower than some baseline (e.g., 21820 for JP p=10000). The MAR:MR ratio is a wide band from roughly 9:1 to 33:1.
- **by_design_reason**: In a 90% outpatient cohort, MR = outpatient prescriptions + initial inpatient orders only; MAR = multi-day administration records in inpatient care. ~0.4–0.6 MR/enc combined with a high MAR:MR ratio is real EHR reality. Session 45 seed=100 verification observed 32.6, which is a natural pattern from the compounding of long-LOS IMP and continuous-infusion drips. Merged with C1-08 (cycle 1) + session 45 verification.
- **signature**: `MR count / encounter count ≈ 0.4–0.7` AND `MAR / MR ≈ 5–40`. Within both ranges = by-design. Outside = requires investigation (cohort mix has changed, or MAR bloat).
- **established_session**: session 41, 2026-07-07 (cycle 1) — band widened session 45, 2026-07-11
- **established_pr**: cycle 1 close + session 45 verification
- **revalidation_check**: Compute the two ratios and confirm they are in range. If the upper bound is exceeded, check whether the mixture rate of continuous-infusion drip has changed abruptly.

### clinical-impression-summary-optional

- **id**: `clinical-impression-summary-optional`
- **observation**: `ClinicalImpression.summary` field is empty (omitted for many CIs).
- **by_design_reason**: FHIR R4 `ClinicalImpression.summary` has cardinality 0..1 (optional). No corresponding source data exists in the CIF (clinosim does not generate distinct findings-summary data). Fabricating one would violate the no-fabrication policy. `description` is populated ("Day N clinical assessment"). Confirmed at C1-11 (cycle 1).
- **signature**: Every CI omits the `summary` field (the emit code does not produce it). Planned to be populated in a future β-JP-1 LLM narrative pass (see FHIR completeness registry).
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close
- **revalidation_check**: Grep-verify that `fhir_r4/documents/composition.py` (or the clinical_impression builder) does not emit summary.

### care-team-inactive-for-completed-encounter

- **id**: `care-team-inactive-for-completed-encounter`
- **observation**: Many records have `CareTeam.status = "inactive"` (CTs attached to discharged encounters). A review expected "active".
- **by_design_reason**: The FHIR R4 `CareTeam.status` valueSet includes `active | inactive | suspended | entered-in-error`. Discharged encounter = the team is no longer providing care = `inactive` is the spec-correct value (`fhir_r4/encounters/care_team.py:88-89`). Confirmed at C1-14 (cycle 1).
- **signature**: Every CT with `status = "inactive"` has `encounter.discharge_datetime` non-null.
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close
- **revalidation_check**: Every inactive CT's encounter has a non-null discharge_datetime (= completed).

### population-vs-patient-count-utilization-rate

- **id**: `population-vs-patient-count-utilization-rate`
- **observation**: With `--population 10000`, `Patient.ndjson` has around 5000-6000 records (not everyone becomes a patient).
- **by_design_reason**: population = catchment area total = hospital service-area population (includes healthy people). Patient = only those who had an encounter within the period. A ~50% healthcare utilization rate is consistent with real data. Confirmed at C1-20 (cycle 1).
- **signature**: `Patient count / population` is within `0.4–0.7` (varies by country demographics).
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close
- **revalidation_check**: Compute the ratio and confirm it is in range. Out of range = suspect drift in the disease incidence data.

### coverage-type-text-only-no-fabrication

- **id**: `coverage-type-text-only-no-fabrication`
- **observation**: `Coverage.type` has only `{"text": "..."}` and no `coding`.
- **by_design_reason**: No authoritative FHIR CodeSystem has been finalized for JP insurance types (公費 / 社保 / 国保 etc.). Following the no-fabrication policy, text-only is preserved (`fhir_r4/demographics/patient.py:152-155`). Confirmed at C2-12 (cycle 2).
- **signature**: `Coverage.type.coding` is omitted on every Coverage (no fabricated code exists in `fhir_r4/demographics/patient.py`).
- **established_session**: session 42, 2026-07-07 (cycle 2)
- **established_pr**: cycle 2 close
- **revalidation_check**: Every Coverage's type has no `coding`, only `text`. When an authoritative code source is established, this entry is retired.

### condition-severity-none-on-chronic-primary-encounter [RETIRED]

- **id**: `condition-severity-none-on-chronic-primary-encounter`
- **status**: **RETIRED — session 45, 2026-07-11 verification**
- **retirement_reason**: Cycle 6-7 residual sweep + Cycle 4 C4-05/07-09 chronic-inherit paths together populate severity on every Condition. Session 45 seed=100 verification confirmed 0 Conditions missing severity = the pattern disappeared. Any missing severity detected in the future is **a real bug** (this entry is no longer a by-design exception).
- **original_observation**: Some Conditions were missing `severity` (65.8% observed at cycle 2 for I10 routine visits).
- **original_by_design_reason**: When the primary dx is a chronic disease (I10 essential HTN etc.), acute severity for a routine outpatient follow-up is not inferable from sensor data → severity None is clinically correct. Confirmed at C2-32 (cycle 2).
- **established_session**: session 42, 2026-07-07 (cycle 2)
- **retired_session**: session 45, 2026-07-11 (verification)
- **retired_pr**: session 45 verification chain

### composition-vs-documentreference-format-type-split

- **id**: `composition-vs-documentreference-format-type-split`
- **observation**: Resource counts of `Composition.ndjson` and `DocumentReference.ndjson` differ ("distribution looks skewed").
- **by_design_reason**: `ClinicalDocument.format_type` intentionally branches: `composition` (H&P / Discharge Summary / Nursing / SOAP and other section-structured records) → emit Composition; `free_text` (Progress Note / Nursing Record / Triage etc.) → emit DocumentReference. These are independent resource types; a matching ratio is not required. Confirmed at C4-25 (cycle 4).
- **signature**: The `format_type` filter in `fhir_r4/documents/composition.py` and `fhir_r4/documents/documents.py` is consistent across both builders (composition → Composition emit / free_text → DR emit / other → skip).
- **established_session**: session 43, 2026-07-08 (cycle 4)
- **established_pr**: cycle 4 close
- **revalidation_check**: Every Composition resource originates from a `format_type == "composition"` doc, and every DR resource originates from a `format_type == "free_text"` doc (verify by id back-trace).

### compound-rx-with-device-alternative-real-drug

- **id**: `compound-rx-with-device-alternative-real-drug`
- **observation**: `MedicationRequest` / `MedicationAdministration` text contains compound expressions such as `"エノキサパリン ... または 間欠的空気圧迫"`. 184 observed (cycle 5 baseline).
- **by_design_reason**: The real CIF Order detail is a compound orderable of "real drug (Enoxaparin) OR alternative device (IPC)". Session 43 CY2-B fix + session 44 C5-19 introduced a splitter that prefers the primary alternative, but when the substring before "または" is a real drug, the drug side is adopted and the alternative text may remain = not a classification bug. Confirmed at C5-16 (cycle 5).
- **signature**: The primary drug in the compound text hits code_mapping and has a coding; the text after " または " remains in the display. If the primary is uncoded, that is a real bug.
- **established_session**: session 43, 2026-07-09 (cycle 5)
- **established_pr**: cycle 5 close
- **revalidation_check**: For a compound-text MR/MAR, `medicationCodeableConcept.coding[0].code` is non-empty (the primary drug is resolved).

### amb-encounter-no-hospitalization

- **id**: `amb-encounter-no-hospitalization`
- **observation**: `Encounter.hospitalization` is emitted for only ~10% of the cohort (3951/37137 in cycle 6).
- **by_design_reason**: `Encounter.hospitalization` holds admission/discharge episode information (admit source / discharge disposition / dietary preference etc.). AMB (ambulatory / outpatient) encounters have no admission/discharge episode, so FHIR R4 does not emit `hospitalization`. Only EMER + IMP encounters carry hospitalization = consistent with real EHR behavior.
- **signature**: Every Encounter missing `hospitalization` has `class.code == "AMB"`. Missing on EMER / IMP = a real bug.
- **established_session**: session 44, 2026-07-11 (Cycle 6 review)
- **established_pr**: cycle 6 open (`892c15051c`)
- **revalidation_check**: Aggregate class.code across Encounters missing hospitalization; every one is "AMB". EMER + IMP are 100% populated.

### observation-method-lab-only

- **id**: `observation-method-lab-only`
- **observation**: `Observation.method` cohort emit rate is ~12% (cycle 6 baseline 282762/2340725).
- **by_design_reason**: Session 44 CO-8 wired `Observation.method` for the lab category only. vital-signs (device auto-measured values), survey (questionnaire / consciousness level), and social-history (smoking / alcohol / occupation) conceptually do not need method: vital signs are auto-measured by devices, survey uses interview, and social-history uses history-taking. Only lab has meaningful analyzer methods (automated analyzer / culture identification / susceptibility testing).
- **signature**: Every Observation missing method belongs to a non-lab category (`vital-signs | survey | social-history | imaging`). Missing on the lab category = a real bug.
- **established_session**: session 44, 2026-07-11 (Chain 2 + Cycle 6 review)
- **established_pr**: `1481306d2f` (Chain 2 initial) + cycle 6 confirm
- **revalidation_check**: Aggregate categories across Observations missing method; every one is non-lab. The lab category method rate is 100%.

### immunization-not-done-no-performer

- **id**: `immunization-not-done-no-performer`
- **observation**: Some fraction (~2%) of `Immunization.ndjson` records lack the `performer` field (599/29995 in cycle 6).
- **by_design_reason**: `Immunization.status == "not-done"` is the record form for "scheduled but not administered" (refusal / contraindication / logistics etc.). No actual administrator exists, so performer is not emitted. The same behavior exists in both the CDC IIS and the JP immunization ledger. FHIR R4 `Immunization.performer` has cardinality 0..*, so omission on not-done is spec-conformant.
- **signature**: Every Immunization missing performer has `status == "not-done"`. Missing on `status == "completed"` = a real bug.
- **established_session**: session 44, 2026-07-11 (Cycle 6 review)
- **established_pr**: cycle 6 open
- **revalidation_check**: Aggregate status across Immunizations missing performer; every one is "not-done".

### icu-transfer-rate-classhistory-6pct

- **id**: `icu-transfer-rate-classhistory-6pct`
- **observation**: `Encounter.classHistory` is emitted for only ~6% of IMP encounters (73/1223 in cycle 7).
- **by_design_reason**: `classHistory` records transitions of the encounter class (general ward → ICU, ICU → general ward). Only cases with ICU transfer produce a transition, so within IMP only the ICU-transit rate (clinical reality ~5-10%, cycle 7's 6.0% is plausible) has classHistory. This is the feature introduced at session 43 C5-22; the correct behavior is "100% of the applicable cases", not 100% overall.
- **signature**: Every IMP encounter missing classHistory has no `icu_transferred_day` (never routed through ICU). Missing classHistory on an ICU-transit case (icu_transferred_day present) = a real bug.
- **established_session**: session 44, 2026-07-11 (Cycle 7 review)
- **established_pr**: cycle 7 open (`499f72a09d`)
- **revalidation_check**: For every IMP encounter missing classHistory, confirm the corresponding CIF record's `icu_transferred_day` is -1 (or missing).

### cy7-05-synth-ed-encounter-no-condition

- **id**: `cy7-05-synth-ed-encounter-no-condition`
- **observation**: `Condition.ndjson` does not reference the synthesized ED Encounter resources (id suffix `-ED`) — clinical audits show IMP/EMER-without-Condition count matches exactly the number of ED→IMP partOf-linked synth encounters (session 45 seed=400: 972/972).
- **by_design_reason**: CY7-05 (session 44) synthesizes a lightweight ED Encounter FHIR resource so IMP.partOf resolves, but the diagnosis lives on the primary IMP encounter — not duplicated on the synth stub. The synth carries chief-complaint text in `reasonCode` and `hospitalization.admitSource = "outp"` / `dischargeDisposition = "hosp"` to convey the ED-visit event without inflating downstream Condition/Procedure/Order counts. Adding a Condition specifically for the synth stub would misrepresent EHR reality (in practice, ED-to-admission is billed on the inpatient encounter, not the ED subacct). Session 45 seed=400 verification confirmed all 972 IMP/EMER missing-Condition were synth `-ED` ids (`class == "EMER"`, `status == "finished"`, id endswith `-ED`).
- **signature**: `IMP/EMER encounters without any Condition.encounter = Encounter/<id> reference` all have id endswith `-ED`.
- **established_session**: session 45 verification, 2026-07-11
- **established_pr**: session 45 chain #5 (`210bc6b057`..)
- **revalidation_check**: Sort no-Condition IMP/EMER by id; every id must end with `-ED` (the CY7-05 synth suffix).

### vital-signs-no-refrange-for-device-setting-or-categorical

- **id**: `vital-signs-no-refrange-for-device-setting-or-categorical`
- **aliases**: `o2-flow-rate-device-setting-no-refrange` (original session 43 name; kept as alias for back-reference from session 41-44 cycle docs)
- **observation**: Some vital-family `Observation` records lack `referenceRange`. Cycle 5 baseline observed 13,843 obs at LOINC 3151-8 (O2 flow rate). Session 45 seed=100 verification added 131,364 obs at LOINC 80288-4 (AVPU consciousness level).
- **by_design_reason**: The following two kinds of vital observations do not conceptually require a physiologic normal range:
  - **Device setting**: LOINC 3151-8 O2 flow rate = a device setting value (oxygen administration = therapeutic intervention dose; no reference range against healthy subjects exists).
  - **Categorical scale**: LOINC 80288-4 AVPU = 4-level categorical valueSet (Alert / Verbal / Pain / Unresponsive); a numeric range is meaningless. Added session 45.
  Any other categorical vital scale (e.g., the 3 sub-components of GCS) added in the future follows the same pattern. FHIR R4 does not require refRange (cardinality 0..*).
- **signature**: The `code.coding[0].code` of a vital Observation missing refRange must match one of `{3151-8 (O2 flow rate), 80288-4 (AVPU consciousness)}`. Missing refRange on any other LOINC = a real bug (out of scope for this registry).
- **established_session**: session 43, 2026-07-09 (cycle 5) — signature extended session 45, 2026-07-11
- **established_pr**: cycle 5 close + session 45 verification
- **revalidation_check**: Confirm the LOINC of every Observation missing refRange is in the whitelist. If a new categorical vital LOINC is discovered, update the registry.

### cy8-29-unknown-condition-imp-no-partof

- **id**: `cy8-29-unknown-condition-imp-no-partof`
- **observation**: Some fraction (roughly 6/1265 ≈ 0.5%) of IMP encounters in `Encounter.ndjson` lack `partOf`. In real operations most admissions come via ED (`admit_source="emd"`), and the `admit_source_encounter_id` derivation added in CY7-05 emits partOf accordingly. The remaining 0.5% is a residual pattern without a synth ED.
- **by_design_reason**: `_simulate_unknown_condition` (the `disease_id=None` idiopathic inpatient path) does not go through the discharge-phase logic of `_simulate_patient`, so the CY7-05 admit_source completion logic never fires and `admit_source=""` is written to CIF as-is. The FHIR builder falls back to emitting empty admit_source as `hosp` (from hospital administration), which is semantically correct (recorded as a direct admission). Missing partOf = "direct admission without ED routing" = spec-conformant. Fabrication avoided (no CY7-05 forcing on paths that clinically do not necessarily route via ED).
- **signature**: Every IMP encounter missing partOf has `hospitalization.admitSource.coding[0].code == "hosp"` (FHIR builder fallback default), and the corresponding CIF record's `condition_event.disease_id` is empty (originates from the unknown-condition path). Missing partOf with any other admit_source (emd / outp / born etc.) = a real bug (out of scope for this registry).
- **established_session**: session 48, 2026-07-13 (Cycle 8 verify)
- **established_pr**: cycle 8 close (this commit)
- **revalidation_check**: Extract every IMP encounter missing partOf; every admit_source is `"hosp"`. The expected range on JP p=10000 seed=42 is ≤ 0.6% of IMP.

### cy8-23-condition-bodysite-selective

- **id**: `cy8-23-condition-bodysite-selective`
- **observation**: Some fraction (≈ 92%) of `Condition.ndjson` records lack `bodySite`.
- **by_design_reason**: The bodySite emit introduced in session 48 cycle 8 is limited to a selective set of 15 disease prefixes (respiratory J13/J14/J15/J18/J44/J45 + cardiovascular I21/I25/I50 + cerebrovascular I60/I61/I63 + urologic N10/N17/N30/N39 + skin L03). Non-anatomic diseases (I10 hypertension, E11 diabetes, E78 dyslipidemia etc.) have no anatomic bodySite, so not emitting one is clinically correct. Fabrication avoided.
- **signature**: The primary ICD prefix (first segment before `.`) of a Condition missing bodySite is NOT in the 15 prefixes above. Missing bodySite for a Condition matching the 15 prefixes = a real bug (out of scope for this registry).
- **established_session**: session 48, 2026-07-13 (Cycle 8)
- **established_pr**: cycle 8 close
- **revalidation_check**: Aggregate ICD prefixes across Conditions missing bodySite; confirm none contain the 15 prefixes. When a new anatomic-site disease is added to `disease`, update `_CONDITION_BODY_SITE` (`fhir_r4/conditions/conditions.py`) + this signature.

### cy8-24-condition-abatement-finished-encounter-only

- **id**: `cy8-24-condition-abatement-finished-encounter-only`
- **observation**: Some fraction (roughly 40%) of `Condition.ndjson` records lack `abatementDateTime`.
- **by_design_reason**: The abatement emit added in session 48 cycle 8 is limited to encounters where `encounter.status in ("completed", "finished")` AND `discharge_datetime` is non-empty. In-progress encounters (AD-32 snapshot cutoff) and chronic problem-list-items (which never resolve to begin with) do not emit abatement, consistent with the FHIR spec.
- **signature**: A Condition missing abatementDateTime falls into one of: (a) its corresponding encounter is in-progress, (b) `category=problem-list-item` (originates from the chronic path), or (c) it is a patient-level Condition without an encounter reference. Missing abatement on an encounter-diagnosis for a finished encounter = a real bug.
- **established_session**: session 48, 2026-07-13 (Cycle 8)
- **established_pr**: cycle 8 close
- **revalidation_check**: Extract every Condition missing abatementDateTime; confirm each falls into (a) / (b) / (c) above.

### cy8-20-mar-device-iv-infusion-only

- **id**: `cy8-20-mar-device-iv-infusion-only`
- **observation**: Most (96.5%) of `MedicationAdministration.ndjson` records lack `device`. Only IV continuous-infusion admins emit it, at ~3.5%.
- **by_design_reason**: `device` is the field that references the administration equipment such as an infusion pump. Oral / IM / SC / SL / topical admins do not need a pump, so clinically-accurate operation is to reference `Device/dev-infusion-pump` only for IV continuous-infusion admins (dose_text contains CONTINUOUS/DRIP/`/h` + route=IV). Fabrication avoided (no fictional Device pinned to oral drugs).
- **signature**: An MAR missing device has `dosage.route.text != "IV"` OR `dosage.text` does not contain CONTINUOUS/DRIP/`/h`. Missing device on IV + CONTINUOUS = a real bug (out of scope for this registry).
- **established_session**: session 48, 2026-07-13 (Cycle 8)
- **established_pr**: cycle 8 close
- **revalidation_check**: Aggregate route + dose_text across MARs missing device; confirm the condition above. Guarantee 100% device fire on IV continuous infusion.

### s95-z37-past-birth-marker-stale-onset

- **id**: `s95-z37-past-birth-marker-stale-onset`
- **observation**: A large fraction (~53% JP / 57% US) of `Z37.*` Condition resources emit with `onsetDateTime` many years before `recordedDate`. Extreme cases show a 13-year gap (e.g. `onset=2012-10-25`, `recorded=2025-10-11`).
- **by_design_reason**: **Session 97 update (META #957 Incr 1)** — Z37 is no longer sampled in `chronic_prevalence`; instead the FHIR emit adapter derives one Z37 `problem-list-item` per delivered pregnancy from `person.state_periods` (state_type="pregnancy", outcome="delivered"), anchored at the delivery date. The stale-onset pattern therefore SHRINKS to just those cross-year deliveries the sim actually simulated; the "activation-window historical onset" proxy source is retired. The interim signature below still holds — a Z37 with historical onset must be `problem-list-item` category and the delivery encounter's Z37 `encounter-diagnosis` sibling has current-time onset — but the population is now bounded by (and correlates 1:1 with) the sim's own delivery events.
- **signature**: A Z37 Condition where `onsetDateTime` is many days before `recordedDate` MUST have `category.coding[].code == "problem-list-item"`. If a Z37 with `category == "encounter-diagnosis"` shows stale onset → real bug. Post-Incr-1: the problem-list-item Z37 count equals `Σ delivered pregnancy periods` across the cohort (biology-consistent).
- **established_session**: session 95, 2026-09-01 (post-close p=10000 audit follow-up); **updated session 97**, 2026-09-01 (META #957 Incr 1 refactor).
- **established_pr**: #1034 (issue) — comment thread + registry entry. Incr-1 refactor: this branch.
- **revalidation_check**: For every Z37 with `onset < recorded - 30d`, confirm category is `problem-list-item`. Also verify Z39 postpartum encounter dates > mother's delivery encounter's `period.start` (Z39 scheduler now reads `state_period.metadata.delivered_on` derived from the same delivery event, so no cascade risk).

---

## Non-Entries (real bugs, out of scope for this registry)

The following are **not eligible for registration**. If detected during audit, register them as cycle issues and fix them.

- Every stage system (CKD / NYHA / GOLD 1-4 / asthma 4-tier / HTN Stage 1-2 / CCS I-IV) → require stage.summary.coding to be **present**. Missing coding is a bug.
- Missing `method` on Observations derived from MicrobiologyResult (mb-org-* / mb-sus-*) → fully populated at session 44 CO-8; missing is a bug.
- 100% population of CareTeam.telecom / DR.presentedForm → established at session 44 Chain 1/3; missing is a bug.

---

## Change history

- 2026-07-11 (session 44): first edition. Registered 7 by-design entries confirmed in Chain 1-4.
- 2026-07-11 (session 44 addendum): consolidated 10 by-design / not-a-bug notes retrospectively from cycles 1-5 docs.
  A total of **17 entries** cover all by-design observations across C1-C5:
  - Cycle 1 (5): C1-04, C1-08, C1-11, C1-14, C1-20
  - Cycle 2 (2): C2-12, C2-32
  - Cycle 4 (1): C4-25
  - Cycle 5 (2): C5-16, C5-17
  - Session 44 Chain 1-4 verify (7): snapshot-length, MR substitution, Coverage late-elderly, FMH healthy relative, CO-8 non-JP drugs, HbA1c stage text, CI in-progress status
- 2026-07-11 (session 44 Cycle 6 expansion): added 3 new patterns discovered in the cycle 6 baseline review (`amb-encounter-no-hospitalization` / `observation-method-lab-only` / `immunization-not-done-no-performer`) and expanded the `co8-non-jp-marketed-drugs` whitelist by 5 (Meclizine / Nitrofurantoin / Proparacaine / Ofloxacin ophthalmic / Oxymetazoline). Total **20 entries**.
- 2026-07-11 (session 44 Cycle 7 expansion): added 1 new pattern `icu-transfer-rate-classhistory-6pct` discovered in the cycle 7 baseline review. Total **21 entries**.
- 2026-07-11 (session 45 verification): consolidated 3 fixes (heparin rate adjustment / EMER length synthesis) and 3 registry updates found in the JP p=10000 seed=100 verification:
  - `condition-severity-none-on-chronic-primary-encounter` → RETIRED (after cycle 6-7 residual sweep, missing severity = 0, pattern gone)
  - `o2-flow-rate-device-setting-no-refrange` → renamed + signature extended = `vital-signs-no-refrange-for-device-setting-or-categorical` (added LOINC 80288-4 AVPU consciousness)
  - `realistic-mr-mar-ratio-for-outpatient-heavy-cohort` → MAR/MR band widened 5-15 → 5-40 (accommodating a wide natural band from long-LOS IMP + continuous-infusion drip mixture)
  net: **21 entries** (1 retire + 2 signature updates, no new entries).
- 2026-07-13 (session 48 Cycle 8 expansion): added 4 new patterns confirmed in cycle 8 verify (`cy8-29-unknown-condition-imp-no-partof` + `cy8-23-condition-bodysite-selective` + `cy8-24-condition-abatement-finished-encounter-only` + `cy8-20-mar-device-iv-infusion-only`). Total **25 entries**.
- 2026-09-01 (session 95, Issue #1034 investigation): added `s95-z37-past-birth-marker-stale-onset` after the session-95 p=10000 audit's "Z37 stale onset + Z39 cascade" finding was investigated. Audit's Z39 cascade claim did not reproduce (0/314 Z39s before mother's delivery); the Z37 stale onset is intentional per `demographics.yaml` "past-birth marker". Total **26 entries**.
- 2026-09-01 (session 97, META #957 Incr 1): updated `s95-z37-past-birth-marker-stale-onset` — Z37 chronic-sample proxy retired in favor of a `state_periods`-derived FHIR emit adapter. The stale-onset pattern still exists (delivery date can be historic if the sim ran multi-year) but the emit path and population semantics changed: one Z37 problem-list-item per actually-delivered pregnancy. Total **26 entries** (in-place update, no add/remove).
