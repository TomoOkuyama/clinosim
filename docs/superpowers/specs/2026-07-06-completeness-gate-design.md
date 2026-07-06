# FP-COMPLETENESS-GATE — completeness invariants (capstone) — design

Date: 2026-07-06
Status: approved, capstone of the FHIR-completeness effort
Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` FP-COMPLETENESS-GATE
Analysis: `docs/design-notes/2026-07-06-fhir-completeness-and-data-model-unification.md`

## Purpose

Make the C1/C2/C3 wins of this session durable: a single, fast regression gate that
fails loudly if any completeness property regresses (forbid turned off, an orphan key
reintroduced, a graded-stage condition added as a no-op, etc.). It also encodes
**general** invariants that catch the *class* of each defect, not just the specific
instances fixed — e.g. any future graded-stage condition must have a physiological
consumer, so it cannot recur as I10 did.

This is the pragmatic capstone: a completeness **invariant test suite**
(`tests/unit/test_completeness_invariants.py`, marked `unit`). A heavier cohort-level
`clinosim/audit/axes/completeness.py` audit axis (statistical distribution checks per
disease) remains a documented larger follow-up — the invariant suite delivers the core
anti-backslide protection now, at unit speed, with no audit-framework surgery.

## Invariants encoded

### C1 — silent-drop eliminated and defended
- `DiseaseProtocol.model_config["extra"] == "forbid"` (author-time gate stays on).
- Every shipped disease YAML loads (no orphan key reintroduced; guarded by load).
- No disease YAML carries a top-level `diagnostic_difficulty` (must stay nested — chain 1).
- No `.py` reads `severity_beta` / `severity_minimum` (severity source is disease-YAML only).
- Every disease's `severity.distribution` has mild/moderate/severe summing > 0
  (the canonical severity source is well-formed).

### C2 — degenerate elements eliminated (general class guard)
- **Every graded-stage condition** returned by `_generate_stage`
  (`{N18, I50, J44, J45, I10, I25}`) has a `STAGE_SEVERITY` entry — so no graded stage
  can be emitted without a physiological consumer (the I10-class no-op cannot recur).
- Each `STAGE_SEVERITY` map's stage keys match the stages `_generate_stage` can emit for
  that code (no orphan/typo stage that would fall back to the generic score).

### C3 — missing-structure (where closed) + backlog visibility
- `heart_failure_exacerbation` and `subdural_hematoma` have non-empty `course_archetypes`
  AND `complications` (the two FP-ARCH-1 closures stay closed).
- A **backlog-visibility** assertion: the set of diseases still lacking `course_archetypes`
  equals the known FP-ARCH-2/3 trauma backlog (a curated allowlist). If a NEW disease
  ships without course_archetypes, or a backlog disease is fixed without updating the
  list, the test fails — keeping the C3 backlog honest (no silent regression, no stale
  allowlist).

## Determinism / cost

Pure static/load-time assertions over the YAMLs + module constants; no generation, no
rng, sub-second. No golden impact.

## Out of scope (documented follow-up)

- Cohort-level statistical completeness audit axis (`audit/axes/completeness.py`):
  e.g. authored severity.distribution reflected in the generated cohort within tolerance;
  I10 Stage-2 patients' BP distribution separated from Stage-1 at cohort scale; per-disease
  expected-resource matrix. Larger; needs audit-framework integration.
- The broader `Condition.stage.type` SNOMED-code fix (all 6 staged conditions).

## Files

- `tests/unit/test_completeness_invariants.py` (new).
- Registry update (FP-COMPLETENESS-GATE → DONE for the invariant suite; axis deferred).
</content>
