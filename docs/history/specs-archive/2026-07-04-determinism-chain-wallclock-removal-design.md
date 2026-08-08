# Determinism chain: wall-clock removal — Design Spec

**Date:** 2026-07-04 (session 34)
**Status:** Approved for implementation
**Branch:** `feature/determinism-chain-wallclock` (to be created)
**Source:** `TODO.md` "★★ Determinism chain: wall-clock removal (extends session-30 TODO)"

## 1. Problem

`clinosim` claims full determinism from a fixed RNG seed (AD-16), and the project's
goal is byte-identical structural CIF output across runs of the same seed/config —
this underlies golden-file regression testing (AD-66) and lets refactors be verified
by byte-diff instead of manual review. However, several code paths read the wall
clock (`datetime.now()` / `date.today()`) instead of deriving timestamps from
already-deterministic simulation state, breaking this invariant. A session-30
investigation found two byte-diff-measured live fields
(`discharge_prescription.issue_date`, `physiological_states[].timestamp`); a
session-34 follow-up investigation (this spec) found three more live wall-clock
reads, one edge-case wall-clock fallback, and a JP blood_type YAML floating-point
artifact that bypasses the project's `normalize_probabilities` safety net.

Beyond the currently-*live* (byte-diff-affecting) sites, the same dataclass fields
also carry `default_factory=datetime.now`/`date.today` on several other fields that
are today always overridden by an explicit value at every call site — i.e.
currently harmless, but a structural footgun: a future call site that forgets to
pass the value silently reintroduces non-determinism with no test failure to catch
it (the exact failure class the project's `lift_firing_proof` / `validate_*`
silent-no-op-defense pattern exists to prevent elsewhere).

**Decision (user-approved):** fix comprehensively — remove `default_factory` reads
of the wall clock from every field in scope, live or currently-dead, so the class
of bug is closed structurally rather than patched site-by-site.

## 2. Principle

No CIF-affecting dataclass field may default to a wall-clock read. Every timestamp
must be explicitly threaded from an already-deterministic reference value in scope
at construction time — almost always `encounter.admission_datetime` (inpatient/ICU)
or `visit_datetime` (outpatient/ED), optionally offset by `timedelta(days=day)` /
`timedelta(hours=N)` following the existing precedent at
`clinosim/simulator/outpatient.py:199` (`visit_date + timedelta(hours=2)`).

Where no deterministic reference is available at a call site — this indicates a
caller/test-setup gap, not a real simulation path, since production runs always
resolve a snapshot/admission reference before touching patient records — fail loud
with `ValueError` rather than silently falling back to `datetime.now()` /
`date.today()`. This matches the project's existing `validate_*(...)  -> None`
silent-no-op-defense convention (AD-60 companions: `_validate_hai_organisms`,
`_validate_demographics`, etc.).

## 3. Scope — per-site fix plan

| # | Site | Fix |
|---|------|-----|
| 1 | `PhysiologicalState.timestamp` (`types/clinical.py:13`) | `physiology/engine.py:initialize_state()` gains a required `admission_datetime: datetime` parameter. All 4 call sites (`inpatient.py:132`, `inpatient.py:1721`, `outpatient.py:123`, `emergency.py:119`) already have this value in scope. `device/engine.py:_peak_state_for_encounter`'s `PhysiologicalState()` fallback (hit when `record.physiological_states` is empty) is changed to build from `encounter.admission_datetime` instead of the bare default. |
| 2 | `StateChangeDirective.timestamp` (`types/clinical.py:56`) | `clinical_course/engine.py:get_daily_directive()` gains a required `admission_datetime: datetime` parameter (function already receives `day: int`). Sole caller `inpatient.py:600` already has both in scope. `apply_diagnosis_modifier` (which forwards `directive.timestamp` from an already-built directive) is unaffected. |
| 3 | `PrescriptionRecord.issue_date` (`types/encounter.py:148`) | Discharge prescription (`inpatient.py:1666`) passes the discharge datetime already computed in that function. Outpatient renewal (`outpatient.py:212`) passes `visit_datetime`. |
| 4 | `DifferentialDiagnosis.timestamp` (`modules/diagnosis/engine.py:65`) | `initialize_differential()` and `update_differential()` gain a required `as_of: datetime` parameter. Callers `inpatient.py:282` / `inpatient.py:839` pass `admission_datetime` (+ day offset where applicable — `update_differential` is called per-day). `diagnosis/engine.py:173`'s explicit `datetime.now()` assignment is replaced with the passed-in `as_of`. |
| 5 | `immunization/enricher.py:_as_of()` — 3rd fallback (`date.today()`) | Replaced with `raise ValueError(...)`. First two fallbacks (`ctx.config.snapshot_date`, latest encounter `admission_datetime`) are already deterministic and unchanged; the CLI always resolves `snapshot_date` (default: today, resolved once at invocation, not re-read per record), so this fallback is only reachable from programmatic/test callers that skip both, which is a setup bug, not a real simulation path. |
| 6 | `locale/jp/demographics.yaml` blood_type sampling (`population/engine.py:145`) | Wrap with `normalize_probabilities(list(bt.values()), fallback="raise")`, matching the sibling `rng.choice(..., p=...)` call sites already in the same file (lines 170, 180, 472, 485, 509, 517, 664). No YAML edit needed — the authored weights (0.40/0.30/0.20/0.10) are correct; `0.9999999999999999` is a pure IEEE-754 summation artifact at runtime, which `normalize_probabilities` already corrects for every other weighted-choice site in this file. |
| 7 | `default_factory=datetime.now`/`date.today` sweep | Remove the default from every remaining field in `types/clinical.py`, `types/encounter.py`, `types/procedure.py`, including fields verified currently-dead (`Encounter.admission_datetime`, `OrderResult.result_datetime`, `MedicationAdministration.scheduled_datetime`, `Order.ordered_datetime`, `VitalSignRecord.timestamp`, `ProcedureRecord.start_datetime`/`end_datetime`, `RehabSession.session_date`). For each field: grep every constructor call site (production code **and** test fixtures), confirm each already passes an explicit value or add the missing plumbing, then remove the default. Dataclass field-ordering rules (non-default fields must precede default fields) require moving the now-required field to the front of its class where it isn't already first — e.g. `DifferentialDiagnosis.timestamp` (currently last of 4 fields) must move to first position. |

## 4. Out of scope (deferred, recorded separately in TODO.md)

- Moving `DifferentialDiagnosis` / `DiagnosisCandidate` from `modules/diagnosis/engine.py`
  to `clinosim/types/` — an existing, unrelated TODO.md "Single items" entry. Not
  required for determinism; folding it in here would violate scope discipline.
- `NarrativeVersionManifest.generated_at`, `ClinicalDocumentNarrative.generated_at`,
  and CIF export `metadata.generation_timestamp` — intentionally non-deterministic
  by design (they record actual generation wall-clock time for provenance; this is
  the documented "+ metadata generation_timestamp, by design" exception already
  noted in the TODO.md entry that seeded this chain).
- The CLI's `--end` default (`snapshot_date` defaults to "today" when the flag is
  omitted) — this is a legitimate single wall-clock read at the program's entry
  boundary, resolved once into `config.snapshot_date` and threaded deterministically
  from there on. Not a bug; out of scope by definition (removing it would just move
  the "what is today" question to a different, less natural, boundary).

## 5. Verification

- `pytest -x -q` full suite green (existing 234 tests, plus new tests from §3
  item 7's call-site fixes).
- New determinism regression test: run the same seed + config twice with
  `datetime.now`/`date.today` monkeypatched to different values between runs (or
  a real wall-clock delay), diff the resulting structural CIF NDJSON — must be
  byte-identical. Same spirit as the existing AD-66 golden byte-diff check, scoped
  to this chain's regression rather than reusing the disease-profile golden fixtures.
- `clinosim audit run` on a small US + JP cohort — confirm no clinical-axis
  regression from the timestamp threading changes.
- Post-implementation sweep: `grep -rn "datetime.now\|date.today" clinosim/` and
  confirm every remaining hit is one of the §4 out-of-scope exceptions.

## 6. Testing note

Removing `default_factory` from dataclass fields is a breaking change for any
existing unit test that constructs these types without passing the now-required
field. This is expected, in-scope churn (not a side effect to minimize) — those
tests were relying on wall-clock defaults, which is exactly the anti-pattern this
chain removes; fixing them to pass explicit deterministic values is part of the
work, not a regression.

## 7. Addendum (session 34, planning phase) — two mechanism refinements

Investigation during `writing-plans` (exact call-site counts, not available at
spec-approval time) surfaced two facts that changed *how* §3 is implemented,
without changing the spec's goal or scope:

**7a. Sentinel-default mechanism, not default removal.** `PhysiologicalState()`
alone has 90+ existing test call sites that construct it with no `timestamp=`
kwarg (pure physiology-math unit tests, unrelated to timestamps). Removing the
`default_factory` entirely (§3 item 7's original wording, "field-ordering rules
require moving the now-required field to the front") would force meaningless
`timestamp=...` edits onto all of them for zero benefit. **User-approved
revision:** keep every field's `default_factory`, but change the factory itself
from `datetime.now`/`date.today` to a fixed, obviously-fake sentinel constant
(`datetime(1970, 1, 1)` / `date(1970, 1, 1)`) defined once per type file. This
still eliminates 100% of wall-clock reads (the stated goal) with zero
call-site/test churn for currently-dead fields, and a sentinel value showing up
in real output is self-evidently a bug (unlike a wall-clock default, which looks
deceptively plausible). The §3 items that are genuinely live still get the real
deterministic value threaded in explicitly, overriding the sentinel — that part
of §3 is unchanged.

**7b. `StateChangeDirective.timestamp` and `DifferentialDiagnosis.timestamp` are
fully dead, not merely "currently live via a separate mechanism."** Grepping
every consumer confirmed neither field is ever read anywhere outside its own
class definition (`StateChangeDirective.timestamp`: `physiology/engine.py:update()`
only reads `directive.changes`, never `.timestamp`) or the one call site that used
to reassign it (`DifferentialDiagnosis.timestamp` is written by
`update_differential()` but the `DifferentialDiagnosis` object itself is never
serialized to CIF — only derived strings like `get_current_diagnosis_code()`'s
output are). §3 items 2 and 4 originally called for threading `admission_datetime`
into `get_daily_directive()` / `initialize_differential()` / `update_differential()`
as new required parameters. **Revised:** since neither field is read by anything,
the sentinel-default fix (7a) alone fully resolves both — no signature changes to
these functions. The one live side effect, the explicit `diff.timestamp =
datetime.now()` line inside `update_differential()`, is deleted outright (it was
a real wall-clock call whose result nothing consumed).

**Also folded into the §3 item 7 sweep** (discovered while reading the full
content of `clinosim/types/encounter.py` and `clinosim/types/clinical.py`,
mechanical, zero call-site risk — every one of these was already confirmed
explicit at its sole production call site): `ADLAssessment.date`,
`NursingRiskAssessment.date`, `IntakeOutputRecord.date`,
`ImmunizationRecord.occurrence_date` (all `default_factory=date.today` in
`encounter.py`), and `ClinicalImpressionRecord.date` (`default_factory=date.today`
in `clinical.py`). Same bug class, same files already being edited — leaving
these out would defeat the "no reachable wall-clock reads remain" grep-sweep
verification goal in §5 for no reason.

See `docs/superpowers/plans/2026-07-04-determinism-chain-wallclock-removal.md`
for the resulting task breakdown.
