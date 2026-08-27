# Issue #854 — Full-sweep remainder plan (post-v0.4.0)

**Status**: planning document, no code changes proposed here.
**Author**: session ending 2026-08-26, ahead of v0.5.0 development cycle.
**Predecessor**: `docs/plans/2026-08-25-issue-853-854-non-hai-mr-opaque-id.md` (Bucket A row 1-3 recipe).
**Baseline**: `master` at v0.4.0 (`fd175c6768` — chore(release): bump version to 0.4.0 (#876)).

## Goal

Close out the remaining rows of Issue #854 (Bucket A row 4 + Bucket B + Bucket C)
so every per-patient-event resource id becomes an opaque `sha256`-derived
short id and the compound-key anti-pattern is eliminated. After landing,
`Patient.id` and `Encounter.id` become the last two identifiers that still
carry a patient-recognizable slug — both decisions require a design call
(external identity, not just internal ordering).

The follow-on H100 22h full regen (`sim` + `narrate` + `export-fhir` at
this new baseline) can then land a byte-consistent, opaque-id-throughout
FHIR corpus into iris4h-ai.

## Completed in v0.3.0 → v0.4.0

- **Bucket A row 1**: Device + DeviceUseStatement (#867)
- **Bucket A row 2**: Procedure across 3 emit paths (#868)
- **Bucket A row 3**: ServiceRequest + DR/Observation/ImagingStudy basedOn cascade (#869)
- **MedicationRequest family**: MR (inpatient / discharge / outpatient) + MA (#853 / #863, v0.3.0)

## Remaining (this plan)

### Bucket A row 4 — Observation (1,580,109 records, highest volume)

Volume-dominant. `Observation.id` currently spans 5 semantic families,
each with its own compound key. All share the same fix pattern
(`derive_opaque_id` + `identifier[]` round-trip under a new
`OBSERVATION_KEY_SYSTEM`), but the cross-reference cascade edges vary.

Deploy inventory (from `feedback` in the resume-prompt, iris4h-ai
2026-08-26 build):

| id-prefix | count | family | cross-refs to fix |
|---|---:|---|---|
| `vs-*` | 827,244 | vitals (respiratory-rate / heart-rate / blood-pressure / temp / spo2) | none — stand-alone |
| `lab-*` | 243,543 | lab results | **critical** — DR.result[] + Observation.basedOn (SR) |
| `gcs` / `news2` | 211,928 each | scoring | none — stand-alone |
| `intake` / `output` / `urine` | 14,025 each | fluid balance | none — stand-alone |
| `barthel` / `braden` / `morse` | 2,365 each | risk assessment | none — stand-alone |
| `alcohol` / `blood-abo` / `blood-rh` / `occupation` / `smoking` | 6,732 each | patient-scoped social/screening | none — stand-alone |
| `carelevel` | 751 | patient-scoped | none — stand-alone |
| `codestatus` | 879 | encounter-scoped | none — stand-alone |
| `mb-sus` / `mb-org` | 746 / 260 | microbiology | isolate → susceptibility fan-out |

Recommended split (4 PRs, in this order):

1. **PR-obs-lab** — `lab-*` only. LOAD-BEARING: `lab_obs_id` at
   `clinosim/modules/output/fhir_r4/labs/diagnostic_report.py:211` encodes
   the order-list index into the id (`lab-{enc_id}-{idx:04d}`). Keep the
   compound as the structural key input to `derive_opaque_id`; apply the
   resolver at both the Observation emit site AND at DR.result[] emit site
   (`_bb_diagnostic_reports` and radiology-report path). Coordinates with
   the SR resolver PR #869 already in v0.4.0.
2. **PR-obs-vs** — `vs-*` / `gcs` / `news2` (~1.25M records). Stand-alone;
   no cross-ref cascade. Volume dominant but mechanically simplest.
3. **PR-obs-stand-alone** — patient-scoped (`blood-abo` / `blood-rh` /
   `smoking` / `alcohol` / `occupation` / `carelevel`) + encounter-scoped
   (`codestatus` / `intake` / `output` / `urine` / `barthel` / `braden` /
   `morse`). All stand-alone (~40k total).
4. **PR-obs-microbiology** — `mb-sus` (susceptibility) references `mb-org`
   (isolate) via `hasMember[]`. Small volume (~1k combined) but cross-ref
   pair. Keep in a separate PR so the cascade is visible.

**Byte-diff check after each**: `.id` length uniform post-fix (~15 chars
= `<prefix>-<12hex>`); `.identifier[]` carries `OBSERVATION_KEY_SYSTEM` +
original compound; 0 dangling cross-refs (DR.result[] / hasMember[]).

**MINOR bump** justified after this closes — byte-output changes across
Observation NDJSON.

### Bucket B — MEDIUM-risk, non-Encounter first

8 resource types, all with compound-key ids embedding patient + encounter
refs (`ENC-POP-{patient}-{encounter}-*`). Fix pattern identical to
Bucket A. Order chosen so cascades land in narrow scope before Encounter
(the biggest cascade of all) migrates.

5. **PR-specimen** — `Specimen.id` (243,803). Cross-refs from
   `DR.specimen[]` + `Observation.specimen`.
6. **PR-condition** — `Condition.id` (39,179). Cross-refs from
   `Encounter.diagnosis[].condition.reference`, `reasonReference[]`
   across MR / Procedure / ServiceRequest / DiagnosticReport, plus
   condition-of-encounter walkers. Heavy cascade — expected to be the
   biggest single Bucket B PR by touched-file count.
7. **PR-diagnostic-report** — `DR.id` (42,514). No further cascade
   (Composition.entry references DR but Composition migrates later).
8. **PR-imaging-study** — `ImagingStudy.id` (4,735). Stand-alone.
9. **PR-document-reference** — `DocumentReference.id` (57,166). Cross-refs
   from Composition.entry (section-level attachments).
10. **PR-composition** — `Composition.id` (51,967). Section-tree
    self-references (section.entry) + Encounter attach.
11. **PR-clinical-impression** — `ClinicalImpression.id` (14,025). Stand-alone.
12. **PR-care-team** — `CareTeam.id` (41,948). Referenced from
    `Encounter.diagnosis[]` and DR.performer.

### Bucket B — Encounter (biggest cascade)

13. **PR-encounter** — `Encounter.id` (42,826). **LEAK ROOT**: every other
    resource inherits the `ENC-POP-{patient}-{encounter}` shape from
    Encounter.id via string templating. Cascade extent (from Issue #854
    reference-edge inventory):
    - `*.encounter.reference` on every downstream resource (Observation /
      MR / MA / Procedure / DR / ImagingStudy / ClinicalImpression /
      Specimen / DocumentReference / Composition / CareTeam)
    - `*.context.reference` on MA
    - `Composition.author`, `Composition.event.detail[]`
    - Inline extension refs (JP-CLINS structuredSection entries)
    - Test assertion sites — likely 30-50 files need updates
    Coordinates with all preceding Bucket B PRs so the ENC prefix
    reference edge on each of them uses the shared resolver by the time
    Encounter itself flips to opaque.

### Bucket C — LOWER-risk (patient-scoped only, no encounter number)

14. **PR-immunization** — `Immunization.id` (29,359).
15. **PR-family-member-history** — `FamilyMemberHistory.id` (18,843).
16. **PR-coverage** — `Coverage.id` (6,732).
17. **PR-allergy-intolerance** — `AllergyIntolerance.id` (1,016).
18. **PR-patient** — `Patient.id` (6,732). **DESIGN DECISION** required:
    - Patient.id is the **external identity** used by every downstream
      consumer (iris4h-ai clinical cockpit, HAPI validator, integration
      tests). Migrating it to opaque `pt-<12hex>` breaks every existing
      URL like `/Patient/POP-000002` that has been captured or bookmarked.
    - Alternative A: keep `POP-{patient}` as the external id but add
      `Patient.identifier[]` with an internal opaque id for the FHIR
      "opaque id is opaque" invariant. This is a *documented deviation*
      from the invariant, not a code fix.
    - Alternative B: full opaque `pt-<12hex>` with a lookup identifier[]
      of `urn:clinosim:identifier:patient-external` = `POP-{patient}`
      to preserve the current external identity in a first-class field.
    - Alternative C: skip. Patient stays as `POP-{n}` documented as an
      accepted deviation; every other Bucket C resource fully opaque.
    Recommendation: **discuss with the maintainer before PR** — this is
    the only remaining decision that is not mechanical.

## Reference-integrity resolver protocol (shared across all above)

Each new resource follows the pattern established by PR #357 / #863 /
#867 / #868 / #869:

1. New module-private helper `_resolve_{resource}_id(structural_key: str)`
   in the emit module. Uses `derive_opaque_id({PREFIX}, structural_key)`.
2. New PUBLIC constant `{RESOURCE}_KEY_SYSTEM = structural_key_system("{resource}-key")`.
3. Every cross-reference reader uses the same resolver — never
   string-parses the resource id.
4. `.identifier[]` unconditionally carries
   `wrap_as_identifier(structural_key, {RESOURCE}_KEY_SYSTEM)` so
   consumers can recover the original compound key.
5. New test file `tests/unit/output/test_fhir_{resource}_opaque_id_854.py`
   pins resolver contract + emit path + cross-ref byte-consistency + US
   locale + fallback edge cases.

## Cadence + tag plan

- **v0.4.x PATCH** — no PATCH ships during this cycle (byte-output changes
  break byte-identity every PR). Each PR is atomic + landable but the
  full sequence spans multiple sessions.
- **v0.5.0 MINOR** — cut at the end of Bucket A + Bucket B (PRs 1-13).
  H100 22h regen at this tag; iris4h-ai deploy refresh.
- **v0.6.0 MINOR** — cut at the end of Bucket C (PRs 14-18). Second
  regen if the maintainer wants the patient-scoped resources refreshed
  too, or absorbed into a later regen.

## Risk / dependency notes

- **Cascade coordination**: Every Bucket B resource that Encounter
  eventually references must be resolvable by the shared resolver BEFORE
  PR-encounter lands. Order 5-12 → 13 → 14-18 respects this.
- **Test churn**: Existing tests pin literal compound ids at ~50+ sites
  across `tests/unit/output/`. Each PR will need a search-and-replace
  through its test surface (per the pattern established by PR #869).
- **Determinism**: Sha256 output is deterministic; same input → same
  opaque id. No RNG cascade concern. Cross-run byte identity holds within
  a MINOR line.
- **Test coverage guard**: Every new resolver PR ships a coverage-guard
  test (`test_all_{resource}_ids_are_opaque_shape`) that scans a p=200
  sim's ndjson for regressions. Prevents future emit-path additions from
  silently reintroducing compound ids.

## Non-goals

- **No CIF schema changes**. All resource ids are FHIR-emit-only fields;
  CIF Order.order_id / Encounter.encounter_id / etc. stay as-is (they
  become structural-key inputs to the resolver).
- **No downstream consumer coordination in this plan**. iris4h-ai
  clinical cockpit and HAPI validator continue to consume the FHIR bundle
  regardless of internal id shape (they read `.identifier[]` when they
  need the semantic slug). Patient.id (PR-18) is the one exception where
  external contract matters — flagged for maintainer discussion.

## Open questions

1. **Patient.id**: mechanical opaque migration, alternate identifier-only
   route, or accepted deviation? See PR-18 alternatives.
2. **Cadence within a session**: 4 PRs (Bucket A row 4) is a plausible
   single session; Bucket B needs 2-3 sessions realistically; Bucket C
   is 1 session for 4 mechanical PRs + PR-18 discussion. Total ~5-6
   focused sessions to close.
3. **v0.5.0 cut point**: is "Bucket A + B done" the right MINOR boundary,
   or should Encounter migration be its own tag (v0.5.0 = Bucket A + B
   non-Encounter, v0.6.0 = Encounter, v0.7.0 = Bucket C)? Depends on how
   long the Encounter cascade PR takes to review.

## Sequencing summary

```
PR-obs-lab       (Bucket A row 4, cross-ref cascade)
   ↓
PR-obs-vs        (Bucket A row 4, stand-alone volume)
   ↓
PR-obs-standalone
   ↓
PR-obs-microbiology
──────────────── Bucket A CLOSED (100 %) ────────────────
PR-specimen      (Bucket B, cross-ref)
PR-condition     (Bucket B, heaviest cascade in B)
PR-diagnostic-report
PR-imaging-study
PR-document-reference
PR-composition
PR-clinical-impression
PR-care-team
──────────────── Bucket B non-Encounter CLOSED ─────────
PR-encounter     (LEAK ROOT — biggest cascade of all)
──────────────── v0.5.0 tag + H100 regen candidate ─────
PR-immunization
PR-family-member-history
PR-coverage
PR-allergy-intolerance
PR-patient       (DESIGN DECISION — maintainer discussion)
──────────────── Bucket C CLOSED ─────────────────────────
──────────────── v0.6.0 tag ─────────────────────────────
```

## Appendix — commands template (per resource)

Each PR follows this shell + edit template (illustrative, adapt to
resource):

```bash
# 1. Branch from master
git checkout master && git pull --ff-only origin master
git checkout -b fix/854-bucket{A|B|C}-{resource}-opaque-id

# 2. Inventory current id shapes on a p=200 sim
clinosim simulate --format cif -p 200 -s 500 --country JP -o /tmp/p200_pre
clinosim export-fhir --cif-dir /tmp/p200_pre --country JP
jq -r '.id | length' /tmp/p200_pre/fhir_r4/{Resource}.ndjson | sort -u

# 3. Add resolver + emit change + identifier[] round-trip
# 4. Update every test that pins literal compound ids
# 5. pytest tests/unit/ (whole tree)
# 6. ruff check + format
# 7. Commit + push + PR
# 8. Post-merge: p=200 verify opaque ids + 0 dangling cross-refs
```
