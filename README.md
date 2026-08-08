# clinosim

> **Clinically Realistic Hospital Data Simulator** — Generate FHIR R4 EHR data from a virtual hospital

[![CI](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-84%25-yellowgreen)](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml)
[![Docs](https://github.com/TomoOkuyama/clinosim/actions/workflows/docs.yml/badge.svg?branch=master)](https://tomookuyama.github.io/clinosim/)
[![PyPI](https://img.shields.io/pypi/v/clinosim.svg?label=PyPI&color=blue)](https://pypi.org/project/clinosim/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4%20Bulk-orange)](https://hl7.org/fhir/uv/bulkdata/)
[![Status](https://img.shields.io/badge/status-v0.2-yellow)]()

📚 **Documentation site**: [tomookuyama.github.io/clinosim](https://tomookuyama.github.io/clinosim/) *(deployed from `master` on every push)*

🇯🇵 **日本語版**: [README.ja.md](README.ja.md)

> ⚠️ **Personal project disclaimer**: This is an independent personal project and is **not** an official product of any company or organization. All design decisions and code are the responsibility of the individual contributors listed in `pyproject.toml`.
>
> ⚠️ **Synthetic data only**: All output is **fully synthetic**. clinosim does not ingest, reference, or reproduce any real patient data or PHI/PII. The output is **not intended for clinical use** and must not be relied upon for any diagnostic, therapeutic, or care decision.

**clinosim** generates synthetic EHR data through **forward simulation** starting from a population. Rather than producing random values, every patient carries a hidden **13-variable physiological state**, and all observations (labs, vitals, medications, diagnoses) are derived from that state — ensuring **clinically coherent** data.

Primary use cases:
- Training data for medical AI/ML models
- EHR system testing and QA
- Clinical research simulation
- Educational case datasets

---

## Why clinosim?

Most synthetic-EHR tools produce records by sampling from disease
distributions. **clinosim runs the disease.** Every patient carries a
hidden 13-variable physiological state, and every lab / vital /
medication is derived from that state. A CKD patient's ED creatinine is
elevated even when they present for something unrelated. A
warfarin-anticoagulated patient sits in the therapeutic PT-INR band. A
sepsis patient shows the WBC / CRP / lactate cascade.

Three concrete differentiators:

- **Clinical coherence by construction.** Not a post-hoc filter — the
  physiology model makes incoherent labs impossible.
- **JP + US natively.** JP Core profile compliance for 16 primary FHIR
  resource types, JLAC10 / MHLW YJ codes, JP names / addresses /
  insurance out of the box. Not an English-only tool with translations
  bolted on.
- **YAML-driven extension.** 32 inpatient diseases + 46 ED / outpatient
  conditions are all data files, not code. Adding a disease is editing
  YAML.

### How clinosim compares to Synthea

[Synthea](https://synthetichealth.github.io/synthea/) (the widely-used
state-transition simulator by MITRE) and clinosim tackle synthetic EHR
from different angles. Both are open source and both emit FHIR — the
differences are in modeling approach and locale coverage.

| Dimension | clinosim | Synthea |
|---|---|---|
| Modeling approach | Physiology-driven forward simulation (13-var hidden state per patient) | State-transition modules per condition |
| Coherence between labs / vitals | Guaranteed by shared physiological state | Independent per module |
| Native FHIR R4 output | Bulk Data Access NDJSON, one file per ResourceType | FHIR R4 JSON per patient |
| JP Core profile compliance | 16 resource types (Patient / Condition / Encounter / Observation / MedicationRequest / DiagnosticReport / Procedure / Immunization / Coverage / ...) | Not a design goal |
| Multi-locale (US + JP) | Both first-class; JP names, addresses, insurance, JLAC10, MHLW YJ | US-first; internationalization via community modules |
| Determinism guarantee | Byte-identical output within a MINOR release for the same seed | Deterministic per-run seed |
| Extension model | YAML-driven (edit a file, no code) | Java module (`.json` state machines + code) |
| Runtime | Python 3.11+ | Java 11+ |
| License | MIT | Apache 2.0 |

**When to use which:**

- **clinosim** — you need clinically coherent labs / vitals, JP output,
  or want to iterate on disease definitions without touching Java code.
- **Synthea** — you need a broad US population with well-established
  disease modules and a mature downstream tooling ecosystem.

They're not exclusive — both write FHIR, and a Synthea comparison
harness (same evaluation metrics on both sides) is on the roadmap.

### Sample output — one physiology-driven lab

For a JP patient on chronic warfarin for atrial fibrillation, clinosim
emits a PT-INR Observation like:

```json
{
  "resourceType": "Observation",
  "id": "lab-enc-jp-042-15-pt-inr",
  "meta": { "profile": [
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"
  ]},
  "status": "final",
  "category": [{"coding": [{
    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
    "code": "laboratory",
    "display": "検体検査"
  }]}],
  "code": {"coding": [
    { "system": "urn:oid:1.2.392.200119.4.504", "code": "2B160000002327101",
      "display": "PT-INR" },
    { "system": "http://loinc.org", "code": "6301-6",
      "display": "INR in Platelet poor plasma by Coagulation assay" }
  ]},
  "subject": {"reference": "Patient/jp-042"},
  "effectiveDateTime": "2026-04-15T08:00:00+09:00",
  "valueQuantity": {"value": 2.7, "unit": "{INR}",
    "system": "http://unitsofmeasure.org", "code": "{INR}"},
  "referenceRange": [{
    "low": {"value": 2.0}, "high": {"value": 3.0},
    "text": "Warfarin therapeutic (AF stroke prevention)"
  }],
  "interpretation": [{"coding": [{
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "code": "N",
    "display": "Normal"
  }]}]
}
```

Notice: the INR value 2.7 wasn't sampled from a "PT-INR normal range"
— the physiology engine detected warfarin from the chronic-medication
list, placed this patient in the 2.0–3.0 therapeutic band, and picked
the reference range and interpretation to match. Change the seed → a
different but still-therapeutic value. Remove the warfarin → a normal
(~1.0) INR next run. This is what "clinical coherence by construction"
means in practice.

### Demo

> 📷 **Demo GIF placeholder.** An asciinema recording of
> `clinosim simulate --country JP --population 100 --seed 42` will land
> at `docs/assets/demo.gif` — see the
> [good first issues](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue)
> tracker for the current TODO.
>
**Architecture** — the population → CIF → FHIR pipeline:

![clinosim end-to-end pipeline: population generation → physiology + encounter simulation → enricher stages → CIF → format adapters → NDJSON output](docs/assets/pipeline.svg)

For a step-by-step walkthrough see [`docs/design-guides/data-generation-walkthrough.md`](docs/design-guides/data-generation-walkthrough.md).

---

## Table of Contents

- [Why clinosim?](#why-clinosim)
  - [How clinosim compares to Synthea](#how-clinosim-compares-to-synthea)
  - [Sample output](#sample-output--one-physiology-driven-lab)
  - [Demo](#demo)
- [Features](#features)
- [Installation](#installation)
- [Versioning & Releases](#versioning--releases)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Output Formats](#output-formats)
- [Data Flow](#data-flow)
- [Module Architecture](#module-architecture)
- [Code Systems & Authoritative Sources](#code-systems--authoritative-sources)
- [Supported Diseases](#supported-diseases)
- [Multi-Country Support](#multi-country-support)
- [Hospital Configuration](#hospital-configuration)
- [Design Philosophy](#design-philosophy)
- [Testing](#testing)
  - [Reproducibility](#reproducibility)
- [Datasets](#datasets)
- [Evaluation](#evaluation)
- [Extension Guide](#extension-guide)
- [Governance & Community](#governance--community)
- [License](#license)

---

## Module Map

For a single-page overview of all 30 modules, their dependencies, typical call chains, and a 5-step new-module quick-start, see **[`MODULES.md`](MODULES.md)**.

Other navigation:

| Looking for | Read |
|---|---|
| ★ **How data is generated** (population → CIF → FHIR, end-to-end for newcomers) | [`docs/design-guides/data-generation-walkthrough.md`](docs/design-guides/data-generation-walkthrough.md) |
| New-contributor reading path (concept → rules → walkthrough) | [`docs/design-guides/README.md`](docs/design-guides/README.md) |
| Scenario / medication flags | [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Architecture + ADR table | [`DESIGN.md`](DESIGN.md) |
| Module author HOW-TO + PR verification guide | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) |
| New module template | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |

---

## Quality & Compliance

clinosim's true goal is **FHIR R4 + JP Core compliant output with clinical coherence and JP localization quality**. PRs that change output data are gated by a 3-axis Data Quality Review (structural / clinical / JP language) — see [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) "PR 検証ガイド".

Verification framework: `clinosim audit run` (AD-60) is the unified new-feature gate — 4 axes (structural / clinical / jp_language / silent_no_op) + Module-owned audit.py plug-ins. byte-diff stays as a separate refactor-PR mechanic.

Latest reviews:
- [`docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-1-dqr.md`](docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-1-dqr.md) — Tier 1 #3 Document Density α-min-1: **1/4 axes PASS** (silent_no_op 17/17 PASS). DocumentReference 0 → 23,760 (US) / 3,909 (JP); Composition 0 → 9,275 / 474; ClinicalImpression 0 → 23,760 / 3,909. AllergyIntolerance SNOMED upgrade. [AD-63]
- [`docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`](docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md) — Tier 1 #3 Document Density α-min-2: **2/4 axes PASS** (clinical PASS + silent_no_op 25/25 PASS). CareTeam 0 → 158,811 (US) / 16,046 (JP) ★ GAP CLOSED. DocumentReference +22,798 (nursing shift notes). Composition +8,671 (nursing 2 types). 3 new always-on POST_ENCOUNTER Modules. [AD-64] — see [master plan](docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md)
- [`docs/reviews/2026-06-30-tier1-imaging-chain-dqr.md`](docs/reviews/2026-06-30-tier1-imaging-chain-dqr.md) — Tier 1 #2 Imaging chain α-min: **4 axes PASS** (structural / clinical / JP language / silent_no_op) on JP p=5k + US p=10k. ImagingStudy + Endpoint + radiology DR + imaging SR. 15/15 lift_firing_proof PASS. Bug found+fixed: encounter_id invariant for `_simulate_unknown_condition`. [AD-62]
- [`docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md`](docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md) — PR1 ServiceRequest lab order lifecycle: **4 axes PASS** on US p=10k + JP p=5k. 362k + 42k SR, panel SR 5.3%. [AD-61]
- [`docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`](docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md) — Phase 3b-2 HAI culture S/I/R susceptibility chain: **all 3 axes PASS** + antibiogram firing proof + byte-diff NDJSON IDENTICAL
- [`docs/reviews/2026-06-25-clinosim-audit-baseline.md`](docs/reviews/2026-06-25-clinosim-audit-baseline.md) — first `clinosim audit run` baseline (all 4 axes for `modules/hai`; structural / jp_language / silent_no_op PASS, clinical WARN at p=2000 rare-event)
- [`docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review-post-fix.md`](docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review-post-fix.md) — Phase 3a HAI lift after the xhigh code-review hardening: **all 3 axes PASS** + byte-diff 37/37 NDJSON IDENTICAL + closed-form lift firing proof
- [`docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md`](docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md) — Phase 3a initial DQR (pre-fix; superseded by the post-fix review above)
- [`docs/reviews/2026-06-24-master-comprehensive-dqr.md`](docs/reviews/2026-06-24-master-comprehensive-dqr.md) — comprehensive master review (June 2026), **all 3 axes PASS** on master @ p=10,000 (US) + p=5,000 (JP):

- **Structural**: 3.4M + 434K Observations across 10 FHIR resource types; id uniqueness 100%; reference integrity 100%
- **Clinical**: 17 major lab analytes in clinically valid bands for both locales (DKA acidosis, ACS troponin, sepsis WBC/CRP/lactate, HF BNP, VTE D-dimer, AF warfarin therapeutic INR, etc.)
- **JP Language**: 100% Japanese display across Condition / DR / Med / Immunization / care_level / smoking / alcohol; JLAC10 codes with JCCLS-JSLM authoritative display; 0 US-locale Japanese leakage

---

## Features

- **HL7 FHIR Bulk Data Access** compliant NDJSON output (Patient.ndjson, Encounter.ndjson, ...)
- **Three-stage pipeline**: `generate` (structured CIF) → `narrate` (LLM clinical documents) → `export-fhir` (FHIR R4 NDJSON). Each stage is re-runnable and independently testable.
- **Clinical documents as FHIR DocumentReference** (LOINC-coded): Discharge Summary, Death Note, Operative Note, Admission H&P, Procedure Note — each base64-encoded and linked to Patient/Encounter/Procedure
- **Pluggable LLM providers** (Ollama, AWS Bedrock, Mock) with YAML-driven factory and SHA256 disk cache for reproducibility and cost control
- **13-variable physiology model** ensures labs/vitals are physiologically and clinically coherent
- **Bayesian differential diagnosis** with likelihood ratios; 6 disease trajectory archetypes
- **Authoritative code systems** (ICD-10-CM, LOINC, RxNorm, JLAC10, YJ codes, CPT, SNOMED CT subset) with multilingual display
- **32 diseases + 46 ED/outpatient conditions** defined in YAML (no code changes to add new ones)
- **JCCLS reference ranges 2022** for Japanese labs; Tietz/Mayo for US
- **NEWS2-compatible vitals** including AVPU consciousness level and supplemental oxygen
- **Microbiology cultures + antibiotic susceptibility** for bacterial infections (sepsis, pneumonia, UTI, cellulitis): organism identification (SNOMED) and S/I/R antibiograms — emitted as FHIR `DiagnosticReport` + `Specimen` + `Observation`. All codes data-driven (`observation/reference_data/microbiology.yaml`)
- **Cardiac injury markers** (Troponin I, CK-MB): physiology-derived and clinically coherent — MI-level in ACS, mild type-2 elevation in other cardiac stress, negative in non-cardiac rule-outs (ED chest pain/syncope), with a CKD clearance confounder and sex-specific cutoffs. Lab order aliases (stat/serial variants) canonicalize across inpatient/ED/outpatient
- **Arterial blood gas** (pH, pCO₂, pO₂, HCO₃): an `ABG` order expands into its component results (data-driven panel), so respiratory/metabolic cohorts (COPD, pneumonia, asthma, DKA) get blood-gas data
- **Dysnatremia coherence**: serum sodium tracks the disease — dilutional hyponatremia in chronic heart failure / cirrhosis, SIADH hyponatremia in pneumonia and HF exacerbation, and hypernatremia from dehydration — via a `sodium_status` physiology axis (disease drivers are data-driven)
- **Glycemic coherence**: HbA1c reflects each diabetic's chronic glycemic control (a `glycemic_control` axis, median ~6.8%, tail to ~12%), and Glucose baseline co-moves with it — so a poorly-controlled diabetic shows both high HbA1c and high glucose. Scenarios that imply poor control (DKA) drive HbA1c high even for new-onset diabetes, and the diabetes `Condition.stage` HbA1c display matches the labs.
- **Unified physiology-driven labs across venues** (AD-57): inpatient, ED, and outpatient all derive lab true values from the patient's physiological state, so comorbidities are reflected everywhere (e.g. a CKD patient's ED creatinine is elevated, not a fixed normal)
- **AKI / DKA admit-day calibration** to published clinical bands: AKI admit Creatinine sits in the KDIGO 2-3 envelope (p50 ~3.3 mg/dL US, ~4.1 JP — not ESRD-level), and DKA admit HCO₃ stratifies into the ADA severity bands (severe <10, moderate 10-15, mild 15-18 mEq/L). Surgical (formula-only) calibration: state variables, coupling rules, and disease YAMLs unchanged, so patient cohorts and downstream complications match master byte-for-byte at fixed seed
- **FHIR `DiagnosticReport` panel grouping** (CBC / BMP / LFT / Lipid / Coag / UA / ABG) with authoritative LOINC panel codes: lab Observations drawn in the same encounter-day are grouped into one DR per panel, with `result[]` references back to the component Observations. Existing microbiology DRs (blood/urine/sputum/wound culture) continue to emit unchanged
- **FHIR `ServiceRequest` lab order lifecycle** (PR1, 2026-06-29) — panel-aware grouping (CBC/BMP/LFT/ABG/Lipid/Coag/UA): 1 SR per panel instance, stand-alone orders emit 1 SR each. JP Core PLAC identifier (HL7 v2-0203), dual category coding (SNOMED 108252007 + v2-0074 LAB). US p=10k: 362k SR; JP p=5k: 42k SR; panel SR 5.3%. [AD-61]
- **Imaging metadata chain** (Tier 1 #2, 2026-06-30) — ImagingStudy (DCM modality, multi-series, urn:dicom:uid identifier), Endpoint (WADO-RS URL placeholder for future PACS / image-gen AI integration), radiology DiagnosticReport (findings + impression in `text.div` + `conclusion`), and ServiceRequest with imaging category (SNOMED 363679005 + v2-0074 RAD). PR1 scope: CR (X-ray) + CT modalities, chest + head body sites, bacterial / aspiration pneumonia + hemorrhagic stroke. [AD-62]
- **Document Density chain α-min-1** (Tier 1 #3, 2026-07-01) — Stage 1 default template-based clinical document emission: DocumentReference (Admission H&P + Progress Note + Discharge Summary, LOINC-coded, base64-encoded), Composition (structured discharge summary with 7 sections), and ClinicalImpression (daily clinical impression) for all inpatient/ICU/rehab encounters. AllergyIntolerance upgraded to 8-field SNOMED-coded schema (allergen SNOMED + reaction + category + criticality + clinical/verification status). US p=10k: 23,760 DR + 9,275 Composition + 23,760 CI; JP p=5k: 3,909 DR + 474 Composition + 3,909 CI. [AD-63]
- **Document Density chain α-min-2** (Tier 1 #3, 2026-07-01) — CareTeam FHIR resource (1:1 with Encounter, attending physician + primary nurse), 3 nursing document types (ADMISSION_NURSING_ASSESSMENT 78390-2 / NURSING_SHIFT_NOTE 34746-8 / NURSING_DISCHARGE_SUMMARY 34745-0), triage module (JTAS/ESI), 46 encounter YAML narrative extensions. US p=10k: CareTeam 158,811 + DR 46,558 + Composition 17,946. silent_no_op 25/25 PASS, clinical axis PASS. [AD-64] — see [master plan](docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md)
- **CBC / BMP panel orders emit canonical children** with **per-specimen RNG isolation**: a `{test:"CBC"}` admission order produces WBC + Hb + Hct + Plt as four child Observations from one specimen (and `{test:"BMP"}` produces the **full canonical 8** — Na/K/Cl/HCO3/BUN/Cr/Glucose/Ca — from one specimen), with the panel's specimen-rejection / hemolysis draws sourced from a per-parent sub-RNG (`panel_specimen_seed(parent_order_id)`) so a panel registry edit cannot cascade into unrelated patients' cohorts (AD-16). Per-panel `min_components` thresholds follow the canonical-N − 1 rule (**CBC = 3, BMP = 7** post Cl/Ca physiology PR) — validated by audit. **Individual (non-panel-child) lab orders** are likewise isolated via `individual_lab_seed(order_id)`, so any future analyte added to `derive_lab_values` cannot leak through the master stream
- **Anion-gap-aware chloride** (`anion_gap_status` axis): Cl follows Na for electroneutrality plus HCO3 reciprocity gated by the AG axis — high-AG acidosis (DKA / sepsis / uremia) keeps Cl near normal as unmeasured anion absorbs the HCO3 deficit, non-AG acidosis (diarrhea / RTA) gives hyperchloremic Cl. The axis is orthogonal to the AD-57 acid-base 2-axis (does NOT affect pH/HCO3/pCO2) and disease YAMLs set it where AG is recorded as varying in real-world BMPs
- **Coag panel activation** (LOINC 24373-3 = aPTT and PT/INR panel): `APTT`, `PT` (seconds = 12 × PT_INR ISI=1.0 invariant), and `Fibrinogen` all derive from existing `coagulation_status` + `inflammation_level` axes — APTT proportional to DIC severity, PT mathematically tied to the existing PT_INR, Fibrinogen **biphasic** (acute-phase reactant ↑ in inflammation, consumed ↓ in DIC). PR also adds `Coag` / `LFT` / `Lipid` / `UA` to `lab_panels.yaml` so panel orders can expand symmetrically with `lab_panel_groups.yaml`. AD-57 BNP-pattern surgical (formula-only, no new state field) + AD-59 per-order RNG isolation keep all additions cohort-neutral (byte-diff vs master @ p=2000 seed=42 shows zero shift in Patient/Encounter/Condition/Med/Procedure/Imaging/Immunization/FamilyHistory NDJSONs)
- **VTE-spectrum D-dimer** (LOINC 48065-7 / JLAC10 2B140): `D_dimer` derive from `coagulation_status` + `inflammation_level` + age + a new `causes_vte` scenario flag (set on PE / DVT / embolic ischemic stroke). PE / DVT / cerebral_infarction admit-day D-dimer p50 ≥ 4 ug/mL FEU (clinically positive); sepsis without VTE stays non-specific p50 < 2. Hemorrhagic stroke deliberately does NOT get the flag (intracerebral fibrinolysis is captured by `coagulation_status` alone). The scenario-flag wiring is centralized via a `scenario_flags_from_protocol(protocol)` helper — adding any future flag to `derive_lab_values` reaches every call site (inpatient / ED / outpatient) automatically. The fix also cures a latent defect where ED-route MI patients had no troponin upshift because `emergency.py` was calling `derive_lab_values` without the `causes_myocardial_injury` flag
- **Warfarin therapeutic PT-INR coupling** (Phase 2b): `PT_INR` derivation now reads a sibling `medication_flags_from_context(patient, medication_orders, admission_date, current_day)` helper that detects warfarin from (1) `patient.current_medications` (chronic AC for AF I48 + post-VTE I26 / I82 / I63 via `chronic_medications.yaml`) or (2) in-hospital warfarin orders ≥ 3 days old (loading-dose rule, peeked from `all_orders`). When `on_warfarin=True`, PT_INR overrides to 2.5 + half-gain comorbidity perturbation — so warfarin-only patients sit in the therapeutic 2.0-3.0 band, warfarin + cirrhosis (hepatic ↓) or DIC (coag ↑) compounds into 3.0-3.5 (over-AC bleeding-risk visible), and DOAC (apixaban / rivaroxaban / edoxaban / dabigatran) patients are intentionally NOT detected — INR is not clinically monitored for DOAC. US p=10000 audit: warfarin p50 INR 2.70 (therapeutic), DOAC p50 1.80 ≈ no-AC p50 1.70 (DOAC correctly unshifted). Same `**flags` merge pattern as scenario flags — adding any future medication coupling (steroid → glucose, etc.) reaches every call site through one helper edit
- **Ward + bed Location hierarchy** with PractitionerRole.location assignment
- **Operating rooms** modeled as FHIR Locations; surgical procedures include category (SNOMED), performer.function (surgeon/anaesthetist), bodySite, outcome, and complications
- **Occupational injuries**: 6 work-related conditions (crush injury, industrial burn, fall from height, electrical injury, eye foreign body, chemical exposure) with occupation-based risk multipliers
- **Patient occupation** field (12 categories) with FHIR Observation (LOINC 11341-5, social-history)
- **Social history & SDOH**: smoking status (US Core, LOINC 72166-2 + SNOMED) and alcohol use (LOINC 11331-6) social-history Observations, plus the Japanese long-term-care need level (**要介護度** / 介護保険 区分, JP only, age-driven)
- **Family history**: first-degree relatives (mother/father/siblings) with disease history synthesized from locale prevalence × heritability (correlated with the patient's own chronic conditions) — FHIR `FamilyMemberHistory` (cardiometabolic + major cancers)
- **Code status** (resuscitation status): 4-tier (Full Code / DNR / DNR+DNI / Comfort care) on serious encounters (inpatient always; ED when critical/terminal), age/acuity-driven — FHIR survey `Observation` (SNOMED)
- **Nursing flowsheets** (NEWS2 / GCS / Braden / Morse) and **adult immunization history** (CVX, US/JP schedules) as FHIR Observation / `Immunization`
- **Japanese insurance enrollment** (opt-in, `--jp-insurance`): occupation-driven 社保/国保/後期高齢者, valid 保険者番号/被保険者番号 check digits, マイナンバーカード・マイナ保険証 status — emitted as JP Core FHIR `Coverage` + 保険者 `Organization`. マイナンバー stays internal (never exported).
- **Multilingual FHIR coding**: Condition and Procedure emit dual coding entries (primary language + interop language); Condition code.text includes clinical abbreviations (COPD, CHF, CKD, DM)
- **Snapshot date** support — includes "currently admitted" patients (in-progress encounters)
- **30-day readmission chains** with `prior_encounter_id` linking
- **Multi-country**: US (English) and JP (Japanese) parallel output
- **Fully deterministic** with seed
- **English-first with language fallback** in code systems and LLM prompt templates

---

## Installation

### As a user (recommended)

Once released to PyPI, install the packaged version directly:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install clinosim                # (PyPI upload pending — see fallback below)
clinosim --help
```

**Pre-PyPI fallback** — install straight from GitHub:

```bash
pip install "git+https://github.com/TomoOkuyama/clinosim.git@master"
clinosim --help
```

### As a developer (editable install with dev deps)

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**Requirements**:
- Python 3.11+
- Main dependencies: numpy, scipy, pydantic, pyyaml, httpx
- (Optional) Ollama for local LLM narrative generation
- (Optional) `pip install "clinosim[parquet]"` for CIF Parquet export

---

## Versioning & Releases

clinosim follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html):

- **MAJOR** — incompatible API / CIF / FHIR schema changes.
- **MINOR** — backward-compatible feature additions (new modules, new
  resource types, additional locale support). May change output byte-for-byte
  even at the same seed.
- **PATCH** — backward-compatible bug fixes and data-quality corrections
  that preserve the CIF/FHIR schema. **Byte-identical output within the
  same seed is a hard guarantee for PATCH releases within one MINOR line.**

### Cutting a release

Version lives in exactly one place: `clinosim/__init__.py::__version__`.
`pyproject.toml` reads it dynamically (`[tool.hatch.version]`), so PyPI
metadata, `pip show clinosim`, and `import clinosim; print(clinosim.__version__)`
never drift.

```bash
# 1. Bump the version and update the changelog
$EDITOR clinosim/__init__.py       # e.g. __version__ = "0.2.0"
$EDITOR CHANGELOG.md               # move [Unreleased] entries under [0.2.0] - YYYY-MM-DD

# 2. Commit and tag
git add clinosim/__init__.py CHANGELOG.md
git commit -m "release: v0.2.0"
git tag -a v0.2.0 -m "clinosim v0.2.0"
git push origin master --tags

# 3. Create the GitHub Release
# Draft a new release on GitHub against tag v0.2.0, paste the CHANGELOG entry
# as the release notes, and attach the built wheel + sdist:
python -m pip install --upgrade build
python -m build                    # produces dist/clinosim-0.2.0-py3-none-any.whl + .tar.gz
# then upload dist/* through the GitHub Release UI or `gh release create`.

# 4. (Once PyPI is set up) upload to PyPI
python -m pip install --upgrade twine
python -m twine upload dist/*
```

The `Changelog` URL in `pyproject.toml [project.urls]` points at
`CHANGELOG.md`, so PyPI users can reach the notes without leaving the
package listing.

---

## Quick Start

### CLI

```bash
# === Stage 1: structured simulation (always local, deterministic) ===

# Default: US, past 1 year ending today, 40,000 catchment, 50-bed hospital
clinosim simulate -o ./output

# Custom period (--end is the snapshot date)
clinosim simulate -o ./output --start 2024-01-01 --end 2024-12-31

# Japan 10-bed clinic
clinosim simulate -o ./output \
  --country JP \
  --hospital-config clinosim/config/hospital_small.yaml \
  -p 12000

# === Stage 2: clinical documents ===
# As of α-min-1 (2026-07-01), DocumentReference / Composition / ClinicalImpression
# are generated automatically during Stage 1. The standalone `clinosim narrate`
# subcommand is deprecated; LLM narrative integration is deferred to the β-JP-1
# chain (see docs/roadmap.md).

# === Stage 3: FHIR Bulk Data export ===
clinosim export-fhir --cif-dir ./output/cif

# === Debug / inspection ===

# Forced disease scenario (debugging)
clinosim test-disease bacterial_pneumonia -n 5 --severity moderate

# Encounter unit test
clinosim test-encounter chest_pain_noncardiac --age 65 --sex M

# List available diseases and encounters
clinosim list-diseases
```

### Python API

```python
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig

config = SimulatorConfig(
    catchment_population=40_000,
    country="US",
    random_seed=42,
    snapshot_date="2026-04-08",   # EHR snapshot at this point in time
)
dataset = run_beta(config)

# Access results
for record in dataset.patients:
    enc = record.encounters[0]
    print(f"{record.patient.name.family_name}: {enc.encounter_type} → {enc.status}")
    print(f"  labs={len(record.lab_results)}, vitals={len(record.vital_signs)}")
```

### Code System Lookup

```python
from clinosim.codes import lookup, get_system_uri

lookup("icd-10-cm", "N10", "en")
# → "Acute tubulo-interstitial nephritis"

lookup("icd-10-cm", "N10", "ja")
# → "急性腎盂腎炎"

get_system_uri("loinc")
# → "http://loinc.org"
```

---

## CLI Reference

Moved to [`docs/reference/cli.md`](docs/reference/cli.md) — CLI reference (all subcommands + flags).

## Output Formats

Moved to [`docs/reference/output-formats.md`](docs/reference/output-formats.md) — Output format reference (CIF / FHIR R4 / CSV).

## Data Flow

Moved to [`docs/architecture/data-flow.md`](docs/architecture/data-flow.md) — End-to-end data flow (population → simulation → FHIR export).

## Module Architecture

Moved to [`docs/architecture/module-architecture.md`](docs/architecture/module-architecture.md) — Module architecture — high-level layering.

## Code Systems & Authoritative Sources

Moved to [`docs/reference/code-systems.md`](docs/reference/code-systems.md) — FHIR code system URIs + authoritative-source references.

## Supported Diseases

32 diseases defined in YAML, covering ~80% of acute hospital admissions:

| Category | Diseases |
|---|---|
| **Respiratory** | Bacterial pneumonia, Aspiration pneumonia, COPD exacerbation, Asthma exacerbation, Influenza, Pulmonary embolism |
| **Cardiovascular** | Heart failure exacerbation, Acute MI, Atrial fibrillation/RVR |
| **Neurological** | Cerebral infarction, Hemorrhagic stroke, Subdural hematoma |
| **GI/Hepatic** | GI bleeding, Acute pancreatitis, Ileus, Decompensated cirrhosis |
| **General Surgery** | Acute appendicitis, Acute cholecystitis |
| **Orthopedic** | Hip fracture, Vertebral compression fracture, Wrist fracture |
| **Trauma** | Severe traffic accident |
| **Metabolic** | Diabetic ketoacidosis |
| **Renal** | Acute kidney injury |
| **Infectious** | Sepsis, Urinary tract infection, Cellulitis |
| **Vascular** | Deep vein thrombosis |
| **Occupational (労災)** | Crush injury (hand), Severe industrial burn, Fall from height, Electrical injury |

Plus **46 ED/outpatient conditions** (chest pain, viral gastroenteritis, ankle sprain, annual screening, flu vaccination, dialysis session, etc.) — see `clinosim/modules/encounter/reference_data/`.

Adding new diseases requires **only adding a YAML file** (no code changes). See `clinosim/modules/disease/README.md`.

---

## Multi-Country Support

Moved to [`docs/reference/multi-country.md`](docs/reference/multi-country.md) — Multi-country locale + code-system dispatch reference.

## Hospital Configuration

Moved to [`docs/reference/hospital-configuration.md`](docs/reference/hospital-configuration.md) — Hospital YAML config reference (beds / departments / roster).

## Design Philosophy

1. **State before observation** — Lab values are never generated independently. All observations derive from physiological state.
2. **Process before outcome** — Diagnoses emerge from Bayesian reasoning over test results. Treatment changes are tied to observable clinical triggers.
3. **Institution shapes behavior** — The same disease produces different data depending on healthcare system (insurance, discharge criteria, culture).
4. **Code is the truth** — CIF stores only codes; display text is resolved at output time via the codes module.
5. **YAML-driven extensibility** — Adding a disease = adding a YAML file. No engine code changes.
6. **English-first** — All codes must have English display; other languages are translation attributes.
7. **Authoritative sources** — Code values and English text follow official definitions from CMS/NLM/AMA/WHO/etc.
8. **Single source of truth** — No duplicate data (e.g., CIF doesn't store display, codes module is the only source).

---

## Testing

Moved to [`docs/development/testing.md`](docs/development/testing.md) — Test suite layout, markers, and how to run each tier.

## Datasets

Moved to [`docs/reference/datasets-full.md`](docs/reference/datasets-full.md) — Full dataset descriptions (chronic / disease / population).

## Evaluation

`clinosim eval` scores any generated cohort against three axes —
**structural** (FHIR compliance), **clinical** (physiological
coherence), and **locale** (language + code-system compliance) — and
emits a JSON + Markdown report. Distinct from
[`clinosim audit run`](docs/CONTRIBUTING-modules.md) which is the
internal per-Module PR gate; `eval` is the public-facing tool for
researchers and ML engineers grading synthetic data before using it.

```bash
clinosim dataset build jp-100 --output ./jp-100
clinosim eval -d ./jp-100                           # print Markdown to stdout
clinosim eval -d ./jp-100 --json report.json        # machine-readable
clinosim eval -d ./jp-100 --md report.md --strict   # exit 1 on any FAIL
```

Each axis holds five checks (MVP). Severity-weighted scoring:
CRITICAL = 3, MAJOR = 2, MINOR = 1; PASS = 1.0, WARN = 0.5, FAIL / N/A
= 0. Axis score = 100 × Σ pass-weight / Σ total-weight; overall score
= mean of axis scores. Full reference: [`docs/eval.md`](docs/eval.md).

---

## Extension Guide

Moved to [`docs/reference/extension-guide.md`](docs/reference/extension-guide.md) — How to add a new disease / country / module (short form).

## Module Dependency Graph

Moved to [`docs/architecture/module-dependency-graph.md`](docs/architecture/module-dependency-graph.md) — Import dependency graph across the top-level packages.

## LLM Integration (Optional)

Moved to [`docs/reference/llm-integration.md`](docs/reference/llm-integration.md) — LLM integration reference (currently deferred to β-JP-1).

## Data Quality Validation

```bash
# Compare against published benchmarks (LOS, mortality, complication rates)
clinosim validate -p 5000 --country US
```

Public sources:
- JAMA, NEJM clinical guidelines
- AHRQ Healthcare Cost and Utilization Project (HCUP)
- MHLW Patient Survey (Japan)
- OECD Health Data

Details: `clinosim/modules/validator/README.md`

---

## Disclaimer

clinosim simulates entirely **synthetic** data. No real patient information is used or produced. Generated data is intended for software development, algorithm research, and system testing only. **It must not be used for clinical decision-making**.

---

## Contributing

Contributions are welcome, especially from clinicians who can review the realism of disease modules and physiological mappings.

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Each module's README has extension guidelines.

---

## Governance & Community

clinosim is an independent personal project. Community-facing documents:

| Document | Purpose |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to file issues, propose changes, and open a PR. Includes the DCO signoff requirement (`git commit -s`). |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Contributor Covenant 2.1. Contact: `tomo.okuyama@gmail.com`. |
| [SECURITY.md](SECURITY.md) | How to report vulnerabilities privately via GitHub Security Advisories. **Please do not open public issues for security bugs.** |
| [CITATION.cff](CITATION.cff) | Machine-readable citation metadata — renders as GitHub's "Cite this repository" button. |
| [CHANGELOG.md](CHANGELOG.md) | Keep a Changelog format, [SemVer](https://semver.org/) contract. |
| [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) | Practical playbook for adding a new module / FHIR builder — the how-to layer above the general CONTRIBUTING.md. |
| [Issue templates](.github/ISSUE_TEMPLATE/) | Structured bug report / feature request forms. |
| [Pull request template](.github/PULL_REQUEST_TEMPLATE.md) | PR checklist with determinism impact + DCO reminder. |
| [`good first issue` label](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue) | Starter-friendly tasks currently open. |

CI enforces: unit tests (Python 3.11 + 3.12), integration tests, packaging
(`python -m build` + `twine check`), and DCO signoff. Lint / typecheck are
informational for now while pre-existing debt is being worked down.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

Code system data follows the original registry's license:
- ICD-10-CM, RxNorm: Public domain
- LOINC: LOINC License (free for commercial use)
- WHO ICD-10: WHO Terms of Use
- CPT: AMA Copyright (educational/research subset only)
- JLAC10, YJ, K-codes: MHLW / JCCLS public data

---

## Citation

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2026},
  url    = {https://github.com/TomoOkuyama/clinosim}
}
```

---

## Related Documentation

- [README.ja.md](README.ja.md) — 日本語版 README
- [DESIGN.md](DESIGN.md) — Detailed design document (architecture decisions, ADRs)
- [docs/roadmap.md](docs/roadmap.md) — Development roadmap (points at the GitHub Issues board)
- [CLAUDE.md](CLAUDE.md) — Claude Code development guidelines
- [docs/clinical_documents.md](docs/clinical_documents.md) — Clinical document generation guide (LOINC mapping, prompts, extending to new types)
- [docs/bedrock_setup.md](docs/bedrock_setup.md) — EC2 + AWS Bedrock setup for Stage 2 at scale
- Each module's `README.md` — Module-level API reference
