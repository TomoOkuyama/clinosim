# FP-I10 — hypertension stage → BP baseline physiological consumer — design

Date: 2026-07-06
Status: approved (pattern extension), no new architecture
Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` FP-I10
Goal linkage: closes a C2 (degenerate-element) instance — I10 `Condition.stage`
("Stage 1"/"Stage 2") is emitted but has NO physiological consumer, so it is a no-op:
every hypertensive patient (~33% of the population) carries a degenerate stage element
that doesn't affect vitals/labs.

## Background

`_generate_stage` (`activator.py:70-71`) samples I10 "Stage 1"/"Stage 2", but I10 is
absent from `STAGE_SEVERITY` (`activator.py:37-44`), so its `severity_score` falls back
to the generic `uniform(0.1, 0.4)`. The baseline vitals bump (`activator.py:262-264`)
is a FLAT `systolic += 10, diastolic += 5` regardless of stage. `physiology/engine.py`
`initialize_state` has no I10 branch. Net: stage is generated and emitted to FHIR but
never consumed — a true no-op (registry: "single STAGE_SEVERITY addition is forbidden —
needs a real physiological consumer").

The 5 sibling graded-stage conditions (N18/I50/J44/J45/I25) were wired in session 37;
I10 was deliberately deferred because it lacked a consumer. This adds that consumer.

## Design (extends the CKD/HF session-37 pattern)

1. **`STAGE_SEVERITY["I10"] = {"Stage 1": 0.3, "Stage 2": 0.6}`** — stage → severity_score
   (0-1 scale, comparable to the CKD/HF entries; Stage 2 ≈ moderate).
2. **Stage-scaled baseline BP** in `activator.py`: replace the flat I10 bump with a
   severity_score-scaled elevation. Build a `{code: severity_score}` map from the
   `conditions` list already constructed above, then:
   ```
   sev = i10_severity_score  # 0.3 (Stage 1) or 0.6 (Stage 2)
   vitals.systolic_bp  += int(round(8 + sev * 20))   # Stage1≈+14, Stage2≈+20
   vitals.diastolic_bp += int(round(4 + sev * 10))   # Stage1≈+7,  Stage2≈+10
   ```
   Grounded: `sbp_base` for a 60yo ≈ 125 → Stage1 ≈ 139 (stage-1 range), Stage2 ≈ 145
   (stage-2 range). Both clearly hypertensive; Stage 2 higher than Stage 1.
   The elevated baseline flows through `physiology/engine.py:632-634` (BP derived from
   `baseline.systolic_bp` + volume/perfusion) into every encounter's vitals, so a
   higher-stage hypertensive now has measurably higher BP in the FHIR output — the
   stage is no longer degenerate.

## Determinism (AD-16)

The generic `severity_score` uniform (`activator.py:218`) is still drawn for I10 (it
runs before the STAGE_SEVERITY substitution); adding I10 to STAGE_SEVERITY only changes
which value is USED, not the draw sequence. The vitals bump change consumes
`severity_score` (no rng). So the RNG stream position is unperturbed — only I10
patients' `severity_score` and baseline BP VALUES change. New-feature-class output shift
→ golden regen (AD-66); any profile fixture with an I10 comorbidity will change.

## Out of scope (registry/TODO follow-up)

- **FHIR `Condition.stage.type` SNOMED code**: `_fhir_conditions.py:197` emits
  385356007 "Tumor stage finding" for ALL staged conditions (N18/I50/J44/I25/I10), not
  just I10 — a clinically wrong tumor-staging code applied to non-cancer stages. Fixing
  it needs authoritative per-staging-system SNOMED codes (or omitting the optional
  `.type`); it is a broader pre-existing bug across all 6 staged conditions, filed
  separately. FP-I10 makes the stage physiologically real; the coding correction is a
  distinct sweep.

## Testing (TDD)

1. Unit: `STAGE_SEVERITY["I10"]` present; an I10 patient's `ChronicCondition.severity_score`
   equals the stage-mapped value (0.3/0.6), not the generic uniform.
2. Unit: baseline BP is stage-graded — a Stage-2 I10 patient has higher baseline
   systolic than a Stage-1 one (holding age/seed comparable), and both exceed a
   non-hypertensive baseline.
3. Determinism: RNG draw count unchanged (a non-I10 patient generated with the same seed
   is byte-identical pre/post — verified via a targeted activator test or cohort byte-diff
   on a no-I10 patient).
4. Full suite + golden regen (I10-comorbid profiles shift) + audit 0 FAIL.
5. Real-cohort read (AD-66 Rule 2): hypertensive cohort BP distribution shifts up and is
   stage-graded; non-hypertensive unchanged.

## Files

- `clinosim/modules/patient/activator.py` (STAGE_SEVERITY entry + stage-scaled bump).
- `tests/unit/test_i10_stage_physiology.py`.
- Regenerated goldens (if I10-comorbid profiles), registry update.
</content>
