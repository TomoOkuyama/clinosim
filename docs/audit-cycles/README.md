# CIF/FHIR Audit Cycles — Issue Tracker

This directory records the sequential CIF/FHIR data-quality audit cycles that
became the default workflow for clinosim from **session 41 onward**
(user directive at session 40 wrap-up, 2026-07-07).

## Workflow (per cycle)

1. Generate US p=10000 + JP p=10000 CIF/FHIR (once per cycle).
2. Global review of the NDJSON — FHIR spec compliance, display fallback,
   reference integrity, spec-violating datetimes, silent-drops, statistical
   anomalies, etc.
3. Random-sample N patients (5–10 recommended) and review every FHIR resource
   for that patient (data quality / clinical integrity / data realism).
4. Repeat 2 + 3 until **exactly 20 issues** are listed for the cycle.
5. Fix all 20 issues. **New additions are made only when the FHIR-consistency
   contradiction cannot be resolved without adding** (see memory
   `feedback_cif_fhir_quality_focus.md`).
6. Regenerate CIF/FHIR at the same seed / population.
7. Verify per-issue resolution (resolved / not resolved / newly discovered).
8. **Ask the user before starting the next cycle**. Auto-continuation is
   forbidden.
9. Unresolved issues carry over to the next cycle's opening list; then
   review + sampling proceeds to 20 issues total for that cycle.

## Progress display (required during fixes)

At every fix step, display `[Cycle N · n/20] <short description>` so the
user always sees cycle number + progress. End-of-cycle summary shows
resolved X / carried-over Y / newly discovered Z.

## Judgment priorities

1. **Data quality** — FHIR spec conformance, zero display fallback, reference
   integrity.
2. **Clinical integrity** — physiologic validity of values, temporal
   consistency, disease → workup → treatment causality.
3. **Data realism** — statistical distributions, rare-event incidence,
   agreement with clinical-practice reality.

## Per-cycle record

Each cycle has its own file, `cycle-<N>.md`, with:

- Cycle number, start date, master HEAD at cycle start.
- Generation command, seed, output paths.
- **Issue list (20 items)** — each with id, summary, detection path, sample
  data or code, impact, category (FHIR spec / clinical / realism /
  silent-drop / etc.).
- **Fix content** — commit hashes, change summaries, and (for each issue)
  the alternatives considered before choosing the resolution approach.
- **Verification result** — appended at the next cycle's opening: which
  issues were closed, which carried over, which new issues surfaced.

## Index

_(populated as cycles run — session 41 will open cycle 1)_

- Cycle 1 — not yet started.

## Related documents

- `docs/design-notes/2026-07-06-fix-point-registry.md` — session 38 FP-*
  registry (background from the completeness work that preceded this
  audit-cycle workflow).
- `docs/design-guides/data-model-and-completeness-conventions.md` — the C1/
  C2/C3 completeness convention shared across the codebase.
- Memory `feedback_audit_cycle_workflow.md` — the durable workflow rule.
- Memory `feedback_cif_fhir_quality_focus.md` — the "additions only when
  strictly required" rule that gates cycle 5 (fix) decisions.
