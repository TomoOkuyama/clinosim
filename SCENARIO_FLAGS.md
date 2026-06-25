# Scenario & Medication Flags

clinosim's `physiology.derive_lab_values()` accepts boolean flags that
lift specific lab values at derive time. This document is the single
source of truth for **all current flags**, the **helper architecture**
that wires them, and the **5-step process** for adding new ones.

## What are these?

Disease YAMLs declare **scenario flags** (`causes_X`); patient context
provides **medication flags** (`on_X`). All flags follow the BNP-pattern
surgical principle (AD-57): **no `PhysiologicalState` mutation,
formula-only override**. This keeps state immutable and prevents the
master-RNG-cascade defect documented in spec
`docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md`.

## All current flags

| Flag | Type | Set in | Read in | Effect on lab values |
|---|---|---|---|---|
| `myocardial_injury` (alias: `causes_myocardial_injury` on disease YAML) | scenario | `acute_mi.yaml` | `physiology.engine.derive_lab_values` | Troponin_I → ACS-grade (~10-100 ng/mL); CK_MB also elevates |
| `causes_vte` | scenario | `pulmonary_embolism.yaml`, `deep_vein_thrombosis.yaml`, `cerebral_infarction.yaml` (embolic) | `derive_lab_values` | D_dimer → VTE-positive (clamp 0.15-20 μg/mL FEU; PE/DVT/CI admit p50 ≥ 4) |
| `on_warfarin` | medication | `PatientProfile.current_medications` (chronic AF/post-VTE) **OR** in-hospital warfarin order ≥ 3 days old (loading-dose rule) | `derive_lab_values` | PT_INR → therapeutic 2.5 + half-gain comorbidity perturbation; PT also (PT = 12 × PT_INR) |
| `hai_inflammation_lift` | post-encounter | `extensions["hai"]` populated by `hai` POST_ENCOUNTER enricher (Phase 3a) — CDC severity proxy (CLABSI/VAP 0.35, CAUTI 0.20) × ramp factor (`min(1.0, days_since_onset / 2.0)`) | `derive_lab_values` (kwarg) **invoked from `modules/hai/lab_lift.apply_hai_lab_lift`** | `effective_infl = min(1.0, infl + lift)` routed only into CRP + WBC formulas; applied as a forward-delta on top of existing observation values so original noise + circadian is preserved |

## Helper architecture

Three sibling helpers in `clinosim/modules/physiology/engine.py`:

```python
def scenario_flags_from_protocol(protocol) -> dict[str, bool]:
    """Read all scenario flags from a disease YAML protocol.

    Currently returns {"myocardial_injury": bool, "causes_vte": bool}.
    Extend the dict for future scenario flags."""
    ...

def medication_flags_from_context(patient, medication_orders=None,
                                  admission_date=None, current_day=None) -> dict[str, bool]:
    """Read all medication flags from patient + encounter context.

    Currently returns {"on_warfarin": bool}.
    DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) intentionally NOT
    detected — INR is not clinically monitored for DOAC; modeling DOAC
    INR lift would be clinically misleading.
    Extend the dict for future medication couplings."""
    ...

def hai_flags_from_record(record, encounter_id, current_day) -> dict[str, float]:
    """Phase 3a primitive (not currently wired into the 4 daily-loop sites
    because `extensions["hai"]` is populated AFTER the daily loop completes).
    Returns {"hai_inflammation_lift": float in [0.0, 0.35]} based on the
    matching HAI event's ramp factor and CDC severity proxy. Kept as a
    reusable primitive for Phase 3b couplings (e.g. antibiotic decay,
    antibiotic_flags_from_record sibling).

    Phase 3a uses the sibling `modules.hai.lab_lift.apply_hai_lab_lift`
    to apply the forward-delta to existing obs values."""
    ...
```

**Call sites merge dicts** (Phase 2b 4-site pattern, unchanged by Phase 3a):

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, all_med_orders, admission_date, day),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, **flags)
```

**Phase 3a forward-delta path** (separate from the call-site merge):

```python
# In simulator/inpatient.py after the daily loop:
record = CIFPatientRecord(...)
run_stage(POST_ENCOUNTER, EnricherContext(config, master_seed, records=[record]))
apply_hai_lab_lift(record=record, encounter=encounter,
                   state_history=state_history, admission_time=admission_time)
```

**4 derive_lab_values call sites** (all using this pattern after Phase 2b):

| Site | File | Purpose | medication context |
|---|---|---|---|
| Pass-1 lab loop | `simulator/inpatient.py:563-571` | daily inpatient labs | full (orders + day) |
| unknown-condition site | `simulator/inpatient.py:~1701` | unknown-condition encounter labs | chronic-only |
| ED admit | `simulator/emergency.py:126-130` | ED visit labs | chronic-only |
| Outpatient followup | `simulator/outpatient.py:152-160` | chronic-disease followup labs | chronic-only |

## Adding a new flag (5-step)

1. **Identify type**:
   - Disease-driven (e.g. `causes_dehydration`) → **scenario flag** → extend `scenario_flags_from_protocol`
   - Medication-driven (e.g. `on_steroid`) → **medication flag** → extend `medication_flags_from_context`
2. **Set the flag at its source**:
   - Scenario: add `causes_X: true` to relevant disease YAMLs
   - Medication: add detection rule to the helper (string match on `current_medications` and/or `medication_orders`)
3. **Extend the helper's return dict** to include the new key
4. **Add `<flag_name>: bool = False` kwarg** to `derive_lab_values`
5. **Implement formula change** in `derive_lab_values` (BNP-pattern surgical: no state mutation, formula-only)

**NEVER** add `flag=value` directly at a call site — J5 prevention (see
[CLAUDE.md](CLAUDE.md) "AD-55 enricher patterns"). The helper is the
single edit point so adding a new flag automatically reaches all 4 sites
through the `**flags` splat.

## DOAC exclusion (Phase 2b clinical decision)

For PT_INR, DOAC drugs (apixaban / rivaroxaban / edoxaban / dabigatran)
are intentionally **NOT detected** by `medication_flags_from_context`.
Clinical practice does not monitor INR for DOAC; modeling DOAC INR lift
would be clinically misleading and contradict the project's "the true
goal is FHIR/JP Core compliance + clinical coherence" principle. See
PR #82 (Phase 2b) for the full rationale.

## 関連

- [DESIGN.md](DESIGN.md) AD-57 (BNP-pattern surgical) / AD-59 (per-order sub-rng) / AD-56 (enricher registry)
- [CLAUDE.md](CLAUDE.md) "AD-55 enricher patterns"
- [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) "PR 検証ガイド" + "sub-seed 導出ルール"
- [clinosim/modules/physiology/README.md](clinosim/modules/physiology/README.md) — helper API reference
- spec / plan: `docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md` (causes_vte) + `docs/superpowers/specs/2026-06-24-phase2b-on-anticoagulation-design.md` (on_warfarin)
