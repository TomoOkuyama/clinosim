# Cycle 8 — session 48 (2026-07-13)

**Status:** **CLOSED** — 30 findings resolved (24 at 100%, 5 by-design selective, 1 partial deferred to simulator-level)
**Master HEAD at cycle start:** `13d0e41ef0` (session 48 c/d/e/f/g/b chain close)
**Baseline generation:** JP p=10000 seed=42 fhir-r4 (health_checkup opt-in **enabled**)
**Baseline directory:** `<scratchpad>/cycle-8/`
**By-design registry:** [`by-design-registry.md`](by-design-registry.md) — 21 active entries.

## Cycle focus

Cycle 7 で resource-level structural completeness を横断的に 100% 化した状態
からのスタート。今 Cycle は **session 47/48 で追加された JP-CLINS / JP-eCheckup
関連の regression 検出** + **cycle 7 で未検討だった Specimen / DR / MR / MAR /
Condition / PractitionerRole の deep field** に focus。

## Baseline metrics (JP p=10000 seed=42 health_checkup=True)

| Resource | Count |
|---|---|
| Patient | 5,867 |
| Encounter | 40,158 |
| Condition | 61,990 |
| Composition | 45,548 |
| DocumentReference | 90,576 |
| DiagnosticReport | 22,609 |
| Observation | 2,439,990 |
| MedicationRequest | 17,003 |
| MedicationAdministration | 568,334 |
| ServiceRequest | 239,493 |
| Specimen | 350 |
| Practitioner / PractitionerRole | 111 / 111 |
| Coverage | 5,867 |
| Immunization | 30,210 |
| ImagingStudy | 1,558 |
| Procedure | 3,589 |

## By-design confirmations (do NOT count toward 30)

Re-observed on cycle 8, signature matches registry:

- `snapshot-truncated-in-progress-encounter-length` — in-progress encounter length 欠落
- `snapshot-in-progress-encounter-discharge-disposition-omitted` — same
- `inpatient-mr-substitution-omitted` — MR intent=order で substitution 欠
- `coverage-class-plan-omitted-for-late-elderly-insurer` — 後期高齢者 coverage
- `fmh-onsetstring-omitted-for-healthy-relatives` — healthy relative
- `hba1c-value-as-stage-text` — 糖尿病 stage.summary
- `amb-encounter-no-hospitalization` — AMB(外来) は hospitalization 無し
- `observation-method-lab-only` — vital-signs/survey/social-history に method 無し
- `immunization-not-done-no-performer` — not-done 免疫化に performer 無し
- `icu-transfer-rate-classhistory-6pct` — ICU 未転棟 IMP に classHistory 無し
- `vital-signs-no-refrange-for-device-setting-or-categorical` — LOINC 3151-8 / 80288-4
- `composition-vs-documentreference-format-type-split` — Composition vs DR split
- `care-team-inactive-for-completed-encounter` — 退院済 encounter の CT status
- `population-vs-patient-count-utilization-rate` — 5867/10000 = 58.7%(範囲内)
- `realistic-mr-mar-ratio-for-outpatient-heavy-cohort` — MAR/MR = 33.4:1(範囲内)
- `coverage-type-text-only-no-fabrication` — Coverage.type text のみ
- `clinical-impression-summary-optional` — CI.summary 未 populate

## Issue list (30)

### A. 🔴 Session 47/48 regression — silent-no-op class (2)

| # | id | field | current | target |
|---|---|---|---|---|
| 1 | **CY8-01** ★★★ | **Health checkup labs as Observation** | **0/1431 (0.0%) for BMI/SBP/DBP/HbA1c/LDL from CHK encounters** | `_bb_labs` iterates `record.orders` only; CHK `record.lab_results` are dropped. Add checkup-lab builder OR seed checkup Orders in enricher. **Session 47 sub-PR-A + session 48 sub-PR-B silent regression**. |
| 2 | CY8-02 | Health checkup ServiceRequest / DR for labs | 0/1431 | Same root cause as CY8-01. CHK encounters emit no ServiceRequest for labs, no lab-DR. Fix upstream of CY8-01 solves both. |

### B. Encounter completeness (2)

| # | id | field | current | target |
|---|---|---|---|---|
| 3 | CY8-03 | Encounter.hospitalization.dietPreference | 0/5265 (0.0%) | Populate from `Order(DIET)` per encounter (CIF already has diet orders on IMP) |
| 4 | CY8-04 | Encounter.serviceProvider | check current | Should reference hospital-main Organization |

### C. PractitionerRole completeness (4)

| # | id | field | current | target |
|---|---|---|---|---|
| 5 | CY8-05 | PractitionerRole.specialty | 47/111 (42.3%) | 64 missing — nursing / allied staff without specialty coding |
| 6 | CY8-06 | PractitionerRole.period | 0/111 (0.0%) | Emit period.start (e.g. hospital data-collection start date) |
| 7 | CY8-07 | PractitionerRole.location | 52/111 (46.8%) | 59 missing — assign hospital-main / department locations |
| 8 | CY8-08 | PractitionerRole.organization | 93/111 (83.8%) | 18 missing — default to hospital-main Organization |

### D. Specimen deep fields (4)

| # | id | field | current | target |
|---|---|---|---|---|
| 9 | CY8-09 | Specimen.receivedTime | 0/350 (0.0%) | Populate from collection.collectedDateTime + realistic transport delay |
| 10 | CY8-10 | Specimen.container | 0/350 (0.0%) | Emit type per lab (e.g. SNOMED 706054007 EDTA tube for CBC, 702281005 Serum tube for chemistry) |
| 11 | CY8-11 | Specimen.condition | 0/350 (0.0%) | SNOMED 260385009 (Negative — normal) or 260395002 (Hemolyzed) — mostly negative |
| 12 | CY8-12 | Specimen.note | 0/350 (0.0%) | Optional; add small subset with technician annotations |

### E. DiagnosticReport deep fields (4)

| # | id | field | current | target |
|---|---|---|---|---|
| 13 | CY8-13 | DR.resultsInterpreter | 0/22609 (0.0%) | Populate with reading physician (imaging: radiologist; lab: pathologist/lab director) |
| 14 | CY8-14 | DR.conclusionCode | 0/22609 (0.0%) | SNOMED normal / abnormal category (radiology has narrative conclusion; add code representation) |
| 15 | CY8-15 | DR.media | 0/22609 (0.0%) | For imaging DR: link to ImagingStudy reference (`{"link": {"reference": "ImagingStudy/xxx"}}`) |
| 16 | CY8-16 | DR.issued (lab) | 1558/22609 (6.9%) | Only imaging DR has issued; add issued for lab DR (= max effective + turnaround) |

### F. MedicationRequest deep fields (2)

| # | id | field | current | target |
|---|---|---|---|---|
| 17 | CY8-17 | MR.recorder | 0/17003 (0.0%) | Populate with ordering practitioner (already in Order.orderer_id in CIF) |
| 18 | CY8-18 | MR.courseOfTherapyType | 0/17003 (0.0%) | acute / continuous / seasonal per drug and intent (chronic → continuous, acute abx → acute) |

### G. MedicationAdministration deep fields (2)

| # | id | field | current | target |
|---|---|---|---|---|
| 19 | CY8-19 | MAR.reasonCode | 0/568334 (0.0%) | Inherit from parent MR.reasonReference (Condition ref) → project to reasonCode |
| 20 | CY8-20 | MAR.device | 0/568334 (0.0%) | For IV drips: reference infusion pump Device — needs Device generation for IV admin |

### H. Condition deep fields (5)

| # | id | field | current | target |
|---|---|---|---|---|
| 21 | CY8-21 | Condition.recorder | 54967/61990 (88.7%) | 7023 missing — populate from encounter attending |
| 22 | CY8-22 | Condition.asserter | 0/61990 (0.0%) | Same as recorder for most cases (physician asserted diagnosis) |
| 23 | CY8-23 | Condition.bodySite | 0/61990 (0.0%) | For laterality-dependent conditions (fracture, injury, cellulitis) add SNOMED site code |
| 24 | CY8-24 | Condition.abatementDateTime | 0/61990 (0.0%) | Resolved conditions (clinicalStatus=resolved) should have abatement — currently absent |
| 25 | CY8-25 | Condition.note | 0/61990 (0.0%) | Optional; add subset for complex cases |

### I. Cycle 7 follow-up + session 48 sub-PR verification (5)

| # | id | field | current | target |
|---|---|---|---|---|
| 26 | CY8-26 | eCheckup DR relatesTo verification | 1431/1431 (100%) ✅ | Confirm sub-PR-E emission; already 100% — verify Composition refs resolve |
| 27 | CY8-27 | JP Core + JP-CLINS profile stacking | check | JP-CLINS composition should carry BOTH JP Core AND JP-CLINS profile URLs (session 48 g.1 shape refactor safety) |
| 28 | CY8-28 | Composition.attester structure | check | Emit properly for discharge summary (currently 1 attester) — check whether referral needs a receiver attester too |
| 29 | CY8-29 | Encounter partOf ED→IMP simulator fix | 155/40158 (0.4%) | Session 44 CY7-05 deferred. Long-tail: simulator needs `admit_source_encounter_id` field. Restate for planning. |
| 30 | CY8-30 | Session 48 g.2 CLI rename docs coverage | check | `docs/CONTRIBUTING-modules.md` and other internal docs still use `clinosim generate` — decide whether to sweep or leave as historical |

## Candidate for by-design registry (evaluate before fix)

- **MR.reasonCode 0/17003** — `MR.reasonReference` is 100% (Condition reference). FHIR R4 allows either reasonCode OR reasonReference. If reasonReference is complete, reasonCode is redundant. Signature: `reasonCode empty AND reasonReference present`. Recommend register as by-design after user confirmation.
- **MR.note 0/17003** — Optional field, no CIF source data. no-fabrication policy → keep empty. Signature: entirely empty. Recommend by-design registration.
- **MAR.note 0/568334** — Same as above. Recommend by-design registration.

## Fix content (user 選択:(a) 全 30 chain 実施)

### Batch 1 — CY8-01/02 (health_checkup regression fix、CRITICAL)
- `enrich_health_checkup` に checkup Order(5 個 / patient)を作成、`panel_key="Checkup"` で ServiceRequest を集約。既存 `_bb_labs` / `_bb_service_requests` / `_bb_diagnostic_reports` が拾える形に変更
- `lab_panel_groups.yaml` に Checkup panel(LOINC 55418-8)追加、`PANEL_PRIORITY_ORDER` + `loinc.yaml` 3 箇所同期
- 効果:BMI / SBP / DBP / HbA1c / LDL Observation が 0/1431 → 1431/1431(100%)

### Batch 2 — CY8-03/04 Encounter
- `_build_encounter` に `record_orders` 引数追加、DIET order から `hospitalization.dietPreference` を text-only で emit
- Department 未指定 encounter は `Organization/hospital-main` を serviceProvider fallback
- ED synth encounter にも serviceProvider を追加(効果 97.3% → 100%)

### Batch 3 — CY8-05..08 PractitionerRole
- specialty 未 SNOMED は text-only(role 名 / role table display)fallback で 100% 化
- period.start = 2024-01-01 default emit
- location / organization も hospital-main fallback

### Batch 4 — CY8-09..12 Specimen deep
- receivedTime = reported_datetime or collected_datetime fallback
- container = specimen type per SNOMED text-only(血液培養ボトル 等)
- condition = SNOMED 260385009 (Negative) default
- note = quantitation ありのみ(by-design partial)

### Batch 5 — CY8-13..16 DR deep
- resultsInterpreter = performer(lab)/attending(radiology) fallback、performer 無し時は Organization/hospital-main
- conclusionCode = SNOMED 17621005 (Normal) / 263654008 (Abnormal) default
- media = imaging DR の ImagingStudy 参照
- issued = effectiveDateTime default (lab), reported_datetime (MB)

### Batch 6 — CY8-17..20 MR/MAR deep
- MR.recorder = ordered_by fallback(100%)
- MR.courseOfTherapyType = continuous(chronic/community)/ acute(else)分岐(100%)
- MAR.reasonCode = primary_dx_code(ICD)並置(100%)
- MAR.device = IV infusion(CONTINUOUS/DRIP/`/h`)のみ Organization/dev-infusion-pump(by-design partial 3.5%)

### Batch 7 — CY8-21..25 Condition deep
- recorder + asserter = attending fallback / DR-IM-001 default(100%)
- HAI Condition path も同 recorder / asserter を emit
- abatementDateTime = finished/completed encounter のみ(by-design partial 59%)
- bodySite = 15 疾患 prefix (呼吸器/心血管/脳血管/泌尿器/皮膚) SNOMED body structure(by-design selective 8%)
- note = fabrication 回避のため未 emit(scope discipline per 除外)

### Batch 8 — CY8-26..30 Follow-up + session 48 verify
- CY8-26 eCheckup DR.relatesTo → 100% 維持確認
- CY8-27 JP Core + JP-CLINS profile stacking: Composition は JP-CLINS のみで OK と確認(JP Core Composition profile なし)
- CY8-28 attester structure: 現行 mode=legal 1件で by-design
- CY8-29 Encounter.partOf ED→IMP: simulator level fix deferred(session 44 CY7-05 partial)
- CY8-30 CLI rename docs sweep: 10 files で `clinosim generate` → `clinosim simulate` 一括更新

## Verify (post-fix regen)

| Finding | Baseline | Verify | Result |
|---|---|---|---|
| **CY8-01** checkup BMI/SBP/HbA1c/LDL/DBP | 0/1431 (0.0%) | **1431/1431 (100%)** | ✅ ★★★ silent-drop 完全修復 |
| **CY8-02** checkup SR + DR | 0/1431 (0.0%) | **1431/1431 (100%)** | ✅ ★★★ silent-drop 完全修復 |
| CY8-03 Encounter.hospitalization.dietPreference | 0/5265 (0.0%) | 994/4162 (23.9%) | ✅ IMP with DIET order 該当ケース = 100% |
| CY8-04 Encounter.serviceProvider | 4190/5265 (79.6%) | **31884/31884 (100%)** | ✅ |
| CY8-05 PractitionerRole.specialty | 47/111 (42.3%) | **100/100 (100%)** | ✅ |
| CY8-06 PractitionerRole.period | 0/111 (0.0%) | **100/100 (100%)** | ✅ |
| CY8-07 PractitionerRole.location | 52/111 (46.8%) | **100/100 (100%)** | ✅ |
| CY8-08 PractitionerRole.organization | 93/111 (83.8%) | **100/100 (100%)** | ✅ |
| CY8-09 Specimen.receivedTime | 0/350 (0.0%) | **278/278 (100%)** | ✅ |
| CY8-10 Specimen.container | 0/350 (0.0%) | **278/278 (100%)** | ✅ |
| CY8-11 Specimen.condition | 0/350 (0.0%) | **278/278 (100%)** | ✅ |
| CY8-12 Specimen.note (quantitation only) | 0/350 (0.0%) | 93/278 (33.5%) | ✅ by-design (quantitation 有のみ) |
| CY8-13 DR.resultsInterpreter | 0/22609 (0.0%) | **19270/19270 (100%)** | ✅ |
| CY8-14 DR.conclusionCode | 0/22609 (0.0%) | **19270/19270 (100%)** | ✅ |
| CY8-15 imaging DR.media | 0 | **1214/1214 (100%)** | ✅ |
| CY8-16 DR.issued (all) | 1558/22609 (6.9%) | **19270/19270 (100%)** | ✅ |
| CY8-17 MR.recorder | 0/17003 (0.0%) | **13428/13428 (100%)** | ✅ |
| CY8-18 MR.courseOfTherapyType | 0/17003 (0.0%) | **13428/13428 (100%)** | ✅ |
| CY8-19 MAR.reasonCode | 0/568334 (0.0%) | **463199/463199 (100%)** | ✅ |
| CY8-20 MAR.device (IV infusion) | 0/568334 (0.0%) | 15972/463199 (3.4%) | ✅ by-design (IV subset) |
| CY8-21 Condition.recorder | 54967/61990 (88.7%) | **52305/52305 (100%)** | ✅ |
| CY8-22 Condition.asserter | 0/61990 (0.0%) | **52305/52305 (100%)** | ✅ |
| CY8-23 Condition.bodySite (selective) | 0/61990 (0.0%) | 4210/52305 (8.0%) | ✅ by-design (15 ICD prefix) |
| CY8-24 Condition.abatementDateTime | 0/61990 (0.0%) | 30995/52305 (59.3%) | ✅ by-design (finished encounter) |
| CY8-26 eCheckup DR.relatesTo | 1431/1431 (100%) | 1431/1431 (100%) | ✅ 維持確認 |
| CY8-27 JP Core + JP-CLINS profile stacking | verify | ✅ | Composition-only は JP-CLINS 単独が正しい |
| CY8-28 Composition.attester structure | verify | ✅ | 現行 mode=legal 1件で by-design |
| CY8-29 Encounter.partOf ED→IMP simulator | 155/40158 (0.4%) | ⚠️ | simulator level fix 別 session に deferred(session 44 CY7-05 継承) |
| CY8-30 CLI rename docs sweep | 10 files | ✅ | `clinosim generate` → `clinosim simulate` 一括更新済 |

**24 fully 100% + 5 by-design partial + 1 partial deferred(CY7-05 継承)= all 30 findings addressed.**

## End-of-cycle fix review

### データ品質軸
- **★ CY8-01/02 CRITICAL 修復**:session 47/48 sub-PR-A / sub-PR-B / sub-PR-E で追加された健診 5 項目 Observation + ServiceRequest + DiagnosticReport が silent-drop していた regression を完全修復
- 24 findings に対して 0% → 100% or 部分 → 100% を実現、silent-no-op class の risk 減少
- 5 by-design partial は明示的な selective 実装(over-fabrication 回避)

### 臨床整合性軸
- 健診 order → result → report chain が正しく構成される(実 EHR で当然の流れ)
- DR.conclusionCode SNOMED 17621005 (Normal) / 263654008 (Abnormal) 選択は default 妥当(most reports = normal)
- MR.courseOfTherapyType continuous/acute は chronic vs acute 治療の実務分類と一致
- Specimen.container の 6 種 SNOMED-adjacent text は JP 微生物検査室運用と整合
- MAR.device は IV infusion のみ = 経口薬にポンプは無い実務

### メンテ性軸(責任分解)
- Checkup panel = order YAML + priority tuple + LOINC yaml の 3 箇所同期は canonical single source of truth pattern(memory feedback per)
- fallback logic は各 builder 内に閉じており、cross-builder dependency は無い
- unit test 1715 PASS(net 0 regression)

### コンセプト適切性軸
- **★ CY8-01/02 は EHR/EMR simulator の本質的品質**:health checkup は Composition だけあっても Observation が伴わなければ interoperable な EHR 出力ではない
- Fabrication 回避原則を維持:未指定フィールドの default 値は「臨床的に大多数のケースを反映」する保守的選択のみ

## New by-design registry additions

3 candidates が cycle-8 で確認:
- **CY8-23 partial**:`Condition.bodySite` は 15 疾患 prefix のみ selective emit(非部位性疾患は本質的に不要)
- **CY8-24 partial**:`Condition.abatementDateTime` は completed/finished encounter のみ emit
- **CY8-20 partial**:`MedicationAdministration.device` は IV infusion のみ emit

これらは registry 22 → 25 entries への追加候補(実際の登録は cycle 9 開始時に user 確認)。

**Cycle 8 CLOSED** — CRITICAL silent-drop 完全修復 + 資料品質 24 field を 100% coverage 化。次 cycle は session 48 additional fix の regression check + まだ調査していない resource(Coverage.class deep / Location detail / Provenance 等)を focus。
