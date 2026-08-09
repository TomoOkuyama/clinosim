# `clinosim.modules.physiology` — 13-variable physiological state engine

## Purpose

Holds and mutates the **13-variable physiological state** at the core
of clinosim's clinical-coherence claim. Every lab value, vital sign,
and medication response derived elsewhere in the simulator ultimately
consults this state.

Where [`clinical_course`](../clinical_course/README.md) decides
"how the state should move on the next day" (a
`StateChangeDirective`), `physiology` decides "what the state means
for this patient's labs and vitals right now" and applies the
directive from clinical_course to update the state.

## Scope

- **In scope**: the `PhysiologicalState` dataclass and its 13
  scalar variables, per-disease coupling coefficients (how disease
  severity moves each state variable), threshold-based derivations
  (dehydration → BUN / hypernatremia; renal function → creatinine /
  eGFR; anaemia level → Hb), homeostasis / regression-to-mean
  behaviours, drug-effect application on state (BNP-pattern surgical
  per AD-57).
- **Out of scope**: temporal trajectory selection (in
  [`clinical_course`](../clinical_course/README.md)), the labs /
  vitals *values* derived from state (in
  [`observation`](../observation/README.md)), disease definitions
  (in [`disease`](../disease/README.md)).

## Public API

```python
from clinosim.modules.physiology import (
    PhysiologicalState,          # 13-variable dataclass
    initialise_state,            # (patient, disease, rng) -> PhysiologicalState
    apply_state_directive,       # (state, directive) -> PhysiologicalState (new)
    apply_drug_effect,           # (state, drug, dose, ...) -> PhysiologicalState (new)
)
```

`PhysiologicalState` is immutable; `apply_*` functions return a new
instance so byte-diff determinism is easy to verify.

## Dependencies

- `clinosim.types.clinical` — `PhysiologicalState`,
  `StateChangeDirective`.
- `clinosim.types.patient` — `PatientPhysiologicalProfile` (patient
  archetype attributes).

## Constants and configuration

Physiology carries the **highest clinical-density hotspot** of the
codebase, flagged in
[`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md):

- **Coupling coefficients** in `engine.py` (`0.9`, `0.4`, `0.15`,
  `0.3`, `0.5`, etc.) — Hotspot A, pending extraction to
  `_coupling_coefficients.py`.
- **Dehydration thresholds** in
  `dehydration_thresholds.py` — already a compliant `_thresholds`-style
  file (56 LOC) with clinical citations.
- **Renal thresholds** in `renal_thresholds.py` — already compliant
  (46 LOC).

## Directory contents

```
clinosim/modules/physiology/
  __init__.py                   public API
  engine.py                     state initialisation + directive application (Hotspot A)
  dehydration_thresholds.py     compliant _thresholds file (model shape)
  renal_thresholds.py           compliant _thresholds file
  drug_effects.py               drug → state effect application
  audit.py                      per-module audit spec
```

## Testing

```bash
pytest tests/unit -k physiology -q
pytest tests/integration -k physiology -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
