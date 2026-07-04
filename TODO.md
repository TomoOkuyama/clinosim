# clinosim — TODO

## Status (current as of 2026-07-02)

**v0.2 (Simulation realism + Japanese/English documents + Occupational injuries)** — population-driven simulation with full FHIR R4 Bulk Data Export, multi-country (US/JP), 32 diseases + 46 ED/outpatient conditions, occupational injury support (6 work-related conditions + occupation field), snapshot date support, pluggable LLM providers (Ollama/Bedrock/Mock), three-stage CLI pipeline (`generate` → `narrate` → `export-fhir`), FHIR DocumentReference for 5 clinical document types (Tier A+B) in English and Japanese.

Latest generated datasets:

US full run (40K catchment, 50-bed hospital, seed=42):
- 102,485 encounters (1,501 inpatient + 96,114 outpatient + 5,029 ED)
- 3,344 Bedrock EN narrative documents (1,501 H&P + 1,501 DC + 181 Proc + 97 Op + 64 Death)
- 15 in-progress encounters (snapshot date)
- FHIR Bulk Data 2.0GB, 14 resource types (+ FamilyMemberHistory) + DocumentReference, 0 ID violations

JP full run (5K catchment, 50-bed hospital, seed=42):
- 16,637 encounters (227 inpatient + 15,886 outpatient + 524 ED)
- 499 Bedrock JP narrative documents
- Multilingual FHIR coding (JP primary + EN secondary for Condition/Procedure)
- CRP unit conversion (mg/L→mg/dL) code-side (AD-42)
- FHIR Bulk Data 467MB

Code system coverage:
- 349 ICD-10-CM codes, 306 ICD-10 (WHO) codes (EN + JA bilingual)
- 72 LOINC, 68 RxNorm, 31 CPT, 25 K-codes, 39 YJ, 31 SNOMED CT
- 120+ drug name JP translations (drug_names_ja.yaml)
- 420 unit + 80 integration + 39 e2e tests passing

**AD-55 Base data-enrichment roadmap complete (2026-06):** microbiology, cardiac
markers, nursing flowsheets, immunization, family history, code status, extended
SDOH (smoking/alcohol/JP 要介護度). The FHIR adapter was split from one 3015-line
monolith into per-theme `_fhir_*` builder modules (FA-1, byte-identical). See
`docs/reviews/2026-06-22-data-quality-audit.md` (clean).

**AKI Cr / DKA HCO3 surgical calibration (PR #69, 2026-06-22):** Two coefficients
in `derive_lab_values()` (Cr low-renal slope 15→6.5, HCO3 metabolic-axis gain
24→31) shift AKI admit Cr p50 from ESRD-domain (~5.6 US / 7.9 JP) into the KDIGO
2-3 band (~3.3 US / 4.1 JP), and DKA admit HCO3 / pH into ADA-stratified bands,
while leaving every state variable and disease YAML at master. BNP-pattern
surgical fix (#28 / #62): byte-diff at US/JP p=2000 seed=42 confirms only
`Observation.ndjson` differs and patient cohorts are preserved exactly. See
`docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md` (byte-diff +
percentile audit) and `docs/reviews/2026-06-22-aki-dka-surgical-calibration-data-quality-review.md`
(post-calibration FHIR/CIF data-quality review, clean).

**BNP wall-stress historical-record + I50 cohort decomposition (PR #70/#71,
2026-06-22):** The BNP wall-stress formula (already landed in commits
`ac36ff63` / `1c22a3e6` on 2026-06-20) gets its spec + plan committed as
design history (PR #70). The "I50 admit BNP below ADHF band" item from the
PR #69 review is closed: decomposing the I50 cohort by
`condition_event.ground_truth_diseases` + `encounter_type` shows inpatient
+ heart_failure_exacerbation admits at BNP p50 = 603.6 US / 931.8 JP (inside
the ADHF 800-1500 band) and outpatient chronic-I50 follow-up at p50 = 68.6
US / 74.9 JP (correctly mild for compensated HF). The mixed-cohort p50 was
a grouping artifact, not a formula deficiency (PR #71). See
`docs/reviews/2026-06-22-i50-bnp-cohort-decomposition.md`.

**FHIR DiagnosticReport panel grouping (PR #72, 2026-06-23):** Post-hoc
grouping of existing lab Observations into FHIR `DiagnosticReport`
resources for 7 panels (CBC / BMP / LFT / Lipid / Coag / UA / ABG) with
authoritative LOINC codes (`58410-2 / 51990-0 / 24325-3 / 57698-3 /
24373-3 / 24356-8 / 24338-6`). Implemented as a new AD-56-registered
bundle builder (`build_lab_panel_reports`) reading `ctx.record["orders"]`
and emitting one DR per (panel, encounter, day) with `result[]`
referencing the existing Observation ids. No CIF schema change, no
observation-engine change, no new RNG. Byte-diff at US/JP p=2000 seed=42
preserves every non-DR NDJSON identically; every existing microbiology
DR record is preserved byte-identically as a complete JSON line.
Referential integrity: 4025 US + 3502 JP panel DRs with 0 dangling
references. Audit at US p=8000 / JP p=4000 yields ~15k panel DRs
(LFT 5510 + CBC 5324 + ABG 2581 + BMP 2189 + Lipid 54 + microbiology 160
on US). Two calibrations to simulator emission (vs spec) documented:
day-resolution bucket (vs minute — the lab generator randomizes
per-component timing) and lowered `min_components` (Hct/Cl/Ca absent
from current physiology engine). See
`docs/reviews/2026-06-22-diagnostic-report-panels-audit.md`.

**CBC / BMP panel registry + panel-children RNG isolation (PR #74,
2026-06-23):** Two structural changes shipped together because PR #72's
calibration comments misdiagnosed the gap. (1) `lab_panels.yaml` gains
`CBC: [WBC, Hb, Hct, Plt]` and `BMP: [Na, K, Cl, HCO3, BUN, Creatinine,
Glucose, Ca]` entries so 9 silently-dropped `{test:"CBC"}` /
`{test:"BMP"}` orders in cerebral_infarction / DVT / hemorrhagic_stroke
/ DKA finally emit their canonical children — including **Hct, which
the engine already derived but had no emission path** (US count 3 →
114, 38×). (2) `_run_daily_loop` splits the lab-resulting loop into
Pass 1 (master RNG, non-panel-child orders — byte-identical to master)
and Pass 2 (panel children, per-parent isolated sub-RNG seeded by
`panel_specimen_seed(parent_order_id)` in the new `simulator/seeding.py`
helper). This closes a latent AD-16 violation that PR #72's emission
profile would have widened, and converts specimen rejection from
per-analyte (clinically impossible — pH rejected while pCO2 from the
same draw is fine) to per-specimen (one parent → all-or-nothing on
children). Cohort drift on non-lab files within the structural-fix
band; data-quality preserved (refRange 100%, display ≠ code 100%).
See `docs/superpowers/specs/2026-06-23-cbc-bmp-panel-expansion-design.md`
and `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`.

**CBC / BMP min_components raise + cerebral_infarction redundancy
removal (PR #75, 2026-06-23):** Audit-driven follow-up to PR #74.
`lab_panel_groups.yaml` raises `CBC.min_components` 2 → 3 and
`BMP.min_components` 3 → 5 per the canonical-N − 1 rule (one
specimen-handling tolerance). Validated by a new audit script
(`scratchpad/cbc_bmp_panel_audit.py`) at US p=4000 showing the
5th-percentile floor of "panel-order-placed" days sits at the
canonical maximum (4 / 6) — large margin above the chosen
thresholds. Headline outcome: **CBC DR count drops 81 % (1466 → 274)
and BMP DR 48 % (673 → 350) on US p=2000** as the new thresholds
suppress coincidence-only groupings. `cerebral_infarction.yaml` lines
139-140 lose their redundant `{test:"Hb"}` / `{test:"Plt"}` orders
(pre-PR1 workaround now superseded by the CBC panel's children).
Two existing DR-grouping unit tests expanded so their component
counts continue to clear the new thresholds. See
`docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md`.

**Post-PR #75 data-quality review + JP lab localization fix (PR #76,
2026-06-23):** 3-axis review at US p=10000 + JP p=5000 (seed=42).
Structural quality perfect on both populations (zero duplicate ids,
zero unresolved references across 9.1 M + 1.1 M reference checks,
refRange 100 %, display ≠ code 100 %). Clinical fidelity 13 / 14
PASS on both (CKD SKIP is structural — chronic_followup cohort outside
the inpatient walk); every per-disease admit-day band lands in the
clinically expected range. JP localization: US bundle byte-clean of
Japanese characters, JP `Condition.code.text` and `DiagnosticReport.code`
display 100 % Japanese, JP CM-granular ICD-10 leaks zero. One defect
detected and fixed in the same PR: five JLAC10 entries (3B015 CK-MB,
3B035 AST, 3B045 ALT, 4A055 TSH, 5C070 CRP) had `ja` populated with
the English abbreviation rather than the JCCLS Japanese name — replaced
with the JSLM v137 canonical names. See
`docs/reviews/2026-06-23-pr75-data-quality-review.md` and
`scratchpad/dqr_pr75_review.py`.

**Phase 2a — D-dimer (LOINC 48065-7 / JLAC10 2B140) + causes_vte flag
+ J5 wiring fix (2026-06-24):** Activates the D-dimer analyte by
extending `physiology.derive_lab_values` with a multi-axis formula +
a new `causes_vte` scenario flag (AD-57 BNP-pattern surgical, no new
`PhysiologicalState` field):

  age_factor = max(0, age - 50) * 0.005
  D_dimer = clamp(0.3 + age_factor + infl*0.5 + coag*1.5
                  + (4.0 if causes_vte else 0), 0.15, 20.0)

Three disease YAMLs gain `causes_vte: true`: pulmonary_embolism,
deep_vein_thrombosis, cerebral_infarction (embolic stroke). NOT
hemorrhagic_stroke (intracerebral fibrinolysis is captured by
coagulation_status alone). NOT AF / sepsis / COPD / acute_mi that
order D-dimer to screen — their elevation should stay non-specific.

**Improvement J5 bundled (same PR)**: introduces
`physiology.engine.scenario_flags_from_protocol(protocol)` helper and
replaces hardcoded `myocardial_injury=...` named arguments at every
`derive_lab_values` call site with `**flags`. Pre-J5, only
`inpatient.py:559-560` (Pass-1 daily loop) read `causes_myocardial_injury`;
emergency.py and outpatient.py passed nothing — so MI patients
presenting through the ED produced type-2 troponin only. The new
`causes_vte` would have replicated this gap if simply added. The fix
is structural (one helper, four sites) and future-proofs additional
scenario flags. Outpatient explicitly passes `None` to pin the
"acute scenario flags don't apply to chronic follow-ups" intent.

Authoritative codes:
- LOINC 48065-7 "Fibrin D-dimer FEU [Mass/volume] in PPP" — NLM
  verified (the spec/plan candidate 30240-9 did not exist; replaced
  with the authoritative FEU code matching locale reference range)
- JLAC10 2B140 "D-Dダイマー" — JSLM v137 sheet 「分析物コード」 verified,
  JCCLS-official ja per PR #76 rule

Byte-diff vs master `b6bc8eab` @ p=2000 seed=42 (both US and JP):
9 NDJSONs (Patient/Encounter/Condition/Medication*/Procedure/
Imaging/Immunization/FamilyHistory) byte-identical; only Observation
changes (+65 US / +15 JP, all D-dimer); DR unchanged (D-dimer is
panel-external to Coag LOINC 24373-3). 3-axis DQR (US p=10000 +
JP p=5000) all PASS — structural / clinical (PE/DVT/cerebral_infarction
D-dimer p50 4.45-4.91 ug/mL FEU, sepsis non-specific p50 0.84-0.90) /
JP language. See
`docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md`,
`docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md`,
`docs/superpowers/plans/2026-06-24-phase2a-vte-d-dimer.md`.

Phase 2a deferred backlog → carried forward:
- I4 panel-YAML unification refactor
- I6 `clinical_course.actions[].test` field disambiguation
- I7 `platelet_status` axis independence
- D-dimer LOS-mid analysis (cohort-level DIC trajectory)

**Phase 2b — `on_warfarin` medication-physiology coupling for PT_INR
therapeutic range (2026-06-24):** Extends Phase 2a by coupling warfarin
medication state to PT_INR derivation, completing the admit → ramp →
discharge → outpatient followup cohort trajectory for VTE / AF /
embolic-CI patients.

Sibling helper `medication_flags_from_context(patient, medication_orders,
admission_date, current_day)` parallel to `scenario_flags_from_protocol`.
Detection rules:
1. Chronic warfarin: `patient.current_medications` contains warfarin /
   ワルファリン / coumadin substring (chronic AF I48 + post-VTE I26 /
   I82 / I63 via `chronic_medications.yaml`)
2. In-hospital warfarin: a medication order with warfarin in display_name
   ordered ≥ 3 days ago (loading-dose 3-day rule, `all_orders` peek)

`derive_lab_values` PT_INR block:

  base_inr = 1.0 + (1 - hepatic) * 2.0 + state.coagulation_status * 1.5
  PT_INR = 2.5 + (base_inr - 1.0) * 0.5  if on_warfarin else base_inr

DOAC (apixaban / rivaroxaban / edoxaban / dabigatran) intentionally
NOT detected — INR is not clinically monitored for DOAC, and modeling
DOAC INR lift would be clinically misleading.

YAML data: `chronic_medications.yaml` gains 3 indications — I26 PE
(DOAC 80% / warfarin 20%), I82 DVT (same), I63 embolic CI (60% AC +
70% antiplatelet — combined therapy reflects clinical practice).
`helpers.py` `chronic_prefixes = ("I", ...)` already covers all three.

Byte-diff vs master `9e0b97a7` @ p=2000 seed=42 (US/JP): 8 of 9 NDJSONs
sha256-identical (Patient/Encounter/Condition/MedicationRequest/
MedicationAdministration/Procedure/Immunization/FamilyMemberHistory +
DR). Observation same-count change (199,492 US / 163,662 JP lines
preserved; 40/366 US PT_INR values shifted across 13 encounters, all
upward — warfarin lifting INR into therapeutic).

3-axis DQR (US p=10000 + JP p=5000) all PASS — structural (refRange
100%, code lookup LOINC 6301-6 + JLAC10 2B030) / clinical (US warfarin
p50 INR 2.70 therapeutic, DOAC p50 1.80 ≈ no-AC p50 1.70 unshifted,
warfarin shifted +1.00 above no-AC; JP warfarin p50 3.00 mirror) / JP
language (US 0 JP chars, JP warfarin ワルファリン + PT_INR
プロトロンビン時間 intact). See
`docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md`,
`docs/superpowers/specs/2026-06-24-phase2b-on-anticoagulation-design.md`,
`docs/superpowers/plans/2026-06-24-phase2b-on-anticoagulation.md`.

CLAUDE.md new architecture rule: `derive_lab_values` reads TWO flag
dicts (scenario + medication); call sites merge via
`{**scenario_flags, **medication_flags}` and splat as `**flags`. Never
add a `flag=value` named arg directly at a call site (J5-prevention
extended).

Phase 2c backlog (anticoagulation deepening):
- aPTT / heparin therapeutic monitoring (UFH IV drip → aPTT 60-80s target)
- DOAC INR micro-effect (rivaroxaban 0.2-0.3 lift) — clinical practice
  ignores, low realism gain, YAGNI
- Warfarin linear ramp (day 1 → 5 continuous vs step at day 3)
- HIT modeling (heparin-induced thrombocytopenia, PLT < 50% baseline
  after day 4 of heparin)
- Vitamin K reversal (PCC / FFP infusion drops INR within hours)
- Activator AC-drug exclusivity (warfarin OR apixaban, not both —
  pre-existing independent-probability draw limitation)

**AD-55 Module Foundation Refactor PR1 (G1 structural DRY) — 2026-06-24:**
Mechanical refactor preparing clean foundation for device + HAI feature
modules (chosen first AD-55 Module from brainstorming session 13).
Three structural-DRY items consolidated:

- `_get(obj, name, default)` 6-way duplication -> `clinosim/modules/_shared.py:get_attr_or_key`
  (5 enrichers + 1 FHIR builder import with `as _get` alias; -30 lines duplicate code)
- 7-module sub-seed offsets -> `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`
  central registry (identity 540_054 + microbiology 770_077 grandfathered as
  decimals; immunization 0x494D / code_status 0x4353 / family_history 0x4648 /
  care_level 0x434C / nursing 0x4E55 use 16-bit hex ASCII convention)
- `care_level.load_rates(country: str = "JP")` signature unified with
  immunization / family_history / code_status + preserved @lru_cache

Convention docs locked in: CLAUDE.md "AD-55 enricher patterns" subsection +
docs/CONTRIBUTING-modules.md 3 sub-section edits (sub-seed registry, shared
helper, locale signature regulation).

Byte-diff vs master `dcb47ccc` @ p=2000 seed=42: all 11 NDJSON sha256-IDENTICAL
for both US and JP (pure mechanical refactor; numerical identity preserved
through registry). test_seeding.py precomputed-literal pins (914786652 /
914785364 / 2694613518) continue to pass as cross-check. See
`scratchpad/refactor_pr1_byte_diff_results.md`.

Series context: PR1 of 4 (G1 done) → PR2 (G2 SDOH integrity done) → PR3
(G3 `_fhir_observations.py` theme split done) → PR_docs (G4 absorbed
done) → next: device + HAI feature work (2 modules with cross-module
enricher consumption).

**AD-55 Module Foundation Refactor PR2 (G2 SDOH integrity) — 2026-06-24:**
Mechanical SDOH integrity refactor preparing for future SDOH expansion
(occupation / education / housing / food insecurity). Three items:

1. 6 SNOMED enum->code mappings (3 smoking + 3 alcohol) moved from
   Python dict hardcode in _fhir_sdoh.py to YAML in new lightweight
   `clinosim/modules/sdoh/` module ("data-only module variant" —
   reference data + loader only, no enricher / no ENRICHER_SEED_OFFSETS;
   `clinosim/codes/` is the preexisting precedent).
2. `_fhir_sdoh.py` 88-line file split into `_fhir_smoking_alcohol.py`
   (LOINC-keyed pattern) + `_fhir_care_level.py` (JP-only, custom code
   system). `_fhir_sdoh.py` deleted.
3. `_social_category` + `_value` helpers promoted to `_fhir_common.py`
   for future SDOH builder reuse (occupation / education / housing /
   food insecurity will inherit).

CONTRIBUTING-modules.md gains "データ専用モジュール (variant)" sub-section
documenting the new module shape. DESIGN.md AD-56 entry extended.

Byte-diff vs master `36ac9afd` @ p=2000 seed=42: all 11 NDJSON
sha256-IDENTICAL for both US and JP (pure mechanical refactor;
numerical identity preserved through YAML). See
`scratchpad/refactor_pr2_byte_diff_results.md`.

Series context: PR2 of 4 (G2 done) → PR3 (G3 done) → PR_docs (G4
absorbed, done) → next: device + HAI feature work.

**Comprehensive Documentation Update (G4 absorbed) — 2026-06-24:**
Pure documentation PR (no code changes; no byte-diff / DQR required).
Five-fold improvement to first-time-viewer onboarding + module-
relationship visibility:

1. **MODULES.md** (new top-level) — 22-module inventory + dependency
   tree + 3 typical call chains + 5-step new-module quick-start.
2. **SCENARIO_FLAGS.md** (new top-level) — central reference for all
   scenario + medication flags routed through derive_lab_values
   (currently myocardial_injury / causes_vte / on_warfarin) + helper
   architecture + 5-step new-flag guide.
3. **.github/TEMPLATE_MODULE_README.md** (new) — standardized template
   for new module READMEs with canonical section order.
4. **All 22 module READMEs gained `## Consumers` section** — reverse-
   dependency visibility (impact tier core/medium/guard) so contributors
   can assess downstream impact of any module change. 4 batches (A:
   small / B: small-medium / C: medium / D: large).
5. **7 weak READMEs** gained `## データ構造` section (disease/encounter/
   order/facility/procedure/validator/population; population already
   had one and was skipped).

Additional fixes:
- `output/README.md` gained "拡張方法 (Extensibility) 総合ガイド" section
  (register_bundle_builder + register_output_adapter patterns + common
  helper list documented).
- `sdoh/README.md` language consistency fix (line 3 was English).
- `CONTRIBUTING-modules.md` gained "PR 検証ガイド: byte-diff vs 3-axis
  DQR" sub-section — clarifies that the TRUE goal is FHIR R4 / JP Core
  compliance + 臨床整合性 + JP language quality; byte-diff is a
  refactor-PR no-regression mechanic only. Captures user feedback:
  "byte-diffってなんのため？CIFにある情報は、適切にFHIRやJP COREに
  準拠したFHIR R4にするのがゴールだよ？"
- `CONTRIBUTING-modules.md` typed-field-vs-extensions decision tree
  extended (G4 doctrine docs absorbed): 3-question judgment flow +
  decision matrix table + PR2 data-only variant lesson.
- Cross-reference integration: README EN/JP gain Module Map section;
  DESIGN.md AD-56 extended with PR_docs note; CLAUDE.md gets new
  "Quick navigation" table at top; CONTRIBUTING-modules.md header
  link directs new contributors to TEMPLATE + MODULES + PR verification.

Series context: PR1 (G1, merged) + PR2 (G2, merged) + **PR_docs (G4
absorbed, merged) ✓** + **PR3 (G3 Observation-family split, this PR) ✓**.
**AD-55 Module Foundation Refactor series complete** — next: device +
HAI feature work.

**AD-55 Module Foundation Refactor PR3 (G3 Observation-family split) — 2026-06-24:**
Pure mechanical refactor — the final structural piece of the foundation
refactor series. Three items:

1. `_fhir_observations.py` (727 lines / 31 KB) decomposed into three
   new per-theme files matching PR2's precedent:
   - `_fhir_microbiology.py` (~110 lines) — Specimen + Observation +
     DiagnosticReport (`_bb_microbiology`), plus the file-private
     `_SUSCEPTIBILITY_DISPLAY` constant.
   - `_fhir_nursing.py` (~210 lines) — NEWS2 / GCS / Braden / Morse /
     Barthel / I&O survey Observations (`_build_nursing_observations`).
   - `_fhir_immunization.py` (~70 lines) — CVX Immunization
     (`_build_immunizations`).
2. Residual `_fhir_observations.py` (~380 lines) is now the canonical
   numeric Observation builder (lab helper + vital builder); module
   docstring trimmed to reflect the final scope; three unused imports
   (`_micro_coding`, `_loinc_coding`, `_survey_category`) and now-unused
   `BundleContext` pruned.
3. `fhir_r4_adapter.py` import block rewired: `_build_immunizations` from
   `_fhir_immunization`, `_bb_microbiology` + `_SUSCEPTIBILITY_DISPLAY`
   from `_fhir_microbiology`, `_build_nursing_observations` from
   `_fhir_nursing`, and only `_build_lab_observation` +
   `_build_vital_observations` from `_fhir_observations`. Down-stream
   re-export surface preserved via `noqa: F401` (every existing
   `from ...fhir_r4_adapter import X` keeps working).

No `_fhir_common.py` helper promotion needed (PR2 already promoted
what was required). `_BUNDLE_BUILDERS` registration order unchanged
(byte-diff prerequisite).

Byte-diff vs master `0ed65f86` @ p=2000 seed=42: **all 33 NDJSON files
(US 16 + JP 17) sha256-IDENTICAL** for both countries. pytest
`unit or integration` 604 passed. See `scratchpad/pr3_byte_diff_results.md`.

DESIGN.md AD-56 entry extended with PR3 continuation. CLAUDE.md output
directory description unchanged (the "per-theme `_fhir_*` builders"
phrasing already covered the new files). `output/README.md`
Extensibility section's per-theme builder table updated with the three
new files + residual `_fhir_observations.py`.

Clears the runway for device + HAI feature builders to land in clean
per-theme files (`_fhir_device.py` / `_fhir_hai.py`) without inheriting
a multi-theme blob.

**Device module (PR-A) — 2026-06-24:** First phase of the 4-PR device +
HAI series. `modules/device/` post_records enricher emits FHIR Device +
DeviceUseStatement for ICU encounters with state-based placement
criteria:

- CVC (SNOMED 52124006) when severity_moderate_plus (ICU inpatient)
- Indwelling catheter (SNOMED 23973005) when severity_moderate_plus OR
  altered_consciousness (vital_signs[i].gcs_score < 13)
- Ventilator (SNOMED 706172005) when hypoxia (perfusion_status < 0.4)
  OR high_respiratory_demand (respiratory_fraction > 0.7)

SNOMED codes verified via tx.fhir.org $expand text-search; spec's
tentative 467021000 was not in SNOMED CT International — replaced
with the verified 23973005 (PR #80 LOINC 2B010 fabrication precedent).
ENRICHER_SEED_OFFSETS["device"] = 0x4445 ("DE"). New
`clinosim/types/device.py` (`DeviceRecord` dataclass under
`extensions["device"]`). `_fhir_device.py` builder file emits Device +
DeviceUseStatement via _BUNDLE_BUILDERS list (PR3 theme-per-file
pattern). 3-axis DQR PASS at US p=10000 + JP p=5000: 353 + 20 devices,
all structural checks 100%, line-days p50 = 6 (US) / 13 (JP) within
plausible bands. byte-diff supplement confirms zero regression on
pre-existing NDJSON. See
`docs/reviews/2026-06-24-device-module-data-quality-review.md`.

Series context: PR-A (✓ done) → PR-B (✓ done) → PR-C (helper
DRY if needed) → PR-D (comprehensive docs sync). Phase 1 simplifications
acknowledged in DQR doc: ICU sub-period ≈ inpatient encounter LOS
(over-estimates true line-days, calibratable in Phase 2); CVC + catheter
always co-emit on ICU inpatient (criteria overlap by design); ventilator
adoption ~82% of CVC (hypoxia proxy broader than true clinical need).

**HAI module (PR-B) — 2026-06-24:** Phase 2 of the 4-PR device + HAI
series. `modules/hai/` post_records enricher (order=80, after
device=70) consumes PR-A `extensions["device"]` line-days and samples
CLABSI/CAUTI/VAP onsets via CDC NHSN baseline per-line-day risk
rates (0.0010 / 0.0014 / 0.0015 per device-day = 1.0/1.4/1.5 per
1000 device-days):

- CLABSI ← CVC (SNOMED 736442006 verified)
- CAUTI ← indwelling catheter (SNOMED 68566005 verified, generic
  UTI — CAUTI-specificity in ICD-10-CM T83.511A + text)
- VAP ← ventilator (SNOMED 429271009 verified)

Onset: cumulative `1 - (1 - per_day_risk)^line_days`; offset uniform
over `[2, line_days)` per CDC ≥48h rule; snapshot in-progress device
→ conservative `line_days=7`. Organism sampled from CDC NHSN top
organism distribution per HAI type (S. aureus / E. coli / Candida /
S. epidermidis / etc., 11 organism SNOMEDs total — 6 reused from PR3
microbiology section, 5 new for HAI). Culture appended to
`record.microbiology` so the existing `_fhir_microbiology.py` builder
emits Specimen + Observation + DiagnosticReport without new wiring.

ENRICHER_SEED_OFFSETS["hai"] = 0x4841 ("HA"). Codes verified at
Task 1: NLM ICD-10-CM API (T80.211A / T83.511A / J95.851); WHO ICD-10
(T80.2 / T83.5 / J95.8); tx.fhir.org $lookup/$expand for SNOMED HAI +
organisms + specimens; existing PR3 microbiology section reused for
LOINC 600-7 / 630-4 / 619-7 (blood / urine / sputum culture). New
`clinosim/types/hai.py` (HAIEvent under `extensions["hai"]`). New
`_fhir_hai.py` builder file emits only the HAI Condition (dual coding
ICD-10 + SNOMED). 3-axis DQR PASS at US p=10000 + JP p=5000: US 4
HAI (3 CAUTI + 1 VAP) within Poisson 2σ of expected ~3.2; JP 0 HAI
acceptable rare event at p=5000 (P(X=0) ≈ 0.71). byte-diff supplement:
all 37 pre-existing NDJSON byte-identical. See
`docs/reviews/2026-06-24-hai-module-data-quality-review.md`.

Series context: PR-A (✓ done) → PR-B (this, ✓ done) → PR-C (helper
DRY if needed) → PR-D (comprehensive docs). Phase 2 simplifications:
snapshot in-progress fallback line_days=7; at-most-one HAI per device;
no antibiotic / susceptibility / mortality / WBC-CRP lift (all Phase 3).

First clean implementation of cross-module enricher consumption pattern
(PR-A device → PR-B hai); foundation for Phase 3+ device-consuming
modules.

**Phase 3a HAI WBC + CRP forward-delta lift — 2026-06-25 (✓ done)**:
Closes the clinical chain HAI 発症 → 炎症マーカー上昇 left open by
PR-B. Adds new `POST_ENCOUNTER` enricher stage to
`simulator/enrichers.py` (alongside `POST_POPULATION` and
`POST_RECORDS`) which runs per-encounter immediately after the daily
loop completes, inside the encounter simulator. Migrates `device`
(order=70) + `hai` (order=80) from POST_RECORDS to POST_ENCOUNTER —
their sampling depends on icu_transferred + GCS + perfusion which
are only known after the loop, and their output (HAI events) is then
consumed by `clinosim/modules/hai/lab_lift.apply_hai_lab_lift` which
walks `extensions["hai"]` and adds a forward-delta to existing
WBC + CRP `obs.value` using per-day state_history snapshots
(`delta = derive(state, lift>0) - derive(state, lift=0)`, preserving
original noise + circadian). New `clinosim/modules/hai/reference_data/
hai_lab_lift.yaml`: CDC severity proxy CLABSI/VAP=0.35, CAUTI=0.20,
ramp_peak_days=2.

The `derive_lab_values` signature gains one new kwarg
`hai_inflammation_lift: float = 0.0` (routed only to CRP + WBC via
`effective_infl = min(1.0, infl + lift)`). PCT / Albumin / Fibrinogen /
pO2 / Ca / Temperature / SBP-DBP continue to read
`state.inflammation_level` directly — Phase 3a scope guard, Phase 3c
will revisit.

AD-55 Module classification refined:
**"encounter-bound Module"** (device/hai — POST_ENCOUNTER) vs
**"cross-record Module"** (nursing/immunization/family_history/
code_status/care_level/sdoh — POST_RECORDS). byte-diff PASS: 37/37
NDJSON byte-identical at US p=2000 + JP p=2000 (HAI Poisson rare at
this size; lift verified by closed-form proof script — see post-fix
DQR review).

**xhigh code review hardening (PR-90, 2026-06-25 second pass)**:
A workflow-backed xhigh review on the merged PR-90 surfaced 13
confirmed + 2 plausible bugs. The critical one: YAML hai_type keys
were UPPERCASE (`CLABSI`/`VAP`/`CAUTI`) while the enricher writes
lowercase, silently no-op'ing the entire lift in production. The
+2,135 WBC / +50.4 CRP CAUTI delta in the DQR was a UTI disease
confounder, not the lift code. Fixes applied (commit `4dd36a55`):
single-source-of-truth `HAI_TYPES = ("clabsi","cauti","vap")` +
import-time YAML validation; `run_forced` calls
`register_builtin_enrichers()`; closed-form `_hai_lift_delta` replaces
double-`derive_lab_values`; multi-event = max; `state_history[N+1]`
off-by-one fix; `obs.flag` recomputed via `determine_flag`; draw hour
from order.ordered_datetime; snapshot_dt truncation extended to HAI
events + cultures; `hai_flags_from_record` deleted as dead code;
29-line dead block removed from `_simulate_unknown_condition`.
Verification: lift-firing proof (closed-form delta matches actual
`apply_hai_lab_lift` output exactly), DQR 3-axis still PASS, byte-diff
37/37 IDENTICAL preserved. See
`docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review-post-fix.md`.

**Phase 3b-1 HAI empirical antibiotic regimen — 2026-06-25 (✓ done)**:
First of the 4-PR Phase 3b series. `modules/antibiotic/` always-on
Module (AD-55 *near-essential clinical cascade* category — new AD-55
supplement in DESIGN.md). Consumes `extensions["hai"]`, emits IDSA
2009/2016 guideline empirical regimens (CLABSI = Vanc q12h + Pip-Tazo
q6h × 14d / CAUTI = Ceftriaxone q24h × 7d / VAP = Vanc q12h + Pip-Tazo
q6h × 7d). Dual-write storage: `record.orders` (MedicationRequest) +
`record.medication_administrations` (MAR) + `extensions["antibiotic"]`
(cross-PR consumption). Zero new FHIR builders (reuses
`_fhir_medications.py`). AD-32 future-onset HAI defensive skip in
enricher prevents orphan Order/MAR. `modules/antibiotic/audit.py` =
second AD-60 plug-in with closed-form lift_firing_proof (Ceftriaxone
q24h × 7d delta). `ForcedScenario.force_hai_event` added (Task 7b) for
deterministic HAI testing. Vancomycin RxNorm 11124 + YJ 6113400
centralized (existing repo usage). 12 commits across 12 tasks.

**Phase 3b-2 HAI culture S/I/R — 2026-06-26 (✓ done)**:
PR #96 + adversarial fan-out fix PRs #97 + #98.
`_append_hai_culture` extended with antibiogram-driven susceptibility sampling.
`hai_antibiogram.yaml` (CDC NHSN AR 2018-2020) as source of truth; import-time
3-way cross-validation (HAI_TYPES + hai_organisms + ANTIBIOTIC_LOINC_LOOKUP) +
`_NHSN_RESISTANCE_BANDS` import-time validation (PR #98 MED-4).
`MicrobiologyResult.hai_event_id` backref + `AntibioticRegimen.discontinuation_datetime`
forward-compat reserves shipped. `ANTIBIOTIC_DRUGS` tuple → dict refactor +
`ANTIBIOTIC_LOINC_LOOKUP` companion. LOINC orphan fix (ciprofloxacin → cefepime).
`run_forced` force_hai_event injection gap closed (PR #96 Task 6 + PR #97 F-CRIT-2
load-bearing test). Audit: `antibiogram_firing_proof` (PR-94 equality_checks format)
+ non-degenerate cefazolin sentinel (PR #98 LOW-1) + sub-proof exception isolation
(PR #98 MED-3). AD-16 hardening: `_CapturingRNG` logs `p=` array; YAML key-order pin
tests for clabsi/cauti/vap pinned organisms; YAML header LOAD-BEARING comment
(PR #98 MED-1+MED-2). DQR:
`docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`

**Post-merge adversarial fan-out (8 agents)** found 30+ findings the per-task
+ final whole-branch reviews missed, including 2 CRITICAL (mypy strict 11 errors
in `clinosim/audit/registry.py:23` `clinical_acceptance` type; Task 6 run_forced
injection had zero load-bearing test — reverting passed all tests = PR-90 class
silent-no-op recurrence) + 1 MAJOR (HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE denominator
undefined → PR3b-3 gate would always-FAIL). Fix PR #97 closed all 7 load-bearing
findings; Fix PR #98 closed 25+ MEDIUM/LOW/MINOR. Validates `feedback_iterative_adversarial_review`
memory: test green + final review APPROVE is not ship-ready; fix PRs themselves
need adversarial review (3-stage chain pattern from PR-93/#94/#95 re-confirmed).

Phase 3b backlog (remaining):
- ~~PR3b-3~~: ✓ done 2026-06-27 — narrow / de-escalation chain. Same `enrich_antibiotic`
  Pass 2 reads `MicrobiologyResult.hai_event_id` backref → ladder walk → 3 outcomes
  (SWITCH / ELIMINATION / NO_CHANGE). New `narrow_ladder.yaml` (3-way validated).
  `OrderStatus.STOPPED` + FHIR `MedicationRequest.status="stopped"` wiring.
  Audit clinical axis active enforcement: NHSN R-rate + empty rate + new narrow rate.
  `lift_firing_proof` extended to 17 equality_checks (8+3+6).
- ~~PR3b-3 D1+D2~~: ✓ done 2026-06-29 (PR #112 + adv-1 #113 + adv-2 #114
  + adv-3 #115 = 4-stage adversarial chain converged) — clinical axis
  per-(hai_type, organism, antibiotic) R-rate filter via `_organism_per_encounter`
  + panel-eligible empty-rate denominator via `_panel_eligible_organisms`.
  Both TODO markers removed (clinical.py + antibiotic/audit.py). 6-layer
  silent-no-op defense complete. PR3b-3 original-spec deferred TODOs = 0.
- ~~PR3b-5~~: ✓ done 2026-06-29 (PR #117 + adv-1 #118 + adv-2 #119 =
  3-stage adversarial chain converged) — specimen-based susc → organism
  join + FHIR HAI_EVENT_ID_SYSTEM identifier emission
  (`urn:clinosim:identifier:hai-event-id`) resolved the PR3b-3 D1
  encounter-level attribution approximation. C1 (multi-organism encounter
  double-count) and C2 (community + HAI culture co-occurrence) both
  mechanically excluded. New helpers `_organism_per_specimen` +
  `_hai_specimens` in `clinosim/audit/axes/clinical.py`. FHIR identifier
  emission added to Specimen + mb-org-* / mb-sus-* Observation +
  DiagnosticReport (`clinosim/modules/output/_fhir_microbiology.py`). See
  `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`.

Out-of-scope items deferred from PR3b-5 (formal tracking — each one
required so the chain closure can honestly claim "no half-finished state
remains"):

- PR3b-4: WBC/CRP forward-delta decay coupled with antibiotic-day count.
  Sibling to the Phase 3a HAI lift pattern; antibiotic start_day initiates
  a forward decay on WBC + CRP observed values mirroring the lift profile.
  Independent of PR3b-3 / PR3b-5 — purely new realism work.
- ~~Sibling YAML loader sweep~~: ✓ done 2026-06-29 (this PR + adversarial
  chain) — `_validate_hai_rates` + `_validate_hai_codes` +
  `_validate_hai_specimens` + `_validate_hai_lab_lift_config` (refactor
  inline → function) + `_validate_hai_organisms` forward-coverage
  strengthen. **6-layer silent-no-op defense now applied to all 6
  hai_*.yaml loaders** (antibiogram + organisms + lab_lift + rates +
  codes + specimens). YAML data unchanged; byte-diff verified zero
  (NDJSON identical, only manifest.json transactionTime differs).
  **区切り達成宣言可能** (PR3b-3 + PR3b-5 + sibling sweep 3 chain
  CLOSED).
- audit registry `_reset_for_test` ordering bug: 10 fail master baseline
  (production code healthy, test isolation issue only). Tests that call
  `discover()` end up with empty registry after another test's
  `_reset_for_test`. Fix candidate: autouse fixture in conftest that
  re-discovers before each integration test.
- audit clinical axis Phase 2 (per-event observed-vs-theoretical
  enforcement): new axis-level enforcement walking CIF state_history per
  event for closed-form delta verification. Currently the silent_no_op
  axis lift_firing_proof covers this at synthetic-fixture level; Phase 2
  would enforce per-real-event at audit run time.
- NHSN clinical-accuracy band verification (CoNS / K.pneumoniae VAP /
  A.baumannii VAP exempt entries): adv-2 Agent 1 (PR #114 review) flagged
  that NHSN AR 2018-2020 may publish stable population bands for organisms
  currently in `_NHSN_REVERSE_COVERAGE_EXEMPT`. Verify against the NHSN
  tables and either ADD a band (preferred) or tighten the exempt rationale.
- I1 WARN per-country diagnostic improvement: current WARN message fires
  per country with identical wording; symptom (antibiogram corruption /
  mb-org drift / SNOMED URI drift) is global. Improve by probing
  individual root cause and emitting one global WARN with specific
  dispatch.
- Unused MB_*_PREFIX cleanup (MB_SUS / MB_SPECIMEN / MB_DR): extracted
  in PR #113 for consistency but currently no reader imports them.
  YAGNI cleanup once a reader appears (or remove if no reader added by
  the next refactor).
- DESIGN.md AD-55 / AD-60 PR3b-3 supplement extended ADR text: brief
  closure note already in AD-60. A longer ADR-quality narrative covering
  the 7-layer silent-no-op defense pattern (including
  `HAI_EVENT_ID_SYSTEM` from PR3b-5) and the AD-55 near-essential clinical
  cascade extension is a documentation polish item.
- **Sepsis SBP<90 過少 (septic shock 過少 fire)** — clinical realism gap.
  Memory `project_realism_gaps` and session 23 DQR
  (`docs/reviews/2026-06-29-session23-breakpoint-dqr.md`) both observe
  that sepsis cohort SBP distribution has too few values <90 mmHg at p=10000
  (60 sepsis patients, SBP median 116 / p95 142 — low tail thin despite
  R65.21 septic shock conditions in cohort). PR #62 fixed this once via
  `derive_vital_signs` SBP/DBP surgical edit (`-(infl-0.7)*60` term) but
  the magnitude / fire-rate needs strengthening. Recommended approach:
  PR #62 BNP-pattern surgical pattern continued — increase inflammation
  coupling slope OR add `causes_septic_shock` scenario flag with
  encounter-bound SBP suppression. **DO NOT alter `perfusion_status` state
  variable** — PR #62 教訓 documents this would re-trigger clinical_course
  RNG cascade affecting unrelated patients (AD-16 violation, ~76% cohort
  contamination). Verify via DQR per-cohort SBP<90% target ~20-30% for
  R65.21 patients.
- **HAI cohort rare-event regime**(by-design, NOT a TODO fix item — recorded
  as decision rationale): hai_rates.yaml uses 0.001-0.0015/device-day per CDC
  NHSN AR 2018-2020. At p=10000 this yields CAUTI n=14 / CLABSI 0 / VAP 0 —
  matches CDC truth but production-scale band firing (n≥30 per cohort) requires
  p≥50k or `ForcedScenario.force_hai_event` injection. This is **usability vs
  realism trade-off, not a data quality bug**. Do not rate-inflate. If
  production-scale band testing needed, use ForcedScenario harness instead.

Phase 3c backlog:
- HAI → outcome_benchmarks mortality coupling
- Lactate / Plt / 体温 / SBP sepsis cascade using same forward-delta pattern
- LOS extension from HAI

DQR audit-script strengthening (post PR-90 review learning) ✓ done
2026-06-25: clinosim audit framework Phase 1 (AD-60). New CLI subcommand
`clinosim audit run` absorbs the previous 3-axis DQR scripts and adds a
silent_no_op axis (canonical-constants cross-check + lift-firing proof) —
the load-bearing verification PR-90 was missing. Per-Module checks
co-locate in `clinosim/modules/<name>/audit.py`. First plug-in:
`modules/hai/audit.py`. byte-diff vs master @ p=2000: 37/37 NDJSON
byte-IDENTICAL — audit framework is pure read-only consumer. See
`docs/reviews/2026-06-25-clinosim-audit-baseline.md`.

Per-Module audit.py backlog for Phase 3b/c:
- modules/antibiotic/audit.py ✓ done 2026-06-25 (PR3b-1, empirical regimen + lift_firing_proof)
- modules/antibiotic/audit.py ✓ extended 2026-06-26 (PR3b-2: _ABX_LOINCS + _NHSN_RESISTANCE_BANDS + HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE + antibiogram_firing_proof)
- modules/antibiotic/audit.py ✓ extended 2026-06-27 (PR3b-3: _NARROW_RATE_BANDS + _pr3b3_narrow_proof_checks (6 checks) + load_narrow_ladder import-time touch; clinical axis active enforcement of all 3 gates in clinosim/audit/axes/clinical.py)
- modules/decay/audit.py (Phase 3b-4: WBC/CRP antibiotic-day decay)
- modules/mortality/audit.py (Phase 3c: HAI → outcome coupling)
- modules/sepsis_cascade/audit.py (Phase 3c: Lactate/Plt/Temp/SBP)
Each Module's own PR adds its audit.py alongside the feature.

Backlog: **PR_C type consolidation** — 7 modules currently define types
in `engine.py` instead of `clinosim/types/` (CLAUDE.md "All types
defined in clinosim/types/" rule). Code refactor with byte-diff risk;
separate concern from docs work. Modules: population (PersonRecord/
LifeEvent/HospitalizationSummary), facility (HospitalState), procedure
(ProcedureMeta/ProcedureRecord/RehabSession), encounter (no Pydantic
protocol type), staff (StaffMember/StaffRoster), validator (4 dataclass
reports). DiseaseProtocol is already in protocol.py — different concern.

**Master HEAD Comprehensive 3-axis DQR — 2026-06-24:** First post-PR_docs
goal verification using the new "PR 検証ガイド" framework. **All 3 axes
PASS for both US and JP** at the project's true goal: FHIR R4 / JP Core
compliance + 臨床整合性 + JP localization 品質.

- US p=10,000 + JP p=5,000, seed=42, format=CIF + fhir-r4
- Structural: 0 errors, 0 warnings (3.4M US + 434K JP Observations,
  id uniqueness 100%, reference integrity 100%, refRange/interp 87.2%
  with the 12.8% being legitimate O2 admin + 24h I/O)
- Clinical: US warfarin INR shift +1.00, HbA1c×Glucose r=0.636; JP
  JLAC10 全 17 主要 lab (Cr/Glucose/WBC/AST/ALT/Hb/K/Na/CRP/PT_INR/
  HCO3/Plt/pH/pCO2/pO2/D-dimer/Troponin) 全て臨床的妥当帯
- JP Language: US 全 10 NDJSON で日本語混入 0; JP 100% 日本語化
  (Cond/DR/Med/Imm/care_level/smoking/alcohol); JLAC10 with JCCLS-JSLM
  公式日本語表示 (クレアチニン / プロトロンビン時間 等); CM-granular
  ICD 漏洩 0

**Audit findings clarified (not defects)**:
- DOAC INR delta = 0.60 (US) / 1.10 (JP) was an audit-script false-
  negative caused by `_derive_home_medications` independent-draw
  artifact (Phase 2c backlog). JP has 0 DOAC-only patients; the
  warfarin-only cohort (n=4) shows correct therapeutic INR p50=2.70.
- JP DR text=0% was an audit-script bug (checked `code.text` instead
  of `code.coding[].display`); actual display is 100% Japanese
  ("肝機能パネル" 等).
- JP non-INR labs n=0 was audit-script's US-LOINC-only filter
  limitation; manual JLAC10 query confirmed all bands valid.

Report: `docs/reviews/2026-06-24-master-comprehensive-dqr.md` —
includes per-axis evidence tables and the top-15 JLAC10 codes with
counts + JCCLS Japanese display verification.

**Audit script enhancements queued (next DQR cycle)**:
- Add JLAC10 code support (currently only LOINC; JP non-INR labs
  silently return n=0 without JLAC10 hardcoded)
- Fix JP DR display check (read `code.coding[].display` not `code.text`)
- DOAC cohort separation: filter out warfarin co-prescription so
  "DOAC-only" INR baseline can be measured cleanly

These are non-blocking; the manual JLAC10 confirmation in this DQR
already validated JP clinical bands.

**Coag panel activation (LOINC 24373-3) + APTT/PT/Fibrinogen derives
(2026-06-24):** Activates the previously-defined-but-dormant Coag
DiagnosticReport panel (LOINC 24373-3) by extending
`physiology.derive_lab_values` with three new analytes — all from
existing state axes (no new `PhysiologicalState` field), AD-57
BNP-pattern surgical:

- `APTT = clamp(30 + coagulation_status*55, 20, 150)` (seconds; healthy
  ~30, DIC ~85)
- `PT = clamp(12 * PT_INR, 9, 90)` (seconds; ISI=1.0 consistency
  invariant tying PT to the existing PT_INR)
- `Fibrinogen = clamp(300 + infl*250 - coag*280, 50, 800)` (mg/dL;
  **biphasic** — acute-phase reactant ↑ in inflammation, consumed ↓ in
  DIC. Healthy ~300, sepsis-no-DIC ~512, sepsis+DIC ~289, severe DIC
  floor 50.)

Also adopts improvements (uniform rule
`feedback_propose_improvements_to_existing`):
- I1: `lab_panels.yaml` gains Coag/LFT/Lipid/UA (symmetry with
  `lab_panel_groups.yaml` restored)
- I2: `lab_panel_groups.yaml` Coag block documents LOINC 24373-3
  authoritative scope (Fibrinogen/D-dimer panel-external)
- I3: stale "Cl/Ca in BMP today" comment refreshed
- I8: Fibrinogen "range exists, derive missing" gap closed

Authoritative code data (NLM + JSLM v137 verified): LOINC 14979-9 APTT,
5902-2 PT (existing entry reused), 3255-7 Fibrinogen (existing; `en`
shortened to "Fibrinogen" per clean-display convention). JLAC10 2B020
APTT, 2B100 Fibrinogen, 2B030 (existing — shared by PT seconds and
PT-INR since the 5-char analyte code does not distinguish result
representation).

Byte-diff vs master `fbd80607` @ p=2000 seed=42 (both US and JP):
nine NDJSONs (Patient/Encounter/Condition/Medication*/Procedure/
Imaging/Immunization/FamilyHistory) byte-identical; only
Observation.ndjson + DiagnosticReport.ndjson change (new APTT/PT/
Fibrinogen Observations + new Coag DRs). 3-axis DQR (US p=10000 +
JP p=5000) all PASS — structural / clinical (sepsis admit
Fibrinogen p50 501-516 in 350-650 acute-phase band, APTT p75 31.1-31.9
above upper reference) / JP language (zero US leak, 2760 JP
instances, jlac10 `ja` JCCLS-official). See
`docs/reviews/2026-06-24-coag-panel-data-quality-review.md`,
`docs/superpowers/specs/2026-06-23-coag-panel-physiology-design.md`,
`docs/superpowers/plans/2026-06-23-coag-panel-physiology.md`.

Deferred to follow-up PRs (recorded as backlog):
- **Phase 2**: `D_dimer` derive + `causes_vte` scenario flag for
  PE/DVT/cerebral_infarction/hemorrhagic_stroke
- **`on_anticoagulation` axis**: warfarin/heparin therapeutic-range INR
  modelling (pair with D-dimer Phase 2 PR)
- **I4 panel-YAML unification**: merge `lab_panels.yaml` and
  `lab_panel_groups.yaml` to a single canonical analyte source
- **I6 `clinical_course.actions[].test` field disambiguation**: separate
  orderable test names from natural-language action descriptors
- **I7 `platelet_status` axis**: decouple Plt from `coagulation_status`
  so ITP/chemotherapy/MDS can be modelled separately
- **LOS-mid DIC subset audit**: confirm Fibrinogen DIC-consumption tail
  emerges in the sepsis subset that accumulates `coagulation_status`
  over LOS

**BMP Cl/Ca physiology + anion_gap_status axis + Pass 1 sub-RNG
isolation (PR Cl/Ca, 2026-06-23):** Completes BMP canonical 8
emission. `derive_lab_values` gains Cl (AG-aware: high-AG keeps Cl
near normal, non-AG diarrhea gives hyperchloremic Cl) and total Ca
(multi-axis: sepsis / CKD / hepatic dysfunction drop it, mild
dehydration lifts). A new `anion_gap_status` axis on
`PhysiologicalState` (orthogonal to AD-57 acid-base 2-axis, does NOT
affect pH/HCO3/pCO2) is set on 20 AG-disturbing disease YAMLs +
2 encounters (viral GE / food poisoning) per textbook AG behaviour.
BMP `min_components` raised 5 → 7 (canonical N − 1 = 8 − 1) with the
5th-percentile floor of panel-order-placed days landing at 7.
**Structural defect discovered + fixed in the same PR:** `inpatient.py`
Pass 1 / `emergency.py` / `outpatient.py` lab loops were drawing
specimen-rejection / hemolysis / technician / noise from the master
RNG. PR #74 had isolated panel children only; individual (non-panel-child)
lab orders remained on the master stream, so any YAML edit toggling a
`{test:"X"}` order between "engine doesn't produce X" → "engine
produces X" silently shuffled unrelated cohorts. Fixed via a new
`simulator/seeding.py:individual_lab_seed(order_id)` mirroring
`panel_specimen_seed`; the three lab loops now build a per-order rng
from it. Integration tests guard the property
(`tests/integration/test_individual_lab_isolation.py`). Data-quality
review (US p=10000 + JP p=5000, seed=42): structural 100 % clean, JP
localization 100 %, 7/8 clinical PASS, HF BNP `[FAIL]` is the same
admit-day-mixing artifact documented in PR #71 (no BNP change in this
PR). See `docs/reviews/2026-06-23-bmp-cl-ca-data-quality-review.md`,
`docs/reviews/2026-06-23-bmp-cl-ca-audit.md`,
`docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md`.

## Architecture Decisions (current)

| Decision | Date | Description |
|---|---|---|
| AD-1 | 2026-04-04 | Two simulation modes: Mode 1 (Patient Record) and Mode 2 (Hospital Operations). Mode 2 is a superset. Design for Mode 2, implement Mode 1 first. |
| AD-2 | 2026-04-04 | Modular folder structure: each module is a self-contained folder with README.md. |
| AD-3 | 2026-04-04 | Population-driven forward simulation: generate catchment population first, simulate life events, hospital visits are consequences of population dynamics. |
| AD-4 | 2026-04-04 | Two-layer population model: Layer 1 (lightweight registry for all persons) and Layer 2 (detailed clinical profile, activated only on hospital visit). |
| AD-5 | 2026-04-04 | Household-based generation: people belong to households, enabling realistic family history, infection transmission, and shared attributes. |
| AD-6 | 2026-04-04 | Referring clinics as context (not simulation targets): generate referral letters and prior records without full GP simulation. |
| AD-7 | 2026-04-04 | LLM as selective amplifier: enhances narratives and clinical reasoning; all numerical/structural data remains rule-based. |
| AD-8 | 2026-04-04 | Three generation modes: `none` (structured only), `template` (rule-based text), `llm` (full LLM enhancement). System fully functional without LLM. |
| AD-9 | 2026-04-04 | Compact context pattern: pre-summarized `LLMClinicalContext` (~300 tokens) instead of full patient record for each LLM call. |
| AD-10 | 2026-04-04 | Batch + cache strategy: LLM called at key narrative points only (4–11 calls per patient), with pattern caching for common scenarios. |
| AD-11 | 2026-04-04 | All LLM calls go through `llm_service` module. No other module may call LLM directly. |
| AD-12 | 2026-04-04 | Default LLM provider: local Ollama (qwen:7b). Cloud APIs (Anthropic) available as optional fallback. Provider abstraction enables addition of other LLM providers. |
| AD-13 | 2026-04-04 | Two LLM task categories: JUDGMENT (always English) and NARRATIVE (target country language). English judgment = better quality + fewer tokens. |
| AD-14 | 2026-04-04 | Three-tier validation: Tier 1 statistical benchmarks (automated), Tier 2 clinical pattern validation (automated+expert), Tier 3 domain expert blind test (human). |
| AD-15 | 2026-04-04 | Output as pluggable adapter system: each format (FHIR R4, CSV, HL7v2, etc.) is a separate adapter implementing OutputAdapter interface. |
| AD-16 | 2026-04-04 | Reproducibility via hierarchical seed management. Each module gets deterministic sub-seed. LLM outputs cached to disk for reproducible runs. |
| AD-17 | 2026-04-04 | Three-stage output: (1) Sim + JUDGMENT LLM → CIF structural (immutable) → (2) CIF + NARRATIVE LLM → narrative layer (replaceable) → (3) structural + narrative → format adapters. |
| AD-18 | 2026-04-04 | Pydantic for YAML configs (schema validation at load). @dataclass for runtime types. |
| AD-19 | 2026-04-04 | Preset + override config: `SimulatorConfig.preset("japan_medium").override({...})` |
| AD-20 | 2026-04-04 | LLM graceful degradation: retry → template fallback → structured-only. Never halt. |
| AD-21 | 2026-04-04 | Vertical slice: v0.1-alpha (1 patient) → v0.1-beta (population) → v0.1 (full). |
| AD-22 | 2026-04-04 | Three-level testing: unit (<30s) → integration (<5min) → e2e golden file (<30min). |
| AD-23 | 2026-04-04 | Async LLM at patient level. Bounded concurrency. Sync fallback available. |
| AD-24 | 2026-04-04 | JUDGMENT and NARRATIVE use independently configurable LLM providers/models. Local + cloud mix supported. |
| AD-25 | 2026-04-04 | CIF is language-neutral. Person names are country-specific at generation time. All other localization at output/Stage 2. |
| AD-26 | 2026-04-04 | Clinical terminology uses official master data only (JLAC10, LOINC, etc.). Never LLM-translated. |
| AD-27 | 2026-04-04 | All locale data (names, terminology, code mapping, formatting) centralized in `clinosim/locale/`. Adding a country = adding YAML files. |
| **AD-28** | 2026-04-06 | **Diagnosis vs ground truth separation**: `ConditionEvent` (hidden truth) vs `ClinicalDiagnosis` (what hospital concludes). Misdiagnosis is first-class. |
| **AD-29** | 2026-04-06 | **Diagnostic accuracy via likelihood ratios**: Bayesian update with per-disease LR_TABLE. Configurable correctness rates. |
| **AD-30** | 2026-04-08 | **Code is the truth**: CIF stores only codes + system keys. Display text is resolved at output time via `clinosim.codes`. No `*_name` fields in CIF types. |
| **AD-31** | 2026-04-08 | **FHIR Bulk Data Export NDJSON**: replaced per-encounter Bundle JSON with HL7 FHIR Bulk Data Access compliant NDJSON (one file per resource type + manifest.json). Globally unique Resource.id within each type. |
| **AD-32** | 2026-04-08 | **Snapshot date semantics**: `--end` is the snapshot date. Inpatients still admitted at snapshot become `Encounter.status="in-progress"` with no `discharge_datetime`. Enables current-state EHR queries. |
| **AD-33** | 2026-04-08 | **English-first code systems**: every entry in `clinosim/codes/data/*.yaml` MUST have an `en` field. Other languages are translation attributes with English fallback. |
| **AD-34** | 2026-04-08 | **Hospital config-driven physical layout**: `available_departments` + `department_rollup` + `wards` + `ward_capacity` in hospital YAML drives staff generation, ward assignment, bed location resources. |
| **AD-35** | 2026-04-08 | **codes module separated from locale**: international code systems (ICD/LOINC/RxNorm/etc.) live in `clinosim/codes/`, NOT under `locale/`. Codes are international standards; translations are attributes. |
| **AD-36** | 2026-04-09 | **FHIR Procedure structural fields via SNOMED CT**: category (surgical/diagnostic/therapeutic), performer.function (surgeon/anaesthetist), recorder, reasonReference, bodySite, location (OR), outcome, complication. Metadata table `_PROCEDURE_METADATA` in procedure engine. |
| **AD-37** | 2026-04-09 | **Three explicit CLI stages**: `generate` (structural CIF) → `narrate` (clinical documents) → `export-fhir` (FHIR R4 NDJSON). Each stage is independently runnable; Stage 2 can be executed remotely (e.g. EC2 for Bedrock) while Stage 1/3 stay local. |
| **AD-38** | 2026-04-09 | **Clinical documents as FHIR DocumentReference (Tier A+B)**: Discharge Summary (LOINC 18842-5), Death Note (69730-0), Operative Note (11504-8), Admission H&P (34117-2), Procedure Note (28570-0). 5 document types, ~374 documents per 5000-population run. Base64 text/plain attachment with sha1 hash and size. |
| **AD-39** | 2026-04-09 | **LLM provider plugin registry**: `providers/` subpackage with `LLMProvider` Protocol. Registry maps config keys (`ollama`, `bedrock`, `mock`, `local`) to builder callables. `factory.build_from_config_file()` wires providers + cache + registry from YAML. Bedrock uses boto3 lazy import. |
| **AD-40** | 2026-04-09 | **Prompt templates as per-language YAML**: `clinosim/modules/llm_service/prompts/<lang>/<task>.yaml` with `system`, `user_template`, `max_tokens`, `temperature`, `version`. Rendered via `string.Template` (stdlib, zero deps). Language fallback to English (mirrors codes module). |
| **AD-41** | 2026-04-09 | **SHA256 disk cache for LLM responses**: `PromptCache` keys by `SHA256(system ‖ user ‖ model)`. Enables reproducible re-runs, partial re-run recovery, and cost control for Bedrock. Cache stats in `cost_report()`. |
| **AD-42** | 2026-04-13 | **Code-side unit conversion for Japanese locale**: CRP mg/L→mg/dL conversion happens in `hospital_course_extractor` and `document_generator` (not in LLM prompt). `format_lab_trends(language=)` and `_initial_labs(language=)` apply locale-specific conversion factors. |
| **AD-43** | 2026-04-13 | **Japanese narrative prompt quality rules**: All ja prompts include mandatory 「医師」suffix for staff names. Markdown forbidden — use 【】 section headers, ■ subheaders, ・ bullets. |
| **AD-44** | 2026-04-15 | **Enrichment is language-neutral, display at output time**: A/B test confirmed LLM translates drug/procedure names reliably. Enrichment passes English text to LLM; only 2 code-side exceptions: (1) `code_lookup(system, code, lang)` for official short-form diagnosis names, (2) CRP unit conversion (math). |
| **AD-45** | 2026-04-15 | **Occupation field on Patient/PersonRecord**: 12 categories (manufacturing, construction, agriculture, healthcare, service, office, transportation, education, homemaker, student, retired, unemployed). Drives work-related injury incidence via `occupation_risk_multipliers` in demographics.yaml. FHIR Observation (LOINC 11341-5, social-history). |
| **AD-46** | 2026-04-16 | **Multilingual FHIR coding**: Condition and Procedure emit dual coding entries (primary language + interop language). `_build_diagnosis_codeable_concept()` resolves from both `icd-10` and `icd-10-cm` with cross-system fallback. Never emits `display==code`. |
| **AD-47** | 2026-04-16 | **FHIR Observation referenceRange/interpretation consistency**: Both must be present and consistent per FHIR R5 Note 5. Lab interpretation recomputed from value vs referenceRange (not CIF flag alone). Vital signs include normal + critical (panic) reference ranges as separate entries. |
| **AD-48** | 2026-04-16 | **Procedure display via code dictionary (AD-30 strict)**: `procedure_name` removed from ProcedureRecord — display resolved at output time via `code_lookup("k-codes"|"cpt", code, lang)`. Both `procedure_code_jp` and `procedure_code_us` stored in CIF for multilingual FHIR output. |
| **AD-49** | 2026-04-18 | **Condition code.text with clinical abbreviations**: `_CONDITION_SHORT_NAME` maps ICD base codes to search-friendly short names (COPD, CHF, CKD, DM, AF, etc.) in both EN and JA. `coding[].display` keeps official ICD name. |
| **AD-50** | 2026-04-18 | **Medication protocol prefix stripping**: `_strip_protocol_prefix()` separates category prefixes (DVT_prophylaxis:, antipyretic:, etc.) from drug name in `medicationCodeableConcept.text`. Drug name only in text, protocol context in dosageInstruction. |
| **AD-51** | 2026-06-23 | **Panel-children RNG isolation (one specimen, one RNG)**: every lab `Order` produced by panel expansion (`_run_daily_loop`'s Pass 2) draws specimen-rejection / hemolysis / staff-assignment / result-timing from a per-parent sub-RNG seeded by `panel_specimen_seed(parent_order_id)` (in `clinosim/simulator/seeding.py`), not from the patient-scoped master RNG. Two consequences: (a) editing `lab_panels.yaml` (e.g. registering CBC or BMP) cannot cascade into unrelated patients' cohorts — the master stream stays exactly the same length regardless of which panels are registered (AD-16 compliance). (b) Specimen rejection becomes per-specimen (one parent → all-or-nothing on children) rather than per-analyte, which is clinically correct because a panel order is one tube. PR #74. Tested by `tests/integration/test_panel_expansion_cbc_bmp.py::test_panel_children_cancellation_is_per_specimen` and `tests/unit/test_seeding.py::TestPanelSpecimenSeed::test_formula_is_pinned`. |

## Implementation Status

### v0.1-alpha — "Hello World" ✅ COMPLETE

All 12 tasks complete. 1 pneumonia patient end-to-end.

### v0.1-beta — Population + archetypes + multi-country ✅ COMPLETE

| # | Task | Module | Status |
|---|---|---|---|
| 1 | Population generation (households, Layer 1) | `population` | ✅ |
| 2 | Life event engine (monthly loop, disease onset) | `population` | ✅ |
| 3 | Care-seeking decision model | `population` | ✅ |
| 4 | Layer 1→2 activation / deactivation | `patient` | ✅ |
| 5 | Staff roster + assignment (ward-aware) | `staff` | ✅ |
| 6 | All 6 archetypes | `disease`, `clinical_course` | ✅ |
| 7 | Treatment selection + change logic | `clinical_course` | ✅ |
| 8 | Bayesian differential diagnosis | `diagnosis` | ✅ |
| 9 | LLM service — template mode | `llm_service` | ✅ |
| 10 | CIF → FHIR R4 adapter | `output` | ✅ (Bulk Data NDJSON) |
| 11 | CIF → CSV adapter | `output` | ✅ |
| 12 | Multiple patients (10–100,000) | `simulator` | ✅ (tested up to 30k) |

### v0.1 — Foundation hardening ✅ COMPLETE

| # | Task | Module | Status |
|---|---|---|---|
| 1 | clinosim.codes module (EN-first) | `codes` | ✅ |
| 2 | FHIR R4 Bulk Data NDJSON export | `output` | ✅ |
| 3 | Snapshot date semantics | `simulator` | ✅ |
| 4 | Hospital config-driven layout | `facility`, `staff` | ✅ |
| 5 | Bed Location resources (FHIR) | `output` | ✅ |
| 6 | PractitionerRole.location assignment | `staff`, `output` | ✅ |
| 7 | All Resource.id globally unique | `output` | ✅ (0 violations) |
| 8 | UCUM-compliant units | `observation`, `output` | ✅ |
| 9 | NEWS2-compatible vitals (AVPU + O2) | `physiology`, `output` | ✅ |
| 10 | 28 diseases + 44 ED/outpatient conditions | `disease`, `encounter` | ✅ |
| 11 | Module READMEs (all 17 modules) | docs | ✅ |

### Milestone 1 — Clinical documents + pluggable LLM ✅ COMPLETE (2026-04-09)

| # | Task | Module | Status |
|---|---|---|---|
| 1 | FHIR Procedure structural fields (SNOMED) | `procedure`, `output` | ✅ (AD-36) |
| 2 | `snomed-ct.yaml` code system | `codes` | ✅ |
| 3 | Operating room Location resources | `output` | ✅ |
| 4 | LLM provider subpackage (base, ollama, mock, bedrock) | `llm_service` | ✅ (AD-39) |
| 5 | Provider registry + factory (YAML → LLMService) | `llm_service` | ✅ |
| 6 | Prompt templates as per-language YAML | `llm_service` | ✅ (AD-40) |
| 7 | PromptCache (SHA256 disk cache) | `llm_service` | ✅ (AD-41) |
| 8 | `ClinicalDocument` type + CIF extension | `types`, `output` | ✅ |
| 9 | `hospital_course_extractor` (deterministic facts) | `output` | ✅ |
| 10 | `document_generator` (narrative CIF writer) | `output` | ✅ |
| 11 | FHIR `DocumentReference` builder | `output` | ✅ (AD-38) |
| 12 | `clinosim narrate` / `export-fhir` CLI | `simulator` | ✅ (AD-37) |
| 13 | `llm_service.bedrock.yaml` config | `config` | ✅ |
| 14 | 6 LOINC codes for document types | `codes` | ✅ |
| 15 | Unit tests (32 new, 141 total) | tests | ✅ |
| 16 | Tier A+B English prompts (5 YAML files) | prompts | ✅ |

### Milestone 2 — Simulation fixes + Bedrock full run ✅ COMPLETE (2026-04-10)

| # | Task | Module | Status |
|---|---|---|---|
| 1 | EC2 Bedrock 5-type validation (4 rounds, 12 diseases) | infra, `output` | ✅ |
| 2 | YAML-driven `medication_holds` in disease protocols | `disease`, `simulator` | ✅ (hemorrhagic_stroke, pancreatitis, DKA, sepsis, AKI) |
| 3 | Surgery procedure names from disease YAML | `procedure`, `disease` | ✅ (cholecystitis→CPT47562, appendicitis→CPT44970, trauma→CPT49000) |
| 4 | Hip fracture discharge prescription | `disease` | ✅ (oxycodone + enoxaparin + Ca/VitD) |
| 5 | DC Rx Cr-based contraindication check | `simulator` | ✅ (final_renal_function < 0.3 gates nephrotoxic drugs) |
| 6 | BPH sex filter (demographics.yaml) | `population` | ✅ (sex: M field + engine filter) |
| 7 | LLM hallucination prevention (DC Rx prompt) | `llm_service` | ✅ (prompt rule: only listed meds) |
| 8 | Nurse assignment per department (was IM-only) | `simulator` | ✅ (MAR + vitals use patient's dept nurse) |
| 9 | Staff ID → name in narrative prompts | `output` | ✅ (DR-XX-NNN → Dr. Name) |
| 10 | Country-specific recommended_population | `config` | ✅ (US: 40K, JP: 5K) |
| 11 | .gitignore fix (clinosim/modules/output/ was excluded) | repo | ✅ |
| 12 | EC2 Bedrock full 421-document run | infra | ✅ |
| 13 | FHIR Bulk Data with DocumentReference → iris-ai | `output` | ✅ |

### v0.2 — Simulation realism + JP/EN documents + Occupational injuries (CURRENT)

| # | Task | Module | Status |
|---|---|---|---|
| 1 | Severity-based lab frequency modulation | `simulator` | ✅ severe 1.3x, mild 0.6x |
| 2 | Trauma Hgb recovery model / discharge gate | `physiology`, `simulator` | ✅ |
| 3 | HF exacerbation: IV diuretic not in MAR | `simulator`, `order` | ✅ |
| 4 | narrate progress display (patient N/M) | `output` | ✅ |
| 5 | Treatment escalation from disease YAML | `simulator` | ✅ Day 3 escalation when inflammation > 0.3 |
| 6 | Treatment change detection in extractor | `output` | ✅ |
| 7 | JP Bedrock full run (5K pop, 499 docs) | infra | ✅ |
| 8 | Japanese prompts (`prompts/ja/*.yaml`) | `llm_service` | ✅ 5 types, 【】format, 「医師」suffix |
| 9 | Template fallbacks for Tier A+B | `llm_service` | ✅ |
| 10 | Diurnal lab variation | `physiology` | ✅ |
| 11 | Critical patient vitals q2h | `simulator` | ✅ |
| 12 | Consistency validator Tier 2 (8 checks) | `validator` | ✅ 0 errors |
| 13 | AKI complication → metformin cancel | `simulator` | ✅ |
| 14 | CRP mg/L→mg/dL code-side conversion | `output` | ✅ (AD-42) |
| 15 | Staff name 「医師」 suffix | `llm_service` | ✅ (AD-43) |
| 16 | Chronic med base code fallback | `simulator` | ✅ |
| 17 | Empty medication string filter | `simulator`, `patient` | ✅ |
| 18 | JP FHIR full localization | `output` | ✅ (display/text/name 全て JP) |
| 19 | A/B test: enrichment localization strategy | `output` | ✅ (AD-44) English enrichment + LLM translates |
| 20 | Enrichment language-neutral refactor | `output` | ✅ (AD-44) code_lookup + CRP のみ locale依存 |
| 21 | Occupation field (PersonRecord + PatientProfile) | `population`, `patient` | ✅ (AD-45) 12 categories |
| 22 | Work-related injuries (4 inpatient + 2 ED) | `disease`, `encounter` | ✅ (AD-45) occupation_risk_multipliers |
| 23 | Multilingual FHIR coding (Condition + Procedure) | `output` | ✅ (AD-46) primary + interop dual coding |
| 24 | FHIR Observation referenceRange/interpretation | `output` | ✅ (AD-47) 0 inconsistencies |
| 25 | procedure_name removed from CIF (AD-30 strict) | `procedure`, `output` | ✅ (AD-48) code_lookup only |
| 26 | JP drug name dictionary (120+ entries) | `locale` | ✅ drug_names_ja.yaml |
| 27 | JP allergen/procedure/dosage term localization | `output` | ✅ FHIR adapter |
| 28 | Emergency contact real person names | `patient` | ✅ (佐伯 紬, not 佐伯家) |
| 29 | Condition code.text abbreviations (COPD, CHF, CKD) | `output` | ✅ (AD-49) |
| 30 | Medication protocol prefix stripping | `output` | ✅ (AD-50) |
| 31 | US 40K Bedrock full run (3,344 EN docs) | infra | ✅ |
| 32 | JP recommended_population 5K → 10K | `config` | ✅ |
| 33 | Anthropic direct provider (non-Bedrock) | `llm_service` | Open |
| 34 | OpenAI-compatible provider (LiteLLM / vLLM) | `llm_service` | Open |
| 35 | Population demographics externalization (US) — sex_ratio, physiology, lifestyle, comorbidity_correlations, lifestyle_risk_multipliers, insurance_distribution, race_distribution, occupation age thresholds | `population`, `patient`, `locale` | ✅ US complete (2026-04-20) |
| 36 | Population demographics externalization (JP) — apply same sections to `jp/demographics.yaml` | `locale` | 🔲 Pending user approval |
| 37 | CIF smoke run with US demographics externalization — generate 500-patient CIF and verify BMI/smoking/insurance/race fields are realistic | `simulator`, `population` | 🔲 TODO |

## Open Design Questions

### High Priority

| # | Question | Module | Status |
|---|---|---|---|
| 1 | State variable granularity for severe sepsis / MOF | `physiology` | Open (v0.2: may need lactate, MAP, urine output as separate variables) |
| 2 | Pediatric disease modules (currently adult only) | `disease`, `physiology` | Open (v0.2) |
| 3 | OB/GYN encounters (pregnancy, delivery, NICU) | `encounter`, `disease` | Open (v0.2) |
| 4 | Outpatient chronic disease management depth | `encounter`, `population` | Partial (chronic_followup.yaml exists but limited) |
| 5 | LLM judgment phase wiring (currently template only) | `llm_service`, `diagnosis` | Open |
| 6 | Realistic 80% bed occupancy at default population | `facility`, `population` | ✅ Fixed — US 40K / JP 5K recommended_population (was 60K) |
| 7 | Code coverage expansion: more LOINC/RxNorm/CPT codes | `codes` | Continuous (349 ICD-10-CM, 306 ICD-10, 83 LOINC, 68 RxNorm, 31 CPT currently) |

### Medium Priority

| # | Question | Module | Status |
|---|---|---|---|
| 8 | SNOMED CT integration (clinical findings) | `codes` | Open |
| 9 | Discrete-event simulation engine (Mode 2) | `simulator` | Open (planned for v1.0) |
| 10 | Holiday calendar per country (admission/discharge patterns) | `healthcare_system`, `facility` | Open |
| 11 | Diurnal variation in lab values | `observation` | ✅ Implemented (glucose postprandial, WBC circadian) |
| 12 | Episode-of-care linking (multi-encounter problem tracking) | `encounter` | Open |
| 13 | Consult workflow (specialty consultation requests) | `encounter`, `staff` | Open |
| 14 | Diagnostic drift over hospital stay | `diagnosis` | Open |
| 15 | Anesthesia record detail (intra-op vitals, drugs) | `procedure` | Open |

### Low Priority

| # | Question | Module | Status |
|---|---|---|---|
| 16 | Medical cost / claims data (DPC/DRG codes) | `output` | Open |
| 17 | End-of-life model (DNR/DNAR, palliative care) | `clinical_course` | Open |
| 18 | Teaching hospital resident rotation | `staff`, `facility` | Open |
| 19 | Mental health encounters (psychiatric admission) | `disease`, `encounter` | Open |
| 20 | Equipment throughput real-world validation | `facility` | Open |
| 21 | Seasonal incidence curves per disease per country | `disease` | Partial (basic seasonal mod exists) |
| 22 | Screening program participation rates | `population` | Open |
| 23 | Narrative/discharge text referencing HbA1c + glycemic control | `enrichment`, `output` | Open (HbA1c now modeled via `glycemic_control` axis; narratives don't yet mention it) |
| 24 | Non-diabetic HbA1c patient spread + prediabetes cohort | `physiology`, `population` | Open (non-DM HbA1c currently ~5.1–5.3, low-variance) |
| 25 | Remove dead `ChronicCondition.controlled` field (superseded by `glycemic_control`) | `types`, `patient` | Open (kept to preserve RNG stream; clean up in a determinism-aware pass) |

## Roadmap

### v0.2 — Clinical reasoning + LLM integration (CURRENT)

- [x] Clinical document pipeline (Tier A+B, 5 LOINC-coded types) ← Milestone 1
- [x] Pluggable LLM providers (Ollama / Bedrock / Mock) ← Milestone 1
- [x] Prompt templates as YAML (per-language) ← Milestone 1
- [x] FHIR DocumentReference output ← Milestone 1
- [x] SHA256 prompt cache ← Milestone 1
- [x] EC2 + Bedrock production run (421 documents, Claude Sonnet 4) ← Milestone 2
- [x] 4-round clinical review (35 documents, 12 disease patterns) ← Milestone 2
- [x] 8 simulation fixes (YAML medication_holds, surgery names, Cr check, sex filter, nurse dept, staff names) ← Milestone 2
- [x] Country-specific recommended_population (US:40K, JP:5K) ← Milestone 2
- [x] Japanese prompts with clinician review (5 types, 2 rounds, 8+8 patients) ← Milestone 3
- [x] JP FHIR localization (Location names, Encounter type, dosage, marital status) ← Milestone 3
- [x] CRP unit conversion (mg/L→mg/dL) at code level for ja locale (AD-42)
- [x] Staff name suffix 「医師」 consistency in ja prompts (AD-43)
- [x] Chronic medication base code fallback (E11→E11.9 lookup)
- [x] Empty medication string filter (drug_name key + empty filter)
- [ ] LLM JUDGMENT phase wiring (diagnostic reasoning, treatment rationale)
- [ ] Validator Pass 2 (LLM consistency review)
- [ ] **[TODO] CIF smoke run: US demographics externalization end-to-end verify** — generate 500-patient US CIF, check PatientProfile.bmi/smoking_status/alcohol_use/insurance_type/race/ethnicity are populated realistically
- [ ] **[TODO] JP demographics externalization** — add sex_ratio, physiology, lifestyle_distribution, lifestyle_risk_multipliers, comorbidity_correlations, insurance_distribution, occupation age_thresholds to `jp/demographics.yaml` (pending user approval)
- [ ] Diagnostic drift over hospital stay
- [ ] Pediatric disease modules (start with viral URI, asthma, gastroenteritis)
- [ ] OB/GYN module (pregnancy, delivery, NICU)
- [ ] Performance optimization (async LLM, parallel patient simulation)

### v0.3 — Operational realism + LLM intelligence

- [ ] Resident identifier & insurance numbering — `modules/identity/` (AD-54)
  - [x] P1: module skeleton (base/registry/generators/providers) + JP numbering (employer-level 記号, 社保/国保/後期高齢, 枝番) + representative payer Organizations + snapshot single enrollment + FHIR `Coverage` (JP Core) + sensitive-field chokepoint (`national_id` not emitted) — 22 unit + 5 e2e tests, verified end-to-end
  - [ ] P2: period-bounded enrollment history + deterministic 75-yr → 後期高齢者 transition + encounters reference time-valid `Coverage.period`
  - [ ] P3: light employment transitions (就職/退職/転職) + マイナンバーカード取得日 / マイナ保険証登録日 + qualification verification method (紙/online)
  - [ ] P4: US `_sample_insurance` migration into `providers/us.py` (behavior-compat tests) + docs/ADR finalize
  - [x] Verify JP Core `Coverage` profile (記号/番号/枝番 extensions, subscriberId/dependent, payor namingsystem) — recorded in `locale/jp/identity.yaml:fhir_coverage` + DESIGN §6.9
  - [x] Realism+quality pass: occupation-driven 社保/国保 (emergent <75 ≈ 73:27, MHLW), insurance_type unified with identity.category, マイナ保険証 marginal preserved, payor Organization real names + `organization-type#pay`, Coverage.type text + relationship
  - [ ] Verify (裏取り) remaining: representative 保険者番号 vs official registries · 75-yr transition rules · 保険者番号 検証番号 algorithm · 個人番号 check-digit formula (replace `# TODO: verify` placeholders) · 健保組合 dual-income households (each earner own 社保, Phase 2/3)
- [ ] LLM JUDGMENT phase wiring (diagnostic reasoning, treatment decisions)
- [ ] Progress Note (Tier C, opt-in — daily SOAP notes via LLM)
- [ ] Validator Pass 2 (LLM consistency review)
- [ ] Discrete-event simulation engine (Mode 2)
- [ ] Resource contention (OR scheduling, ICU bed allocation)
- [ ] Multi-day treatment scheduling
- [ ] Consult workflow
- [ ] Episode-of-care multi-encounter tracking
- [ ] Performance: 100k+ patients, parallel sim

### Phase 0 — Extensibility foundation (AD-56, do before the enrichment roadmap)

> Enabling refactors so each AD-55 item is "register a builder/enricher" instead of editing
> central monoliths. Gate with existing golden/e2e + determinism (AD-16).

- [ ] **① FHIR resource-builder registry** — replace the hand-appended `_build_bundle()`
  (`output/fhir_r4_adapter.py`) with a registry of `(record, ctx) -> list[resource]` builders;
  each declares dedup behaviour (patient-level vs per-encounter). Core loops & emits. **Highest leverage.**
- [ ] **② Simulator enricher registry** — replace inlined passes in `run_beta()`
  (`simulator/engine.py`) with enrichers registered as `name`/`order`/`enabled(config)`/`run(...)`;
  iterate in fixed order (determinism). Migrate `assign_identities` to it as the first consumer.
- [ ] **④ CIF extensions slot** — add `CIFPatientRecord.extensions: dict[str, Any]`
  (`types/output.py`). Base = typed fields; Modules write `extensions[<module>]`, never edit core type.
- [ ] **③ Config module-enablement map** — `SimulatorConfig.modules: dict[str, bool]` +
  `module_enabled()` helper (`types/config.py`); keep `jp_insurance_numbers` as back-compat alias.
- [ ] **⑤ (with microbiology)** externalize `observation` lab catalog (CV/precision/units) to YAML.
- Deferred: ⑥ CSV adapter registry (low leverage — new table ≈ 3 lines).

### AD-57 — Unify observation (lab + vital) generation across venues

> Today lab/vital values come from **3 divergent paths**: inpatient = physiology
> `derive_lab_values(state)` (state/comorbidity-aware); ED (`emergency.py`) + outpatient
> (`outpatient.py`) = hardcoded `baseline_values` dicts + a dangerous `default 100`
> fallback, ignoring patient comorbidities. This caused the troponin canonicalization to
> be applied in 3 places and risks venue inconsistency (e.g. a CKD patient's ED creatinine
> reads normal). Unify into one generation service.

- [x] **Phase 1 — ED/outpatient labs → physiology.** `emergency.py` + `outpatient.py` now
  build a baseline `PhysiologicalState` from the patient's chronic conditions
  (`initialize_state`) and derive true values with `derive_lab_values` (comorbidity-aware:
  CKD → high Cr/low eGFR, verified). Dangerous `default 100` replaced with a normal fallback.
  `baseline_values` retained only for analytes physiology doesn't model. Same RNG draw
  count → determinism preserved; integration/e2e green.
- [ ] Extract a single `generate_observations(...)` wrapper so the 3 venues share one
  call (currently they share the physiology functions but duplicate the boilerplate).
- [x] **Encounter scenarios carry acute physiology.** ED encounter YAMLs gained an optional
  `initial_state_impact` (per severity, same schema as disease protocols) + `acid_base_type`;
  `emergency.py` applies it via `apply_disease_onset` after `initialize_state`, so BOTH labs
  and vitals reflect the acute illness, not just comorbidity baseline. Populated for the
  conditions with a clear physiological signature: infections (UTI/viral URI → WBC/CRP/temp),
  dehydration (gastroenteritis/food poisoning → volume↓ → BUN↑, BP↓/HR↑), hyperventilation
  (asthma/panic → respiratory alkalosis), local→systemic (animal bite/minor burn).
  Trivial presentations (screening, suture removal) carry no impact (no-op). Audit (pop 30k):
  UTI WBC median 10,177 (vs ~7,500 baseline), gastroenteritis dehydration, panic pCO2 < 38.
  Data-driven (user principle: lab changes from scenario/profile). 4 unit tests.
- [x] **ABG panel expansion + pO2 done.** `observation/reference_data/lab_panels.yaml`
  (data-driven) maps `ABG` → pH/pCO2/pO2/HCO3; panel orders are expanded into component
  lab orders (parent marked resulted) so each resolves via the scalar path. physiology
  derives pO2 (inflammation-proxied hypoxemia). LOINC/JLAC10 codes added. Respiratory
  cohort now gets blood-gas results (was none) — verified COPD pH/pCO2/pO2/HCO3 resolve.
- [x] **Unify vitals generation.** ED (`emergency.py`) + outpatient (`outpatient.py`) now
  derive vitals from the comorbidity-adjusted `PhysiologicalState` via the same path as
  inpatient. New shared helper `physiology.derive_observed_vitals(state, baseline, ts, rng)`
  = `derive_vital_signs` + measurement noise; inpatient `_make_raw` delegates to it (output
  unchanged — identical RNG draws). ED temp/SpO2/HR now track physiology (e.g. febrile up to
  39.1 °C, hypoxia to 87 %, shock SBP to 66) instead of a fixed normal template; outpatient
  keeps its measured-subset (`fields`) logic. Determinism preserved (same draw count/order);
  unit/integration/e2e green. **Acute-presentation injection** (folding ED scenario severity
  into the state so labs+vitals reflect the acute illness, not just comorbidity baseline)
  deferred — see the `initial_state_impact` item above.
- [x] FHIR code-mapping cleanup (from CIF/FHIR eval): US LOINC for lipids/TSH/ESR
  (+ loinc displays), outpatient lipid/ESR baselines (was 1.0 garbage), ECG/non-analyte
  guard in ED/outpatient (was fabricated empty-code lab). US empty-code labs 328→0.
- [x] **JP JLAC10 codes verified & corrected.** Added Troponin_I (5C094), CK_MB (3B015),
  LDL (3F077), HDL (3F070), TG (3F015), TC (3F050), TSH (4A055), ESR (2Z010) — all verified
  against the official **JSLM JLAC10 master v137 (2026-06)** (`jslm.org/committees/code/`),
  lipids cross-checked vs jpfhir.jp JP-CLINS/eCheckup. **Audit also exposed ~13 pre-existing
  fabricated/mismapped codes** in `jlac10.yaml` (Hb/Hct/BUN/Na/K/Cl/Ca/T_Bil/LDH/PCT/BNP/
  Lactate were off, blood gas pH/pCO2/pO2/HCO3 pointed at the 6A0xx **microbiology** range) —
  all corrected to the master codes. Source cited in both files; integrity guard test added
  (`test_codes_jlac10.py`, 28 cases). JP FHIR audit: 31 correct JLAC10 codes + 和名 emitted.
- [x] **US LOINC verified.** All 38 US-mapped LOINC codes confirmed vs NLM Clinical Tables
  LOINC API (no fabrication). Fixed 4 duplicate YAML keys + normalized verbose display
  (PR #10). Cross-system dup-key guard added (`test_codes_integrity.py`).
- [x] **Authoritative-source comments** added to every code-data file (icd-10-cm, icd-10,
  rxnorm, cpt, k-codes, yj + earlier jlac10/loinc/snomed) and locale code_mapping files.
- [x] **ICD diagnosis-code review (2026-06 finding) — FIXED.** `code_mapping_diagnosis.yaml`
  was dead config (`load_code_mapping` never called for "diagnosis") so US emitted
  non-billable 3-char category codes (I50, I21, ...) and WHO-only codes (F00). Now wired into
  the FHIR adapter (`_build_conditions`, both primary + chronic dx via `_map_diagnosis_code`).
  US translates every internal chronic/history base code + non-billable primary to a billable
  ICD-10-CM leaf (chronic→unspecified leaf; past-acute-as-chronic→"history of/old" e.g.
  I21→I25.2; primary specificity/7th-char e.g. R05→R05.9, S72.00→S72.009A, T07→T07.XXXA).
  All targets verified vs NLM ICD-10-CM API (no fabrication) + added to `icd-10-cm.yaml`.
  Audit (US 10k): 91/91 distinct Condition codes billable, 0 non-billable.
- [x] **Used-but-missing diagnosis codes — FIXED (PR #19).** Disease/encounter scenarios
  referenced 19 ICD codes absent from code-data (display fell back to approximate prefix
  match). Registered after NLM/WHO verification; fixed miscode K57.11 (small-intestine) →
  K57.31 (large-intestine diverticular bleeding). Coverage invariant added
  (`test_diagnosis_code_coverage.py`).
- [x] **JP diagnosis output → true WHO ICD-10 granularity — FIXED (PR #20).** JP previously
  emitted ICD-10-CM-granularity codes (7th-char `S06.0X0A`, 5-char `A41.01`, `Z00.00`) under
  the WHO `icd-10` system URI, resolving only via cm-fallback. `code_mapping_diagnosis/jp.yaml`
  now folds every internal code to WHO 3-4 char (+110 WHO codes verified vs icd.who.int/
  browse10/2019; R65 axis differs in WHO so severe-sepsis R65.20/.21→R65.1, SIRS R65.10→R65.2).
  `icd-10.yaml` is now 100% WHO format. Structural guards: `test_jp_never_emits_cm_granular_code`,
  `test_icd10_who_file_has_no_cm_granular_codes`. Generation: 0 CM-granular codes emitted.
- [x] **engine.py differential codes registered — FIXED (PR #21).** The `DIFFERENTIALS` table +
  LR tuples in `modules/diagnosis/engine.py` are a third emittable Condition-code source; ~65
  codes were unregistered (prefix-fallback). Added after NLM/WHO verification (+58 CM, +58 WHO,
  +35 us_map, +2 jp_map incl. K56.9→K56.7). Coverage test now ranges over `ALL_EMITTABLE`
  (disease + encounter + engine.py). Generation (US 51k + JP 28k Conditions): 0 prefix-fallback.
- [ ] **engine.py diagnosis tables → YAML (data-driven, follow-up #2).** `DIFFERENTIALS`,
  `LR_TABLE`, `DIAGNOSIS_PROGRESSION` + display `name`s are hard-coded in Python (violates the
  YAML-driven AD). Move to `reference_data` YAML and resolve `name` via `clinosim.codes` lookup.
  Output-logic adjacent → must preserve determinism/golden output.
- [ ] **RxNorm / CPT / SNOMED / YJ / K-code** — authoritative-source comments added but codes
  not yet machine-verified (RxNorm verifiable via NLM RxNav API; others need licensed masters).
- [ ] **ECG as a proper diagnostic** (currently skipped from labs; model as Procedure/
  diagnostic order so the "ECG was done" fact is recorded).
- [x] **Acid-base model** (eval finding): pH/HCO3/pCO2 derived from a single `ph_status`
  axis couldn't distinguish metabolic vs respiratory acidosis or show correct compensation.
  **Fixed** with a two-axis model: `ph_status` (disturbance magnitude) + new
  `PhysiologicalState.respiratory_fraction` (0 = metabolic → HCO3, 1 = respiratory → pCO2).
  Blood gas now follows Henderson-Hasselbalch with partial compensation (Winter's for
  metabolic acidosis → Kussmaul low pCO2; ~0.35 mEq/mmHg renal compensation for respiratory
  acidosis → raised HCO3). Axis is **scenario/profile-driven** (same pattern as
  `causes_myocardial_injury`): disease `acid_base_type` field (`metabolic` default,
  `respiratory` for COPD/asthma) + chronic J44/J45 in `initialize_state`. Audited (pop 30k):
  DKA pCO2 34.8 (Kussmaul ✓), COPD HCO3 26.7 / pCO2 47.5 (compensation ✓). 6 unit tests.
- [ ] ED non-cardiac troponin now reflects cardiac comorbidity (median ~0.095, can exceed
  the 0.04 cutoff) — decide comorbidity-baseline vs rule-out-negative semantics.

### EHR data enrichment roadmap (AD-55 — Base vs Module)

> Benchmarked vs Synthea / USCDI v5 / MIMIC-IV. **Imaging/modality data out of scope**
> (CT/MRI/X-ray/US, echo, ECG tracings, endoscopy, spirometry, pathology) — see DESIGN §6.10.
> **Base** = always-on, extends core (`types`/`population`/`observation`/`simulator`/`output`).
> **Module** = opt-in, **one theme per module** (same pattern as `identity`).
> Cross-cutting for all: types in `types/`, module-independence (deps in README),
> deterministic sub-seed, FHIR built in `output` reading CIF (modules stay output-agnostic).

#### Base — near-essential (always generated; extends existing core)

- [x] **Microbiology & susceptibility** — `observation/microbiology.py` + `types/microbiology.py` + `observation/reference_data/microbiology.yaml` (all codes data-driven). Emits FHIR `DiagnosticReport` + `Specimen` + `Observation` via the AD-56 builder registry; CSV `microbiology.csv`. Sepsis/pneumonia/UTI/cellulitis/aspiration cohort. Encounter-scoped sub-seed (main stream unperturbed). 10 unit tests. `# TODO: verify` SNOMED/LOINC codes + antibiogram rates vs authoritative sources.
- [~] **Blood-based markers**: cardiac troponin + CK-MB **done** — `physiology` derives Troponin_I/CK_MB (ACS flag `causes_myocardial_injury` on the disease scenario → MI-level; other cardiac dysfunction → mild type-2; CKD confounder via renal; sex-specific cutoff). Lab order-name aliases (`observation/reference_data/lab_aliases.yaml`) canonicalize stat/serial/variant orders across inpatient/ED/outpatient; FHIR uses canonical name → LOINC resolves. Lactate already worked. **ABG panel (pH/pCO2/pO2/HCO3 from one "ABG" order) + pO2 deferred** — needs panel-expansion (one order → multiple results), tracked under AD-57.
  - [x] JP JLAC10 codes for Troponin_I (5C094) / CK_MB (3B015) verified vs JSLM master v137.
    Serial-troponin intra-day trend still open.
- [ ] **`DiagnosticReport` grouping** — `output` adapter (+ `types/output`): group lab Observations into panels (CBC/BMP/LFT). Structural fidelity, no new clinical data.
- [x] **Nursing flowsheets** — `observation/nursing.py` (純粋関数 NEWS2/GCS/Braden/Morse) + `nursing_enricher.py` (AD-56 Base post_records, 専用 hashlib サブシード → メインストリーム不変)。CIF: `VitalSignRecord.news2_score`/`gcs_score` + `NursingRiskAssessment` (Braden 6 サブスケール + Morse)。FHIR `category=survey` Observation 7 件 (NLM 照合済み LOINC: GCS 9269-2, Braden 38227-5, Morse 59460-6, Barthel 96761-2, 輸液 9108-2/9192-6/9262-7; NEWS2 は権威 LOINC なし → `code.text` のみ)。CSV: `nursing_risk.csv` 新規 + `vital_signs.csv` に NEWS2/GCS 列追加。thresholds はすべて `reference_data/nursing_scores.yaml` データ駆動。
- [x] **Immunization history** — `modules/immunization/engine.py` (純粋関数 `load_schedule`/`generate_immunizations`) + `enricher.py` (AD-56 Base post_records, 専用 hashlib サブシード 0x494D → メインストリーム不変, AD-16)。CVX コード 10 件を CDC IIS で照合済み (`codes/data/cvx.yaml`、FHIR URI `http://hl7.org/fhir/sid/cvx`)。US adult schedule 5 ワクチン (Influenza/COVID-19/PPSV23/Tdap/Zoster-RZV) + JP 3 ワクチン (Influenza/COVID-19/PPSV23)。各ワクチンは `available_from` + `coverage_by_age_sex` (年齢帯×性別 接種率) 付き。AS-OF = snapshot_date または最新入院日 (AD-32)。CIF: `ImmunizationRecord` (vaccine_cvx/occurrence_date/status/primary_source)。FHIR R4 `Immunization` (US英語/JP日本語 display)。CSV: `immunizations.csv`。接種率出典: CDC FluVaxView/MMWR (US), MHLW 接種率統計 (JP) — 概数モデリングパラメータ。
- [x] **Family history** — `modules/family_history/` (engine 純粋関数 + `reference_data/family_history.yaml` 遺伝倍率/続柄) + `locale/{us,jp}/family_history_prevalence.yaml` (国別有病率)。AD-56 post_records enricher (person_id サブシード 0x4648 → メインストリーム不変, AD-16)。本人 chronic_conditions × locale 有病率 × 遺伝倍率で第1度近親 (母 MTH/父 FTH/兄弟姉妹 NSIB) の疾患を合成。心血管代謝系 (E11/I10/I25/I63/I64/E78) + 主要がん (C50/C18/C34/C61、性別制限)。FHIR `FamilyMemberHistory` (v3-RoleCode + ICD)、CSV `family_history.csv`。`CIFPatientRecord.family_history` typed field。PR #63。
- [x] **Code status / resuscitation status** — `modules/code_status/` + `locale/{us,jp}/code_status_rates.yaml`。AD-56 post_records enricher (encounter_id サブシード 0x4353 → 主乱数列不変)。4 段階 (Full Code/DNR/DNR+DNI/Comfort)、入院=全例 + ED=`deceased`/`icu_transferred` のみ + 外来=なし。年齢×acuity (terminal>icu>routine) で確率割当。FHIR survey `Observation` (SNOMED resuscitation-status)、CSV `code_status.csv`。`CIFPatientRecord.code_status`。SNOMED は環境制約で `# TODO: verify`。PR #64。
- [x] **Extended SDOH (smoking/alcohol/JP 要介護度)** — 喫煙 (US Core Smoking Status, LOINC 72166-2 + SNOMED) と飲酒 (LOINC 11331-6) を social-history `Observation` 化 (既存属性を読むだけ)。JP **要介護度** は新規 `modules/care_level/` (JP-only post_records enricher, person_id サブシード 0x434C, 年齢駆動) + `jp-care-level` ローカルコード体系 (MHLW 介護保険 区分)。新 `modules/output/_fhir_sdoh.py` (3 builder)、CSV `care_level.csv` + `alcohol_use` 列。`CIFPatientRecord.care_level`。alcohol SNOMED は `# TODO: verify`。PR #65。

#### Modules — specialized / optional (opt-in, one theme each)

- [ ] **`modules/billing/`** — country-pluggable レセプト/claims (JP **DPC** per-diem bundling / US `Claim`+`ExplanationOfBenefit`). Mirrors `identity`: provider registry, deps `types`/`codes`/`locale`, reads CIF, FHIR in `output`, `--billing` flag. **Supersedes the v0.5 "DPC/DRG cost data" item.**
- [ ] **`modules/device/`** — device placement (central line / urinary catheter / ventilator / telemetry) + **HAI risk** (CLABSI/CAUTI/VAP) from dwell time; deps `procedure`/`types`; emit `Device`/`DeviceUseStatement` (+ HAI `Condition`). Flag-gated.
- [ ] **`modules/care_coordination/`** — `CarePlan`/`CareTeam`/`Goal` for USCDI/Synthea interoperability completeness; deps `types`; reads CIF; flag-gated.

Suggested order: ~~microbiology+markers~~ ✅ → ~~nursing flowsheets~~ ✅ → ~~immunization~~ ✅ → ~~family-history~~ ✅ → ~~code-status~~ ✅ → ~~extended SDOH (要介護度)~~ ✅ → `DiagnosticReport` grouping → `modules/billing` (JP DPC) → `modules/device` → `modules/care_coordination`. **AD-55 Base roadmap complete** (only `DiagnosticReport` panel grouping remains, structural-only).

### v0.4 — Coverage expansion

- [ ] SNOMED CT clinical findings
- [ ] Mental health encounters
- [ ] Long-term care / rehabilitation
- [ ] Home health
- [ ] More countries (UK, EU, China, Korea)
- [ ] Holiday calendars

### v0.5 — Polish

- [ ] DPC/DRG cost data
- [ ] HL7 v2 output adapter
- [ ] CDA output adapter
- [ ] SQL output adapter
- [ ] Tier 3 expert blind test program

### v1.0 — Production-ready

- [ ] 1M+ patient generation in reasonable time
- [ ] Full validation against published benchmarks
- [ ] Comprehensive documentation
- [ ] Stable API contracts

## Recent completions (2026-04-20 — Demographics externalization US)

- ✅ Population demographics externalization (US): 8 hardcoded fields moved to `us/demographics.yaml` — sex_ratio, physiology (BMI/height CDC NHANES), lifestyle_distribution (smoking/alcohol sex-specific CDC NHIS), lifestyle_risk_multipliers (BMI + smoking → chronic + acute events), comorbidity_correlations (I10/E11.9/E78 Framingham), insurance_distribution (age-band KFF 2023), race_distribution (Census 2020), occupation age_thresholds
- ✅ PersonRecord now carries bmi, smoking_status, alcohol_use (Layer-1 lifestyle attributes for risk multipliers)
- ✅ PatientProfile now carries race, ethnicity (US only; empty string for JP)
- ✅ activate_patient() refactored: demo: dict replaces country: str; BMI/lifestyle from Layer-1; insurance/race from YAML
- ✅ load_demographics() injects _country key for downstream locale selection
- ✅ 201 unit tests passing (was 200)
- 🔲 JP locale deployment pending approval
- 🔲 End-to-end CIF smoke run pending

## Recent completions (2026-04-19 — Milestone 4: FHIR standards compliance + occupational injuries)

- ✅ Occupational injuries: 4 inpatient (crush_injury_hand, industrial_burn_severe, fall_from_height, electrical_injury) + 2 ED (eye_foreign_body, chemical_exposure) — with occupation_risk_multipliers in demographics.yaml
- ✅ Occupation field on PersonRecord/PatientProfile: 12 categories with age-based distribution from labor statistics. FHIR output as Observation (LOINC 11341-5, social-history)
- ✅ A/B test: empirically confirmed English enrichment + LLM translation gives equal/better quality vs pre-localization. Reverted over-localization (AD-44)
- ✅ Multilingual FHIR coding: Condition and Procedure emit dual coding (JP primary + EN interop, or vice versa). `_build_diagnosis_codeable_concept()` with cross-system fallback (AD-46)
- ✅ FHIR Observation referenceRange/interpretation consistency: 0 inconsistencies (was 5,522). SpO2 100% HH bug fixed. Vital signs include normal + critical ranges. JP display for all (AD-47)
- ✅ procedure_name removed from ProcedureRecord (AD-48, AD-30 strict): display via code_lookup("k-codes"|"cpt", code, lang). Both procedure_code_jp and procedure_code_us stored
- ✅ k-codes.yaml expanded 2→25 entries, cpt.yaml +6 entries. Procedure display via code dictionary (not hardcoded dict)
- ✅ Comprehensive JP FHIR localization: all display/text/name fields (Encounter class, Condition category/severity, Observation category/interpretation, referenceRange, Organization type, Location name/type, Patient relationship, Procedure code, MedicationRequest/Administration text)
- ✅ Drug name dictionary (120+ entries) + allergen/procedure/dosage term translation for FHIR adapter
- ✅ Condition code.text abbreviations (COPD, CHF, CKD, DM, AF etc.) for search friendliness (AD-49)
- ✅ Medication protocol prefix stripping — DVT_prophylaxis:, antipyretic: etc. removed from medicationCodeableConcept.text (AD-50)
- ✅ Emergency contact person names (佐伯 紬 instead of 佐伯家)
- ✅ JP recommended_population 5K→10K (realistic 70-80% bed occupancy)
- ✅ US 40K full run on EC2: 3,344 Bedrock EN documents, FHIR 2.0GB
- ✅ JP 5K full run on EC2: 499 Bedrock JP documents, FHIR 467MB
- ✅ ICD-10 + ICD-10-CM: 12 missing codes added (J12.9, A08.4, M54.50 etc.)
- ✅ 189 unit tests passing

## Recent completions (2026-04-13 — Milestone 3: Japanese narrative quality + simulation fixes)

- ✅ Japanese narrative prompts (5 types: admission_hp, discharge_summary, death_summary, operative_note, procedure_note)
- ✅ 2-round clinician review with Bedrock Claude Sonnet 4 (8+8 patients, 23+22 documents)
- ✅ 8 diverse diseases validated: sepsis, acute appendicitis, hip fracture, AMI, GI bleed, hemorrhagic stroke, cellulitis, AF-RVR
- ✅ CRP unit conversion moved from LLM prompt to code (AD-42): `format_lab_trends(language=)` + `_initial_labs(language=)` with `_JA_CONVERSION` dict
- ✅ Staff name suffix 「医師」 enforced in all ja prompts (AD-43) — was inconsistent in v1 review
- ✅ Chronic medication base code fallback: `chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])` in `inpatient.py` (was exact-match only)
- ✅ Empty medication string filter in `helpers.py` (`drug_name` key support + empty filter) and `activator.py` (filter before emptiness check)
- ✅ JP FHIR localization: Location names (4E病棟, 4E-01号室), Encounter type (入院), serviceType (内科), maritalStatus (既婚), dosageInstruction (経口, 1日1回)
- ✅ JP staff name format in narratives (佐伯 紬医師, not Dr. 佐伯 紬)
- ✅ JP 5K full Bedrock run initiated on EC2 (CIF + narrative, nohup-safe)
- ✅ 187 unit tests passing (up from 141)

## Recent completions (2026-04-10 — Milestone 2: Simulation fixes + Bedrock full run)

- ✅ 4-round Bedrock clinical validation (35 documents, 12 disease patterns, 5 document types)
- ✅ YAML-driven `medication_holds` in disease protocols (hemorrhagic_stroke, pancreatitis, DKA, sepsis, AKI)
- ✅ Surgery names from disease YAML (cholecystitis→laparoscopic cholecystectomy CPT 47562, appendicitis→CPT 44970, trauma→exploratory laparotomy CPT 49000)
- ✅ Hip fracture discharge prescription (oxycodone/acetaminophen + enoxaparin + calcium/vitamin D)
- ✅ Discharge Rx renal contraindication check (final_renal_function < 0.3 → skip metformin/celecoxib/NSAIDs)
- ✅ BPH sex filter in demographics.yaml (N40 male-only + population engine sex check)
- ✅ LLM hallucination prevention (discharge_summary prompt: "only prescribe listed medications")
- ✅ Nurse assignment per department (was hardcoded to internal_medicine → now uses patient's dept)
- ✅ Staff ID → name resolution in narrative prompts (DR-XX-NNN → Dr. Name, NS-XX-NNN → RN Name)
- ✅ Country-specific recommended_population (US: 40K, JP: 5K based on bed/population ratios)
- ✅ .gitignore fix (clinosim/modules/output/ was accidentally excluded)
- ✅ EC2 Bedrock full run: 421 documents generated (191 H&P + 191 DC + 22 Procedure + 9 Op + 8 Death)
- ✅ FHIR Bulk Data with 13 NDJSON types (incl. DocumentReference 421 + Practitioner 71 all-dept nurses)
- ✅ Full dataset delivered to iris-ai (209MB FHIR Bulk Data)

## Recent completions (2026-04-09 — Milestone 1: Clinical documents)

- ✅ FHIR Procedure structural fields: category, performer.function, recorder, reasonReference, bodySite, location (OR), outcome, complication (all via SNOMED CT subset, AD-36)
- ✅ `clinosim/codes/data/snomed-ct.yaml` — 32-code minimal SNOMED subset for procedures/outcomes/complications/body sites (en + ja)
- ✅ Operating room Location resources in facility bundle (hospital-config-driven)
- ✅ `clinosim/modules/llm_service/providers/` subpackage: `base.py` Protocol, `ollama.py`, `mock.py`, `bedrock.py` (boto3 lazy, Converse API)
- ✅ Provider registry + `register_provider()` extension point (AD-39)
- ✅ `factory.build_from_config_file()` — YAML-driven LLMService construction
- ✅ `PromptRegistry` with `string.Template`-based rendering and English fallback (AD-40)
- ✅ `PromptCache` (SHA256 disk cache) with per-call stats in `cost_report()` (AD-41)
- ✅ 5 English prompt YAML files: `discharge_summary`, `death_summary`, `operative_note`, `admission_hp`, `procedure_note`
- ✅ `ClinicalDocument` type in `clinosim/types/clinical.py` + `CIFPatientRecord.documents` field
- ✅ `clinosim/modules/output/hospital_course_extractor.py` — deterministic event extraction (admission, surgeries, lab peaks, complications, discharge)
- ✅ `clinosim/modules/output/document_generator.py` — Stage 2 narrative CIF writer (Tier A+B)
- ✅ `_build_document_reference()` in `fhir_r4_adapter` — base64 attachment + sha1 hash + related Procedure reference
- ✅ `clinosim narrate` and `clinosim export-fhir` CLI subcommands (AD-37)
- ✅ `clinosim generate --narrative --llm-config PATH --narrative-version ID` integrated pipeline
- ✅ `clinosim/config/llm_service.bedrock.yaml` — EC2 Bedrock config template
- ✅ 6 LOINC codes (34117-2, 11506-3, 18842-5, 69730-0, 11504-8, 28570-0) added to `loinc.yaml` with en + ja
- ✅ 32 new unit tests in `tests/unit/test_clinical_documents.py` (prompts, cache, providers, extractor, document generator E2E, FHIR DocumentReference builder)
- ✅ Total test count: 141 passing
- ✅ Documentation: README.md, DESIGN.md (AD-36 to AD-41 + Part 7/8), TODO.md, new docs/clinical_documents.md, new docs/bedrock_setup.md

## Recent completions (2026-04-06 to 2026-04-08)

- ✅ codes module with 8 international code systems (577 codes total, EN required)
- ✅ FHIR R4 Bulk Data Export NDJSON format (replacing per-encounter Bundle)
- ✅ Snapshot date semantics with in-progress encounters
- ✅ Hospital config-driven department/ward/bed layout
- ✅ Bed Location resources with partOf hierarchy
- ✅ PractitionerRole.location assignment
- ✅ Staff roster scaled to hospital config (ward-aware nurse distribution)
- ✅ All Resource.id globally unique (0 violations across 12 types)
- ✅ UCUM-compliant units with system+code in valueQuantity
- ✅ NEWS2-compatible vitals (AVPU consciousness, supplemental O2)
- ✅ Realistic vital sign measurement patterns (continuous monitoring, event-driven rechecks, per-field offsets)
- ✅ Outpatient vital subset by visit type (HTN visit = BP+HR only)
- ✅ Procedure expansion (15 bedside procedures, disease-driven rules)
- ✅ Condition staging (CKD G/NYHA/GOLD/HbA1c/CCS/asthma severity)
- ✅ Encounter.length, reasonReference, hospitalization, location
- ✅ Patient.identifier (MRN), maritalStatus, communication, contact, telecom
- ✅ MedicationRequest dosageInstruction (timing, route, doseAndRate)
- ✅ MedicationAdministration structured dose + reasonReference
- ✅ Observation.interpretation (lab + vital), referenceRange (vital)
- ✅ Practitioner gender, telecom, qualification, prefix
- ✅ Module READMEs for all 17 modules + main README (EN/JA)
- ✅ CLAUDE.md updated with new architecture rules

## Future design improvements (tracked, not scheduled)

| # | Item | Priority | Notes |
|---|---|---|---|
| F-1 | encounter YAML-ization (workflow as data) | Medium | v0.2 |
| F-2 | clinical_course absorption into physiology | Low | Current separation works well |
| F-3 | DI/Registry pattern for module wiring | Low | Manual wiring is fine for now |
| F-4 | More languages in codes module (de, zh, ko, fr) | Low | Just add language keys to YAML entries |
| F-5 | UCUM module in codes/ for unit display translation | Low | Currently units are bare strings |

---

## PR1 ServiceRequest follow-ups (Tier 1 backlog)

### PR2 — ServiceRequest for PROCEDURE
- Procedure orders currently flow through ProcedureRecord (no Order intermediate).
- Path: extend `_fhir_procedures.py` builder to emit ServiceRequest preceding each Procedure,
  link via ProcedureRecord.procedure_id.

### PR3 — ServiceRequest for REFERRAL / CONSULTATION
- New CIF data required (no current source).
- Path: extend disease YAML with `referrals:` field, generate Orders with
  OrderType.REFERRAL (or CONSULTATION), new SR category (SNOMED 308540006 + HL7 v2-0074 REF).

### Tier 1 #2 — ServiceRequest for IMAGING [DONE 2026-06-30]
- ~~Bundled with full Imaging chain (ImagingStudy + DiagnosticReport(rad) + Endpoint stub).~~
- **COMPLETED**: Imaging chain α-min delivered (AD-62). ImagingStudy + Endpoint + radiology DR +
  imaging SR. US p=10k + JP p=5k production cohort generated and audited. DQR: 4 axes PASS.

### Tier 1 #3 — Document Density α-min-1 [DONE 2026-07-01]
- ~~Stage 1 default template-based document emission (DocumentReference / Composition / ClinicalImpression) + AllergyIntolerance schema upgrade.~~
- **COMPLETED**: Document Density chain α-min-1 delivered (AD-63). DocumentReference 0 → 23,760
  (US) / 3,909 (JP); Composition 0 → 9,275 / 474; ClinicalImpression 0 → 23,760 / 3,909.
  AllergyIntolerance 8-field SNOMED upgrade. 2 always-on POST_ENCOUNTER modules (`allergy` (POST_POPULATION) + `document` (POST_ENCOUNTER)).
  3 new FHIR builders. silent_no_op 17/17 PASS. US p=10k + JP p=5k cohorts verified.
  DQR: `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-1-dqr.md`.
  Task 15 (generator migration / cleanup) completed on same branch.

### Tier 1 #3 — Document Density α-min-2 [DONE 2026-07-01]
- ~~Nursing domain narratives (admission nursing assessment / nursing shift note / discharge nursing summary) + CareTeam + triage infrastructure + 46 encounter YAML narrative extensions.~~
- **COMPLETED**: Document Density chain α-min-2 delivered (AD-64). CareTeam 0 → 158,811 US /
  16,046 JP (1:1 with Encounter, ★ GAP CLOSED). DocumentReference +22,798 (nursing shift daily
  notes). Composition +8,671 (nursing admission + nursing discharge). 3 new always-on POST_ENCOUNTER
  Modules (`triage` order=93 + `nursing_assignment` order=94 + extended `document` order=95).
  CareTeam FHIR builder. 6 new DocumentType specs (78390-2/34746-8/34745-0/34131-3/34878-9/54094-8).
  silent_no_op 25/25 PASS. clinical axis PASS (CareTeam 1:1 with Encounter). 27 integration tests.
  DQR: `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`.
  **Known gap → RESOLVED (α-min-2 Task 14 fix, verified 2026-07-02)**: outpatient.py +
  emergency.py DO invoke `run_stage(POST_ENCOUNTER)` (both carry the "α-min-2 Task 14 fix"
  block). Production-verified at US p=500 seed=42: OUTPATIENT_SOAP 1,841 Composition +
  ED_NOTE 210 Composition + ED_TRIAGE_NOTE 210 DocumentReference. The α-min-3 section
  below no longer contains this item.

### β-JP-1: LLMNarrativePass 実装(AD-65 base 上に drop-in)

- `LLMNarrativePass(NarrativePass)` subclass 実装 — AD-65 `NarrativePass` base の上に Bedrock/Ollama LLM integration を layer
- Bedrock Sonnet-4 provider + Ollama qwen:7b provider 対応 + localhost fallback
- Bedrock prompt cache(5 分 TTL)発火の実測 verify + cost reduction report
- `facts_used` gate 有効化 — template facts vs LLM-rephrased facts の audit diff
- `docStatus` 4 状態化:
  - `"final"` (template完全生成)
  - `"final"` (LLM完全生成)
  - `"preliminary"` (LLM fallback to template)
  - `"amended"` (human reviewed)
- `Composition.author` extension で AI-assisted attribution 明示
- Section-level LLM replacement 発火の条件化 (section 例外リスト + LLM-capable section list by doctype)
- `clinosim narrate --patient-filter POP-000001` 対応 — single-patient iterative loop for testing

#### β-JP-1 chain 1a adv-1 deferred (2026-07-03)

Findings triaged out of the chain-1a adv-1 fix PR (scope discipline rule):

- **Small-p roster export gap**: p=100 cohort audit shows 5 dangling nurse
  Practitioner references in CareTeam. PROVEN pre-existing (same refs dangle
  in the α-min-2-era p=100 cohort; US p=10k / JP p=5k production audits
  pass). Needs a roster-export-at-small-p fix decision (export full staff
  roster regardless of cohort size vs. clamp assignments to exported staff).
- **outpatient.py chronic-followup severity**: the chronic-followup path
  leaves `encounter.severity=""` (no value in scope). Decide a severity
  source (condition state? stable default?) and wire it.
- **`narrative/context.py:build_narrative_context` delete-or-unify**: the
  parallel ctx factory has ZERO production callers and diverges from
  `NarrativePass._build_context` (e.g. no `discharge_medications` /
  MAR-only split from adv-1 I-1). Delete it or unify both on a single
  factory before β-JP-1 builds on the ctx contract.
- **Remaining encounter-template placeholders** (chain 1b T4 shipped the
  vitals subset — `{sbp}` / `{dbp}` / `{hr}` / `{temp}` / `{spo2}` / `{rr}`
  now resolve from `ctx.vitals`): everything else in the encounter YAML
  inventory still triggers the whole-section generic fallback (adv-1 I-2
  follow-up; `_KNOWN_PLACEHOLDERS` / `_VITAL_PLACEHOLDER_FIELDS` in
  `template_generator.py` are the extension points). Remaining inventory
  (grep over `modules/encounter/reference_data/*.yaml`, 2026-07-03):
  high-frequency `{disposition_display_*}` (28) / `{lab_summary_*}` (27) /
  `{imaging_summary_*}` (26) / `{primary_dx_display_*}` (17) /
  `{workup_summary_*}` (16) / `{follow_up_*}` (16); low-frequency
  `{weight}` `{severity_desc_*}` `{last_lab_date}` `{duration_days}`
  `{cxr_result_*}` + ~25 one-off condition-specific tokens
  (`{ua_result_*}`, `{troponin_result_*}`, `{ottawa_result_*}`, ...).
- **ctx.medications MAR dedupe for LLM constraint lists** (adv-1 M-3): MAR
  entries repeat per administration; LLM prompt constraint lists built from
  `ctx.medications` may want per-drug dedupe (+ merge with discharge rx
  where the prompt needs "all meds this stay").
- **`KNOWN_JA_ONLY_FALLBACK_SECTIONS` blanket-name exemption** (adv-1 M-2):
  the ja-leak audit gate exempts whole section names; a section that later
  gains proper en templates keeps its exemption silently. Future: tag-based
  matching (exempt only sections actually rendered via `ja_only_fallback`
  facts_used tags).

#### β-JP-1 chain 1b adv-1 deferred (2026-07-03)

Findings triaged out of the chain-1b adv-1 fix PR (scope discipline rule):

- **MockProvider call_count couples llm-mock goldens to global walk order**
  (adv-1 M-1): the mock stub text embeds a per-run `call_count`, so ANY
  change to the (doc_type, language, patient) walk order — or adding a doc
  type — shifts every subsequent mock golden byte. Consider
  order-insensitive stubs keyed on a prompt hash (e.g.
  `[Mock:{sha1(prompt)[:8]}]`) so goldens only change when the prompt for
  THAT document changes.
- **Vitals placeholder per-field nearest-reading can mix timepoints**
  (adv-1 M-4): `_resolve_vital_placeholders` picks the nearest non-null
  reading PER placeholder, so one sentence can combine `{sbp}` from day 2
  with `{hr}` from day 3 when readings are sparse. Prefer single-reading
  resolution: pick the best reading for the stub's day once, resolve all
  placeholders from it, and fall back whole-section if it lacks any wanted
  field.
- **ja-leak check gaps** (adv-1 M-5, known data gap): the semantic-check
  ja-leak axis is disabled for mixed-language cohorts, and free-text
  (non-composition) document bodies are not checked for language leaks at
  all.
- **I-1 residual — export-time partial-version guard**: `export-fhir` on a
  partial "current" version still emits with a per-doc WARN only (narrate
  now guards set-current and merge writes; manifest carries
  `partial: true`). Consider a version-level guard at export time: read
  `manifest.json.partial` and require an explicit flag (or hard-fail) when
  exporting a partial narrative version.

### Post-AD-65 fixture library (α-min-2c) — ✅ COMPLETED (session 30, PR #132)

Shipped in α-min-2c chain (AD-66):
- `tests/fixtures/patient_profiles/` with 6 canonical disease-based inpatient/ICU profiles
- `PatientProfile` Pydantic type in `clinosim/types/config.py`
- `test-disease --patient-profile` CLI + `regenerate-goldens` CLI
- `pytest -m regression` suite (opt-in, marker=regression)
- Determinism at seed 42 verified for narrative output

### Post-α-min-2c fixture library extensions (β-JP-1 or later)

- Encounter-based profiles (ED / outpatient) — requires symmetric
  `test-encounter --patient-profile` extension + `PatientProfile.condition_id`
  field, or unified `test-profile` verb
- Additional disease-based profiles beyond α-min-2c 6 (as β-JP-1 LLM
  regression scope grows)
- LLM semantic diff mechanism — byte-diff insufficient for LLM output
  (fuzzy match, tolerance thresholds, expected phrase substrings)
- Clinical review loop — per-profile physician + nurse validation
- CI GitHub Actions workflow for automated regression at PR time
- LLM parallel goldens (`<profile>.llm-<model>.golden.json`) alongside
  `<profile>.golden.json`
- Re-add `PatientProfile.chronic_medications` / `time_range` WITH actual
  consumption (removed in adv-1 F-1 as unwired fields — they were declared but
  nothing consumed them, defeating the extra=forbid typo defense)

### Imaging chain OOS formal entries (Tier 1 #2 PR1 scope-out)

The following FHIR fields / features were **explicitly out of scope** for the α-min imaging chain
(per spec Section 11). Each is a valid future extension:

#### ImagingStudy field-level OOS

- **ImagingStudy.numberOfSeries / numberOfInstances**: field values deferred; always-present
  `series[]` array is the canonical count source at α-min.
- **ImagingStudy.series[].instance[]**: DICOM SOP Instance UID expansion. Each series contains
  one conceptual instance at α-min; real PACS integration will expand to per-slice.
- **ImagingStudy.series[].number**: DICOM series number (integer) — ordinal within study.
- **ImagingStudy.interpreter**: radiologist practitioner reference. Deferred to Phase 2 when
  radiology staff roster is added.
- **ImagingStudy.referrer**: ordering clinician reference — already available as
  `Order.ordered_by`; FHIR wire deferred.
- **ImagingStudy.availability**: ONLINE / OFFLINE / NEARLINE / UNAVAILABLE. Deferred; Endpoint
  presence implies ONLINE semantics.
- **ImagingStudy.encounter**: explicit Encounter reference on the ImagingStudy. Deferred; can
  be derived from basedOn SR's encounter.
- **ImagingStudy.location**: imaging suite Location resource. Deferred to Location hierarchy PR.
- **ImagingStudy.reason**: clinical indication reference (Condition). Deferred; reason text is
  present in the imaging SR.
- **ImagingStudy.procedureCode**: SNOMED CT procedure code for the imaging study type. Tier 2.
- **ImagingStudy.series[].performer**: technician who acquired the series. Tier 2 (radiology
  staff roster).
- **ImagingStudy.series[].laterality**: body laterality SNOMED code (right/left/bilateral).
  Tier 2; body site only at α-min.
- **ImagingStudy.note**: free-text annotation at study level. Tier 3.

#### Endpoint field-level OOS

- **Endpoint.connectionType**: hardcoded to DICOM WADO-RS at α-min. Future: DICOMweb STOW-RS
  for push-based upload integration.
- **Endpoint.payloadMimeType**: DICOM media type list deferred. Tier 2.
- **Endpoint.header**: HTTP auth headers for PACS auth. Out of scope for placeholder URL.

#### DiagnosticReport (radiology) field-level OOS

- **DiagnosticReport.resultsInterpreter**: radiologist practitioner. Tied to interpreter on
  ImagingStudy — both deferred to Phase 2 staff roster.
- **DiagnosticReport.presentedForm**: base64-encoded PDF or HTML for structured radiology
  report export. Deferred; text.div + conclusion covers α-min needs.
- **DiagnosticReport.media**: key images as Attachment. Deferred until image-gen AI integration.
- **DiagnosticReport.effectiveDateTime**: date of imaging procedure. Wire from
  `ImagingStudyRecord.study_datetime` — deferred to pass 2.

#### Disease YAML imaging coverage OOS

- **aspiration_pneumonia.yaml**: imaging_orders exists for CR (Chest_Xray) but no YAML
  for aspiration pneumonia → imaging chain skips it (legacy order path). Tier 2.
- Additional diseases (COPD / sepsis / hip fracture / etc.): imaging_orders not yet in YAML.
  Bundle with legacy migration sweep PR (see "Legacy IMAGING order emission sites" item below).

### imaging chain JP language axis
- **ModuleAuditSpec** lacks `jp_language_checks` field. `clinosim/modules/imaging/audit.py` deferred 6 JP language audit checks (modality / bodySite / DR.code / conclusion / text.div / SR.code displays in ja for JP cohort). When framework gains the field, wire these checks. Spec Section 9.4 brief includes the full list.

### Legacy IMAGING order emission sites need migration to Task 3 path
- **Issue:** `clinosim/simulator/inpatient.py` lines 852, 1737, 1781 + `clinosim/simulator/emergency.py` line 183 emit Order(OrderType.IMAGING) without `imaging_modality` / `imaging_body_site_code`.
- **Current workaround:** Task 4 imaging_enricher silently skips these via filter (test_enricher_skips_legacy_orders_without_imaging_metadata) to avoid breakage.
- **Fix path:** Migrate these emission sites to use `place_imaging_orders` so they emit ImagingStudy + radiology DiagnosticReport + Endpoint resources through the normal Task 3/4 pipeline.
- **Scope:** Out of scope for Tier 1 #2 PR1 (imaging chain α-min), track for follow-up sweep PR.
- **TODO #1 (whole-branch review, 2026-06-30):** Legacy `bacterial_pneumonia.yaml:152-153` style
  entries (`imaging: [Chest_Xray_PA_Lateral]`) still emit `Order(IMAGING)` without metadata, causing
  ~17,691 orphan SRs in US p=10k cohort (98% of SR(RAD)). Migration plan:
  (a) Extend imaging_chain audit module to flag orphan ratio > N% as WARN.
  (b) Log a warning in enricher when IMAGING order lacks metadata (currently silent skip).
  (c) Disease YAML migration sweep: replace `imaging: [name]` with `imaging_orders: [...]` for all
  30 disease YAMLs. Sites: `bacterial_pneumonia.yaml` + all diseases with legacy `imaging:` field.

### TODO #2 (whole-branch review, 2026-06-30): JP language audit gate
- **ModuleAuditSpec** lacks `jp_language_checks` field. `clinosim/modules/imaging/audit.py` deferred
  6 JP language audit checks (modality / bodySite / DR.code / conclusion / text.div / SR.code
  displays in ja for JP cohort). When framework gains the field, wire these checks.
  Spec Section 9.4 brief includes the full list. Extension proposal:
  (a) Add `jp_language_checks: list[str]` field to `ModuleAuditSpec`.
  (b) Wire into JP language axis dispatcher.
  (c) Implement imaging_chain JP checks + add to other always-on Modules.

### TODO #3 (whole-branch review, 2026-06-30): Adversarial fan-out chain deferred
- Per memory `feedback_iterative_adversarial_review`, PR-class precedent calls for post-impl
  5-lens parallel adversarial fan-out review. Imaging chain ran per-task reviews + 1 final
  whole-branch review. Adversarial fan-out (5 reviewers × silent-no-op / data unification /
  FHIR-JP Core / AD-16 + scale / spec adherence) deferred to post-merge per chain length +
  user roadmap re-evaluation timing (memory `project_ehr_sample_dataset_roadmap`).

### TODO #4 (whole-branch review, 2026-06-30): Spec deviations to document
- Update spec `docs/superpowers/specs/2026-06-30-tier1-imaging-chain-design.md`:
  (a) `ENRICHER_SEED_OFFSETS["imaging"] = 0x4947 ("IG")` — actual vs spec's 0x494D ("IM").
  (b) `Order.imaging_spec_meta: dict[str, Any]` — 4th imaging field not in original spec.
  (c) `RadiologyReport.findings_text_ja` / `impression_text_ja` — lang-keyed fields.

### TODO #5 (whole-branch review, 2026-06-30): `views=[]` fallback edge in place_imaging_orders
- `place_imaging_orders` increments `sequence_counter["I"]` even when views=[] and
  `default_views_by_body_site` lookup fails for a modality+body_site combo. Future modality
  additions could trip silently. Add `_validate_modalities` Layer-5 invariant: every
  (modality, supported body_site) pair has a `default_views_by_body_site` entry.

### TODO #6 (whole-branch review, 2026-06-30): Integration test population size
- `run_generate("US", 100, 42, ...)` integration tests skip when no studies emit. n=100 is
  fragile — raise to 200 where DQR shows enough disease distribution for stable coverage.
  Files: `tests/integration/test_imaging_chain.py`, `test_imaging_basedon_coverage.py`, etc.

### TODO #7 (whole-branch review, 2026-06-30): DQR phrasing "1/4 PASS" is misleading
- DQR Axis 4 summary had "1/4 PASS" when structural/jp_language axes are N/A (not applicable).
  Replace with explicit "clinical PASS + silent_no_op PASS (structural/jp_language N/A — no
  module-specific gates)" to clarify the 4-axis accounting. Fixed to "2/4 PASS" post I-3 fix.

### Out-of-scope permanent — ServiceRequest for MEDICATION
- FHIR `MedicationRequest` is the correct resource; ServiceRequest not used.

### Tier 2 — ServiceRequest for HAI microbiology culture
- MicrobiologyResult is a separate type from Order; bundle with general microbiology ordering
  refactor.
- Note: PR1 audit gate (`clinical.py:_check_lab_obs_basedon`) excludes mb-org-* / mb-sus-*
  Observations via MB_ORG_ID_PREFIX / MB_SUS_ID_PREFIX. Re-include when microbiology SR lands.

### Tier 1 #6 — ServiceRequest.requisition (Identifier) for cross-resource grouping
- Defer until Appointment/Schedule introduces multi-SR batch requisition.

### Tier 1 #5 — Lab requisition workflow narrative
- Defer to DocumentReference Stage 2.

### Tier 2 — ServiceRequest.performer (lab technician/department)
- Bundle with CareTeam.

### Tier 2 — Filler order number `FILL` identifier
- Lab interface specifics; placer alone sufficient for PR1.

### M-6 — Disease YAML `code_loinc:` field backfill
- Many disease YAMLs lack `code_loinc:` on lab entries → `order_code` ends up as internal
  test name ("CRP", "WBC") or empty string → JP cohort SR.code.coding[].display falls back
  to English. Affects ~105 of 42k JP SRs (~0.25%).
- Backfill `code_loinc:` field on every lab entry in
  `clinosim/modules/disease/reference_data/*.yaml`. Touches ~30 disease YAMLs; source LOINC
  codes via NLM API per CLAUDE.md authoritative-source rule.

### M-7 — Order status not updated on last simulation day at snapshot boundary
Some stand-alone Orders retain `OrderStatus.PLACED` even after a result Observation is
written, when the simulation truncates at the snapshot boundary. Discovered as pre-existing
bug during PR1 Stage 2 adversarial review (commit 57285e2126). The expected invariant:
PLACED Orders MUST have no result Observation (and conversely, RESULTED Orders MUST have a
result Observation).

**Fix path:** Update Order.status during snapshot truncation in `clinosim/modules/inpatient.py`
(or wherever the snapshot day handling lives) — propagate the order_status transition
consistently with the result emission.

**Currently gated by:** `tests/integration/test_servicerequest_snapshot.py::test_snapshot_placed_orders_have_no_observation`
marked `pytest.mark.xfail(strict=False)`. When the bug is fixed, remove the xfail marker.

**Discovered:** PR1 stage 3 Minor fixes (2026-06-30).

### `_code_in_data` LOINC-existence helper — promote to public API
- Now exists in 3 places: `hai/engine.py`, `panel_grouping.py`, and this TODO.
- Path: promote to `clinosim/codes/loader.py:code_exists(system, code)` and migrate all 3
  consumers.

### `_o` dual-access helper — promote to `_shared.py` public API
- Now exists in `_fhir_service_request.py` + `_fhir_observations.py` (PR1 added second+third
  consumers).
- Path: promote to `clinosim/modules/_shared.py` as `o(obj, name, default)` and migrate.

### Audit framework — `_BUNDLE_BUILDERS` dict-compat sweep
- `test_device_fhir_output.py::test_device_extension_through_fhir_pipeline` progresses past
  AttributeError post-fix but fails for a different reason (device count = 0 at p=300).
  Sweep all builders for dict-compat (dataclass vs dict dual-access pattern).

## SS-MIX2 output adapter(セッション25 deferred)

**Decision:** User deferred SS-MIX2 implementation 2026-06-30 セッション25。実 EHR データ density 充実(問診 / 検査 / 手術 / 処方の event 記録)を先に進めるため。

**Scope:**
- 新 output adapter via AD-58 `register_output_adapter`(FHIR と並行出力、CIF read-only consume)
- HL7 v2.5 segment-based、厚労省 SS-MIX2 標準準拠
- 主要 message types:
  - **ADT**(Admit/Discharge/Transfer):A01 admit、A03 discharge、A02 transfer、A04 register
  - **OML**(Order Lab):検査依頼 message
  - **OUL**(Observation Unsolicited Lab):検査結果 message
  - **ORM**(Order Pharmacy):処方依頼 message
  - **RDE**(Pharmacy/Treatment Encoded Order):処方詳細 message
  - **MDM**(Medical Document Management):文書 message
- 既存 `hospital_config` の各 hospital identifier(MEDIS / JANIS / etc.)を SS-MIX2 hospital ID にマップ

**Target consumers(JP EHR vendor debug datasets):**
- 富士通 HOPE LifeMark / EGMAIN-GX
- NEC MegaOakHR
- SSI Hyper-S
- IBM HOPE / IBM 医療情報システム
- 厚労省 医療情報連携基盤 connectivity test

**推定 PR:** 4-6 PR(adapter skeleton + 主要 6 message types + 厚労省仕様検証 + 既存 hospital_config 連動)

**Precondition:**
- ★ Event density 5 chain(Document / MAR / Procedure / LabDR / Nursing)完了後に着手推奨
- 理由:SS-MIX2 は CIF を消費するだけなので CIF の event records 充実が直接 SS-MIX2 dataset 価値に反映

**関連 memory:**
- `project_event_density_strategy.md` — セッション25 戦略軸転換
- `project_ehr_event_emphasis.md` — セッション25 戦略再確認

**Discovered:** セッション25(2026-06-30)。User goal が 病院 event 記録充実 = 並行 SS-MIX2 出力より優先。

---

## Tier 1 #3 α-min-1 Document Density Chain — OOS formal entries (2026-07-01)

These items were **explicitly out of scope** for the α-min-1 document density chain
(per spec §11). Each has a formal phase assignment for the master plan phases:
[docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md](docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md)

### α-min-2 phase (COMPLETED 2026-07-01) — Document types

- ~~看護 narrative (Admission nursing assessment / Nursing shift note / Discharge nursing summary)~~ — **DONE** (AD-64: 78390-2/34746-8/34745-0, inpatient-only)
- ~~CareTeam (2-name: attending + primary nurse)~~ — **DONE** (AD-64: 1:1 Encounter, 158,811 US)
- ~~Triage infrastructure (JTAS/ESI + arrival_mode)~~ — **DONE** (AD-64: triage module POST_ENCOUNTER order=93)
- ~~46 encounter YAML narrative extensions~~ — **DONE**

## Tier 1 #3 α-min-2 Document Density Chain — OOS formal entries (2026-07-01)

These items were **explicitly out of scope** for the α-min-2 document density chain.

### α-min-3 phase — status audit 2026-07-02 (all 3 items closed)

- ~~**CRITICAL: outpatient.py + emergency.py do NOT call POST_ENCOUNTER enrichers**~~ —
  **STALE / RESOLVED**: the α-min-2 Task 14 fix already wired both simulators
  (`outpatient.py` + `emergency.py` "POST_ENCOUNTER stage" blocks). Production-verified
  2026-07-02 at US p=500 seed=42: OUTPATIENT_SOAP 1,841 / ED_NOTE 210 / ED_TRIAGE_NOTE 210.

- ~~**Nursing shift 3-per-day**~~ — **DONE (α-min-3 PR, 2026-07-02)**: `daily_3shift`
  generation_frequency implemented in `document/engine.py` + `document_type_specs.yaml`
  (day 08:00 / evening 16:00 / night 00:00, shift key on the stub, ja labels
  日勤/準夜/深夜 in Stage 2). Production-verified: NURSING_SHIFT_NOTE = exactly 3× per
  LOS day (US p=200: 750 vs 250 progress notes). 6 profile goldens regenerated (AD-66 Rule 1).

- ~~**Composition.author wiring**~~ — **RESOLVED earlier than documented**:
  `_fhir_composition.py` emits `author[]` from `ClinicalDocument.author_practitioner_id`
  (populated by `_pick_document_author` at every emission site); `Practitioner/UNKNOWN` is a
  defensive fallback only — production count 0 at US p=500 + JP p=300 (2026-07-02). The
  remaining design question (whether the UNKNOWN fallback should raise instead) stays in
  "AD-65 adv-1 deferred" (Practitioner/UNKNOWN dangling ref).

### β-JP-1 phase — CareTeam multi-disciplinary expansion

- **CareTeam 6-name multi-disciplinary** — attending physician / attending nurse / pharmacist /
  nutritionist / rehab therapist / MSW roles. Requires expanding StaffRoster to include non-MD
  non-nursing roles. Prerequisite: Practitioner roster expansion (Practitioner count 85 → 150+).

- **JP section.title locale mapping** — `Composition.section[].title` currently uses English
  section key (e.g. `"nursing_history"`) for JP output. Add JP locale dict mapping to Japanese
  titles (e.g. `"看護歴"`) in `_fhir_composition.py` section builder.

- **JTAS/ESI system URI formalization** — `triage_protocols.yaml` uses LOINC 54094-8 for triage
  level coding but does not formalize JTAS (`http://hl7fhir.jp/standards/jtas`) or ESI
  (`http://acep.org/esi`) system URIs as canonical constants. Add to a new `triage_constants.py`
  (mirrors `CARE_TEAM_ID_PREFIX` / `DOC_REFERENCE_ID_PREFIX` pattern).

### β-JP-1 phase — JP localization + 厚労省必須文書

- **QuestionnaireResponse active emission** — `_fhir_questionnaire_response.py` builder for
  structured intake forms. Currently a stub; no CIF data source for questionnaire answers.
- ~~**入院診療計画書** (Admission care plan document)~~ — **DONE (chain 2, 2026-07-03)**:
  LOINC 18776-5, Composition, 10 sections per MHLW 別紙２, JP-only,
  inpatient/icu only (rehab_inpatient uses the 別紙２の２ variant, out of
  scope). `special_nutrition_management` is hardcoded "無" pending a future
  nutrition subsystem chain (see below) — no NutritionOrder/nutritionist
  data source exists yet to derive a real value.
- ~~**栄養管理計画書** (Nutrition care plan)~~ — **DONE (chain 2, 2026-07-03)**:
  LOINC 80791-7, Composition, 12 sections per MHLW 別紙23, JP-only,
  inpatient/icu only, emitted only for admissions with LOS > 7 days (new
  `admission_once_los_gt_7` generation_frequency). Only 3/12 sections are
  data-driven (ward/physician from Encounter, nutrition_risk from
  PatientProfile.bmi, nutrition_supply energy/protein estimate from
  PatientProfile.weight_kg); the other 9 are MVP fixed fallbacks — see
  deferred entries below.
- **重症度、医療・看護必要度に係る評価票**(TODO.mdの旧記載「看護必要度D表」は誤記 — 正式名称は
  A項目/B項目/C項目の評価票、"D表"という区分はMHLW公式には存在しない、chain 2調査で訂正
  2026-07-03)— DPC/診療報酬算定用の国内専用スコアリング様式。**適切なLOINCコードなし**
  (検証済み:LOINC 80346-0 "Nursing physiologic assessment panel"は米国の一般看護身体
  アセスメントパネルで別物、誤用不可)。ローカルコード体系でのQuestionnaireResponse実装が
  必要(現状は`FormatType.QUESTIONNAIRE_RESPONSE`のinfrastructure stubのみ)。GCS/ADLデータは
  `nursing_enricher.py`に既存だが、評価票のA/B/C項目粒度とは一致しない。
- **リハビリテーション計画書** (Rehabilitation plan) — mandatory for rehab wards. Requires
  `extensions["procedure"]` rehab sessions.
- **JP section text full localization** — `past_medical_history` / `medications_at_home` /
  `discharge_medications` sections currently English-only in α-min-1. Full JP: condition names
  via `code_lookup(..., "ja")`, drug names via `_localize_drug_name()`.
- **ClinicalImpression.description JP localization** — currently English-only.
- **多職種 staff allocation** — 主治医 / 担当看護師 / 薬剤師 / 栄養士 / リハ / MSW per
  encounter, required for CareTeam + Composition.author wiring.

### chain 2 deferred: admission_care_plan real nutrition-need derivation

`_build_acp_special_nutrition_management` (`template_generator.py`) always
renders "無" (no special nutritional management needed) — an MVP
simplification, not a real clinical derivation. When the 栄養管理計画書
(nutrition care plan) subsystem chain lands (NutritionOrder + nutritionist
staff role), revisit this section to derive a real yes/no signal (e.g. from
BMI, albumin lab values, or disease-specific nutrition risk flags) instead
of the hardcoded default.

### chain 2 deferred: `section_builders` dict lacks cross-spec key-collision validation

`TemplateNarrativeGenerator._render_composition_sections`'s `section_builders`
dict (`template_generator.py`) is one flat global namespace shared by every
COMPOSITION document type; each new doc type adds more string keys into it
(chain 2 added `ward_and_room` / `diagnosis` / `symptoms` / `test_schedule` /
etc.). `registry.py`'s Layer 1-9 validators check per-spec coherence (e.g.
`llm_enabled_sections ⊆ composition_sections`) but nothing validates that a
NEW doc type's `composition_sections` keys don't collide with an EXISTING,
unrelated doc type's key already registered in this dict — a plain Python
dict literal silently keeps the last definition on a duplicate key, so a
colliding key would silently steal another doc type's renderer with no
error (adv-1 finding on PR #138, not a live bug today — verified no
collision currently exists across all registered specs — but the
architecture has no guard against a future one). Add an import-time
uniqueness check (mirrors the `registry.py` Layer 1-9 pattern) that walks
every `DocumentTypeSpec.composition_sections` list and asserts each section
key maps to at most one doc type's intended semantics, OR restructure
`section_builders` to be keyed by `(doc_type, section)` instead of bare
`section` so collisions become structurally impossible.

### chain 2 deferred: nutrition_care_plan real data derivation

`_build_ncp_dietitian` / `_build_ncp_nutrition_assessment` /
`_build_ncp_nutrition_goals` / `_build_ncp_dysphagia_diet` /
`_build_ncp_dietary_content` / `_build_ncp_nutrition_counseling` /
`_build_ncp_other_issues` / `_build_ncp_reassessment_timing` (8 of 12
sections) render MVP fixed fallback strings — no CIF data source exists for
dietitian staff, real nutrition assessment/counseling content, or dysphagia
screening. Revisit when a richer nutrition-assessment data model + dietitian
staff role are built. `nutrition_risk`'s BMI-threshold heuristic is a coarse
screening proxy (not GLIM/MUST-validated) — acceptable for synthetic-data
MVP but should not be treated as clinically authoritative if reused
elsewhere.

### chain 2 deferred: nutrition_care_plan discharge-time revision

`_build_ncp_discharge_evaluation` always renders a fixed "pending" phrase —
this system has no mechanism to re-render a Stage-1 document stub at a later
encounter phase. If discharge-time nutrition evaluation becomes a priority,
this would need either a second document type (mirroring the
`nursing_discharge_summary` vs `admission_nursing_assessment` split
precedent) or a new Stage-2 revision mechanism.

### chain 2 deferred: LOS-gated document_enricher pattern (final review, PR #139)

`nutrition_care_plan` introduced `admission_once_los_gt_7`, the first
`generation_frequency` that bakes a numeric threshold into the enum string
itself (`document/engine.py`'s `document_enricher` dispatch). This is fine
for one gated doc type, but before a **third** LOS-gated document lands,
consider parameterizing instead of adding `admission_once_los_gt_14` etc.
ad hoc — e.g. keep `generation_frequency: admission_once` plus an optional
`min_los_days: int | None` field on `DocumentTypeSpec`, read once by a
single `admission_once` branch. Relatedly, `document_enricher` now has 3
near-identical 10-field `ClinicalDocument(...)` constructions
(`admission_once` / `admission_once_los_gt_7` / the per-day loop body in
`daily`) — a small local `_make_doc_stub(spec, encounter_id, doc_seq,
authored_dt, pid, lang, author)` helper would collapse the duplication and
make the LOS guard the only visible difference between branches.

### β-2 phase — Clinical event density

- **手術記録** (Operative note) — LOINC 11504-8, existing Stage 2 LLM path; Stage 1 template
  for surgical encounters via `_simulate_surgery` path.
- **麻酔記録** (Anesthesia record) — intra-op vital signs, drug administration. Requires
  anesthesiologist staff role.
- **IC document** (Informed consent documentation) — pre-procedure consent form.
  LOINC 64280-2. Triggered by procedure scheduling.
- **薬剤管理指導記録** (Pharmaceutical care record) — pharmacist intervention notes per
  encounter day. Requires pharmacist staff role.
- **リハビリ実施記録** (Rehabilitation session record) — per-session narrative linked to
  ProcedureRecord of type rehab.
- **多職種カンファレンス記録** (Multidisciplinary conference note) — weekly MDT note.
  Triggered by LOS > 7 days or HAI + antibiotic cascade.
- **家族説明記録** (Family explanation / consent note) — end-of-life / ICU transition.
  Linked to code_status enricher.
- **MedicationDispense (pharmacy 払出)** — pharmacy dispense records per MAR cycle.
  Requires pharmacy staff role.
- **Procedure density 強化** — bedside procedures (central line insertion, intubation,
  lumbar puncture) + surgical catalog for OR encounters.

### γ phase — Transitions + communication

- **MSW / Discharge planning document** — social work assessment + discharge plan.
  LOINC 18776-5 variant.
- **紹介状** (Referral letter / Reply letter) — inter-facility communication.
  LOINC 57133-1 / 57134-9.
- **主治医意見書** (Physician's opinion report for long-term care assessment) — JP 介護保険
  mandatory document.
- **初診時記録** (Initial visit record) — first outpatient encounter narrative.
- **Appointment + AppointmentResponse** — outpatient scheduling cycle.
- **Communication** — patient/provider messaging. FHIR R4 Communication resource.
- **Flag** — clinical alert flags (allergy / fall risk / isolation).

### δ phase — Advanced clinical documentation

- **Pathology / Cytology report** — biopsy / PAP smear / FNAB results.
  Linked to Procedure + Specimen resources.
- **CarePlan** (goal-oriented care coordination) — multi-encounter goal tracking.
- **Goal** — patient-specific care goals linked to CarePlan.
- **EpisodeOfCare** — chronic disease episode tracking across readmission chain.
- **AdverseEvent** — drug adverse event documentation.
- **DetectedIssue** — clinical decision support alerts.
- **死亡診断書** (Death certificate) — JP mandatory document for deceased encounters.
  Requires `cause_of_death` enricher.
- **Pre/Post-op evaluation** — anesthesia consult note pre-surgery.
- **OR nursing record** — circulating/scrub nurse intra-op documentation.

### ε phase — Infrastructure event granularity

- **ADT location transfer** — ward transfer records as Encounter.location[] events.
  Requires admission/transfer/discharge event CIF extension.
- **Vital frequency 拡張** — ICU vitals q1h / q30min / continuous monitoring stream.
  Requires monitor data integration.
- **Specimen 独立** — Specimen resource as independent resource (not embedded in DiagnosticReport).
  Required for cross-lab specimen tracking.
- **Per-dose MAR refactor** — current MAR is per-day; upgrade to per-dose with exact
  administration datetime, route, dose, nurse ID.

### Infrastructure — LLM provider integration (separate chain)

- **Bedrock / Ollama / Anthropic 実装** — infrastructure is prepared in `llm_service/`;
  template fallback is the default. LLM integration for Stage 1 document narrative (higher
  quality clinical notes) is a separate chain from document density chain. Integration testing
  requires API key / Ollama install; not part of α-min chain gate.

### α-min-1 per-task Minor findings (carry-over for adversarial fan-out)

(All Minor findings from Tasks 1-12 progress ledger, to be addressed in post-merge
adversarial fan-out review.)

- **Task 1 M-1**: stale `# EncounterRecord` comment in `clinosim/types/document.py:46`
  should be `# Encounter (clinosim.types.encounter)`.
- **Task 1 M-2**: misleading test name `test_narrative_context_default_constructible` —
  rename to `test_narrative_context_fully_specified_construction`.
- **Task 2 M-1**: ~~`normalize_probabilities` not used for `CATEGORY_WEIGHTS` in allergy enricher~~
  RESOLVED: G-1 fix (post-PR-128 adv fan-out) added `normalize_probabilities(weights, fallback="raise")` guard.
- **Task 2 M-2**: reaction entry per-field validator absent (HAI `_validate_hai_organisms`
  pattern would be tighter).
- **Task 3 M-1**: `field(default_factory=tuple)` → `= ()` simplification in frozen dataclass.
- **Task 3 M-2**: `display_ja` "退院サマリ" vs `loinc.yaml` "退院時サマリー" — registry-internal
  label; FHIR output uses `code_lookup` (AD-30 compliant). Verify canonical form.
- **Task 5 M-3**: baseline YAML `complicated_deterioration` has day_7 gap — add day_7 entry
  for YAML completeness even if not clinically needed at α-min.
- **Task 6 M-1**: `_build_social_history` false-positive `facts_used` marker when
  `occupation=""` — suppress for empty string.
- **Task 9 M-1**: `AllergyIntolerance.category` validation comment missing — add inline
  comment referencing FHIR R4 category binding.
- **Task 10 M-1**: `import base64` module-level hoist (currently inline in builder function).
- **Task 10 M-3**: `docStatus` was "preliminary" for all Stage 1 docs — E-1 fix (post-PR-128
  adv fan-out) changed to unconditional "final". `docStatus` coverage was added to test update
  in post-PR-128 composition test (assertion for `docStatus="final"` should be added to
  `test_fhir_documents.py` to pin the Stage-1="final" invariant).
- **Task 12 M-3**: dead code in determinism test.
- **Task 12 M-4**: `"python"` literal in `_sr_helpers.py` should be `sys.executable`.

## Tier 1 #3 α-min-1 post-merge adversarial fan-out findings (2026-07-01)

5-lens parallel adversarial review of PR #128 surfaced 3 Critical + 15 Important. High-impact
+ low-risk subset applied in fix commit (post-PR-128 adversarial review branch). Deferred items:

### Deferred Important findings

- **Lens 1 I-2**: `_build_dref_from_clinical_doc` silently returns `None` on empty `text`
  or missing `loinc_code`; consider adding a `warnings.warn()` or log so silent skips are
  visible in production runs (currently only surfaced by `DocumentReference.ndjson` count
  being lower than expected).

- **Lens 2 I-1/I-2/I-3 (27-YAML boilerplate refactor)**: 27 disease YAML files each repeat
  a `narrative.discharge_instructions` baseline block ("Diet: General diet as tolerated...").
  Refactor: hoist shared baseline to `modules/document/reference_data/physical_exam_findings.yaml`
  and `discharge_instructions.yaml`; keep only disease-specific overrides in each YAML.
  Separate finding: `uncomplicated_improvement` archetype name in disease YAMLs does not
  match `smooth_recovery` in some template generator branches — audit archetype name
  consistency (`complicated_deterioration` / `uncomplicated_improvement` / `smooth_recovery`
  across all 32 disease YAMLs + `template_generator.py` lookup paths).

- **Lens 3 I-3 JP Composition.section.title locale dict**: `Composition.section[].title`
  currently uses the English section key as-is (e.g. `"chief_complaint"`) for JP output.
  Add a JP locale dict mapping section keys to Japanese titles (e.g. `"主訴"`) + wire it
  in `_fhir_composition.py` section builder. Prerequisite: JP section.title spec in
  β-JP-1 locale dict.

- **Lens 4 I-1 LLMNarrativeGenerator singleton**: `LLMNarrativeGenerator` is instantiated
  once per `document_enricher` call (per patient in POST_ENCOUNTER loop). At Stage 2
  (β-JP-1) with real LLM calls, this incurs per-patient setup overhead. Refactor to module-
  level singleton or pass the generator as a parameter from the enricher registry. Stage 1
  (template-only) unaffected since constructor is lightweight.

- **Lens 4 I-3 allergen prevalence field sampling**: `allergens.yaml` carries a `prevalence`
  field per allergen entry (adult rate 0..1), validated at load time. Current enricher ignores
  it and samples entries uniformly (`rng.integers(0, len(entries))`). Either implement
  prevalence-weighted choice (more clinically realistic) OR remove the field from YAML and
  validator to avoid misleading it is used. Deferring to α-min-2 allergy density phase.

- **Lens 5 I-3 AD-30 allergen_display CIF field**: `Allergy.allergen_display` stores English
  text (e.g. `"Penicillin"`), violating AD-30 (CIF stores codes only; display resolved at
  output time via `clinosim.codes`). Pragmatic exception because `_fhir_allergy_intolerance.py`
  uses `allergen_display` as fallback when SNOMED lookup yields no result. Options: (a) remove
  the field and resolve display purely via `code_lookup("snomed-ct", allergen_code, lang)` at
  FHIR export time; (b) document as pragmatic exception in CLAUDE.md with a `# noqa: AD-30`
  comment. Strict fix preferred (option a) but requires verifying all emitted SNOMED codes are
  in `codes/data/snomed-ct.yaml`.

### Deferred Minor (stale doc cross-references)

- **M-1 DESIGN.md ADR summary stale stage**: DESIGN.md ADR summary row for AD-63 says
  "POST_RECORDS" but allergy is POST_POPULATION and document is POST_ENCOUNTER. Fix to
  "POST_POPULATION (allergy, order=10) + POST_ENCOUNTER (document, order=95)".
- **M-2 DQR Composition gap explanation stale**: DQR Known Limitations item 4 says
  `author: []` for empty attending; now `Practitioner/UNKNOWN` placeholder (A-1 fix). Update.
- **M-3 MODULES.md document row misclassification**: MODULES.md may classify the document
  module as POST_RECORDS; correct to POST_ENCOUNTER order=95.
- **M-4 fhir-data-generation-logic.md cross-refs stale**: check `docs/design-guides/` for
  references to `extensions["document"]` or `docStatus="preliminary"` and update.
- **M-5 DQR Known Limitations 4+5 stale post-Task-15**: post-Task-15 notes in DQR may
  reference legacy activator.py allergy path (now deleted). Verify and remove stale references.
- **M-6 C-1 archetype/severity not wired**: `document_enricher` now resolves `disease_protocol`
  from `_disease_id` IPC key but still uses default `severity="moderate"` and
  `clinical_course_archetype="uncomplicated_improvement"`. Wire `severity` and `archetype` by
  storing them in `record.extensions["_severity"]` / `record.extensions["_archetype"]` in
  `inpatient.py` alongside `_disease_id`, then read in `document_enricher` (same IPC pattern).
  This activates the `physical_exam_findings[archetype][day_N]` and course-archetype-specific
  assessment blocks in `template_generator.py`.

## AD-65 Bug A residual gap — disease YAML English narrative content (2026-07-02)

Discovered while implementing Task 11 (Bug A integration test + audit gate) of the AD-65
two-pass CIF architecture chain. Task 9 fixed the code-level locale-routing bug
(`_pick_localized` helper) and Task 10 populated every missing `_en` YAML peer — but **only**
for fields that actually carry a `<key>_en` / `<key>_ja` suffix pair (`ed_note_template.*`,
`outpatient_soap_template.*` in the 46 encounter YAMLs). Both tasks explicitly flagged (see
`.superpowers/sdd/task-9-report.md` §6 concern 2, `task-10-report.md` §7) that two disease-YAML
narrative sources used by ADMISSION_HP (inpatient H&P, LOINC 34117-2) have **no per-language
split at all** — not even a missing `_en` sibling, the data model itself is severity/day-keyed
with Japanese-only content:

- `disease_protocol.narrative.hpi_template.onset_pattern` (keyed by `mild`/`moderate`/`severe`)
- `disease_protocol.narrative.physical_exam_findings` + the shared baseline
  `clinosim/modules/document/reference_data/physical_exam_findings.yaml` (keyed by
  `clinical_course_archetype` × `day_N`, further nested by body system)

`_build_hpi` / `_build_physical_examination` in `template_generator.py` tag `facts_used` with
the module's documented `:ja_only_fallback` suffix when this path fires for a non-`ja` locale
(so the fallback is auditable, not silent) — but the actual section TEXT emitted for a US
cohort is still Japanese. Verified empirically: US p=100 cohort → 15 ADMISSION_HP documents,
630 Japanese characters, 100% located in `physical_examination` (none in `hpi` for this
seed/config, since `ctx.disease_protocol` was `None` for every generated admission_hp
encounter in that run — see the α-min-3-scope `document_enricher` archetype/severity wiring
gap in "M-6 C-1" above; once that's fixed, `hpi` will very likely start emitting Japanese too).

**Task 11 resolution (interim, shipped)**: `clinosim/modules/document/audit.py`'s
`KNOWN_JA_ONLY_FALLBACK_SECTIONS = {"hpi", "physical_examination"}` and the companion
`tests/integration/test_bug_a_us_hp_english_only.py` both exclude these two sections from
the zero-ja-chars assertion so the gate tracks the actual Bug-A locale-routing fix (any OTHER
section leaking Japanese still fails hard) rather than perpetually red on a known, separate,
tracked issue.

**Follow-up needed to fully close Bug A for ADMISSION_HP**: author English content for
`hpi_template.onset_pattern` (3 severity keys × 32 diseases) and `physical_exam_findings`
(N archetypes × N days × 5 body systems × 32 diseases + the shared baseline file) — this is a
data-model change (add a language axis to structures that currently have none), not a simple
`_en` sibling-key addition, so it is a distinctly larger undertaking than Task 10's 46-file
sweep. Recommend a dedicated chain (own SDD task set) rather than folding into AD-65 Bug A.
Once the data gap closes, remove `hpi` / `physical_examination` from
`KNOWN_JA_ONLY_FALLBACK_SECTIONS` and re-verify both the audit gate and the integration test
still pass with the exclusion removed (expect them to pass unconditionally at that point).

## AD-65 adv-1 deferred (2026-07-02)

Findings from PR #131 (`feature/tier1-narrative-stage2-architecture`) adv-1 5-lens
adversarial review that were triaged as out-of-scope for the fix chain. All are pre-existing
concerns or β-JP-1 (LLM narrative pass) scope, not landing in the AD-65 fix work.

- **L3 I-1 `Practitioner/UNKNOWN` fallback dangling reference**: `_bb_care_teams` emits
  `member.reference = "Practitioner/UNKNOWN"` when the attending id is empty. FHIR R4
  reference integrity says every reference must resolve to an emitted resource — no
  `Practitioner/UNKNOWN` resource is emitted anywhere. Pre-existing broader design issue
  (predates AD-65); options are (a) emit a synthetic UNKNOWN Practitioner, (b) skip the
  participant entirely, (c) use `identifier.value="UNKNOWN"` without a reference. Decision
  needs cross-team alignment.
- **L3 I-2 `Patient/` empty-id dangling reference**: similar pattern where an encounter with
  no patient id emits `Patient/`. Pre-existing; the boundary-raise approach (fail early
  when patient_id empty) is preferred over silent fallback.
- **L3 I-4 Bug A partial — HPI + physical_examination YAML restructure**: already tracked in
  the "AD-65 Bug A residual gap — disease YAML English narrative content" section above.
- **L4 IMPT-2 `_deterministic_timestamp` constant-per-pass → per-doc mix**: current impl
  returns the SAME timestamp for every document in a single narrative pass (base + rng_seed
  offset only). Realism would be per-doc seeded from `(doc.document_id, rng_seed)`. Session
  28 tracked as separate follow-up.
- **L4 IMPT-3 re-narrate orphan file cleanup on same version_id**: re-running narrate on the
  same version_id after a disease/encounter YAML edit that DROPPED a document leaves the
  stale narrative file on disk. CIFReader logs it as orphan but doesn't unlink. Add a
  pre-run cleanup pass or a `--overwrite` flag.
- **L4 IMPT-4 β-JP-1 `NarrativeOutput.metadata.get("generator", ...)` override hook +
  `doc_status` field**: LLMNarrativePass needs a way to signal `preliminary` vs `final`
  narrative status; wire `NarrativeOutput.metadata["doc_status"]` → CIF stub
  `doc_status` field → FHIR `DocumentReference.docStatus` / `Composition.status`. Defer to
  β-JP-1 planning.
- **L2 I-4 Encounter YAML `_en/_ja` peer requirement CI enforcement**: Task 10 (α-min-2)
  populated missing `_en` peers for all 46 encounter YAMLs; add a `_validate_*` gate at
  `load_encounter_condition` time so a future YAML edit that adds a `_ja`-only key raises
  at import.
- **L2 I-5 `current_version.txt` write helper (4-site DRY refactor)**: `open(..., "w") as f:
  f.write("template")` appears in CLI test-disease-generate, test-encounter-generate,
  generate, and narrate. Extract a helper in `cif_writer.py` /
  `clinosim/modules/document/narrative/passes.py`.
- **L2 M-4 `nursing_enricher` function rename to `nursing_assignment_enricher`**:
  CLAUDE.md AD-64 rule already spells out the naming convention (`nursing_assignment`
  for POST_ENCOUNTER order=94 vs `nursing_flowsheets` for POST_RECORDS order=20). Code
  hasn't been renamed yet; the enricher name in `enrichers.py:register_builtin_enrichers`
  is still `nursing`. Cosmetic, low priority.
- **L2 M-5 Integration tests using `ForcedScenario` instead of subprocess p=800**:
  `tests/integration/test_bug_c_triage_all_levels.py` and siblings launch the CLI via
  `subprocess.run` with p=800 which is slow (~30s each). Migrate to
  `ForcedScenario(disease_id=..., count=800)` + `run_forced` for a ~5x speedup.
- **L3 M-1 through M-8 β-JP-1 concerns**: (a) section title JP localization,
  (b) section.code LOINC dispatch, (c) docStatus dispatch, (d) DocumentReference.identifier
  emission, (e) US Core category tag, (f) XHTML `<br/>` escaping, (g) empty div status handling,
  (h) `Encounter.priority` JTAS/ESI mapping. All defer to β-JP-1.
- **L1 M-1 through M-4 cosmetic**: (a) CIFReader multi-encounter walk (currently walks
  encounters[0] only for narrative merge — a multi-encounter patient with narratives on
  encounters[1] would silently drop them; matters for the follow-up-visit scenario),
  (b) `--narrative-version` typo warn (already raise-fired via F-1, cosmetic UX enhancement
  possible), (c) test fixture format_type sanity, (d) manifest timestamp pin.
- **L5 Minor-1 through Minor-6 TODO.md missing entries for Task 3 known issues**: Task 3
  landed several known issues (e.g. sanity check on progress note LOS bounds, discharge
  summary conditional on discharge_datetime) that never made it into TODO.md as formal
  entries.
- **L1 M-1 `NURSING_LOINCS` inline in integration test file (Lens 2 M-1)**: at least one
  integration test hardcodes `{"78390-2", "34746-8", "34745-0"}` instead of importing
  `NURSING_LOINCS` from `clinosim.modules.document`. Should import; low-impact but drift
  risk once the YAML changes.

Full triage report: `/private/tmp/claude-*/adv1_ad65/triage.md` in the fix session
(reproducible from the 5-lens pass over PR #131 HEAD `c61914c716`).


## Common-logic unification review — deferred chains (2026-07-02, session 31)

Source: 4-lens module-wide audit (loader / code-mapping+i18n / generation+narrative IF /
docs) + `docs/design-notes/2026-07-02-grand-design-review-and-roadmap.md` (§3, canonical
prioritization). The byte-identical subset (R1-R7) landed on
`refactor/common-logic-unification`; everything below changes behavior/schema and needs
its own chain.

### ★★★ N-chain: Narrative interface unification (β-JP-1 prerequisite)

- **N-1 generator contract**: add `NarrativeGenerator` Protocol to `clinosim/types/document.py`
  (`generate(ctx, spec) -> NarrativeOutput`); `TemplateNarrativePass` takes the generator by
  constructor injection (currently hardcodes `TemplateNarrativeGenerator()` at
  `document/narrative/passes.py:262`). Decide fate of the ORPHANED α-min-1 Task 7 machinery
  (`llm_generator.py` / `replacement_strategy.py` / `cache.py` — `apply_replacement_strategy`,
  `NarrativeCache`, `DocumentTypeSpec.stage2_strategy` / `llm_enabled_sections` are all
  currently unreachable): wire it under `NarrativePass` per master plan §3 (D template-as-seed
  + E cache + B section-level) or delete it. Aspirational scaffold = PR-90 class risk.
  Also: export public API from empty `llm_service/__init__.py`.
- **N-2 provider unification**: two incompatible protocols share the name `LLMProvider`
  (`narrative/replacement_strategy.py:28 generate(prompt)->str` vs
  `llm_service/providers/base.py:24 complete(...)->ProviderResponse`). Keep the llm_service
  one; thin adapter on the narrative side. Structurally guarantees AD-11.
- **N-3 prompt ownership**: prompts live ONLY in `llm_service/prompts/{en,ja}/*.yaml` (AD-40),
  consumed via PromptRegistry keyed by (doc_type, language); replace `_build_seed_prompt`
  inline assembly. Unify `DocumentType` (9) vs `LLMTaskType` narrative subset drift.
- **N-4 (optional, incremental)**: data-drive `template_generator.py` (1446-line Python string
  assembly) into per-section YAML templates so new doc types need no Python edits.

#### N-chain adv-1 deferred

- **`narrative/cache.py get_default_cache()` singleton = test-only dead seam**: no production
  code path uses the module-level `_default_cache` (LLMNarrativePass owns a per-run
  `NarrativeCache` instance; LLMNarrativeGenerator defaults to a fresh instance). Remove the
  singleton + its test, or wire it deliberately, in a later cleanup.
- **`NarrativePass._build_context` degenerate context fields** (adv-1 reviewer note):
  the production pass path passes `disease_protocol=None` / `clinical_course_archetype`
  fallback `""` / `severity` fallback `""` / `day_index=0` into `NarrativeContext` —
  already documented as spec §6 deferred (structural CIF does not yet carry per-day
  clinical-course context for Stage 2). Cross-reference: the C-1 fix (adv-1) made the
  layer-1 cache safe against this degeneration by adding the template-seed hash to the
  cache key, but richer per-day context remains deferred to spec §6.

### ★★ AD-30 chain: display-in-CIF removal (CIF schema change + golden regen)

- `types/allergy.py:18,28` `manifestation_display`/`allergen_display` (populated at
  `allergy/engine.py:132,140`; builder already re-resolves via code_lookup → dead data).
- `types/imaging.py:27` `body_site_display` (populated from `display_en` at
  `imaging/engine.py:277`).

### ★ Display-dict → codes YAML migration

Python clinical display dicts to migrate to `codes/data/*.yaml` (en+ja) + `code_lookup`:
`_fhir_reference_data.py` (`_CONDITION_SHORT_NAME`, `_ENCOUNTER_TYPE_SNOMED_JA`),
`_fhir_patient.py` (marital/lang), `_fhir_microbiology.py` (`_SUSCEPTIBILITY_DISPLAY`),
`_fhir_allergy_intolerance.py` (status displays), `_fhir_care_team.py` (category en/ja),
`_fhir_endpoint.py` hardcoded displays ("DICOM WADO-RS").

### ★ Dual-access sweep

- Read side: remaining `isinstance(x, dict)` branches → `_o()` (`_fhir_observations.py:431`,
  `csv_adapter.py:290-293`, `_fhir_conditions.py:53,136,183`, `_fhir_device.py:23`,
  `_fhir_hai.py:24`, `_fhir_immunization.py:31`, `observation/nursing_enricher.py:36,70`).
- Write side: NO shared helper exists; `if isinstance(rec, dict): rec["x"]=... else: rec.x=...`
  scattered across 7+ enrichers → add `set_attr_or_key()` to `_shared.py` and sweep.

### Single items (ride along with related chains)

- `PrescriptionRecord.issue_date` precision gap — inpatient discharge prescription
  uses `admission_time` rather than true discharge datetime (deliberate simplification:
  `encounter.discharge_datetime` is not finalized at `_build_discharge_rx()` call site
  in `clinosim/simulator/inpatient.py`, and is `None` for AD-32 snapshot-truncated
  in-progress encounters). If closer precision needed later, move `_build_discharge_rx()`
  call to after discharge_datetime finalization, or duplicate the discharge formula at
  call site.
- Dead Bundle-timestamp footgun — `clinosim/modules/output/_fhir_facility.py:159` and
  `clinosim/modules/output/fhir_r4_adapter.py:456` both call `datetime.now()` to
  populate `Bundle["timestamp"]`, but this field is confirmed never read or serialized
  to output. Scope-clean from determinism chain (only sentinel-default fields +
  PhysiologicalState.timestamp + PrescriptionRecord.issue_date were in scope), but
  track to prevent future refactors accidentally propagating this unread wall-clock
  value into real output without noticing non-determinism.
- Move `DiagnosisCandidate` / `DifferentialDiagnosis` (`diagnosis/engine.py:51,60`) to
  `clinosim/types/` (types rule).
- `inpatient.py:1826` unknown-condition path: call `scenario_flags_from_protocol(None)` in the
  merge instead of comment-justified omission (J5-class risk).
- Unify locale-loader unsupported-country contract to "return {}" (immunization / code_status /
  family_history currently silently fall back to US; care_level is the compliant precedent).
- Root `spec.md` (2026-06-05): add historical-document header pointing to DESIGN.md +
  `clinosim/modules/output/SPEC.md`.
- DESIGN.md: note AD-1/2/12/14/15/27 numbering gaps as reserved/withdrawn; sort compact table.
