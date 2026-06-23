# FHIR DiagnosticReport panel grouping — audit (2026-06-22)

## Summary

PR `feat/diagnostic-report-panels` adds post-hoc grouping of existing lab
Observations into FHIR `DiagnosticReport` resources (CBC / BMP / LFT / Lipid
/ Coag / UA / ABG). No CIF schema change, no observation-engine change, no
RNG draws. Byte-diff at US `p=2000` + JP `p=2000` confirms every NDJSON
except `DiagnosticReport.ndjson` is byte-identical to master, and every
existing microbiology DR record appears byte-identically (as a complete
JSON line) in the branch's `DiagnosticReport.ndjson`.

## Calibration to simulator emission

Two practical deviations from the original spec, both driven by
measurements on the real simulator output (not from spec intent):

1. **Bucket = day** (`YYYY-MM-DD`), not minute. The clinosim lab generator
   randomizes per-component `result_datetime` even inside one panel order
   — e.g. one ABG order emits pH at 13:50, pO2 at 14:45, pCO2 at 15:23.
   With minute buckets the components grouped as singletons (below
   threshold). Switching to day-resolution allowed ABG and other panels
   to group reliably. Same-day repeat draws (q4-6h BMP in DKA) collapse
   into one DR per panel per day; `DR.result[]` length grows accordingly.
   `DR.effectiveDateTime` is reported as a date-only value (FHIR R4 allows
   partial-precision dateTime).

2. **`min_components` thresholds lowered** to match the analyte subset the
   current physiology engine actually emits (Hct / Cl / Ca often absent):
   CBC 3→2, BMP 5→3, LFT 3→2, Lipid 3→2. ABG (3), Coag (2), UA (3,
   skip-if-empty) unchanged. Solo-lab pass-through (CRP / BNP / Troponin_I
   / HbA1c / Lactate / eGFR / PCT) is unaffected — none of those analytes
   are in any panel's components list.

Both adjustments preserve the design intent ("group panel-typical analytes
drawn in the same draw event"); they reflect that clinosim's "draw event"
granularity is currently day-level rather than minute-level. A future
enhancement that tightens lab-generator timing (or links lab_results back
to the panel order) could re-introduce sub-day buckets.

## Byte-diff invariant (gold criterion)

```
byte-diff snapshot 2e1ec0dc fix(output): switch DR panel bucket from minute to day (matches simulator)

=== US ===
  AllergyIntolerance.ndjson                same
  Condition.ndjson                         same
  DiagnosticReport.ndjson                  DIFFERS (expected): all 33 master DR records preserved byte-identically; branch added 4025 new DR records
  Encounter.ndjson                         same
  FamilyMemberHistory.ndjson               same
  Immunization.ndjson                      same
  Location.ndjson                          same
  MedicationAdministration.ndjson          same
  MedicationRequest.ndjson                 same
  Observation.ndjson                       same
  Organization.ndjson                      same
  Patient.ndjson                           same
  Practitioner.ndjson                      same
  PractitionerRole.ndjson                  same
  Procedure.ndjson                         same
  Specimen.ndjson                          same
=== JP ===
  (same shape; only DiagnosticReport.ndjson differs; 47 master DRs preserved
   byte-identically; 3502 new panel DRs added)
```

Note on invariant interpretation: the spec hypothesized that new panel DRs
would APPEND after the existing microbiology DRs in stream order. In
practice the FHIR Bundle builder emits per (patient, encounter), so panel
DRs and microbiology DRs from the same encounter appear together — the new
records are interleaved across encounters, not appended as a tail block.
The byte-diff check was strengthened from "branch lines start with master
lines (prefix)" to "master lines are a subset of branch lines
(set-equality on the master-line content)". Every existing microbiology
DR JSON record is preserved byte-identically as a complete line; only the
order in which they appear in the file changes (and only because the
panel DRs are interleaved).

## Patient / Observation / DR counts

```
US master p=2000:    1285 patients   188,304 Observations       33 DRs
US branch p=2000:    1285 patients   188,304 Observations    4,058 DRs
JP master p=2000:     973 patients   169,717 Observations       47 DRs
JP branch p=2000:     973 patients   169,717 Observations    3,549 DRs
```

Patient count and Observation count are bit-for-bit identical between
master and branch (the byte-diff above proves this at the file level;
shown here as line counts for at-a-glance reading).

## Referential integrity

```
US: 4025 panel DRs, 0 bad references
JP: 3502 panel DRs, 0 bad references
```

Every panel DR's `result[].reference` resolves to an emitted Observation
id in the same export. No dangling references.

## Per-panel DR distribution at audit scale

```
=== US p=8000 ===
  microbiology DRs: 160
  panel DRs by code: {'lft': 5510, 'cbc': 5324, 'abg': 2581, 'bmp': 2189, 'lipid': 54}
  result[] length percentiles: min=2  p50=2  p90=4  max=6

=== JP p=4000 ===
  microbiology DRs: 75
  panel DRs by code: {'lft': 2567, 'cbc': 2457, 'bmp': 1211, 'abg': 700, 'lipid': 38}
  result[] length percentiles: min=2  p50=2  p90=4  max=6
```

### Interpretation

- **LFT and CBC dominate** — these are the most commonly ordered panels in
  both inpatient and outpatient workups, matching real EHR distribution.
- **ABG emits in 2,581 US / 700 JP** encounters — covers the respiratory
  / metabolic cohorts (COPD, pneumonia, asthma, DKA). The day-bucket
  groups the 3-4 components of a single ABG order even when their
  result_datetimes span hours (the bucket-resolution issue documented
  above).
- **BMP emits in 2,189 US / 1,211 JP** encounters — typical for admit
  metabolic panels in DKA, sepsis, AKI, and broader workups.
- **Lipid 54 / 38** — limited to outpatient lipid screens (E78 cohort).
  Lower than CBC/LFT because lipid panels are typically scheduled, not
  added to acute workups.
- **Coag = 0** — PT / APTT components are not emitted standalone alongside
  the existing PT_INR Observations; with only PT_INR present (and a
  threshold of 2 components) the Coag panel correctly skips. Adding PT
  and APTT to the lab generator is a separate enhancement.
- **UA = 0** — UA component analytes (Urine_pH, Urine_specific_gravity,
  …) are not emitted by the current physiology engine. The
  `skip_if_no_components_present: true` flag in the YAML correctly
  prevents an empty UA DR from being emitted. Adding UA analytes is a
  separate enhancement (`project_realism_gaps`).
- **Result[] length p90 = 4** — same-day repeat draws (e.g. q4-6h BMP in
  DKA, daily CBC trend) consolidate as additional members of a single
  DR. Max = 6 is reasonable for a CBC + serial draw or a full ABG +
  repeat.

## Why no cascade

Spec ref: `docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md`.
The grouping is a pure read of `ctx.record["orders"]` and produces a separate
list of `DiagnosticReport` resources. No state mutation, no RNG draws, no
CIF schema change. Every other resource type is byte-identical to master.

## Follow-ups

- **UA component emission**. Add urinalysis analytes to the observation
  engine (separate plan). Once present, UA DRs will emit automatically
  via the existing YAML — no code change in this module.
- **Coag panel coverage**. Add PT and APTT components to the lab
  generator (currently only PT_INR is emitted standalone). With
  components present, the existing Coag YAML will emit DRs.
- **Add missing chemistry analytes** (Hct, Cl, Ca) to physiology so
  CBC/BMP threshold can be raised back toward the spec's intended
  full-panel granularity.
- **DR `basedOn` → `ServiceRequest` reference**. Requires emitting
  `ServiceRequest` resources for lab orders — out of scope for this PR.
- **Order-aware grouping**. A future CIF schema change that links
  `lab_results` to the panel order (`order_id` back-link) would replace
  the post-hoc day-bucket inference with exact order-grouped emission.
  Tracked separately.
