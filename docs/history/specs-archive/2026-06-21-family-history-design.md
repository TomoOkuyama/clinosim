# Family history (FamilyMemberHistory) — AD-55 Base

**Date:** 2026-06-21
**Status:** approved (design)
**Type:** AD-55 Base data enrichment (always-on)

## Goal

Add family history of disease to every patient and emit it as FHIR
`FamilyMemberHistory`. Family history is core EHR data and drives risk; this adds
clinically coherent first-degree-relative history synthesized from population
prevalence and heritability, correlated with the patient's own chronic conditions.

## Approach

Synthesize, per patient, a small set of first-degree relatives (mother, father,
0–2 siblings) and assign each relative diseases by:

```
P(relative has condition C) = base_prevalence(C, relative_sex, relative_age_bracket)
                              * heritability_multiplier(C)   if the PATIENT has C
```

So a diabetic patient is more likely to have a diabetic parent (genetic
clustering), and a patient without the condition gets the population base rate.
This is the standard, clinically realistic model and needs no household linkage.

### Scope of conditions

Cardiometabolic + major hereditary cancers (ICD base codes):
- Diabetes `E11`, Hypertension `I10`, Coronary artery disease / MI `I25`,
  Stroke `I63`/`I64`, Dyslipidemia `E78`
- Cancers: breast `C50`, colorectal `C18`, lung `C34`, prostate `C61`

Sex restrictions: prostate (`C61`) male relatives only; breast (`C50`) female
relatives only (male breast cancer is rare — excluded for v1 simplicity).

### Relatives

- Mother (`MTH`, female), Father (`FTH`, male), 0–2 siblings (`NSIB`, random sex).
- Relative age derived from patient age: parents +25–35 yr; siblings ±0–12 yr.
  Age bracket selects the prevalence row.
- Parents may be `deceased` (probability rising with derived age); FHIR
  `FamilyMemberHistory.deceasedBoolean` set accordingly. No cause-of-death modelling
  (YAGNI).

## Architecture (mirrors the immunization Base feature)

- **`clinosim/modules/family_history/`** (always-on Base package):
  - `engine.py` — pure, seeded generation functions.
  - `reference_data/family_history.yaml` — **country-neutral biology**: heritability
    multipliers per condition, sibling-count distribution, parent/sibling age
    offsets, sex restrictions, condition→ICD map.
- **`clinosim/locale/<country>/family_history_prevalence.yaml`** (US + JP) —
  **country-specific** base prevalence per condition × sex × age bracket (mirrors
  `immunization_schedule.yaml`'s `coverage_by_age_sex`). Loaded via the locale
  loader.
- **AD-56 enricher** registered in `simulator/enrichers.py` at stage
  **`post_records`**, gated always-on. Seeded by a **`hashlib` sub-seed derived from
  `person_id`** so the family history is identical across that patient's multiple
  encounters and the **master RNG stream is unperturbed** (AD-16 — the determinism
  discipline reaffirmed this session). Reads the record's patient
  `chronic_conditions` for the heritability boost; writes the typed field below.
- **`clinosim/types/family_history.py`** — `FamilyMemberHistoryRecord` dataclass:
  `relationship: str` (v3-RoleCode, e.g. `"MTH"`), `sex: str`, `deceased: bool`,
  `condition_codes: list[str]` (ICD base codes; AD-30 codes-only, no display).
  Stored as a typed list on `CIFPatientRecord` (Base may add typed fields).
- **FHIR**: `_build_family_history(ctx)` builder registered via
  `register_bundle_builder()`. One `FamilyMemberHistory` per relative:
  `patient` reference, `relationship` CodeableConcept (`hl7-v3-rolecode` +
  display), `sex`, `deceasedBoolean`, and `condition[].code` (ICD via
  `_build_diagnosis_codeable_concept`, multilingual). De-duped per patient at write
  time (like Patient / AllergyIntolerance), since the record recurs per encounter.
- **CSV**: `family_history.csv` (patient_id, relationship, condition_code,
  condition_display, deceased).

## Codes

- ICD conditions: `E11/I10/I25/I63/I64/E78` already present. **Add cancers
  `C50/C18/C34/C61`** to `codes/data/icd-10-cm.yaml` (US billable leaf or map) and
  `codes/data/icd-10.yaml` (WHO), EN + JA, verified against NLM/WHO — per the
  "Diagnosis code coverage" rules. Family-history codes are NOT diagnosis-emittable
  Conditions, but registering them keeps display resolution authoritative.
- Relationship: `hl7-v3-rolecode` (system already registered). A `relationships`
  section in `family_history.yaml` maps `MTH/FTH/NSIB` → `{en, ja}` display
  (data-driven, country-neutral standard codes).

## Determinism (AD-16)

Generation uses a `hashlib`-derived sub-seed from `person_id` (+ a fixed feature
offset), never the master generator. No master draw is consumed, so existing
output is byte-identical except the new FamilyMemberHistory resources (and the new
CSV). Verified by same-seed byte-diff: only `FamilyMemberHistory.ndjson` (new) and
`family_history.csv` (new) appear; all existing NDJSON byte-identical.

## Testing

TDD on `family_history/engine.py` + FHIR builder:
1. **Determinism** — same person_id + conditions → identical family history;
   stable across encounters.
2. **Heritability** — over many samples, a patient WITH `E11` yields a higher
   parental `E11` rate than a patient without (boost applied).
3. **Sex restriction** — prostate only on male relatives; breast only female.
4. **Base prevalence by locale** — US vs JP prevalence tables produce different
   rates (loaded correctly).
5. **FHIR builder** — relationship coding, deceasedBoolean, condition codes,
   per-patient de-dup across encounters.

Plus: `pytest -m unit`/`-m integration`; generation audit (mean conditions per
patient, heritability correlation, sex-restriction sanity); **byte-diff** proving
the master stream is unperturbed.

## Out of scope (YAGNI)

- Second-degree relatives, age-at-onset, cause of death.
- Household-member linkage (the synthesis approach is self-contained).
- Disease-incidence feedback (family history does not yet raise the patient's own
  disease risk — one-directional for v1).
