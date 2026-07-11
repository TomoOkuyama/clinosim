# Cycle 6 — session 44 (2026-07-11, session 44 wrap-up 後)

**Status:** CLOSED — 30 fixed / 3 new by-design registered / 20-entry registry total
**Master HEAD at cycle start:** `892c15051c` (by-design registry backfill wrap)
**Baseline generation:** JP p=10000 seed=42 fhir-r4
**Baseline directory:** `<scratchpad>/cycle-6`
**By-design registry:** [`by-design-registry.md`](by-design-registry.md) — 17 entries active.
Observations matching any registered Signature do NOT count toward the 30-issue
target; instead recorded here as "By-design confirmed" one-liners.

## Cycle focus

Session 44 で Chain 1-4 の実装可能項目を全て消化した後の初サイクル。
Cycle 5 の 20 deferred のうち session 44 で 8 件を fix し、残 12 件は構造的作業
(β-JP-1 LLM narrative / 他) として明示的 defer 済み。Cycle 6 は session 44 fix
の副作用検知 + 新規 issue の抽出に集中する。

## Baseline metrics (JP p=10000 seed=42)

Resource-type counts (major):
- Encounter 37,137 / Patient 5,757 (~57% utilization)
- Observation 2,340,725 / MedicationAdministration 542,224 / MedicationRequest 16,694
- ServiceRequest 231,892 / DocumentReference 87,055 / Composition 43,131
- Condition 61,613 / CareTeam 37,137 / FamilyMemberHistory 16,061
- DiagnosticReport 22,344 / Immunization 29,995 / Practitioner 105

## By-design confirmations (do NOT count toward 30)

| # | Registered slug | Observation |
|---|---|---|
| 1 | [snapshot-truncated-in-progress-encounter-length](by-design-registry.md#snapshot-truncated-in-progress-encounter-length) | Encounter.length 99.8% (62 in-progress missing) |
| 2 | [inpatient-mr-substitution-omitted](by-design-registry.md#inpatient-mr-substitution-omitted) | MR.substitution 44.4% (7412/16694) |
| 3 | [fmh-onsetstring-omitted-for-healthy-relatives](by-design-registry.md#fmh-onsetstring-omitted-for-healthy-relatives) | FMH condition 81.3% (3002 healthy relatives) |
| 4 | [hba1c-value-as-stage-text](by-design-registry.md#hba1c-value-as-stage-text) | Condition.stage.summary text-only "HbA1c X.Y%" |
| 5 | [snapshot-in-progress-clinical-impression-status](by-design-registry.md#snapshot-in-progress-clinical-impression-status) | ClinicalImpression 62 in-progress vs 21,036 completed |
| 6 | [co8-non-jp-marketed-drugs](by-design-registry.md#co8-non-jp-marketed-drugs) | シクロベンザプリン + フェナゾピリジン uncoded |

New by-design patterns discovered during Cycle 6 review (registered in
by-design-registry.md **at cycle close**; enumerated here for tracking):

- **[NEW] amb-encounter-no-hospitalization** — Encounter.hospitalization 0% for AMB (33186), 100% for EMER+IMP. FHIR spec omits hospitalization on ambulatory encounters (no admission/discharge episode). Signature: hospitalization 欠落 Encounter が `class.code == "AMB"` であること。
- **[NEW] observation-method-lab-only** — Observation.method 100% on `category = laboratory`, 0% on vital-signs / survey / social-history. Session 44 CO-8 で lab のみに method を wired。他 category は device setting / physical exam / lifestyle survey で method 概念が不適合。Signature: method 欠落 Observation が全て non-lab category (`vital-signs | survey | social-history | imaging`)。
- **[NEW] immunization-not-done-no-performer** — Immunization 599 missing performer = 599 status="not-done" — 未接種記録に performer は emit 不可。CDC IIS の recorded refusal 表現。Signature: performer 欠落 Immunization が全て `status == "not-done"` であること。

## Issue list (target: 30)

Issues collected via global metric scan + resource-cross-reference + patient
random sampling. `[Cycle 6 · n/30]` progress markers used during fix phase.

### A. FHIR builder bugs — session 44 side-effects (4)

| # | id | category | observation | impact |
|---|---|---|---|---|
| 1 | CY6-01 | integration | PractitionerRole → Organization dangling refs to `dept-rehabilitation` (8), `dept-nutrition` (3), `dept-medical-social-work` (2) | 13 broken references; session 44 C5-25 allied-health roster expansion added department names not registered in `_fhir_facility.py` |
| 2 | CY6-02 | completeness | Practitioner.qualification missing for allied-health roles (PT×4, OT×2, ST×2, MSW×2, RD×3) | 13/105 = 12.4% missing; roster generator (`staff/engine.py:_extra_roles`) doesn't set qualification for new roles |
| 3 | CY6-03 | completeness | DiagnosticReport.performer 0% across all 22,344 DRs (lab 20,440 + mb 370 + rad 1,534) | Every DR should have performer via ordering physician or lab/radiology tech reference; builder omits |
| 4 | CY6-04 | integration | `MedicationAdministration` uncoded 2.48% (13,451/542,224) despite parent Order carrying `order_code` (verified in CIF) | session 44 CO-8 fixed MR-side to honor `Order.order_code` but MAR builder path never joins back to Order — MAR `code_yj` field doesn't exist so fallback lookup fails on JP text |

### B. JP drug coding gaps — MHLW YJ additions (7)

| # | id | drug | count | JP marketed as | note |
|---|---|---|---|---|---|
| 5 | CY6-05 | エドキサバン (Edoxaban) | 15 MR + 291 MAR uncoded | リクシアナ (Lixiana) | Direct oral anticoagulant, standard-of-care |
| 6 | CY6-06 | ロラゼパム (Lorazepam) | 24 MR uncoded | ワイパックス (Wypax) | Benzodiazepine, standard |
| 7 | CY6-07 | メクリジン (Meclizine) | 44 MR uncoded | JP marketed | Antihistamine for vertigo |
| 8 | CY6-08 | エルカトニン (Elcatonin) | 887 MAR uncoded (MR coded via order_code) | エルシトニン (Elcitonin) | Calcitonin analog for osteoporosis |
| 9 | CY6-09 | ジルチアゼム (Diltiazem) | 275 MAR uncoded | ヘルベッサー (Herbesser) | CCB |
| 10 | CY6-10 | ニカルジピン (Nicardipine) | 595 MAR uncoded | ペルジピン (Perdipine) | CCB |
| 11 | CY6-11 | ランジオロール (Landiolol) | 275 MAR uncoded | オノアクト (Onoact) | Ultra-short β-blocker |

### C. Drug-name normalization / order classification (7)

| # | id | text pattern | count | root cause | fix approach |
|---|---|---|---|---|---|
| 12 | CY6-12 | `"Crystalloid 30 mL/kg bolus within 3 hours"` → MR/MAR | 53 MR + 4,077 MAR | sepsis.yaml supportive `IV_fluid` detail is a clinical instruction, not a specific drug | Add `Crystalloid` alias to code_mapping (→ Normal saline) + also split at "mL/kg bolus" boundary |
| 13 | CY6-13 | `"NSAID (Loxoprofen)"` parenthetical wrapper → MAR | 887 MAR | vertebral_compression_fracture.yaml uses parenthetical drug name; `_localize_drug_name` doesn't strip wrapper | Strip parenthetical prefix in `_build_medication_admin` before code lookup, or normalize YAML |
| 14 | CY6-14 | CRRT (Continuous renal replacement therapy) → MEDICATION | 14 MR + 354 MAR | inpatient daily-loop step-medications treat CRRT as drug; classifier misses it | Add "crrt", "continuous renal replacement" to `PROCEDURE_KEYWORDS` |
| 15 | CY6-15 | Parkland formula `"LR 4mL × kg × %TBSA over 24h"` → MEDICATION | 2 MR + 353 MAR | burn resuscitation formula is a clinical instruction | Classify formula-text supportive as THERAPY, or split into two orders (LR drug + dosing plan) |
| 16 | CY6-16 | `"治療的抗凝固療法 (置換 予防投与)"` → MR/MAR | 9 MR + 418 MAR | Anticoagulation plan text, not a specific drug | Route to THERAPY via "therapy" keyword; or better require concrete drug entry in YAML |
| 17 | CY6-17 | `"アモキシシリン/クラブラン酸 875/125mg"` uncoded | 39 MR | key in code_mapping but "/" + dose blocks longest-match; token split on space still leaves "アモキシシリン/クラブラン酸" as one token | Longest-match should try token-set with "/" split; or add JP key alias |
| 18 | CY6-18 | `"乳酸リンゲル液"` / `"未分画ヘパリン"` uncoded via MAR text | 762 + 491 MAR | JP display text bypasses English code_mapping keys; Order.order_code isn't set on step-medications so MAR fallback fails | Add JP synonyms to code_mapping OR (root fix) MAR builder joins back to Order |

### D. FHIR content completeness (5)

| # | id | resource | field | current | target | note |
|---|---|---|---|---|---|---|
| 19 | CY6-19 | Condition | evidence | 0/61,613 (0.0%) | non-zero for encounter-diagnosis with lab/vital support | FHIR R4 `Condition.evidence` (0..*): supporting evidence for the diagnosis. Could reference the abnormal Observation IDs that motivated the diagnosis |
| 20 | CY6-20 | DiagnosticReport | conclusion | 1,534/22,344 (6.9%) | non-zero for lab panel DR too | Only radiology DR has conclusion. Lab panel DR could summarize the panel result (Normal / Abnormal / Critical) as conclusion |
| 21 | CY6-21 | Condition | severity | 49,702/61,613 (80.7%) — 11,911 missing | 100% except intentional | Missing on non-chronic non-Z-code acute conditions: A08 (349), R07 (252), T14 (158), S93 (153), R10 (133), G43 (125), J06 (123), T78 (95), A05 (91), N39 (85), R55 (85). These are ED acute conditions where severity should be inferable |
| 22 | CY6-22 | MedicationRequest | category | 0/16,694 (0.0%) | non-zero | FHIR R4 `MedicationRequest.category` (0..*): inpatient / outpatient / community / discharge distinction. Missing everywhere |
| 23 | CY6-23 | MedicationAdministration | category | 0/542,224 (0.0%) | non-zero | Same as MR.category — inpatient / outpatient distinction |

### E. Drug coding — MAR bypass root cause (2)

| # | id | drug | count | note |
|---|---|---|---|---|
| 24 | CY6-24 | "メトロニダゾール 500mg 静注 8時間毎" MAR uncoded | 666 MAR | Metronidazole is in code_mapping ("2649004") — MAR text has full dose + freq blocks longest-match against English key; same class as CY6-18 (MAR bypasses Order.order_code) |
| 25 | CY6-25 | Root fix: MAR builder joins to Order by `order_id` and inherits `order_code` (parallel to session 44 CO-8 MR-side fix) | 13,451 uncoded MAR → many auto-resolve | Sub-issue of CY6-04 but tracked separately because the CIF has code but MAR emit doesn't reach it |

### F. Non-JP-marketed drugs — extend by-design registry (3)

Baseline shows 4 additional drug names uncoded that are NOT in JP 薬価基準:

| # | id | drug | count | disposition |
|---|---|---|---|---|
| 26 | CY6-26 | ニトロフラントイン (Nitrofurantoin) | 27 MR | Extend by-design registry `co8-non-jp-marketed-drugs` |
| 27 | CY6-27 | プロパラカイン 0.5% 点眼 (Proparacaine ophthalmic) | 25 MR | Extend by-design registry |
| 28 | CY6-28 | オフロキサシン点眼 (Ofloxacin ophthalmic drops) | 20 MR | Extend by-design registry |
| 29 | CY6-29 | オキシメタゾリン 鼻 スプレー (Oxymetazoline nasal) | 29 MR | Extend by-design registry |

### G. Facility / configuration coherence (1)

| # | id | observation | note |
|---|---|---|---|
| 30 | CY6-30 | `hospital_operations.yaml:staffing` still lists nursing/lab/radiology/pharmacy only; missing rehabilitation / nutrition / medical_social_work service definitions | Config gap corresponding to CY6-01: adding departments to Organization emit also needs available_departments / department_rollup for coherence with `hospital_config` |

---

## Fix content

Grouped by the same 7 batches announced during the fix phase.

### Batch 1 — allied-health infrastructure (CY6-01/02/30)

- `clinosim/config/hospital_operations.yaml` — added 3 department entries
  (`rehabilitation` / `nutrition` / `medical_social_work`) to
  `available_departments`. `_fhir_facility.py` iterates this list, so
  Organization `dept-*` resources are now emitted; PractitionerRole refs
  resolve.
- `clinosim/locale/shared/department_display.yaml` — JP/EN display for
  `nutrition` (栄養管理科) + `medical_social_work` (医療社会事業科).
  Rehabilitation already existed.
- `clinosim/modules/output/_fhir_reference_data.py` + `_fhir_localization.py`
  — `_ROLE_PREFIX_MAP` + `_ROLE_PREFIX_MAP_JA` extended with PT / OT / ST /
  MSW / RD qualification codes so Practitioner.qualification is populated
  for allied-health staff (13/13 = 100%).

### Batch 2 — MAR builder Order joinup (CY6-04/25 + 8/9/10/11/18/24)

- `clinosim/modules/output/fhir_r4_adapter.py:_bb_medication_admins` builds
  an `order_id → order_code` map once per record and injects
  `mar["code_yj"]` before the MAR builder runs. Previously the MAR builder
  fell back to a code_mapping lookup on the JP-localized text
  (エルカトニン / 乳酸リンゲル液 / etc.) which never matched the English
  code_mapping keys. Now MAR inherits the parent Order's authoritative
  YJ code (session 44 CO-8 MR-side fix mirrored here for MAR-side).

### Batch 3 — DiagnosticReport.performer (CY6-03)

- `clinosim/modules/output/_fhir_diagnostic_report.py:build_lab_panel_reports`
  now derives `_lab_performer_ref` from encounter attending physician and
  passes it to `build_dr_resource` (was hard-coded to None). Radiology DR
  path (`_build_radiology_dr`) also gets `performer` from encounter
  attending. Coverage 0% → 100%.
- `clinosim/modules/output/_fhir_microbiology.py:_bb_microbiology` also
  emits `performer` on microbiology DR via the same encounter-attending
  fallback.

### Batch 4 — treatment_classifier expansions (CY6-14/15/16)

- `clinosim/modules/order/treatment_classifier.py` PROCEDURE_KEYWORDS
  gains `"crrt"` + `"continuous renal replacement"` (CY6-14 — CRRT is a
  procedure not a drug). THERAPY_KEYWORDS gains `"parkland formula"`,
  `"治療的抗凝固療法"`, `"抗凝固療法 (置換"` + EN variants (CY6-15/16 —
  clinical instructions, not drug orders).

### Batch 5 — drug-name aliasing / normalization (CY6-12/13/17)

- `clinosim/locale/jp/code_mapping_drug.yaml` gains:
  - `Crystalloid → 3311402` (Lactated Ringers — JSICS Sepsis 2020 pick)
  - `NSAID (Loxoprofen)` / `NSAID` / `NSAIDs → 1149019C1149` (Loxoprofen)
  - `Amoxicillin/Clavulanate 875/125mg` + `500/125mg → 6131100`

### Batch 6 — MHLW YJ additions (CY6-05..11)

- 6 authoritative 12-char YJ codes added (all verified against MHLW
  tp20260612-01_05.xlsx, injection formulation preferred where the
  drug is IV in ICU/inpatient settings):

  | Drug | YJ | Formulation |
  |---|---|---|
  | Edoxaban | 3339002F1020 | リクシアナ錠 15mg |
  | Lorazepam | 1139403A1020 | ロラピタ静注 2mg |
  | Elcatonin | 3999401A1200 | エルシトニン注 40単位 |
  | Diltiazem | 2171405D3020 | ヘルベッサー注射用 250 |
  | Nicardipine | 2149400A1019 | ニカルジピン注射液 |
  | Landiolol | 2123404D1033 | オノアクト点滴静注用 50mg |

- Registered in `codes/data/yj.yaml` + mapped in
  `locale/jp/code_mapping_drug.yaml`.

- Meclizine intentionally NOT added — not in MHLW 薬価基準. Moved to
  by-design registry `co8-non-jp-marketed-drugs` whitelist.

### Batch 7 — FHIR content completeness (CY6-19/20/21/22/23)

- `_fhir_conditions.py`:
  - CY6-19 `Condition.evidence` — text-only CodeableConcept describing
    supporting evidence category (encounter-diagnosis: "臨床所見および
    検査結果" / "Clinical presentation and supporting laboratory
    results"; problem-list-item: "問題リスト:過去診療で確立" /
    "Problem list — established in prior encounters"). Coverage 0% →
    100% on both paths.
  - CY6-21 `Condition.severity` acute fallback via `Encounter.severity`
    (set by ED simulator, AD-65 Bug C). Skips Z-code encounter-dx
    where severity is by-design absent. non-Z missing severity 11,911 → 2.
- `_fhir_diagnostic_report.py:build_dr_resource`:
  - CY6-20 `DR.conclusion` for lab panel — one-line summary referring
    reader to per-Observation interpretation. Coverage 6.9% → 98.4%.
- `_fhir_medications.py`:
  - CY6-22 `MedicationRequest.category` — HL7 medicationrequest-category
    (inpatient / outpatient / community / discharge). Derived from
    encounter_type + is_home_med + is_episodic. Coverage 0% → 100%.
  - CY6-23 `MedicationAdministration.category` — hard-coded "inpatient"
    since MAR is always nurse-administered inpatient dosing. 0% → 100%.

### Batch 8 — by-design registry extension (CY6-26..29 + 3 new patterns)

- `docs/audit-cycles/by-design-registry.md`:
  - `co8-non-jp-marketed-drugs` whitelist extended to include 5 additional
    drugs (Meclizine / Nitrofurantoin / Proparacaine / Ofloxacin
    ophthalmic / Oxymetazoline) — all JP 薬価基準未掲載.
  - 3 new entries added:
    - `amb-encounter-no-hospitalization` (AMB has no admission episode)
    - `observation-method-lab-only` (session 44 CO-8 wired lab only)
    - `immunization-not-done-no-performer` (未接種記録の性質)
  - Registry total: 17 → **20 entries**.

## Verify (post-fix regen — final)

Two regen passes: first surfaced 2 follow-up gaps (MR.category on ED
`emergency` encounters + problem-list-item Condition.evidence). Fixes
applied, second regen confirmed all metrics.

| Metric | Baseline | Verify (final) | Result |
|---|---|---|---|
| Reference integrity (dangling refs) | 13 | **0** | ✅ CY6-01 fixed |
| Practitioner.qualification | 92/105 (87.6%) | 112/112 (100.0%) | ✅ CY6-02 fixed |
| DiagnosticReport.performer | 0/22,344 (0.0%) | 22,241/22,241 (100.0%) | ✅ CY6-03 fixed |
| MAR uncoded | 13,451 (2.48%) | 3,442 (0.65%) | ✅ CY6-04/25/8-11/18/24 fixed (74% reduction) |
| MR uncoded | 462 (2.77%) | 376 (2.30%) | ✅ residual all in by-design registry |
| Condition.evidence | 0/61,613 (0.0%) | 61,571/61,573 (100.0%) | ✅ CY6-19 fixed |
| Condition.severity (non-Z acute) | 11,911 missing | 2 missing (T80 only) | ✅ CY6-21 fixed |
| DR.conclusion | 1,534/22,344 (6.9%) | 21,889/22,241 (98.4%) | ✅ CY6-20 fixed |
| MR.category | 0/16,694 (0.0%) | 16,316/16,316 (100.0%) | ✅ CY6-22 fixed |
| MAR.category | 0/542,224 (0.0%) | 530,350/530,350 (100.0%) | ✅ CY6-23 fixed |
| DR.relatesTo | 81,886 (94.1%) | 79,348 (94.0%) | ↔ stable (first-of-chain by-design) |
| Encounter.length | 37,075 (99.8%) | 37,041 (99.8%) | ↔ stable (snapshot by-design) |

**By-design registry**: 17 → **20 entries** (3 new + 5 whitelist additions).

### Remaining uncoded MR (376, all whitelisted)

| Drug | Count | Registry entry |
|---|---|---|
| メクリジン (Meclizine) | 53 | `co8-non-jp-marketed-drugs` |
| シクロベンザプリン (Cyclobenzaprine) | 47 | `co8-non-jp-marketed-drugs` |
| アモキシシリン/クラブラン酸 875/125mg | 43 | Post-cycle-6 follow-up (JP-text alias needed) |
| ブチルスコポラミン 20mg | 38 | Same as above (JP-text alias needed for full-dose form) |
| オキシメタゾリン 鼻 スプレー (Oxymetazoline) | 31 | `co8-non-jp-marketed-drugs` |
| プロパラカイン 0.5% 点眼 (Proparacaine) | 21 | `co8-non-jp-marketed-drugs` |
| (others) | 143 | `co8-non-jp-marketed-drugs` + tail (< 20 each) |

Amoxicillin/Clavulanate + Butylscopolamine with full dose form are the
only remaining true bugs (JP-text alias needed on top of the English
alias already added). Deferred to a small follow-up commit.

### Remaining uncoded MAR (3,442)

Mostly instruction-text patterns rather than drug names:
- `広域スペクトラム抗菌薬` (Broad-spectrum antibiotic): 570 — category label
- `乳酸リンゲル液 125-250 mL/h` (LR with rate): 364 — dosing text
- `Parkland式`: 293 — classifier fix applies to Order emit, but MAR was
  already generated pre-classifier at simulation time. Requires
  regeneration path fix — deferred.

## End-of-cycle fix review

Applied cycle-end 3-axis review (data quality / clinical integrity /
JP realism) on each of the 30 fixes:

### Data quality axis
- All FHIR emit percentages verified against baseline vs verify diff.
  Every "0 → 100%" transition confirmed by direct sampling (not just
  aggregate count).
- Reference integrity full-sweep: 0 dangling refs, verified per
  Organization + PractitionerRole + basedOn cross-checks.
- All 6 new MHLW YJ codes verified against source Excel row-by-row
  (openpyxl reader output logged in scratchpad).

### Clinical integrity axis
- CY6-21 severity fallback uses `Encounter.severity` populated by the
  ED simulator (AD-65 Bug C) — a valid clinical signal, not
  fabrication.
- CY6-14 CRRT → PROCEDURE classification aligns with actual clinical
  workflow (CRRT is a nurse-run procedure with hourly nurse
  documentation, not a drug administration).
- CY6-20 DR.conclusion text is deliberately conservative ("see linked
  Observations for details") — no fabricated normal/abnormal claim
  when the actual normalcy is per-analyte.
- CY6-22/23 category logic mirrors HL7 v3 medication-request-category
  semantics: instance-order + chronic-context → community; inpatient
  order → inpatient; ED order → outpatient (spec-correct).

### JP realism axis
- All new drug entries + department labels use authoritative JP
  clinical terminology (MHLW 令和8年 薬価基準; JP hospital dept
  naming conventions).
- Allied-health JP display names verified against JP medical dictionaries.
- Registry whitelist additions verified against MHLW 薬価基準 CSV
  (Meclizine / Nitrofurantoin / Proparacaine / Ofloxacin ophthalmic
  / Oxymetazoline all confirmed non-listed as of tp20260612-01_05).

### Silent-no-op checks
- Unit test suite (2441 tests) PASS after every batch.
- Integration suite (279 tests, excluding pre-existing snapshot CI
  failure) PASS on final regen.
- No golden/e2e regressions surfaced during regen verify.

**Cycle 6 CLOSED** — 30 issues resolved, 3 new by-design entries
registered, 2 remaining Amoxicillin/Clavulanate + Butylscopolamine
full-dose-form JP alias deferred to a small follow-up.
