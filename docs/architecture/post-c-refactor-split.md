# Post-C refactor layout — narrative + simulator + population engine split

Between 2026-10-15 and 2026-10-26, three god-class files were decomposed
into focused per-cluster modules through a 26-PR cascade (C1a-C1s +
C2a-C2f + C3a-C3e). Each extracted module stays byte-identical to its
pre-split origin — the engine façade files re-export every moved
symbol, so every historical import path continues to work. This page
is the map a contributor needs to find where a specific behavior now
lives.

Sibling Japanese doc: [`post-c-refactor-split.ja.md`](post-c-refactor-split.ja.md).

## 1. Scoreboard

| God-class file | Pre-split LOC | Current LOC | Reduction | Series |
|---|---:|---:|---:|---|
| `clinosim/modules/document/narrative/template_generator.py` | 6539 | 1399 | **-78.6 %** | **C1** (`a`-`s`) |
| `clinosim/simulator/engine.py` | 2059 | 632 | **-69.3 %** | **C2** (`a`-`f`) |
| `clinosim/modules/population/engine.py` | 2066 | 1157 | **-44.0 %** | **C3** (`a`-`e`) |
| **Total** | **10664** | **3188** | **-70.1 %** | |

Byte-identical for all 26 extraction PRs via `scripts/engine-fingerprint.sh`
on US p=500 seed=42 + JP p=500 seed=17 (full-cohort sha256
`0184a8b382990915e2e04ca6c94bce2d24e105b39d6be827f705c461f8f621a8`).

## 2. C1 — narrative template split (12 section builders + 4 shared helpers)

**Façade**: `clinosim/modules/document/narrative/template_generator.py`
(1399 LOC post-split). Every symbol below is re-exported from the
façade; historical callers (`generator._build_<section>`,
`TemplateNarrativeGenerator()._compose_<name>()`, direct free-function
imports) all keep working.

### Section builders — `renderers/section_builders/`

Twelve files; each exports free functions `build_<section>(generator, ctx)`.

| File | Covers | Phase |
|---|---|---|
| `assessment_and_plan.py` | A&P sections across doc types | C1m |
| `care_plans.py` | ACP + NCP + RP (31 methods) | C1e |
| `chief_complaint.py` | CC resolver + emit | C1n |
| `discharge_summary.py` | DS section cluster | C1i |
| `ed_note.py` | ED note section cluster | C1j |
| `hpi.py` | HPI composition + `_build_hpi_core` | C1o |
| `jp_clins.py` | JP-CLINS 3 Composition profiles | C1g |
| `mortality.py` | DC + DDS mortality narrative | C1f |
| `nursing.py` | Nursing shift / assessment / discharge | C1h |
| `op_pn_notes.py` | Operative + Procedure note cluster (17 methods) | C1d |
| `outpatient_soap.py` | Outpatient SOAP (4 builders + 10 composers; biggest file at 1116 LOC) | C1l |
| `patient_history.py` | PMH / medications / allergies / FH / SH | C1k |

### Shared helpers — `renderers/`

Four shared-cluster modules (post C1p-s) that back the section builders.
Still re-exported from `template_generator.py`.

| File | Content |
|---|---|
| `_resolvers.py` | `_resolve_physical_exam`, `_resolve_daily_trajectory`, `_resolve_daily_trajectory_with_source`, `_generic_trajectory`, `_resolve_discharge_instructions` |
| `_composers.py` | `_compose_progress_subjective_from_state`, `_compose_progress_assessment_from_state`, `_compose_progress_plan_from_state`, `_pick_stable_progress_phrase`, `_compose_today_vitals_line`, `_compose_pe_vitals_line`, `_apply_cc_pe_consistency`, `_compose_vital_signs_line` |
| `_ed_helpers.py` | `_get_ed_note_template`, `_ed_disposition_reason`, `_ed_triage_level` |
| `_shared_helpers.py` | `_pydantic_day_findings_to_dict`, `_format_physical_exam`, `_primary_surgical_procedure`, `_resolve_procedure_display` |

Earlier non-section renderers (B8 pilot + C1a-c, pre-section-builder era)
also live under `renderers/`: `ed_triage_note.py`, `nursing_shift_note.py`,
`progress_note.py`, `composition_sections.py`.

### Pattern

```python
# template_generator.py (façade)
from clinosim.modules.document.narrative.renderers.section_builders.hpi import (
    build_hpi as build_hpi,
    _build_hpi_core as _build_hpi_core,
)
# ...and 11 more section-builder re-exports.

class TemplateNarrativeGenerator:
    def _build_hpi(self, ctx):
        # thin lazy-import delegator so composition_sections.py's
        # generator._build_<section> lookup keeps resolving
        from clinosim.modules.document.narrative.renderers.section_builders.hpi import (
            build_hpi,
        )
        return build_hpi(self, ctx)
```

Direct free-function imports also work:

```python
from clinosim.modules.document.narrative.renderers.section_builders.hpi import (
    build_hpi,
)
```

**When fixing a narrative bug**: trace from the thin delegator in
`template_generator.py` into its backing `renderers/section_builders/<section>.py`.
The delegator is a 2-line shim; the real body is in the per-section file.

## 3. C2 — simulator engine split (setup + dispatch + 4 phases)

**Façade**: `clinosim/simulator/engine.py` (632 LOC post-split).
`run_beta` + `run_forced` remain the top-level entries.

### Extracted modules

| File | Content | Phase |
|---|---|---|
| `clinosim/simulator/_setup.py` | 9 helpers — `_load_health_screening_visit_reason`, `_HEALTH_SCREENING_VISIT_REASON`, `_HEALTH_SCREENING_VISIT_REASON_FALLBACK`, `_pediatric_visit_reason`, `_parse_time_range_bound`, `_TimeRangeBounds`, `_activate_cached_person`, `_derive_time_range_bounds`, `_load_hospital_ops`, `_resolve_pop_size`, `_load_prev_admission_cache` | C2a |
| `clinosim/simulator/_dispatch.py` | Hospital-event dispatcher + overlap handling — `_find_active_inpatient_record`, `_find_overlapping_inpatient_record`, `_verify_no_actual_overlap`, `_handle_overlap_via_merge`, `_merge_disease_into_active_encounter`, `_replay_cached_admission_queue`, `_DispatchState`, `_dispatch_hospital_events` | C2b |
| `clinosim/simulator/phases/_healthcare_calendar.py` | `_run_healthcare_calendar_phase` (per-year scheduler) | C2c |
| `clinosim/simulator/phases/_post_discharge.py` | `_run_post_discharge_phase` | C2d |
| `clinosim/simulator/phases/_readmission.py` | `_run_readmission_phase` | C2e |
| `clinosim/simulator/phases/_ed_slot.py` | `_run_ed_slot_phase` | C2f |

### Why these boundaries (vs the original proposal)

The pre-C2 plan at [`../design-guides/p6-god-function-split-plan.md`](../design-guides/p6-god-function-split-plan.md)
proposed phase names `_run_beta_prepare` / `_run_beta_month_tick` /
`_run_beta_dispatch_window` / `_run_beta_writeback`. The actual split
chose `_setup` + `_dispatch` + the four per-phase runners instead, which
map more directly to the natural data-flow boundary (setup → monthly
dispatch loop → per-phase runners) and allow each phase runner to be
reasoned about in isolation.

## 4. C3 — population engine split (5 clusters)

**Façade**: `clinosim/modules/population/engine.py` (1157 LOC post-split).

### Extracted modules

| File | Content | Phase |
|---|---|---|
| `clinosim/modules/population/_chronic.py` | `ChronicConditionSpec`, `_bmi_category_probabilities`, `_smoking_status_probabilities`, `_expected_lifestyle_multiplier`, `_expected_comorbidity_multiplier`, `_target_prev_at_age_legacy`, `_parse_chronic_prevalence` | C3a |
| `clinosim/modules/population/_demographics.py` | `_load_demographics`, `_parse_age_distribution`, `_disease_monthly_rate_from_locale`, `_sample_age_band`, `_sex_ratio_male_probability`, `_care_seeking_threshold_mean`, `_RH_POSITIVE_FRACTION`, `_derive_race`, `_derive_ethnicity`, `_derive_rh_factor`, `_sample_blood_type` | C3b |
| `clinosim/modules/population/_identity.py` | `_load_name_data`, `_sample_surname`, `_sample_given_name`, `_sample_occupation`, `_generate_household_address`, `_generate_phone` | C3c |
| `clinosim/modules/population/_pregnancy.py` | `_PREGNANCY_ELIGIBLE_MIN_AGE`, `_PREGNANCY_ELIGIBLE_MAX_AGE`, `_PERINATAL_STAGE_COUNTERS`, `_annual_conception_rate`, `_perinatal_stage_incr`, `_pregnancy_lifecycle_events` | C3d |
| `clinosim/modules/population/_chemo.py` | `pick_active_chemo_regimen` (public helper), `_chemo_cycle_events` | C3e |

### Lazy local imports

Several modules under `_chemo.py` / `_pregnancy.py` use lazy local
imports for `clinosim.locale.loader` + `clinosim.seeding` + 
`clinosim.simulator.perinatal` to decouple inter-PR dependency chains.
This keeps `python -c "import clinosim.modules.population"` cheap and
avoids an import cycle through the façade.

## 5. Thin-delegator re-export pattern (uniform)

Every extracted module is wired back through the façade with the
same shape:

```python
# engine.py (façade)
from clinosim.modules.population._chemo import (
    pick_active_chemo_regimen as pick_active_chemo_regimen,
    _chemo_cycle_events as _chemo_cycle_events,
)
```

The `as <name>` form is **required** — `ruff --select F401` would
otherwise flag these as unused imports. The `as` export makes the
re-export visible to type-checkers and keeps the F401 gate clean.

External callers:

```python
# Still works unchanged (historical import)
from clinosim.modules.population.engine import pick_active_chemo_regimen

# Also works (direct import of the authoritative source)
from clinosim.modules.population._chemo import pick_active_chemo_regimen
```

## 6. Verification contract

Every extraction PR passed:

- **Full `tests/unit/` suite**: 7092 passed, 16 skipped, 1 xfailed.
- **Byte-identical cohort fingerprint**: US p=500 seed=42 + JP p=500
  seed=17 window `2025-01..04`, via `scripts/engine-fingerprint.sh`.
  Branch and `origin/master` baseline both carry
  `TOTAL sha256 0184a8b382990915e2e04ca6c94bce2d24e105b39d6be827f705c461f8f621a8`.
- `ruff check`, `ruff format`, `ruff --select F401,F841`,
  `mypy --strict`, `vulture --min-confidence 60` — all green.

**No RNG consumption reordering**: every helper that touched a
caller-supplied `np.random.Generator` kept its sequence intact.
Where new sub-RNGs appeared (e.g. `perinatal_delivery_seed(person_id, year)`,
`chemotherapy_regimen_seed(person_id, cancer_code)`), they are per-
patient / per-code deterministic sub-seeds that do not touch the
master stream — so YAML edits to the yaml data files these helpers
read never cascade into unrelated patients' calendars.

## 7. Where to look next

- [`module-architecture.md`](module-architecture.md) — top-level package tree, now reflects the post-C2 simulator layout.
- [`../design-guides/p6-god-function-split-plan.md`](../design-guides/p6-god-function-split-plan.md) — the original pre-execution plan with the shipped-execution callouts added inline.
- Each extracted module's own file-level docstring — carries the "RNG-neutrality contract", "cross-year state" invariants, and other per-cluster design notes verbatim lifted from the engine original.
