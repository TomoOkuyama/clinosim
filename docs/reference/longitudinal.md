# Longitudinal state evolution

clinosim 0.6.5 ships a year-indexed trajectory engine that evolves
each alive person's clinical state across the simulation window —
HbA1c drifts under an AR(1) process, chronic staging ladders advance
by Markov transition, treatment escalates when guideline-triggers
fire, and new chronic conditions onset against age / sex / comorbidity
yaml. Every per-encounter emit site (lab values, chronic-med list,
TNM stage, GOLD / NYHA / CKD stage, inpatient disease activation)
reads the year-matched `YearSnapshot` through `state_at(person, when)`
rather than resampling from static distributions each visit.

Sibling Japanese doc:
[`longitudinal.ja.md`](longitudinal.ja.md).

## 1. What ships today

Phase 4a-4d features landed between 2026-10-20 and 2026-10-21 and
compose from one engine against per-attribute yaml declarations under
[`clinosim/locale/shared/longitudinal/`](https://github.com/TomoOkuyama/clinosim/tree/master/clinosim/locale/shared/longitudinal/).

| Pattern | Driver yaml | What it does |
|---|---|---|
| **AR(1) continuous latent** | `hba1c_trajectory.yaml` (plus `labs/ldl_trajectory.yaml`, `vitals/sbp_trajectory.yaml`, `anthropometry/bmi_drift.yaml`) | Within-individual HbA1c drift for E11 / E10 adults (phi 0.75, calibrated against DCCT/EDIC, UKPDS 10y, Wu 2023 meta-analysis). Per-encounter measurement-noise overlay (sigma 0.20 %) applied at emit. Replaces the retired `PersonRecord.glycemic_trajectory` proxy. |
| **Markov stage ladder** | `stage/<disease>.yaml` (19 ladders) | Year-over-year stage transitions for CKD (`n18`), heart failure (`i50` → NYHA I-IV), ischemic heart (`i25` → CCS I-IV), atrial fib (`i48` paroxysmal → persistent → permanent), COPD (`j44` → GOLD 1-4), dementia (`f00` → CDR 0.5-3), Parkinson (`g20`), multiple sclerosis (`g35`), alcoholic / fibrotic liver, stroke sequela (`i69` / `i69_1` / `i69_3`), and six cancer-staging ladders (`c16` gastric / `c18` colon / `c22` liver / `c34` lung / `c50` breast / `c61` prostate) under AJCC + BCLC. |
| **Event firing** | `event/<code>_onset.yaml` (30+ files) | Annual Bernoulli roll for chronic onset — DM E11 complications (`dm_nephropathy_e11_21`, `dm_neuropathy_e11_42`, `dm_retinopathy_e11_311`), 20+ adult-chronic ICDs sampled through locale-specific rate yaml with age / sex gating and `has_chronic_prefix` + `requires_sex` triggers (Phase 4b.2.β). |
| **Treatment escalation event** | `med/<regimen>.yaml` | HTN third- + fourth-agent step-up (`htn_escalate_third_agent_i10`, `htn_escalate_fourth_agent_i10`), lipid high-intensity + ezetimibe step-up (`lipid_escalate_high_intensity_e78`, `lipid_escalate_ezetimibe_e78`), DM SGLT2i and insulin step-up (`dm_escalate_sglt2i_e11`, `dm_escalate_insulin_e11`). Fires on guideline-trigger (e.g. HbA1c above target for ≥N years). Phase 4a scopes DM complications to T2DM (E11) only — T1DM (E10) is excluded. |

The engine itself is in
[`clinosim/modules/longitudinal/`](https://github.com/TomoOkuyama/clinosim/tree/master/clinosim/modules/longitudinal/):

- `engine.py` — `advance_one_year(person, year, year_rng)` + `state_at(person, when)` + `initial_snapshot(person, year, init_rng)`.
- `patterns/{ar1,markov,event}.py` — the three composable primitives.
- `loader.py` — yaml → `AttributeSpec`, with topological-sort of `depends_on` edges.
- `snapshot.py` — `YearSnapshot` dataclass (one per person per year on `PersonRecord.longitudinal_history`).

## 2. Public API

```python
from clinosim.modules.longitudinal import (
    YearSnapshot,     # per-year state container
    advance_one_year, # (person, year, year_rng) -> new YearSnapshot
    state_at,         # (person, when) -> YearSnapshot
    initial_snapshot, # (person, year, init_rng) -> first YearSnapshot
)
```

Internals under `patterns/` + `loader.py` + `snapshot.py` are not
part of the stable surface — these four entry points are the contract.
Per-encounter consumers read `state_at(person, when).continuous["hba1c"]`
(AR(1) latent) or `state_at(person, when).stage["n18"]` (Markov stage),
never resample.

## 3. Call integration

The engine is wired at two Layer-1 seams and read at three per-
encounter emit sites:

- **Layer-1 initialization** — `clinosim.modules.population.engine.generate_population`
  calls `initial_snapshot` for every alive person at generation time.
- **Annual advance** — the forward month loop
  (`clinosim/simulator/phases/_forward_loop.py`) calls
  `clinosim.modules.population.aging.advance_population` at each year
  boundary; it calls `advance_one_year` once per alive person per sim
  year, **after** that year's community-mortality draw and the aging
  passes finalise `chronic_conditions`.
- **Lab emit** — `clinosim.modules.physiology.engine.derive_lab_values`
  reads `state_at(person, when).continuous["hba1c"]` and applies the
  per-encounter measurement-noise overlay from the yaml.
- **Chronic-med derivation** — `clinosim.modules.patient.activator._derive_chronic_conditions`
  reads the current year's snapshot to build the DM stage string.
- **Cancer-stage emit** — the oncology service line reads
  `state_at(person, when).stage["<code>"]` to populate the AJCC / BCLC
  stage field on the per-encounter CIF payload.

## 4. Determinism contract

- Each year, the engine takes a single `np.random.Generator` passed
  by `advance_population` / `generate_population`. Draws per attribute
  execute in topological order of `depends_on` edges.
- `aging_sub_seed(person_id, year, "longitudinal")` seeds the per-
  person per-year generator for `advance_one_year`;
  `aging_sub_seed(person_id, base_year, "longitudinal:init")` seeds
  the Layer-1 `initial_snapshot` call. Both are deterministic sub-RNG
  streams, so two cohorts with the same seed produce byte-identical
  longitudinal histories.
- `state_at(person, when)` is pure (no RNG, O(1) lookup by year).
- `advance_one_year` raises on duplicate or backward year — the
  monotonicity invariant is upheld in the caller.

## 5. Tuning / disabling

Each yaml under `clinosim/locale/shared/longitudinal/` is a plain
Pydantic-validated config. To tune a parameter (e.g. HbA1c AR(1)
phi, a cancer stage transition probability, an HTN escalation
threshold), edit the yaml — the loader globs all `*.yaml` files
there at import time.

To disable a pattern on a particular cohort, remove or empty the
driver yaml (e.g. clear `dm_nephropathy_e11_21.yaml`'s rate block).
There is no CLI flag to disable the whole subsystem — the engine
is on the critical cohort-generation path and omitting it would
change the Layer-1 fingerprint.

To add a new attribute: write a new yaml under the matching sub-
directory (`stage/` / `event/` / `med/` or a sibling for a new
AR(1) latent), declare `attribute_id`, `pattern`, `depends_on`,
and the pattern-specific block. The loader + topological sort
pick it up at the next import.

## 6. Design document

Full phased architecture (Phase 1 shipping, Phase 2 Markov, Phase 3
event, Phase 4a-4d features): [`docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md`](https://github.com/TomoOkuyama/clinosim/blob/master/docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md).
Per-phase implementation plans sit alongside under
[`docs/superpowers/plans/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/superpowers/plans/).

## 7. Related references

- [`clinosim/modules/longitudinal/README.md`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/modules/longitudinal/README.md) — contributor-facing module README (purpose / scope / API / dependencies / testing).
- [`oncology-obstetric-service-lines.md`](oncology-obstetric-service-lines.md) — cancer AJCC/BCLC emit path that consumes the stage ladders.
- [`code-systems.md`](code-systems.md) — ICD-10 codes used in `event/*.yaml` triggers.
