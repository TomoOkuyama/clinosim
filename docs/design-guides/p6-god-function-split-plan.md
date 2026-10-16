# P6 god-function split plan — proposed phase boundaries for `_simulate_patient`, `run_beta`, and `narrative/`

> **Status (2026-10-16 close)**: this design was executed in-session. The LOC counts in the table below reflect the **pre-split baseline**; the extractions actually shipped are listed per section. The one remaining dedicated-session item is the `TemplateNarrativeGenerator` god class decomposition (161 methods, now ~6540 LOC in `template_generator.py` after the pre-class helpers were lifted into `_localization.py` / `_template_helpers.py` / `_narrative_utils.py` siblings).

Context: META #1633 code review (2026-10-15) flagged five god functions / files in the simulator + narrative sub-tree. Three were handled in-session (`activate_patient` → `_derive_chronic_conditions` extraction, `fhir_r4/__init__.py` → `builder.py` + facade split). The remaining four are substantial refactors that need design review before mechanical extraction can proceed safely:

| Target | LOC | Risk class |
|---|---|---|
| `clinosim/simulator/inpatient.py:_simulate_patient` | 707 | **RNG hot path** — any extraction that changes consumption order breaks fingerprint byte-identity |
| `clinosim/simulator/engine.py:run_beta` | 1147 | **RNG hot path + multi-stage loop** — month-tick / dispatch / writeback phases interact via shared state |
| `clinosim/modules/document/narrative/template_generator.py` | 7551 | **Not RNG-sensitive but structurally huge** — needs per-disease / per-document-type split design |
| `clinosim/modules/document/narrative/replacement_strategy.py` | 2221 | Same package; splits alongside `template_generator.py` |

This document records the proposed split for each, so a follow-up PR can execute the extraction with a reviewed design in hand rather than deciding boundaries on the fly.

## `_simulate_patient` (707 LOC) — admit / tick / discharge phases

### Phase boundaries proposed

```
_simulate_patient(patient, event, disease_id, protocol, …) -> CIFPatientRecord
  │
  ├─ _simulate_patient_prepare(...)        # ~70 LOC
  │    Severity + archetype + state init + readmission carryover +
  │    scenario-implied-GC override + mixed-condition state superimpose.
  │    No RNG consumption beyond severity.sample_severity + rng.random
  │    for the archetype draw.
  │
  ├─ _simulate_patient_admit(...)          # ~145 LOC
  │    Encounter creation (admit time pattern) → chief-complaint
  │    stash → severity/archetype write-back → department resolution →
  │    ward assignment → bed number → LOS resolution + archetype-min
  │    adjustment → admission orders → imaging orders → home-med
  │    orders → drug-safety gate.
  │
  ├─ _simulate_patient_tick(...)           # ~370 LOC (hot path)
  │    Daily simulation loop: surgery → bedside/routine procedures →
  │    per-day vital evolution + lab orders + imaging follow-ups →
  │    per-day medication administrations + drug-safety re-check →
  │    HAI / event hooks → tracking updates.
  │
  └─ _simulate_patient_discharge(...)      # ~120 LOC
       Discharge disposition → discharge prescription → discharge
       narrative stash → readmission flag → encounter close-out →
       CIFPatientRecord assembly.
```

### State threaded between phases

Each phase gets a `_SimulatorContext` dataclass carrying the mutable state:

```python
@dataclass
class _SimulatorContext:
    patient: PatientProfile
    event: LifeEvent
    disease_id: str
    protocol: DiseaseProtocol
    severity: str
    archetype: str
    state: PhysiologicalState
    encounter: Encounter
    orders: list[Order]
    procedures: list[Procedure]
    rng: np.random.Generator
    los: int
    admission_time: datetime
    department: str
    # … + ~15 more fields threaded through
```

The dataclass has a per-field inventory of "producer → consumer" phase pairs so the next refactor PR can review the state flow before extraction.

### RNG consumption invariant

The current function consumes rng in this exact order:

1. `rng.random()` for archetype selection (when not forced)
2. `rng.random()` × 2-3 for admission-time jitter
3. `rng.random()` for LOS sampler (via `target_los_config.sample_los`)
4. `rng.random()` × N for admission-orders drug_safety gate
5. Daily loop: `rng.random()` × ~6-10 per sim day for vitals / orders / meds / HAI hooks
6. `rng.random()` × ~2-3 for discharge disposition

Byte-identity invariant: the admit/tick/discharge split MUST preserve this ordering. Each phase takes `rng` by reference, each phase has a known per-call RNG budget. Fingerprint-verify after each phase extraction.

### Verification gate

- Fingerprint TOTAL on US s42 + JP s17 p=500 must be byte-identical to the pre-split baseline.
- 237 `tests/unit/simulator/` tests + 94 `tests/integration/` tests must all pass.
- No new mypy / ruff errors.

### Scope-discipline note

The 707 LOC → 4 helpers split is purely about readability, not about changing clinical behavior. If any phase extraction would require re-ordering RNG consumption to be clean, the PR must stop and the function stays at 707 LOC until the ordering is a separate behavior-change PR with its own byte-identity waiver.

---

## `run_beta` (1147 LOC) — month-tick / dispatch / writeback phases

### Phase boundaries proposed

```
run_beta(…) -> list[CIFPatientRecord]
  │
  ├─ _run_beta_prepare(...)          # ~40 LOC (one-time, pre-loop)
  │    Population loading / enricher wiring / seeding / month range
  │    computation.
  │
  ├─ (per-month loop body)
  │  _run_beta_month_tick(...)       # ~400 LOC
  │     Monthly event generation → severity/archetype derivation →
  │     ambulatory / inpatient / unknown-condition dispatch → per-event
  │     writeback plumbing.
  │
  ├─ _run_beta_dispatch_window(...)  # ~250 LOC
  │     Multi-event ordering → concurrency gate → bulk builders.
  │
  └─ _run_beta_writeback(...)        # ~150 LOC
       Post-month population update → chronic prevalence delta →
       state_periods update → aggregated metrics emit.
```

### Why `run_beta` is harder than `_simulate_patient`

- The per-month loop state is non-trivial: `concurrent_patients`, `prev_admission_cache`, `patient_cache` (tuple-keyed per Issue #1581), `monthly_metrics`, `enricher_state`.
- Several enrichers mutate population state mid-loop, so phase extraction must preserve the exact "monthly order" (generate → filter → sort → dispatch → writeback) that the Issue #1596 refactor established.
- The hot path currently has lazy imports (anti-circular-import workaround) that must survive the extraction.

### Verification gate

Same as `_simulate_patient` plus:
- The engine-fingerprint infra (`scripts/engine-fingerprint.sh`) is designed exactly for this — run before + after each phase extraction and require byte-identity.
- Full `tests/e2e/` suite (6 files) + `tests/regression/` (3 files) must pass.

### Scope-discipline note

The `run_beta` refactor is on the simulator's critical path. If any phase extraction produces a fingerprint drift, the PR reverts and the function stays monolithic until the drift root cause is identified in a separate investigation.

---

## `template_generator.py` (7551 LOC) + `replacement_strategy.py` (2221 LOC) — per-disease split

### Problem

`template_generator.py` is **7 % of the entire repo in a single file**. A new contributor who wants to find the F32 depression narrative template has to grep for it across 7500 lines of mixed per-disease code + shared helpers.

### Proposed split

```
clinosim/modules/document/narrative/
├── __init__.py                       # thin facade (public API)
├── template_core.py                  # ~400 LOC shared helpers +
│                                     #   dispatch table
├── replacement_strategy.py           # keep but shrink to shared
│                                     #   logic only (~800 LOC)
├── templates/                        # per-disease / per-document split
│   ├── __init__.py
│   ├── mental_health.py              # F32 / F33 / F41.1 (~300 LOC)
│   ├── metabolic.py                  # E11 / E66 / E78 / E88.81 (~400 LOC)
│   ├── cardiovascular.py             # I10 / I25 / I48 / I50 / I69 (~700 LOC)
│   ├── respiratory.py                # J44 / J45 / J18 (~400 LOC)
│   ├── renal.py                      # N18 (~250 LOC)
│   ├── stroke.py                     # I63 / I69.* sequela (~450 LOC)
│   ├── sepsis.py                     # A41.9 + septic shock arc (~500 LOC)
│   ├── obstetric.py                  # pregnancy / delivery (~300 LOC)
│   ├── pediatric.py                  # newborn / well-child (~300 LOC)
│   └── oncology.py                   # neoplasm narrative (~800 LOC)
│
├── strategies/                       # per-document-type strategies
│   ├── admission_note.py
│   ├── discharge_summary.py
│   ├── progress_note.py
│   ├── imaging_report.py
│   └── pathology_report.py
```

### Alternative: per-document-type instead of per-disease

An equally valid split is by document type (admission note, discharge summary, imaging report, etc.) rather than by disease. The tradeoff:

| Split dimension | Pro | Con |
|---|---|---|
| Per-disease | A new disease = 1 new file; disease-specific logic co-located | Document-shaping helpers scatter across disease files |
| Per-document-type | A new document type = 1 new file; shared helpers co-located | Adding a new disease touches ≥ 5 document files |

Decision deferred to the follow-up PR; both splits are mechanical once agreed upon.

### Why this needs human review before execution

- 7551 LOC is not a mechanical mv — the split dimension (per-disease vs per-document) is a maintainability decision that affects every future narrative PR.
- The current file has implicit shared state (helper functions declared inline, imported locally by sibling helpers) that must be hoisted to `template_core.py` or `_shared/`.
- Byte-identity verification is doable but each per-disease split must fingerprint-check: emission order inside a document must be preserved.

### Scope-discipline note

This split is a dedicated-session item. Do not combine with the `_simulate_patient` or `run_beta` splits.

---

## Execution order (recommended)

1. Review this design note.
2. Choose per-disease vs per-document for narrative (section 4).
3. Execute `_simulate_patient` split (smallest + clearest phases). Verify.
4. Execute `run_beta` split (needs byte-identity on the full simulator hot path). Verify.
5. Execute narrative split following step 2's decision. Fingerprint-verify per-disease.

Each step is its own PR + fingerprint-verify cycle. The META #1633 P6 checkbox is marked done when all four underlying refactors ship.
