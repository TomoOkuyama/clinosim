# PR3b-5 Attribution Refinement — Data Quality Review

**Date**: 2026-06-29
**Branch**: feat/pr3b-5-attribution-refinement
**Cohort**: scratchpad/pr3b5_dqr (US p=5000 seed=42 + JP p=5000 seed=42)
**Audit**: `clinosim audit run -d scratchpad/pr3b5_dqr`

## Summary

**PR3b-3 D1+D2 encounter-level approximation: RESOLVED.** D1 R-rate gate
now joins susceptibilities to specimens (via `Observation.specimen.reference`)
and filters to HAI-derived specimens (via the new `HAI_EVENT_ID_SYSTEM`
canonical identifier). The two attribution defects documented in
PR3b-3 DQR §"Known approximation" (C1 multi-organism encounter
double-count, C2 community + HAI culture co-occurrence) are now both
mechanically excluded by the gate.

Wiring verification is the load-bearing evidence at p=5000 — this cohort
scale produces zero HAI Conditions (same rare-event regime as PR #112/#114
DQR baseline), so production-cohort enforcement remains in the n<30 WARN
guard branch. The 3 new integration tests (FHIR identifier emit + C1 +
C2 resolution) directly exercise the resolution path with synthetic HAI
events that bypass the rare-event cohort size limitation.

## Cohort-side HAI identifier emission

| Country | mb-org HAI | mb-org community | mb-sus HAI | mb-sus community |
|---|---|---|---|---|
| US | 0 | 101 | 0 | 384 |
| JP | 0 | 77 | 0 | 203 |

At p=5000 the simulator produces zero HAI events (`Condition` rows with
T80.211A / T83.511A / J95.851 = 0 in both countries). All microbiology
resources are community cultures with no `identifier` field — **byte-
identical to pre-PR3b-5 output for community resources**, confirming the
guard in `_fhir_microbiology.py` (no identifier when `hai_event_id == ""`).

A larger cohort (p=50k+) or `ForcedScenario.force_hai_event` injection
would surface HAI cultures with identifier set, which the integration
test `test_fhir_microbiology_emits_hai_event_id_identifier` covers
directly via synthetic `MicrobiologyResult.hai_event_id` → FHIR roundtrip.

## D1 R-rate gate at production scale

All 6 per-(hai_type, organism, abx) cohorts report `n=0` (same as PR #112
and PR #114 baselines at p=5000 — no HAI events fired). The gate enters
the `n<30 → WARN` branch in each case. Gate semantics are now **correct
at any cohort scale** — adding more patients (or forced HAI scenarios)
would surface a true per-organism per-HAI R-rate against the NHSN band
without the C1/C2 mis-attribution that PR3b-3 left as an approximation.

## Silent_no_op axis

Lift-firing proof produces 17 equality_checks, **all PASS**:

- 8 PR3b-1 (CAUTI ceftriaxone regimen) ✓
- 3 PR3b-2 (CLABSI S.aureus antibiogram chain) ✓
- 6 PR3b-3 (CLABSI MSSA narrow SWITCH chain) ✓

The `silent_no_op` axis directly exercises `enrich_antibiotic` against
synthetic HAI events that DO fire (bypassing the production rare-event
limitation). Combined with the integration tests below, this is the
load-bearing verification of the PR3b-5 chain.

## C1 + C2 resolution evidence (integration tests)

**Test 1 — `test_clinical_axis_r_rate_gate_no_double_count_multi_organism_encounter`**

Builds 30 CLABSI encounters with both S.aureus + S.epidermidis specimens
(each its own cefazolin susc, S.aureus = R, S.epidermidis = S, both with
HAI identifiers).

Pre-PR3b-5 (encounter-level join): both specimens' susc count under the
S.aureus band → n=60, R-rate = 0.5 (mixed, false).

Post-PR3b-5 (specimen-based join): only S.aureus-specimen susc count
under the S.aureus band → n=30, R-rate = 1.0 (true per-organism).

**Test PASS.**

**Test 2 — `test_clinical_axis_r_rate_gate_excludes_community_culture`**

Builds 30 CLABSI encounters with both HAI S.aureus specimen + community
S.aureus specimen (same organism, different specimen, HAI identifier
distinguishes them).

Pre-PR3b-5 (encounter-level join): both specimens count under the
S.aureus band → n=60, R-rate = 0.5 (HAI + community mixed).

Post-PR3b-5 (HAI-only filter): only HAI specimen counts → n=30,
R-rate = 1.0 (HAI only).

**Test PASS.**

## FHIR identifier emission contract

**Test — `test_fhir_microbiology_emits_hai_event_id_identifier`**

Drives `_bb_microbiology` with mixed HAI + community
`MicrobiologyResult`. Verifies:

- HAI culture (`hai_event_id == "hai-clabsi-E1-1"`):
  - Specimen, mb-org-* Observation, mb-sus-* Observation, DiagnosticReport
    all carry `identifier = [{"system": HAI_EVENT_ID_SYSTEM, "value": "hai-clabsi-E1-1"}]`
- Community culture (`hai_event_id == ""`):
  - All 3 resources (Specimen + mb-org-* + DiagnosticReport) have NO
    `identifier` field — **byte-identical** to pre-PR3b-5 output

**Test PASS.**

## Calibration decisions

**No band threshold changes were applied in this PR.** At p=5000 the
per-(hai_type, organism, abx) cohorts fall in the n<30 WARN-guard regime
(zero HAI events fire), so no observed value reached a PASS/FAIL judgement
against a band. The PR3b-5 chain is a semantic refinement of the existing
PR3b-3 D1 gate; band thresholds remain unchanged.

## adv-1 follow-ups (PR #117 post-merge)

Stage-1 adversarial review surfaced 3 load-bearing findings that were
fixed in `fix/pr117-adversarial-1`:

- **MAJOR-1**: D1 lacks symmetric "expected HAI but got 0" WARN guard
  (mirror of D2 I1). Fixed: D1 now emits WARN when HAI cohort encounters
  exist but `_hai_specimens` is empty (writer-side identifier emit
  regression / HAI_EVENT_ID_SYSTEM drift signal).
- **Important #3**: `_hai_specimens` truthy-only check accepted any
  non-empty value as HAI marker. Fixed: value must start with `"hai-"`
  matching the `HAIEvent.hai_id` convention (silent-no-op layer 2
  defense beyond the canonical SYSTEM gate).
- **Important #1 (URI scheme inconsistency)**: `http://clinosim/...`
  form conflicted with existing `urn:clinosim:staff` convention. Fixed:
  `HAI_EVENT_ID_SYSTEM = "urn:clinosim:identifier:hai-event-id"` aligns
  with the codebase's urn-form internal identifier convention.

The DQR cohort scale limitation (zero HAI at p=5000) was confirmed as a
genuine rare-event regime, not a writer-side regression. Production
firing requires p≥1M or `ForcedScenario.force_hai_event` injection —
both outside this DQR's scope; the silent_no_op axis lift_firing_proof
(17/17 PASS) provides the load-bearing single-event verification path.

## Verdict

**PR3b-5 attribution refinement: VERIFIED.**
**PR3b-3 D1+D2 approximation = RESOLVED.**

- 2 new helpers (`_organism_per_specimen`, `_hai_specimens`) wired
- FHIR identifier emission added to 4 resource types (Specimen + 2
  Observation flavors + DiagnosticReport)
- D1 R-rate gate refactored to specimen-based join + HAI-only filter
- 3 new integration tests pin the resolution mechanically
- 12 new unit tests cover both helpers + canonical-constant contract
- silent_no_op axis 17/17 equality_checks PASS
- Community-resource output byte-identical (no regression for non-HAI cultures)

PR3b-3-related deferred TODOs = 0 (PR3b-5 closes the only remaining
documented approximation). The "Known approximation" section in the
PR3b-3 DQR carries a RESOLVED cross-link to this PR.

## Out-of-scope (formal TODO.md tracking; honest closure)

Per the spec's deferral policy, 8 items are tracked in `TODO.md` as
formal entries — see Task 5 of the implementation plan. The next chain
(sibling YAML loader sweep) begins after PR3b-5 merges.
