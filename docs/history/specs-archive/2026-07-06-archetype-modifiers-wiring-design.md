# FP-YAML-2b — archetype_modifiers wiring — design spec

Date: 2026-07-06
Status: approved (brainstorming), pending implementation plan
Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` FP-YAML-2 (archetype_modifiers portion)
Goal linkage: closes a C1 (silent-drop) instance — the `archetype_modifiers` block
(23 disease YAMLs) is currently dropped at load (`extra="ignore"`) and never read.

## Background

`archetype_modifiers` (present in 23 disease YAMLs) is meant to shift
`course_archetypes` selection probabilities based on patient risk factors, but
`select_archetype` (`clinosim/modules/clinical_course/engine.py:63-103`) reads only
each archetype's `probability` and applies its own **hardcoded** profile modifiers
(`immune_reactivity < 0.3`, `treatment_sensitivity > 1.2`) plus a severity-based
adjustment. The YAML block is silently dropped (`DiseaseProtocol` `extra="ignore"`).

The YAML `archetype_modifiers` is a **superset** of the hardcoded logic: it encodes
the same `immune_reactivity`/`treatment_sensitivity` adjustments plus `age`,
comorbidities (diabetes/CKD/immunosuppressed/…), and disease-specific factors, per
disease. Wiring it (like FP-SEV-MODEL activated the dead `severity.distribution`)
makes the authored, per-disease archetype adjustments drive course selection.

**Decision (brainstorming, user-approved):** wire `archetype_modifiers` into
`select_archetype`, replacing the hardcoded profile modifiers with the YAML-driven
version; keep the severity-based adjustment (orthogonal); diseases without an
`archetype_modifiers` block get no profile adjustment (minor behavior change).

### Data shape (enumerated from the 23 YAMLs)

```yaml
archetype_modifiers:
  - condition: "immune_reactivity < 0.3"          # expression form
    effect: {treatment_resistant: 0.10, gradual_deterioration: 0.05, smooth_recovery: -0.15}
  - condition: "age >= 80"                         # expression form
    effect: {gradual_deterioration: 0.08, sudden_deterioration: 0.04, smooth_recovery: -0.12}
  - condition: "immunosuppressed"                  # named form
    effect: {treatment_resistant: 0.10, smooth_recovery: -0.15}
```

- **53 distinct conditions.** Expression form (`<var> <op> <number>`): vars = `age`,
  `treatment_sensitivity`, `immune_reactivity`, `prior_dka_episodes`. Named form (~45):
  overlaps the severity modifier vocabulary (diabetes/CKD/immunosuppressed/active_cancer/
  liver_cirrhosis/anticoagulant_use/…) plus disease-intrinsic ones (dysphagia_known,
  tpa_received, troponin_elevated_and_rv_dysfunction, hematoma_volume_above_30mL,
  injection_drug_use, antiviral_within_48h, prerenal_etiology, …).
- **`effect` archetype keys** reference archetypes the disease actually defines. NOTE
  (recon correction): `plateau` is NOT a typo for `plateau_then_recovery` — it is a
  legitimate per-disease archetype NAME defined in those diseases' own
  `course_archetypes` block (6 diseases: acute_mi/sepsis/gi_bleeding/copd_exacerbation/
  diabetic_ketoacidosis/cerebral_infarction) and referenced consistently in their
  effects. `course_archetypes` is a free-form dict, so archetype names are per-disease.
  Grep-verified: every disease's `archetype_modifiers` effect keys ⊆ its own
  `course_archetypes` keys (no phantom archetypes). Therefore NO `plateau` data fix;
  validation checks effect keys against the disease's own archetypes (below).

## Design

### Condition evaluation (`clinical_course/engine.py`, owner of archetype selection)

```
def _eval_archetype_condition(condition: str, profile, patient) -> bool:
    # Expression form: "<var> <op> <number>"  (op in <, <=, >, >=, ==)
    #   vars -> age (patient.age), immune_reactivity / treatment_sensitivity
    #   (profile.*), prior_dka_episodes (not modeled -> 0.0, so ">= N" is False).
    #   Parsed with a strict regex (NO eval()); an unparseable expression whose
    #   var is unknown returns False.
    # Named form: reuse disease.severity._evaluate_condition(condition, patient)
    #   for the overlapping comorbidity vocabulary; archetype-specific intrinsic
    #   conditions are in ARCHETYPE_RESERVED_CONDITIONS -> return False (skip).

def _apply_archetype_modifiers(probs: dict, modifiers: list, profile, patient) -> dict:
    # For each modifier whose condition is active, add its effect deltas to probs.
    # (probs may go negative; select_archetype already clamps via max(0.001, ...).)
```

- **Vocabulary** (mirrors severity.py's two-tier partition, enumerated from the 23
  YAMLs): `ARCHETYPE_EXPRESSION_VARS = {age, immune_reactivity, treatment_sensitivity,
  prior_dka_episodes}`; named conditions split into those handled by
  `severity._evaluate_condition` (reused) and `ARCHETYPE_RESERVED_CONDITIONS`
  (disease-intrinsic, skipped, KNOWN so validation doesn't raise).

### select_archetype changes

- Signature gains `protocol_modifiers: list[dict] | None = None` and `patient=None`
  (for age + chronic_conditions in condition evaluation; `profile` already passed).
- Replace the hardcoded `immune_reactivity < 0.3` / `treatment_sensitivity > 1.2`
  blocks (`engine.py:91-97`) with `_apply_archetype_modifiers(probs, protocol_modifiers
  or [], profile, patient)`. **Keep** the severity-based adjustment (`engine.py:82-89`,
  orthogonal — about the sampled severity, not patient risk factors).
- Diseases without `archetype_modifiers` pass `[]` → no profile adjustment (the old
  hardcoded profile modifiers no longer fire for them; a small, intended behavior change).

### Call-site + model

- `DiseaseProtocol` gains `archetype_modifiers: list[dict[str, Any]] = []`.
- `inpatient.py:126` passes `protocol_modifiers=protocol.archetype_modifiers or None,
  patient=patient`. (Single call site — grep-confirmed.)

### Validation (fail-loud at protocol load)

`_validate_archetype_modifiers(disease_id, modifiers, archetype_names) -> None`
where `archetype_names` = the disease's own `course_archetypes` keys (or the 6 fallback
names if it has none):
- every `effect` key ∈ `archetype_names` (self-consistency — a modifier cannot shift a
  probability for an archetype the disease doesn't define; that would silently create a
  phantom archetype with no trajectory at rng.choice time);
- every condition is a parseable expression OR in the KNOWN named vocabulary
  (severity-evaluable ∪ ARCHETYPE_RESERVED) — a typo raises;
- every effect delta is numeric.
Called from `load_disease_protocol` alongside `_validate_severity_block`.

## Determinism / golden strategy

- `_apply_archetype_modifiers` is pure computation before the single `rng.choice`; it
  adds NO rng draws. The archetype *probabilities* change → `rng.choice` outcome
  changes → cohort archetype distribution shifts → new-feature-class golden regen
  (AD-66). Profile regression goldens use forced-archetype (`select_archetype` is
  bypassed when `forced_archetype` is set) → verify byte-unchanged; cohort output
  shifts. Audit US p=2000 + JP p=1000 must stay green.

## Data fix

None. (Recon correction: `plateau` is a legitimate per-disease archetype name, not a
typo — see Data shape note. Validation enforces per-disease self-consistency instead.)

## Scope

**In scope:** model field + validation; `_eval_archetype_condition` +
`_apply_archetype_modifiers`; select_archetype rewire; call-site; `plateau` data fix;
golden regen; AD note. Reuse `disease.severity._evaluate_condition` for overlapping
named conditions (DRY).

**Out of scope (registry/TODO):** archetype-intrinsic conditions (dysphagia_known,
tpa_received, etc.) actual evaluation — reserved (shared with the severity
reserved-intrinsic follow-up: a scenario-flag mechanism resolving disease-intrinsic
flags to patient events would serve BOTH severity.modifiers and archetype_modifiers).
The clear-deletion orphan keys (differential_diagnosis / rehabilitation / precipitants /
prerequisite / dead model fields) and `extra="forbid"` (FP-YAML-3) are the NEXT chain.

## Testing plan (TDD)

1. `_eval_archetype_condition`: expression forms (`age >= 80`, `immune_reactivity < 0.3`,
   `treatment_sensitivity > 1.2`) true/false by profile/patient; named form delegates to
   severity; reserved-intrinsic returns False; unparseable/unknown returns False.
2. `_apply_archetype_modifiers`: active modifier shifts the named archetype probs by the
   delta; inactive is a no-op.
3. `select_archetype`: with YAML modifiers, an elderly/comorbid patient has a higher
   `gradual_deterioration`/`treatment_resistant` share than a young healthy one
   (lift-firing proof); deterministic for a fixed seed.
4. `_validate_archetype_modifiers`: an effect key not in the disease's own archetypes,
   an unknown condition, and a non-numeric delta each raise; all 23 real YAMLs validate
   as-is (self-consistent, grep-verified).
5. Integration: a small inpatient cohort's archetype distribution shifts vs baseline;
   audit green.

## Files touched

- `clinosim/modules/clinical_course/engine.py` (eval + apply + select_archetype rewire),
  `clinosim/modules/clinical_course/README.md`.
- `clinosim/modules/disease/protocol.py` (model field + validation call),
  `clinosim/modules/disease/severity.py` (expose `_evaluate_condition` reuse; no change
  if already importable).
- `clinosim/simulator/inpatient.py:126` (call site).
- (No disease-YAML data edits — `plateau` is legitimate; see Data shape note.)
- `tests/unit/...`, regenerated goldens, DESIGN.md AD note, registry update.
</content>
