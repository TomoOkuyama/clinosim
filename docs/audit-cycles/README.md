# CIF/FHIR Audit Cycles — Issue Tracker

This directory records the sequential CIF/FHIR data-quality audit cycles that
became the default workflow for clinosim from **session 41 onward**
(user directive at session 40 wrap-up, 2026-07-07).

**Cycle 2 onward: JP first + 30 issues per cycle** (user directive at cycle 1
start and mid-fix, 2026-07-07). Cycle 1 opened with US p=10000 + JP p=10000
mixed and used the initial 20-issue rule (grandfathered); from cycle 2 onward
generation/regeneration and review are JP-first (JP-focused, multi-language
architecture preserved for both locales) and the cycle target is 30 issues.
Review points prioritise **appropriateness for Japanese medical-institution
records** and **JP Core FHIR profile compliance**, on top of data quality /
clinical integrity / realism.

## Workflow (per cycle)

1. Generate US p=10000 + JP p=10000 CIF/FHIR (once per cycle).
2. Global review of the NDJSON — FHIR spec compliance, display fallback,
   reference integrity, spec-violating datetimes, silent-drops, statistical
   anomalies, etc. **Before adding an observation to the cycle issue list**,
   check [`by-design-registry.md`](by-design-registry.md) — if the observation
   matches a registered by-design entry's Signature, do not add it; instead
   record one line in `cycle-<N>.md`: `By-design confirmed (see
   by-design-registry.md#<slug>)` so the full-scan record is preserved.
3. Random-sample N patients (5–10 recommended) and review every FHIR resource
   for that patient (data quality / clinical integrity / data realism).
   Same by-design-registry check applies here.
4. Repeat 2 + 3 until **exactly 30 issues** are listed for the cycle
   (by-design confirmations do NOT count toward the 30).
5. Fix all 30 issues. **New additions are made only when the FHIR-consistency
   contradiction cannot be resolved without adding** (see memory
   `feedback_cif_fhir_quality_focus.md`).
6. Regenerate CIF/FHIR at the same seed / population.
7. Verify per-issue resolution (resolved / not resolved / newly discovered).
8. **Cycle-end fix review** (mandatory, added 2026-07-08 by user directive):
   at the end of the cycle, after the regeneration + per-issue verification,
   **also re-review every fix that was applied within the cycle** for risk,
   verification quality, and correctness. Same 3-axis (data quality /
   clinical integrity / realism) plus authoritative-source verification for
   any new codes / URLs / mappings. Report findings to the user before
   moving on to docs update. This mirrors the mid-cycle 3 review of cycle
   2's improvements — the pattern is now permanent.
9. **Cycle-boundary documentation update + cross-session resume prompt
   record** (mandatory before the user prompt in step 10):
   - Append verification results (resolved / carried over / newly
     discovered) to `docs/audit-cycles/cycle-<N>.md`.
   - Update memory if the cycle surfaced new durable rules or knowledge.
   - Add new FP entries to `docs/design-notes/2026-07-06-fix-point-registry.md`
     when warranted.
   - Refresh `.session-resume-prompt.md` so the current cycle state
     (cycle N progress n/20, carry-over list, master HEAD, next action)
     is sufficient for a cold-start in a different session.
   - Reflect the current cycle progress in `TODO.md` Status.
   - Commit + push everything (finish in a clean state).
10. **Ask the user before starting the next cycle** with resolution
    status + carry-over count + doc-update result. Auto-continuation is
    forbidden.
11. Unresolved issues carry over to the next cycle's opening list; then
    review + sampling proceeds to 30 issues total for that cycle.
    **★ In-cycle carry-over judgement is forbidden without user consent**
    (added 2026-07-08). If a fix cannot land within the cycle, ask the
    user whether to attempt it within-cycle or defer — do not silently
    move it to the next cycle's list.

## Progress display (required during fixes)

At every fix step, display `[Cycle N · n/30] <short description>` so the
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
- **Issue list (30 items)** — each with id, summary, detection path, sample
  data or code, impact, category (FHIR spec / clinical / realism /
  silent-drop / etc.).
- **Fix content** — commit hashes, change summaries, and (for each issue)
  the alternatives considered before choosing the resolution approach.
- **Verification result** — appended at the next cycle's opening: which
  issues were closed, which carried over, which new issues surfaced.

## Index

_(populated as cycles run — session 41 will open cycle 1)_

- [Cycle 1](cycle-1.md) — CLOSED 2026-07-07 (session 41): 20 issues addressed
  (13 resolved / 5 not-a-bug / 2 carry-over to cycle 2). US p=10000 + JP p=10000
  audit; JP p=10000 regeneration for verification.
- Cycle 2 — not yet started. Carry-over: C1-09 rules expansion, C1-10 ImagingStudy density,
  C1-18 JP chronic conditions root cause.

## Related documents

- `docs/design-notes/2026-07-06-fix-point-registry.md` — session 38 FP-*
  registry (background from the completeness work that preceded this
  audit-cycle workflow).
- `docs/design-guides/data-model-and-completeness-conventions.md` — the C1/
  C2/C3 completeness convention shared across the codebase.
- Memory `feedback_audit_cycle_workflow.md` — the durable workflow rule.
- Memory `feedback_cif_fhir_quality_focus.md` — the "additions only when
  strictly required" rule that gates cycle 5 (fix) decisions.
