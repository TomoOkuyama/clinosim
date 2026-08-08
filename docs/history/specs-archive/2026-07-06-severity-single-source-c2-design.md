# FP-SEV-MODEL — Severity single source of truth (hybrid c2) — design spec

Date: 2026-07-06
Status: approved (brainstorming), pending implementation plan
Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` FP-SEV-MODEL
Goal linkage: closes the largest C1 (silent-drop) instance — disease YAML
`severity.distribution` + `modifiers` are currently dead; this makes them the
canonical severity source.

## Background

clinosim has three disconnected "severity" systems (session-38 investigation):

- **A. locale continuous** — `demographics.yaml` per-disease `severity_beta: [α,β]`
  + optional `severity_minimum` (float). Drawn at population time
  (`population/engine.py:362-366`). **This is the only live inpatient severity
  source today**, and the same float is also load-bearing for the hospitalization
  decision (`population/engine.py:385`, `requires_hospital = severity > threshold`).
- **B. disease YAML categorical** — `reference_data/*.yaml` `severity.distribution`
  ({mild,moderate,severe} probs) + `severity.modifiers` (comorbidity/risk
  adjustments, clinical-literature-cited). Present in all 30 disease YAMLs but
  **read by zero code** (grep-verified). Dead.
- **C. encounter YAML categorical** — ED/outpatient `severity_distribution`, drawn
  independently in `emergency.py:76-83`. Live, unrelated to A.

Additional coupling defects found: the float→category boundary is hardcoded
(`inpatient.py:117`, `> 0.7`/`> 0.3`); the minimum is defined twice
(`severity_minimum` float in locale + `minimum_severity` str in disease YAML,
clamped separately at `population/engine.py:366` and `inpatient.py:119-124`).

**Decision (brainstorming, user-approved):** hybrid **c2** — make disease YAML
`severity.distribution` × `modifiers` the canonical severity source; derive the
continuous score the hospitalization gate needs via a single category→score
mapping; retire locale `severity_beta`/`severity_minimum`; unify the boundary and
the minimum in one owner. This activates System B (honoring the authored,
citation-backed distributions and comorbidity modifiers), which is the clinical-
integrity payoff. Cohort composition (hospitalization rate/severity mix) changes
to follow disease-YAML distributions — an intended, all-goldens-regenerate change.

## New component: `clinosim/modules/disease/severity.py`

The disease module owns the severity distribution, so it owns severity sampling.

```
SEVERITY_CATEGORIES = ("mild", "moderate", "severe")
# THE single definition of the category <-> continuous-score boundary.
# Half-open ranges so category_from_score is exactly consistent with the
# uniform draw used to produce the score.
SEVERITY_SCORE_RANGES = {
    "mild":     (0.0, 0.3),   # [0.0, 0.3)
    "moderate": (0.3, 0.7),   # [0.3, 0.7)
    "severe":   (0.7, 1.0),   # [0.7, 1.0]
}

def category_from_score(score: float) -> str:
    # score >= 0.7 -> severe; >= 0.3 -> moderate; else mild.
    # Consistent with SEVERITY_SCORE_RANGES (half-open, upper-inclusive severe).

def sample_severity(protocol, person, rng) -> tuple[str, float]:
    # 1. dist = protocol.severity["distribution"]  (mild/moderate/severe probs)
    # 2. dist = _apply_modifiers(dist, protocol.severity.get("modifiers", []), person)
    # 3. dist = _clamp_minimum(dist, protocol.minimum_severity)   # zero < minimum, renormalize
    # 4. category = rng.choice(SEVERITY_CATEGORIES,
    #                          p=normalize_probabilities([dist[c] for c in ...], fallback="raise"))
    # 5. lo, hi = SEVERITY_SCORE_RANGES[category]; score = float(rng.uniform(lo, hi))
    # 6. return category, score

def sample_severity_category(distribution, modifiers, person, rng, minimum) -> str:
    # Steps 1-4 only (no score). Shared primitive for the ED path, which needs
    # no continuous score (no hospitalization gate).

def _apply_modifiers(dist, modifiers, person) -> dict:
    # modifiers: list of {condition, mild_multiplier?, moderate_multiplier?, severe_multiplier?}
    # For each modifier whose condition is active for `person`, multiply the named
    # category probabilities. Renormalization happens at the normalize step.

def _evaluate_condition(condition: str, person) -> bool:
    # Maps a modifier condition string to a person predicate. The full modifier
    # vocabulary was enumerated from the 30 disease YAMLs: 65 distinct conditions,
    # split into two tiers (both are KNOWN — neither raises in validation).
    #
    # EVALUABLE (person-derived, ~35) — actually evaluated this chain:
    #   age_over_65/75/80/85, age_under_5            -> person.age
    #   diabetes -> E11/E10; heart_failure -> I50; CKD / N18 -> N18;
    #   COPD -> J44; liver_cirrhosis -> K74; hypertension_uncontrolled -> I10;
    #   atrial_fibrillation / I48 -> I48; prior_MI -> I25; prior_stroke_or_TIA;
    #   peripheral_vascular_disease; valvular_heart_disease; hyperthyroidism;
    #   dementia / dementia_advanced; osteoporosis; obesity / obesity_bmi_over_30
    #     -> person.bmi; smoking_current -> person.smoking_status;
    #   alcohol_dependence / alcohol_dependence_active -> F10;
    #   active_cancer / malignancy / metastatic_cancer / colorectal_cancer /
    #     hepatocellular_carcinoma -> chronic_conditions cancer codes;
    #   pregnancy -> person.sex/age heuristic; chronic_steroid_use,
    #   immunosuppressed, home_oxygen_use, anticoagulant_use, medication_
    #   noncompliance, multiple_comorbidities, poor_functional_status,
    #   prior_icu_admission/prior_icu_for_asthma -> mapped where person carries a
    #   corresponding attribute; otherwise treated as RESERVED (below).
    #   (The exact per-condition mapping is finalized in implementation step 0 by
    #    reconciling each against actual PersonRecord fields; any condition without
    #    a real person field moves to RESERVED rather than silently returning False.)
    #
    # RESERVED-INTRINSIC (~30) — disease sub-type / scenario-specific, NOT person-
    # derived (anterior_wall_MI, saddle_embolus, iliofemoral_location, bilateral_dvt,
    # phlegmasia_signs, intraventricular_hemorrhage, acalculous, gcs_below_8,
    # APACHE_II_above_8, FEV1_below_30, hypercapnia_baseline, first_presentation_T1DM,
    # delayed_presentation, coagulopathy, multiple_levels, neurological_deficit,
    # hernia_incarcerated, WPW_syndrome, sepsis, prior_abdominal_surgery,
    # urinary_obstruction, urinary_catheter, symptom_duration_over_48h/72h,
    # saddle/…): return False this chain. They are KNOWN vocabulary (validation does
    # NOT raise), reserved for the deferred scenario-flag mechanism (Scope / deferred).

def _validate_severity_block(protocol) -> None:
    # Import/load-time fail-loud (silent-no-op defense):
    #  - distribution has mild/moderate/severe keys, sum > 0, each >= 0
    #  - minimum_severity in SEVERITY_CATEGORIES or None
    #  - every modifier condition in the KNOWN vocabulary (evaluable ∪ known-intrinsic)
    #    -> a typo'd condition raises rather than silently never firing
    #  - every *_multiplier > 0
```

## Data-flow changes

- **`population/engine.py:361-366`** — replace the `severity_beta` draw + `sev_min`
  clamp with `category, severity = sample_severity(load_disease_protocol(disease_id),
  person, rng)`. Keep storing the float in `LifeEvent.severity`; the hospitalization
  gate (`severity > threshold`, line 385) is unchanged — the category→score mapping
  supplies the continuous value. New dependency population→disease (declare in
  `population/README.md`; `load_disease_protocol` is already the canonical loader).
- **`inpatient.py:117`** — replace the hardcoded `> 0.7`/`> 0.3` branch with
  `category_from_score(event.severity)`.
- **`inpatient.py:119-124`** — delete the `minimum_severity` clamp (now owned by
  `sample_severity`; forced-severity path at 114-115 is an explicit override and is
  intentionally not clamped).
- **`emergency.py:76-83`** — replace the hand-rolled normalization + `rng.choice`
  with `sample_severity_category(encounter_distribution, [], person, rng, minimum)`.
  ED has no modifiers/minimum today, so pass `[]`/`None`. NOTE: the shared primitive
  normalizes via `normalize_probabilities` (numpy float64 sum), whereas the old ED
  code used Python `sum()` + a list comprehension; these can differ by ~1e-17, so a
  single `rng.choice` outcome may flip in a boundary case. ED is therefore
  **distribution-preserving, not guaranteed byte-identical** — verify the ED severity
  *distribution* is statistically unchanged (not a byte-diff). Any change is an
  accepted consequence of unifying on the canonical normalizer, not a bug.
- **locale `demographics.yaml` (us + jp)** — remove `severity_beta` and
  `severity_minimum` from every `disease_incidence` entry (incidence-only from now).
  Pre-verify all 30 diseases carry a `severity.distribution` (investigation: they
  do). Encounter/ED conditions keep their `severity_distribution` in encounter YAML
  (their canonical source, unchanged).

## Downstream impact audit (in-scope per user)

The design change alters the severity *distribution* and the RNG stream. A full
grep-audit of severity consumers was run; classification:

**API-compatible (consume the category string / float; type unchanged, only the
sampled value distribution shifts — no code change needed, output changes fold
into golden regen):**
- `clinical_course.select_archetype` / `natural_recovery_directive` (category str)
- `apply_disease_onset(state, category, initial_state_impact)` (category str)
- `target_los` lookup (category str) — LOS distribution shifts
- `imaging/engine` `abnormal_rate_by_severity` / `order/engine` `only_if_severity`
  (category str) — imaging order/abnormality rates shift
- `triage/engine` + `triage/audit` (`Encounter.severity` str; all three categories
  still appear in a cohort, audit invariants hold)
- narrative `template_generator` / `context` / `passes` (`ctx.severity` str)
- FHIR `_fhir_common._severity_coding` / `_fhir_conditions` (`Encounter.severity` str)
- CLI `--severity` forced path (unchanged; forced overrides sampling)

**Requires code change (confirmed in-scope):**
- `population/engine.py` (source) — the core change above.
- `simulator/inpatient.py`, `simulator/emergency.py` — boundary + ED path.
- locale loaders / any `severity_beta`/`severity_minimum` reader — grep confirms
  **population is the only reader**; the implementation MUST re-grep after the
  locale YAML edit to prove zero dangling readers (fail the task if any remain).

**Not disease-severity (must NOT be touched — different concept, verified):**
- `ChronicCondition.severity` + `severity_score` (chronic-condition stage,
  `patient/activator.py`, `physiology/engine.py`).
- allergy reaction `severity`, audit finding `Severity`, validator issue severity.

The implementation plan includes an explicit "re-grep severity consumers, confirm
each is either API-compatible or fixed" verification task; any genuine breakage
found during implementation is fixed within this chain (not deferred).

## Determinism / golden strategy

- Inpatient path RNG changes from one `rng.beta` draw to `rng.choice` + `rng.uniform`
  (two draws) at population time, and the hospitalization decision now follows disease
  distributions — the RNG stream and cohort composition both shift. This is a
  new-feature-class change: **byte-diff intentionally broken; regenerate all goldens**
  (profile regression goldens template + llm-mock, per AD-66 Rule 1) and clinically
  read the diff (AD-66 Rule 2 — severity mix, LOS, archetype, imaging rates should
  shift toward the disease-YAML distributions; nothing structurally broken).
- ED path is distribution-preserving (see emergency.py note above): verify the ED
  severity category distribution is statistically unchanged, not byte-identical.
- e2e tests are property-based (severity mix, archetype variety) — expected to pass;
  if a property threshold now fails, that reveals a distribution the test hard-coded.
- `clinosim audit run` on US p=10k + JP p=5k must stay green.

## Validation (silent-no-op defense)

- `_validate_severity_block` runs at disease-protocol load (fail-loud on malformed
  distribution / unknown modifier condition / bad minimum / non-positive multiplier).
- A "modifier fired" observability check: `sample_severity` is covered by a unit test
  proving a comorbidity modifier actually shifts the severe rate (lift-firing proof
  analogue), so a future refactor that silently stops applying modifiers is caught.

## Scope

**In scope:** the `severity.py` module; population/inpatient/emergency wiring; locale
`severity_beta`/`severity_minimum` removal; person-derived modifier evaluation;
fail-loud validation; the downstream-consumer audit + any fixes it surfaces; golden
regeneration; a new ADR (AD-6x) documenting severity single-source.

**Out of scope (file as TODO/registry follow-ups):**
- Disease-intrinsic modifier conditions (`anterior_wall_MI`, burn extent, etc.) that
  are not person-derived — need a scenario-flag/sub-type mechanism; documented + the
  validation vocabulary reserves them so they are not mistaken for typos.
- `unknown_condition` severity (`population/engine.py:410` `rng.beta(2,3)`) — no
  disease YAML exists; unchanged.
- `incidence.risk_multipliers` (disease YAML) vs locale `disease_risk_multipliers`
  duplication (registry FP-YAML-2) — separate.

## Testing plan (TDD)

1. `category_from_score`: boundary values (0.0, 0.29, 0.3, 0.69, 0.7, 1.0) map to the
   category whose range contains them; exact consistency with `SEVERITY_SCORE_RANGES`.
2. `sample_severity`: over many draws the category frequencies match the (modified,
   minimum-clamped) distribution within tolerance; score always within the sampled
   category's range; deterministic for a fixed seed.
3. Modifier firing: a patient with a comorbidity that carries `severe_multiplier > 1`
   yields a higher severe rate than one without (lift-firing proof).
4. Minimum clamp: `minimum_severity="moderate"` never yields mild.
5. `_validate_severity_block`: malformed distribution / unknown modifier condition /
   bad minimum / non-positive multiplier each raise.
6. ED distribution-preservation: a small ED cohort's severity category counts are
   statistically unchanged pre/post (not a byte-diff — see emergency.py note).
7. Downstream: a small inpatient cohort still produces coherent archetype/LOS/imaging/
   triage/FHIR (audit run green); re-grep proves zero `severity_beta` readers remain.

## Files touched

- `clinosim/modules/disease/severity.py` (new), `disease/protocol.py`
  (`_validate_severity_block` call at load), `disease/README.md`.
- `clinosim/modules/population/engine.py`, `population/README.md` (new disease dep).
- `clinosim/simulator/inpatient.py`, `clinosim/simulator/emergency.py`.
- `clinosim/locale/us/demographics.yaml`, `clinosim/locale/jp/demographics.yaml`.
- `tests/unit/...` (severity sampling, boundary, validation, modifier firing),
  `tests/integration/...` (ED byte-preservation, downstream coherence).
- Regenerated goldens (profiles template + llm-mock).
- `DESIGN.md` (new ADR), registry FP-SEV-MODEL → DONE, TODO.md deferred items.
</content>
