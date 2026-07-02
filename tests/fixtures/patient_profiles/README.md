# Canonical Patient Profile Fixture Library (α-min-2c, AD-66)

Deterministic patient scenario fixtures used by the narrative regression suite
(`tests/regression/test_narrative_profiles.py`). Each profile ships as a pair:

- `<profile_id>.yaml` — input (PatientProfile schema; see
  `clinosim/types/config.py:PatientProfile`)
- `<profile_id>.golden.json` — expected template narrative output for that
  profile at seed 42

This library is the β-JP-1 blocker: it establishes a deterministic
baseline against which future `LLMNarrativePass` output can be regression-tested.

## Profiles (α-min-2c ships 6)

| Profile ID | Disease | Severity | Archetype | Country |
|---|---|---|---|---|
| `jp_inpatient_bacterial_pneumonia` | bacterial_pneumonia | moderate | smooth_recovery | JP |
| `us_inpatient_acute_mi` | acute_mi | severe | plateau | US |
| `jp_icu_sepsis_hai_clabsi` | sepsis (+HAI) | severe | dip_then_recovery | JP |
| `us_inpatient_diabetic_ketoacidosis` | diabetic_ketoacidosis | severe | smooth_recovery | US |
| `jp_inpatient_copd_exacerbation` | copd_exacerbation | moderate | dip_then_recovery | JP |
| `us_inpatient_hemorrhagic_stroke` | hemorrhagic_stroke | severe | dip_then_recovery | US |

## Naming convention

`<country>_<encounter_type>_<condition_slug>.yaml`
- `country`: `us` / `jp`
- `encounter_type`: `inpatient` / `icu` (α-min-2c) / `ed` / `outpatient` (deferred to β-JP-1+)
- `condition_slug`: disease_id verbatim

## Adding a new profile

1. Copy the closest existing `<profile>.yaml`, edit fields
2. Ensure `profile_id` matches the new filename stem (loader raises otherwise)
3. Verify `disease_id` exists in `clinosim/modules/disease/reference_data/` and the chosen `archetype` exists in that disease's `course_archetypes`
4. Generate the initial golden:
   ```bash
   clinosim regenerate-goldens --profile <new_profile_id>
   ```
5. Manually review `<new_profile_id>.golden.json` — does it look right?
6. Commit both files together (see AD-66 rule 1: YAML changes must ship with golden regeneration)
7. Run the regression suite to verify:
   ```bash
   pytest -m regression -k <new_profile_id> -q
   ```

## Regenerating goldens after intentional narrative changes

When you intentionally change template narrative logic (e.g., add a new
section to the H&P template), the goldens will diff. Workflow:

1. Make the narrative change
2. Regenerate all goldens: `clinosim regenerate-goldens --all`
3. `git diff tests/fixtures/patient_profiles/*.golden.json` — inspect the diff
4. **Unexpected diff = regression suspicion**. Revert or fix the implementation.
5. **Expected diff** = commit YAML + golden together in the same PR.

See `CLAUDE.md` AD-66 rules 1-2 for the canonical policy.

## Regression suite invocation

```bash
# Run all profile regressions
pytest -m regression -q

# Run a single profile
pytest -m regression -k jp_inpatient_bacterial_pneumonia -q

# Verbose diff output on failure
pytest -m regression -q -s
```

The regression suite is opt-in via marker; the default `pytest` run does not
execute it (LLM cost + subprocess latency budget considerations).

## Related

- Spec: `docs/superpowers/specs/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`
- Plan: `docs/superpowers/plans/2026-07-03-tier1-3-alpha-min-2c-fixture-library-plan.md`
- ADR: `DESIGN.md` AD-66
- CLAUDE.md AD-66 rules
