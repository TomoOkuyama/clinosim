# Code status (resuscitation status) — AD-55 Base

**Date:** 2026-06-21
**Status:** approved (design)
**Type:** AD-55 Base data enrichment (always-on)

## Goal

Add a documented code status (resuscitation status) to serious encounters and emit
it as a FHIR `Observation`. Code status is core inpatient EHR data and drives
end-of-life care; this adds clinically coherent, age/acuity-correlated code status.

## Scope of encounters (clinical reality)

Code status is documented selectively in real EHRs:
- **Inpatient: always** (admission order sets include code status).
- **ED: only the critical/terminal subset** — assign when the ED encounter is
  `deceased` (died in/around the ED) or `icu_transferred` (high acuity). Routine
  ED visits (seen and discharged) get **no** code status.
- **Outpatient: never** (not a per-visit concept).

Concretely, assign iff `encounter_type == "inpatient"` OR
(`encounter_type == "emergency"` AND (`deceased` OR `icu_transferred`)).

## Values (4 tiers)

`Full Code` / `DNR` / `DNR+DNI` / `Comfort care`. CIF stores the SNOMED code only
(AD-30); display resolved at output. Most patients are `Full Code`; non-full-code
rises with age, ICU, and terminal status.

## FHIR representation

One `Observation` per qualifying encounter:
- `category`: survey (via `_survey_category`).
- `code`: SNOMED resuscitation-status observable (candidate `304251008`
  "Resuscitation status", verify against the SNOMED CT browser).
- `valueCodeableConcept`: one SNOMED concept per tier (candidates: Full Code
  `304252001` "For resuscitation", DNR `304253006` "Not for resuscitation";
  `DNR+DNI` and `Comfort care` to be confirmed against the SNOMED browser).
- `subject` (Patient), `encounter` (the qualifying encounter), `effectiveDateTime`
  (admission datetime).
- `status`: final.

**Codes are verified during the codes task** against the SNOMED CT browser; any
tier lacking a clean single concept gets the closest authoritative concept with a
`# TODO: verify` comment (project rule — never fabricate).

## Assignment (data-driven, locale rates)

Per qualifying encounter, pick a **context** = `terminal` if `deceased` else `icu`
if `icu_transferred` else `routine`; select the patient's **age band**; sample the
tier from that context×age-band weight vector. Younger/routine → almost all Full
Code; elderly terminal → mostly DNR/Comfort.

- `clinosim/locale/{us,jp}/code_status_rates.yaml` — **country-specific** 4-tier
  weights keyed by `context` (routine|icu|terminal) → age band. JP differs (DNAR
  culture; comfort-care documentation patterns differ).
- `clinosim/modules/code_status/reference_data/code_status.yaml` —
  **country-neutral**: tier → SNOMED code + display; the resuscitation-status
  observable code; age-band boundaries.

## Architecture (mirrors immunization / family_history Base features)

- **`clinosim/modules/code_status/`**: `engine.py` (pure, seeded
  `assign_code_status(age, context, country, rng) -> str` returning the SNOMED
  code, or `""`); `reference_data/code_status.yaml`.
- **AD-56 enricher** (`post_records`, always-on) seeded by an **`encounter_id`
  sub-seed** (`derive_sub_seed(master, _CS_SEED_OFFSET, encounter_id)`) so the
  value is stable within an encounter and the **master stream is unperturbed
  (AD-16)**. Applies the encounter-scope gate; writes `record.code_status`.
- **`CIFPatientRecord.code_status: str = ""`** typed field (Base).
- **FHIR**: `modules/output/_fhir_code_status._build_code_status(ctx)` registered in
  `_BUNDLE_BUILDERS`. One Observation when `code_status` is set; id
  `codestatus-{encounter_id}`.
- **CSV**: `code_status.csv` (patient_id, encounter_id, code, display).

## Determinism (AD-16)

`assign_code_status` is a pure function of `(age, context)` + an `encounter_id`
sub-seed; no master draw consumed. Byte-diff (same seed, master vs branch): only
the new code-status Observations appear in `Observation.ndjson`; all other
resources byte-identical.

## Testing

TDD on `code_status/engine.py` + FHIR builder:
1. **Determinism** — same (age, context, seed) → same code.
2. **Acuity gradient** — over many samples, `terminal` context yields more
   non-full-code than `routine` at the same age band; elderly more than young.
3. **Locale differ** — US vs JP weight tables produce different distributions.
4. **Encounter gate** — inpatient always assigned; ED assigned iff
   deceased/icu_transferred; outpatient never.
5. **FHIR builder** — survey category, resuscitation-status code, SNOMED value,
   encounter reference; no Observation when code_status empty.

Plus generation audit (tier distribution by context/age — Full Code dominant
overall, DNR/Comfort concentrated in elderly/terminal) and byte-diff (master
stream unperturbed).

## Out of scope (YAGNI)

- Consent / advance-directive resources, POLST, code-status change over a stay.
- Person-level (cross-encounter) advance directives — code status here is
  per-encounter.
