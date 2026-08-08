# clinical_course: archetype-probability wiring + severity_severe stub fix — design spec

Date: 2026-07-05
Status: approved (brainstorming), pending implementation plan

## Background

A comprehensive multi-agent code review (5 parallel reviewers covering
physiology+clinical_course, disease, population, output/FHIR, and documentation)
found two concrete, verified bugs in `clinosim/simulator/inpatient.py` and
`clinosim/modules/clinical_course/engine.py` that make disease-authored clinical
content in `clinosim/modules/disease/reference_data/*.yaml` silently inert. Both
were independently confirmed by direct code/grep inspection (not just agent
report) before this design was started.

The same review also surfaced a much larger, structural finding: the disease
protocol's `severity.distribution` + `severity.modifiers` block (present in all
30 disease YAMLs, citing real clinical literature) is entirely dead — the actual
severity draw comes from an unrelated `severity_beta` parameter in
`clinosim/locale/{us,jp}/demographics.yaml` — because `DiseaseProtocol`
(`clinosim/modules/disease/protocol.py`) has no `model_config = ConfigDict(extra="forbid")`,
so unrecognized top-level YAML keys are silently dropped at load time. Related
orphaned keys: `archetype_modifiers` (28/30 files), duplicated
`differential_diagnosis`/`diagnostic_difficulty`, `rehabilitation`, `precipitants`,
`prerequisite`, and a fully vestigial `readmission` schema field with zero YAML
usage.

**Scope decision (made during brainstorming):** this design covers ONLY the two
concrete bugs below. The severity-system unification / orphaned-key triage /
`extra="forbid"` rollout is explicitly out of scope for this session — it touches
all 30 disease YAMLs' schema, requires an editorial decision per orphaned field,
and is a genuine architecture question (should disease-YAML severity content
replace or supplement `severity_beta`?) rather than a bug fix. It will be filed
as a TODO.md formal entry (context + file:line + options) for a future session,
per this project's scope-discipline convention.

## Fix A — course-archetype probability wiring

`clinosim/simulator/inpatient.py:129` calls:

```python
archetype = select_archetype(severity, patient.physiological_profile, rng)
```

`select_archetype` (`clinosim/modules/clinical_course/engine.py:63-103`) accepts
an optional `protocol_archetypes: dict[str, Any] | None = None` — when omitted,
it falls back to a generic, disease-agnostic `_FALLBACK_PROBABILITIES` table
(55/20/10/8/5/2% across smooth_recovery/dip_then_recovery/plateau_then_recovery/
treatment_resistant/gradual_deterioration/sudden_deterioration) instead of using
the calling disease's own `course_archetypes[*].probability` values authored in
its YAML. A second call site 470 lines later (`get_daily_directive` at
`inpatient.py:601`) already correctly passes `protocol_archetypes=protocol.course_archetypes or None`.

Git history confirms this is a long-standing oversight, not an intentional
omission: the missing-argument call site is unchanged since before the
`simulator.py` → package split (commit `b409f9b904`, 2026-04-06), and no commit
has ever added `protocol_archetypes=` to this specific call site.

**Fix:** pass `protocol_archetypes=protocol.course_archetypes or None` at
`inpatient.py:129`, mirroring the existing pattern at line 601.

**Effect:** for every disease with a `course_archetypes` block (21/30 diseases —
9 diseases, mostly trauma/fracture plus `heart_failure_exacerbation`, have no
block and will continue to use the fallback exactly as before, since
`course_archetypes or None` evaluates to `None` for an empty dict), the
inpatient course trajectory *type* selection will now follow the disease's own
authored probabilities instead of the generic fallback. This is a real,
intended behavior change — course archetype distributions will shift for those
21 diseases.

## Fix B — `severity_severe` risk-factor stub + duplicate severity derivation

### B1: the stub

`clinical_course/engine.py:252-253` (`_evaluate_risk_condition`):

```python
if condition.startswith("severity_"):
    return False  # simplified
```

This unconditionally returns `False` for any `severity_`-prefixed risk-factor
condition. A full grep across all 30 disease YAMLs' `complications[*].risk_factors[*].condition`
confirms exactly one such pattern exists in the data: the literal string
`"severity_severe"` (no `severity_moderate`/`severity_mild`/compound variants).
So every complication risk multiplier gated on "this encounter is severe" is
silently never applied, for every disease that uses it.

### B2: the root cause is a duplicate, less-accurate severity derivation

Investigation during brainstorming found *why* this was never wired: the
function that needs the severity string, `_run_daily_loop`
(`clinosim/simulator/inpatient.py:547`), already receives an accurate
`severity: str = "moderate"` **parameter**, correctly passed by its caller
(`_simulate_patient`, `inpatient.py:300`: `severity=severity`, where `severity`
was authoritatively computed at lines 115-124 from the sampled continuous
severity score / `forced_severity` / `protocol.minimum_severity`).

But `_run_daily_loop`'s body ignores this parameter and instead **re-derives a
separate local variable** `severity_str` (lines 590-596) via a fragile
heuristic: matching the patient's sampled `target_los` against each severity
tier's documented mean `target_los` within a tolerance of 5 days. This
re-derived (and strictly less accurate — target_los ranges for adjacent tiers
can overlap) value is what currently feeds `natural_recovery_directive` (line
626). This is the exact "duplicate logic instead of reusing an existing
canonical value" anti-pattern this project's own rules warn against — the
correct value was one function-parameter-read away.

**Fix:**
1. Delete the `severity_str` re-derivation block (`inpatient.py:590-596`).
2. Replace its one use site (`natural_recovery_directive(day, disease_id,
   severity_str, ...)` at line 626) with the existing `severity` parameter.
3. Add a `severity: str` parameter to `evaluate_complications`
   (`clinical_course/engine.py:197`) and thread it through to
   `_evaluate_risk_condition`.
4. Update the call site (`inpatient.py:1012`,
   `evaluate_complications(day, state, patient, comp_list, active_complications, rng)`)
   to pass `severity=severity`.
5. Replace the stub in `_evaluate_risk_condition` with a real comparison:
   `condition == "severity_severe" and severity == "severe"` (kept as an exact
   match against the one observed pattern rather than a generic prefix
   parser, since no other variant exists in the data today — a more general
   parser can be added later if a new variant is authored, without breaking
   this).

**Effect:** complications whose risk factors include `severity_severe` (a
per-disease-authored multiplier, e.g. 2.0x–5.0x across ~30 occurrences in the
disease YAMLs) will now actually apply that multiplier for severe-tier
encounters, where previously it silently never did. This raises complication
rates for severe patients across every disease that authored this risk
factor — a real, intended behavioral change.

## Explicitly out of scope (deferred to TODO.md)

- `severity.distribution` / `severity.modifiers` (disease YAML) vs `severity_beta`
  (locale demographics YAML) — two disconnected severity systems; which one
  should be authoritative, or how to merge them, is an architecture decision.
- `archetype_modifiers` (28/30 disease YAMLs) — currently dead; `select_archetype`
  has its own separate hardcoded severity/profile modifier logic instead.
- Orphaned/duplicated top-level YAML keys: `differential_diagnosis` (5 files,
  drifted duplicates of the live nested `diagnostic.differential`),
  `diagnostic_difficulty` (top-level copy dead, only nested copy is read),
  `rehabilitation` (7 trauma files), `precipitants` (DKA), `prerequisite`
  (asthma), and the fully vestigial `readmission` schema field.
- Turning on `model_config = ConfigDict(extra="forbid")` on `DiseaseProtocol` —
  blocked on resolving every orphaned key above first, or load will start
  raising for every existing disease YAML.
- 9 diseases (`heart_failure_exacerbation` + 8 trauma/fracture diseases) with no
  `course_archetypes` block at all — whether that's an acceptable simplification
  (trauma) or a real gap (`heart_failure_exacerbation` has a well-known
  diuresis-driven recovery curve) needs per-disease authoring, not a code fix.

Each of the above will be written up as its own TODO.md formal entry (context +
file:line + options) as part of this fix's PR, per this project's convention
for scope-disciplined deferral.

## Testing / verification plan

Both fixes are deterministic behavior changes affecting every disease's
simulated output (course archetype distribution for Fix A; complication rates
for severe encounters for Fix B), so:

1. **TDD, one fix at a time:**
   - Fix A: a unit test asserting `select_archetype` is called with
     `protocol_archetypes` derived from a disease's `course_archetypes` in an
     end-to-end-ish harness (or a targeted test on `_simulate_patient`/
     `_run_daily_loop` verifying the archetype draw uses YAML probabilities
     when present) — RED before the one-line fix, GREEN after.
   - Fix B: a unit test on `_evaluate_risk_condition` (or
     `evaluate_complications`) asserting `severity_severe` matches when
     `severity="severe"` and does not match otherwise — RED before, GREEN
     after. A second test (or reuse of an existing inpatient-loop test)
     confirming `_run_daily_loop` passes the real `severity` parameter to
     `natural_recovery_directive` instead of the deleted `severity_str`.
2. **Full suite:** `pytest -m unit` then `pytest -m integration` (both green,
   no regressions expected beyond intentional golden/regression fixture
   drift below).
3. **Golden/regression fixtures (AD-66 Rule 1):** since this changes
   generation output, run `clinosim regenerate-goldens --all` and review the
   diff for plausibility (only archetype-distribution-driven fields and
   complication-related fields should differ; an unrelated field changing
   would indicate a bug) before committing goldens + code together in the
   same commit, per AD-66 Rule 2 (categorize AND clinically read the diff,
   not just accept it because it's the expected kind of change).
4. **Real-cohort spot check:** generate a small US + JP cohort and confirm
   (a) archetype distribution across a disease with strong YAML-authored
   probabilities differs visibly from the old fallback shape, and (b)
   `severity_severe`-gated complications now fire at a nonzero rate for
   severe-tier encounters of at least one disease that authors this risk
   factor (e.g. via a `clinosim audit run` pass or a direct CIF grep).
5. Commit with `fix(clinical_course): ...` message; TODO.md entries added in
   the same PR under a new dated backlog section.

## Files touched

- `clinosim/simulator/inpatient.py` (Fix A line ~129; Fix B lines ~590-596,
  ~626, ~1012, function signature additions as needed)
- `clinosim/modules/clinical_course/engine.py` (`evaluate_complications`
  signature + call to `_evaluate_risk_condition`; `_evaluate_risk_condition`
  body)
- `tests/unit/...` (new/extended tests for both fixes)
- Golden/regression fixtures (regenerated, not hand-edited)
- `TODO.md` (new formal entries for the deferred items above)
