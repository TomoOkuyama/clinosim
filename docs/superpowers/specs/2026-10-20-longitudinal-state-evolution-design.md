# longitudinal state evolution — design spec

- **Status**: Draft (awaiting user review)
- **Date**: 2026-10-20
- **Owner**: s104 cohort-audit follow-up
- **Tracks**:
  - #1695 — HbA1c lab time-series lacks physiological temporal smoothness
  - #1696 — Chronic disease stage frozen across sim window (CKD / COPD / DM / dementia / CAD progression)
  - #1697 — Chronic DM / HTN / dyslipidemia 5y uncontrolled: no escalation + no complication-code onset
  - #1705 — Adult BMI / height / weight single scalar across sim window
  - META tracker #1694
- **Anticipated release**: v0.7.0 (MINOR bump — CIF structural change: new `PersonRecord.state_history` field, new per-attribute yaml data, treatment / stage / lab / anthropometry values change for every patient whose chronic trajectory now evolves)

## 1. Purpose

Four audit findings share one architectural root cause: **patient state is modelled as a snapshot, not a trajectory**. The current pipeline captures a single-point `PatientProfile` (height / weight / BMI / stored chronic stage / home-medication list) at Layer-1 generation, and the aging module (`clinosim/modules/population/aging.py`) carries two in-place passes (`_disease_progression`, `_annual_chronic_onset`) that mutate `PersonRecord` fields per year but leave no year-indexed history behind. Per-encounter emit (labs, anthropometric Observations, Condition.stage) reads the end-of-sim snapshot even for mid-sim encounters, which produces the audit's symptoms:

- HbA1c values i.i.d. per encounter against a frozen glycemic target, violating the 120-day erythrocyte-lifespan smoothness bound (±2.5 % swings in 1-2 months on POP-001356).
- Chronic stage strings (`"HbA1c 11.1 %"`, `"CCS III"`, `"Stage 2"`) unchanged across 5 years.
- No treatment escalation under laboratory evidence of non-response (DM A1c > 10 % for 5y on metformin monotherapy; LDL 171 → 192 under atorvastatin).
- No DM-complication code onset (E11.21 / E11.3x / E11.4x) despite sustained poor control.
- Adult BMI constant for 5y encounter stream.

This design introduces a **single longitudinal state-evolution subsystem** that each of those four findings resolves against, instead of four parallel patches that duplicate per-year RNG scaffolding, per-attribute yaml loaders, and per-attribute history serialisation. The design intent is **data split per clinical attribute** (so a domain expert reviews one yaml) and **logic unified in one engine** (so the clinosim maintainer reads one Python module).

## 2. Scope

### 2.1 In scope

Three reusable trajectory **patterns**, implemented once in a new `clinosim.modules.longitudinal` engine, invoked annually from the existing sim-time aging driver:

1. **AR(1) continuous** — per-year mean-reverting Markov step on a scalar latent (HbA1c, LDL, systolic BP, body weight / BMI). The latent drives per-encounter lab / vital sampling via a per-encounter noise overlay.
2. **Discrete Markov transition** — per-year Bernoulli (or multi-state) advance on an ordered categorical state space (CKD G1 → G5, NYHA I → IV, CCS I → III, CDR 0.5 → 3, GOLD 1 → 4).
3. **Event firing** — per-year gated incidence of a new ICD code or medication class, conditional on the current latent and prior history (DM complication onset E11.2x / E11.3x / E11.4x gated on HbA1c trajectory; medication escalation adds SGLT2i / insulin / high-intensity statin / third antihypertensive once uncontrolled N years).

A new serialised structure `PersonRecord.state_history: list[YearSnapshot]` holds one entry per sim year, written to CIF alongside the existing per-patient JSON. Per-encounter emit consumers (labs, anthropometric Observations, FHIR Condition.stage, chronic-condition narrative) read the year-matched snapshot instead of the end-of-sim `PatientProfile` scalars.

Per-attribute data lives in `clinosim/locale/shared/longitudinal/<attribute>.yaml` with a `pattern:` discriminator (`ar1 | markov | event`) and pattern-specific parameters. A per-attribute yaml is reviewed by its clinical domain expert in isolation; the engine never embeds clinical values.

**Phase 1 scope expansion — HbA1c as the clinical primitive**: today's `PersonRecord.glycemic_control: float ∈ [0, 1]` is a synthetic proxy from which `hba1c_from_glycemic_control(gc)` (`clinosim/modules/physiology/engine.py:946`) derives the emitted HbA1c value, and `patient/activator.py:460` emits the stage string. Both are time-invariant. Phase 1 **retires `glycemic_control`** and makes `YearSnapshot.continuous["hba1c"]` the single source of truth — the clinical primitive clinicians measure, not a proxy. All callers of `hba1c_from_glycemic_control` migrate to reading the HbA1c latent from `state_at(person, when).continuous["hba1c"]` directly. This widens Phase 1 touch to `physiology/engine.py`, `patient/activator.py`, and the perinatal / health_checkup HbA1c read sites, but eliminates the proxy / dual-source class of bugs end-to-end.

### 2.2 Out of scope (post-Phase 3 or separate issues)

- **Per-encounter (sub-year) interpolation of continuous latents.** Phase 1 uses per-year snapshots and lets per-encounter emit sample from the current year's latent. If sub-year interpolation is desired later (e.g. HbA1c smoothly interpolated between year endpoints), it is a Phase-4 extension to the AR(1) pattern.
- **New longitudinal attributes beyond the four audit issues.** This design seats the three patterns and three MVP attributes (HbA1c AR(1), CKD/CCS/NYHA Markov, DM-complication event). Adding later attributes (BUN, GFR, FEV1, cognitive-decline-rate-adjusted CDR, oncology staging) is one yaml plus a 2-line engine registration each.
- **Changing the aging driver's cadence.** The engine runs annually, same as `advance_population` today. Monthly or event-driven cadences are out of scope.
- **Pediatric growth-chart longitudinal.** Growth-chart medians at age-at-encounter are already handled by the pediatric-anthropometrics path (PR #1691 + #1692). This design does not touch that path.
- **Mortality trajectory modelling.** `_condition_reactive_mortality` already applies per-year excess qx based on condition load; it stays in the aging module and does not migrate into the new engine.

### 2.3 Non-goals

- **Byte-identity preservation across the migration.** The user has explicitly accepted that pre-PR / post-PR CIF bytes differ for every patient whose trajectory evolves. The reproducibility contract (same seed, same code version → same output bytes) stays intact and is validated by `scripts/reproduce.sh`; what changes is the content of those bytes.
- **"DM-only byte-diff" boundary in Phase 1.** Because the aging driver passes a single Generator to the engine and the engine draws from it, every downstream RNG consumer shifts for every patient — not only DM patients. This is accepted; the quality improvement from a single HbA1c trajectory primitive takes precedence over cursor-preserving isolation. Non-DM patients' per-attribute content is semantically unchanged (no HbA1c latent is written for them), but their byte stream still shifts via the driver's cursor.
- **Direct FHIR Observation `.component[*]` emission of the per-year latent.** The year-level `YearSnapshot` is CIF-only; FHIR emit still produces per-encounter Observations as today, now reading the year-matched latent instead of the stored scalar.

### 2.4 Anti-goals

- A design where the trajectory logic lives in multiple modules (lab sampler, chronic-condition emit, patient activator, aging module) and gets patched four times for every new attribute. This is the current pathology.
- A design where byte-identity across the migration is partly preserved and partly not — the half-preserved case produces an uninterpretable byte-diff and misleads later reproducibility auditing. Either the migration is a clean MINOR bump (chosen) or byte-identical (rejected: the current output is not clinically correct).

## 3. Architecture

### 3.1 Module shape

```
clinosim/modules/longitudinal/
├── __init__.py                       # public API re-export
├── engine.py                         # advance_one_year(person, year, rng); state_at(person, when)
├── patterns/
│   ├── __init__.py                   # pattern registry
│   ├── ar1.py                        # AR(1) step + per-year latent clamp
│   ├── markov.py                     # ordered categorical transition
│   └── event.py                      # gated incidence event (ICD onset / med add)
├── snapshot.py                       # YearSnapshot dataclass + serialisation helpers
├── loader.py                         # yaml → AttributeSpec (lru_cache)
├── audit.py                          # AD-60 audit plug-in (verifies trajectory integrity)
├── reference_data/
│   └── README.md                     # per-attribute yaml schema doc
├── README.md
└── README.ja.md

clinosim/locale/shared/longitudinal/
├── hba1c_trajectory.yaml             # Phase 1 attribute
├── ckd_stage_transitions.yaml        # Phase 2 attribute
├── ccs_stage_transitions.yaml        # Phase 2 attribute
├── nyha_stage_transitions.yaml       # Phase 2 attribute
├── cdr_stage_transitions.yaml        # Phase 2 attribute
├── gold_stage_transitions.yaml       # Phase 2 attribute
├── dm_complication_onset.yaml        # Phase 3 attribute
├── dm_treatment_escalation.yaml      # Phase 3 attribute
├── bmi_drift.yaml                    # Phase 3 attribute
└── README.md                         # catalog + authoring guide
```

**Layer placement**: Foundation. Reads `clinosim/locale/shared/longitudinal/`. Does not depend on `clinosim/modules/output`, `clinosim/simulator` or any encounter module — those are its downstream consumers. Imports from `clinosim.types.population` (`PersonRecord`).

**Driver**: `clinosim/modules/population/aging.py::advance_population` is extended to invoke `longitudinal.engine.advance_one_year(person, year, rng)` per alive person per year, alongside its existing passes (which are themselves refactored to run under the new engine — see §7 Migration). Order within a year is deterministic (see §6 Determinism).

### 3.2 Data flow (one sim year)

```
advance_population(year)
      │
      ▼
for each alive person:
      │
      ▼
longitudinal.engine.advance_one_year(person, year, year_sub_rng)
      │
      ├─ load per-attribute specs (lru_cached)
      ├─ for each registered attribute, in dependency order:
      │     ├─ pattern = AR1 | Markov | Event
      │     ├─ pattern.step(person, year, attr_sub_rng, spec)
      │     │    └─ reads prev YearSnapshot from state_history[-1]
      │     │       computes new value under pattern math
      │     │       writes into the year's YearSnapshot
      │     └─ YearSnapshot is accumulating
      │
      └─ person.state_history.append(YearSnapshot)   # one per sim year

...later, at per-encounter emit time:

per-encounter emit (e.g. lab sampler, Condition.stage emit)
      │
      ▼
longitudinal.engine.state_at(person, encounter_datetime)
      │
      ▼
returns YearSnapshot matching encounter_datetime.year
      │
      ▼
emitter uses snapshot values (bmi, hba1c_latent, chronic_stages[icd], ...)
      │
      ▼
per-encounter noise overlay (continuous attributes only)
      │
      ▼
Observation / Condition / MedicationRequest resource
```

### 3.3 Pattern composition

Attributes may read other attributes within the same year's snapshot — this is why advance order matters and why dependency is declared explicitly in yaml:

- `dm_complication_onset` (event) **depends on** `hba1c_trajectory` (AR1) — complication incidence multiplied by (HbA1c − 7.0)⁺
- `dm_treatment_escalation` (event) **depends on** `hba1c_trajectory` (AR1) — escalates when A1c > threshold for N consecutive years
- `ckd_stage_transitions` (Markov) **depends on** `hba1c_trajectory` (optional, DM-only accelerator) + `bp_trajectory` (optional, HTN-only accelerator)

The engine topologically sorts attributes per sim year using declared `depends_on:` keys and executes in that order. A cycle is a yaml authoring error and raises at import.

## 4. Data model

### 4.1 `YearSnapshot` dataclass

```python
@dataclass
class YearSnapshot:
    year: int
    # Continuous latents (AR(1) attributes)
    continuous: dict[str, float] = field(default_factory=dict)
    # Discrete stage states (Markov attributes), keyed by ICD base code
    chronic_stages: dict[str, str] = field(default_factory=dict)
    # New-this-year ICD codes added by event-pattern attributes
    new_complications: list[str] = field(default_factory=list)
    # New-this-year medication additions (drug name list)
    med_additions: list[str] = field(default_factory=list)
    # Medications held / stopped this year (drug name list)
    med_removals: list[str] = field(default_factory=list)
```

Serialised to CIF under `PersonRecord.state_history: list[YearSnapshot]`. Replaces no existing field — purely additive. The existing per-patient-end `PatientProfile` scalars (height / weight / BMI / stage) remain but become **derived** from the final `state_history[-1]` entry (the end-of-sim snapshot) rather than the authoritative source.

### 4.2 Per-attribute yaml schema (common header)

Every per-attribute yaml follows the same frontmatter so the loader can dispatch to the right pattern:

```yaml
# locale/shared/longitudinal/<attribute>.yaml
attribute_id: hba1c                     # unique key, lower-snake-case
pattern: ar1                            # ar1 | markov | event
depends_on: []                          # list of other attribute_id
clinical_scope:                         # which patients this attribute runs for
  requires_chronic_codes: ["E11", "E10"]  # at least one of these on person.chronic_conditions
  requires_age_band: [18, 120]            # inclusive
# ... pattern-specific body below ...
```

The three pattern-specific bodies:

#### 4.2.1 `pattern: ar1` body

Clinical-primitive note: the Phase 1 attribute is `hba1c` (not `glycemic_control`). The engine replaces the proxy. Parameters are **literature-calibrated** from published long-term DM cohorts (see `source:` field) rather than hand-tuned against synthetic output. The Phase 1 pre-work step produces the fit; the cohort audit then validates against the RBC-lifespan smoothness bound.

```yaml
pattern: ar1
latent_name: hba1c                      # key written into YearSnapshot.continuous
initial:
  distribution:                         # entry-year sampling for new E11.x/E10.x person
    kind: lognormal                     # per DCCT/EDIC distribution shape
    mu: 2.00                            # log(e^2.00) ≈ 7.4%
    sigma: 0.22
    clamp: [4.5, 14.0]
ar1:
  phi: 0.72                             # autoregressive coefficient per year
  sigma: 0.6                            # innovation sd (per-year)
  mean_reversion_target: 7.0            # long-run attractor (treatment-effective target)
  drift:                                # trajectory nudges from other attributes / state
    - when: {attribute: dm_treatment_escalation, event: insulin_add}
      delta: -1.5                       # insulin add drops the latent by 1.5
    - when: {chronic_absent: ["E11.2x", "E11.3x", "E11.4x"]}
      delta: 0.0                        # no-complication cohort: no drift
clamp: [4.0, 15.0]                      # physiologic plausibility
per_encounter_noise:
  sigma: 0.3                            # per-encounter measurement noise overlay (±0.6 %)
narrative_label:
  en: "HbA1c trajectory"
  ja: "HbA1c 推移"
source:                                 # literature anchors — reviewable by the DM domain expert
  - "DCCT/EDIC — Nathan DM et al., NEJM 2005;353:2643. Long-term HbA1c variability under intensive vs conventional therapy."
  - "ADVANCE — Patel A et al., NEJM 2008;358:2560. 5-year HbA1c trajectory under tight glycemic control."
  - "ADA Standards of Care 2024 — HbA1c targets by comorbidity class."
```

#### 4.2.2 `pattern: markov` body

```yaml
pattern: markov
state_name: ckd_stage                   # key written into YearSnapshot.chronic_stages, under the ICD base
icd_base: N18                           # which chronic condition this stage belongs to
states: [G1, G2, G3a, G3b, G4, G5]      # ordered
initial_distribution:                   # entry-year sampling if not already staged
  G1: 0.20
  G2: 0.45
  G3a: 0.20
  G3b: 0.10
  G4: 0.04
  G5: 0.01
transitions:                            # per-year advance probabilities
  G1: {G2: 0.08}
  G2: {G3a: 0.09}
  G3a: {G3b: 0.07}
  G3b: {G4: 0.05}
  G4: {G5: 0.03}
  G5: {}                                # absorbing
modifiers:                              # multipliers on base transition
  - when: {attribute: hba1c, operator: ">", value: 9.0}
    factor: 1.5                         # uncontrolled DM accelerates CKD
  - when: {chronic_code: "I10"}
    factor: 1.2                         # HTN accelerates CKD
narrative_label:
  en: "CKD stage"
  ja: "CKD ステージ"
```

#### 4.2.3 `pattern: event` body

```yaml
pattern: event
event_name: dm_retinopathy_onset
emits_icd: E11.311                      # ICD-10-CM added to chronic_conditions on fire
base_annual_rate: 0.015                 # 1.5 % / year baseline
rate_modifiers:
  - when: {attribute: hba1c, operator: ">", value: 9.0}
    factor: 3.0
  - when: {years_since_dx: {attribute: hba1c, operator: ">", value: 5}}
    factor: 1.5
one_shot: true                          # fires once per patient (no re-onset)
narrative_label:
  en: "Diabetic retinopathy onset"
  ja: "糖尿病性網膜症発症"
```

### 4.3 Loader behaviour

- `loader.load_attribute_specs()` returns `dict[attribute_id, AttributeSpec]`, lru_cached.
- Validates frontmatter + pattern-specific body against a pydantic model per pattern.
- Builds the dependency graph; topologically sorts; raises on cycle.
- `AttributeSpec` carries only data — no python callbacks in yaml.

## 5. API

### 5.1 `longitudinal.engine`

```python
def advance_one_year(
    person: PersonRecord,
    year: int,
    year_rng: np.random.Generator,
) -> YearSnapshot:
    """Advance person's longitudinal state by one year. Appends a new
    YearSnapshot to person.state_history and returns it. Idempotent:
    calling twice for the same (person, year) raises."""

def state_at(
    person: PersonRecord,
    when: datetime | date,
) -> YearSnapshot:
    """Return the YearSnapshot whose year matches when.year. Raises if
    person.state_history is empty (person was never advanced) or if
    when.year falls outside the stored range."""

def initial_snapshot(
    person: PersonRecord,
    year: int,
    init_rng: np.random.Generator,
) -> YearSnapshot:
    """Build the YearSnapshot for the person's sim-start year from
    their Layer-1 PatientProfile values + per-attribute initial
    distributions. Called once per person at sim start (and per baby
    at mid-sim birth)."""
```

### 5.2 Pattern-level API (internal)

```python
# patterns/ar1.py
def step(prev: float, attr_rng: np.random.Generator, spec: AR1Spec, context: StepContext) -> float: ...
def initial(init_rng: np.random.Generator, spec: AR1Spec, context: StepContext) -> float: ...

# patterns/markov.py
def step(prev: str, attr_rng: np.random.Generator, spec: MarkovSpec, context: StepContext) -> str: ...
def initial(init_rng: np.random.Generator, spec: MarkovSpec, context: StepContext) -> str: ...

# patterns/event.py
def step(prev_history: list[YearSnapshot], attr_rng: np.random.Generator, spec: EventSpec, context: StepContext) -> EventResult: ...
```

`StepContext` carries the current year's partially-built snapshot (so an event pattern can read an AR(1) latent that already executed this year), the person's chronic_conditions, age, sex, and country.

### 5.3 Caller-side read

```python
# clinosim/modules/output/.../labs/<lab>.py (lab sampler)
snapshot = longitudinal.engine.state_at(person, encounter.admission_datetime)
hba1c_latent = snapshot.continuous.get("hba1c", DEFAULT_HBA1C)
emitted_value = hba1c_latent + ar1_spec.per_encounter_noise.sigma * rng.standard_normal()

# clinosim/modules/output/fhir_r4/conditions/<condition>.py
snapshot = longitudinal.engine.state_at(person, encounter.admission_datetime)
stage = snapshot.chronic_stages.get("N18", "G2")  # fallback = ICD base + default
```

## 6. Determinism

- The engine takes a Generator from the aging driver and draws from it directly. No internal sub-seeding per attribute — the single-stream model keeps the engine's cursor-shift behaviour predictable and reviewable. "Non-DM patients byte-identical" is explicitly a non-goal (see §2.3); the engine advances every alive person every year, which shifts the aging driver's cursor for everyone.
- Within a year, attributes execute in topologically-sorted order of their `depends_on` edges. The order is derived from yaml declarations only — no python registration order dependence.
- `state_at(person, when)` is pure: no RNG, no I/O, O(1) lookup via `state_history[when.year - sim_start_year]`.
- `advance_one_year` is idempotent per (person, year): a second call raises rather than overwriting. The aging driver enforces a single-call-per-(person, year) invariant upstream; if F4 memoize paths later re-hydrate an already-advanced person, the driver's gate (not the engine) handles the skip.
- The pre-fix / post-fix reproducibility contract: for any given (seed, code version, config, country, start, end, population) tuple, running the sim twice produces byte-identical output. `scripts/reproduce.sh` continues to run as a CI gate on this contract.
- The pre-PR / post-PR output bytes change for every patient (not only DM patients) because of the cursor-shift model above. This is intentional and part of the MINOR bump.

## 7. Migration — existing aging passes absorbed

Today's `clinosim/modules/population/aging.py` carries five per-year passes:

1. `_annual_chronic_onset` — age × sex incidence of new chronic conditions
2. `_stroke_sequela_promotion` — post-stroke I69.x promotion
3. `_disease_progression` — CKD / COPD / NYHA / CCS / CDR stage advancement (via `stage_transition.yaml`)
4. `_allergy_drift` — childhood resolution / adult-onset drug allergy
5. `_condition_reactive_mortality` — excess qx layered on baseline

Of these, (3) is the direct target of the new engine's Markov pattern. (1) partially overlaps with the engine's event pattern (new chronic ICD onset). (2), (4), (5) stay in the aging module.

**Migration plan**:

- **Phase 1 (framework + HbA1c)**: new engine lives alongside aging. aging passes unchanged. The driver `advance_population` calls both. HbA1c AR(1) is the only new attribute. CIF structurally grows a `state_history` field. Per-encounter HbA1c lab sampler is wired to `state_at` and uses the trajectory instead of the current state-conditional draw. No existing aging pass is deleted.
- **Phase 2 (Markov stage absorption)**: `_disease_progression` is rewritten to call the Markov pattern via per-attribute yaml (one yaml per family: CKD / CCS / NYHA / CDR / GOLD). The old `stage_transition.yaml` is retired. Per-encounter Condition.stage emit now reads `state_at(encounter).chronic_stages[icd_base]`.
- **Phase 3 (event absorption)**: `_annual_chronic_onset` adult-chronic path (not the pediatric-calendar path) is rewritten to call the event pattern via per-attribute yaml. DM complication onset (E11.2x / E11.3x / E11.4x) and DM treatment escalation (SGLT2i / insulin add; metformin dose up) land as new event attributes here. BMI drift AR(1) also lands.

Each phase is a separate PR, each MINOR-track, each with its own regenerated-cohort audit (same pattern as PRs #1691 → #1692 → #1693).

## 8. Phase plan

### Phase 1 — framework + HbA1c AR(1) + glycemic_control retirement (this PR's successor)

**Phase 1 pre-work** (lands in the same PR as a separate commit, so review is bisectable):

1. Collect published long-term HbA1c longitudinal data (DCCT/EDIC, ADVANCE, ADA Standards of Care). Fit AR(1) parameters (`phi`, `sigma`, `mean_reversion_target`) by MLE or Kalman filter against the published summary statistics.
2. Record the fit methodology + bibliographic sources in `locale/shared/longitudinal/hba1c_trajectory.yaml::source:` so the DM domain expert can audit.

**Phase 1 build**:

- **In**:
  - new `clinosim.modules.longitudinal` package (engine, patterns/ar1.py, snapshot.py, loader.py, audit.py, README);
  - `YearSnapshot` dataclass + CIF serialisation via `cif_writer.py`;
  - `advance_one_year` + `state_at` + `initial_snapshot` entry points;
  - AR(1) pattern math;
  - `hba1c_trajectory.yaml` with the fit parameters + sources;
  - **retirement of `PersonRecord.glycemic_control`** — `hba1c_from_glycemic_control(gc)` is replaced by direct read of `state_at(person, when).continuous["hba1c"]` at every caller;
  - migration of `clinosim/modules/physiology/engine.py` HbA1c derivation path;
  - migration of `clinosim/modules/patient/activator.py:460` stage-string generation to read the current year's HbA1c latent;
  - migration of health_checkup / per-encounter HbA1c read sites (grep `glycemic_control` to enumerate);
  - unit tests on pattern math, loader DAG, YearSnapshot serialisation, state_at lookup, physiologic HbA1c bounds;
  - integration test: p=50 cohort DM patient's HbA1c series respects AR(1) smoothness and the RBC-lifespan bound;
  - cohort audit on p=500 US seed=42 5y confirming no ±2% jump in any 60-day window across all DM patients;
  - re-generation of any pinned-value fixture (CIF JSON samples, FHIR golden files) touched by the HbA1c migration.
- **Out**: Markov pattern (Phase 2), event pattern (Phase 3), baby `initial_snapshot` wiring (Phase 2 — Phase 1 AR(1) is `requires_age_band: [18, 120]` so BABY patients have empty `state_history` in Phase 1), per-encounter sub-year interpolation (Phase 4 if ever).
- **Closes**: #1695. Does not close #1696 / #1697 / #1705.
- **Byte-diff scope**: every patient (not only DM). DM patients see HbA1c trajectory values change substantively; non-DM patients see cursor-shift-only byte changes with no semantic content change.

### Phase 2 — Markov stage absorption

- **In**: Markov pattern; `ckd_stage_transitions.yaml` + `ccs_stage_transitions.yaml` + `nyha_stage_transitions.yaml` + `cdr_stage_transitions.yaml` + `gold_stage_transitions.yaml`; migration of `_disease_progression` into the new engine; `state_history[y].chronic_stages[icd]` consumed by Condition.stage FHIR emit + narrative stage renderers; retirement of `stage_transition.yaml`.
- **Closes**: #1696.
- **Byte-diff scope**: every patient with CKD / CAD / HF / dementia / COPD chronic. Patients without any of these: byte-identical.

### Phase 3 — event pattern + BMI drift + DM escalation

- **In**: Event pattern; `dm_complication_onset.yaml` (E11.21 nephropathy, E11.31 retinopathy, E11.42 neuropathy); `dm_treatment_escalation.yaml` (metformin → + SGLT2i → + insulin, driven by HbA1c trajectory); `bmi_drift.yaml` (AR(1) on BMI); migration of `_annual_chronic_onset` adult-chronic path into the event pattern.
- **Closes**: #1697, #1705.
- **Byte-diff scope**: every adult patient with DM, HTN, dyslipidemia or obesity (bulk of the cohort).

### Phase 4 (optional, post-audit) — fill-ins

Follow-up audit on the Phase-3 cohort may surface new candidates (LDL / BP AR(1), additional complication events, specialty-driven stage targets). Each lands as one new yaml plus one engine registration line.

## 9. Testing

### 9.1 Unit (`tests/modules/longitudinal/`)

- `test_ar1_step_math.py` — AR(1) step preserves mean reversion to `mean_reversion_target` under long chains; variance converges to `sigma² / (1 − phi²)`; clamp enforced on tails.
- `test_markov_step.py` — transition probability respected; absorbing state never leaves; modifiers compound correctly.
- `test_event_step.py` — one_shot never re-fires; rate modifiers multiplicative; emits_icd gets added to `new_complications`.
- `test_loader_dependency_sort.py` — topological sort stable; cycle raises; missing dependency raises; yaml schema violations caught at import.
- `test_year_snapshot_serialisation.py` — JSON round-trip stable; dataclass asdict compatible with existing CIF writer.
- `test_state_at_lookup.py` — year-matching semantics correct across year boundaries; raises on out-of-range.
- `test_hba1c_physiological_bounds.py` — Phase 1: 1000-seed sweep on a mock DM patient, verify no ±2-point jump in any 60-day window (the audit's violated constraint).

### 9.2 Integration (`tests/integration/`)

- `test_longitudinal_engine_integration.py` — mini cohort p=50 run end-to-end, verify `state_history` populated per alive person; `state_at(encounter)` matches encounter year; no missing years.
- `test_hba1c_trajectory_in_cif.py` — a DM patient's HbA1c lab series extracted from CIF shows AR(1) auto-correlation at Δt < 60 d > 0.6; cohort-level mean reversion within ±0.5 of target.
- `test_byte_reproducibility_longitudinal.py` — same seed run twice; `scripts/reproduce.sh` continues to pass with the new engine.

### 9.3 Cohort audit (manual, per phase)

Each phase lands with a p=500 US seed=42 5y audit comparing pre-fix / post-fix on the attributes it changes. Audit script sits in `scratchpad/` and is not checked in — the per-phase PR body carries the pre/post table.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| New engine's per-year RNG draws shift every downstream RNG consumer (encounter dispatch, lab sampling, etc.) when year sub-seeds collide with existing streams | Use `aging_sub_seed(person_id, year, f"longitudinal:{attribute_id}")` with the `longitudinal:` prefix — this is a brand-new salt namespace, cannot collide with existing aging-pass salts |
| `state_history` growth cost at p=100k × 5y = 500k YearSnapshot instances | YearSnapshot is a small flat dataclass (~5 dict fields, scalar values). At 500k instances in memory ~50 MB — within existing cohort memory envelope. CIF JSON per patient grows by ~5 KB × 5 years. Negligible. |
| Attribute dependency cycle gets introduced accidentally | Loader builds the DAG at import time; cycle raises `ValueError` with the cycle path listed. Test `test_loader_dependency_sort.py` covers. |
| `state_at(encounter)` called for a BABY born mid-sim before any `advance_one_year` has run for them | `initial_snapshot(person, year, rng)` is called at birth from the perinatal path, so even the delivery-day encounter has a snapshot available. Phase 1 wires this in. |
| Pattern math bugs produce clinically implausible trajectories (e.g. HbA1c drifting below 2 %) | Each pattern clamps per yaml spec; audit script in each phase visualises the trajectory distribution and spot-checks outliers. |
| Phase 2 migration retires `stage_transition.yaml` but a downstream caller still reads it | Phase 2 PR runs `grep -r stage_transition` across the repo and migrates every call site before deletion. CI already runs vulture + ruff, which catch orphan references. |

## 11. Open questions

The user has answered all design questions during brainstorming — captured here for the record:

- **Config split**: per-attribute yaml (clinical-domain-expert readable).
- **Engine shape**: single module, 3 patterns (AR(1) / Markov / event).
- **Storage model**: flat per-year `state_history: list[YearSnapshot]` on PersonRecord.
- **Scope strategy**: incremental migration, framework-first PR (α).
- **Byte-identity across the migration**: not required. Clinical quality / realism improvements take precedence.
- **Glycemic_control vs direct HbA1c**: retire `glycemic_control`, make HbA1c the clinical primitive. Phase 1 widens to migrate `physiology/engine.py` + `patient/activator.py` + health_checkup HbA1c reads. Chosen for the single-source-of-truth quality win.
- **AR(1) parameter sourcing**: literature-calibrated against published DM longitudinal cohorts (DCCT/EDIC, ADVANCE), methodology + citations in yaml `source:` field. Not hand-tuned.

No open questions remain for the user as of the design-approval gate.

### Builder-check calls settled by the design author

The builder-check surfaced seven questions. Two (glycemic_control retirement; parameter sourcing) are listed above as user-decided. The other five were settled by the design author and are listed here so the user can override on review:

1. **RNG stream**: pass the aging driver's Generator directly to the engine; no internal sub-seed namespace. All patients byte-shift, which is accepted (§2.3 non-goal).
2. **`state_at` scope**: Phase 1 serves age ≥ 18 only; sim_start-prior encounters and baby delivery-day paths are Phase 2 wiring (BABY `state_history` is empty under Phase 1's `requires_age_band: [18, 120]`).
3. **Reference fixtures**: Phase 1 PR regenerates every pinned-value fixture file (CIF JSON samples, FHIR golden files) that includes an HbA1c value or `glycemic_control` field. `scripts/reproduce.sh` is re-run clean before merge.
4. **Idempotency on `advance_one_year`**: raise on duplicate (person, year); aging driver carries the single-call invariant upstream.
5. **AR(1) initial anchor shape**: lognormal distribution per Q1 answer (not stage-string parsing). Lognormal shape chosen for empirical fit to DCCT entry-cohort HbA1c distribution.

## 12. Follow-up issues (post-Phase 3)

Not scheduled in this spec but surfaced during audit; each is a separate yaml:

- LDL AR(1) trajectory under statin therapy (closes the per-encounter-emit side of #1697's LDL subcase).
- Systolic BP AR(1) under HTN therapy (closes the per-encounter-emit side of #1697's HTN subcase).
- F32 PHQ-9 / F41.1 GAD-7 trajectory (currently frozen to activation value; mental-health patients at severity_moderate_or_above drift over time).
- Age-driven dementia CDR 0.5 → 3 trajectory (currently covered under Phase 2 Markov; may need separate CDR-specific calibration against ADNI longitudinal data).
- Oncology TNM staging (C-codes) — not covered by any of the three patterns directly; may need a 4th pattern (survival-curve-driven stage progression).

## Approval

Awaiting user review. On approval, invoke `superpowers:writing-plans` to produce the Phase-1 implementation plan.
