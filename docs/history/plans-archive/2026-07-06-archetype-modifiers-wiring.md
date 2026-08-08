# archetype_modifiers Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement task-by-task. Steps use checkbox syntax.

**Goal:** Wire the dead `archetype_modifiers` disease-YAML block into `select_archetype`, replacing the hardcoded profile modifiers with the authored per-disease adjustments.

**Architecture:** `clinical_course/engine.py` (owner of archetype selection) gains a condition evaluator (`_eval_archetype_condition`) and applier (`_apply_archetype_modifiers`), reusing `disease.severity._evaluate_condition` for overlapping named comorbidity conditions. `select_archetype` applies YAML modifiers instead of the hardcoded `immune_reactivity`/`treatment_sensitivity` blocks. `DiseaseProtocol` gains the field + fail-loud validation.

**Tech Stack:** Python 3.11, numpy Generator, Pydantic, pytest, ruff, mypy strict.

## Global Constraints

- Determinism (AD-16): no new rng draws in modifier application (pure compute before the single `rng.choice`).
- Reuse canonical helpers; DRY with `disease.severity._evaluate_condition`.
- Types in `clinosim/types/`; YAML-sourced dicts typed `dict[str, Any]` / `list[dict[str, Any]]`.
- fail-loud validation at load; no silent `dict.get` fall-through for archetype/condition vocabularies.
- Line length 100; ruff-format; mypy strict clean on edited files.
- New-feature-class change: golden regen (AD-66); profile goldens forced-archetype → verify byte-unchanged.
- `plateau` is a legitimate per-disease archetype name (NOT a typo) — no data edits.

---

### Task 1: archetype modifier condition evaluator

**Files:**
- Modify: `clinosim/modules/clinical_course/engine.py`
- Test: `tests/unit/modules/clinical_course/test_archetype_modifiers.py`

**Interfaces:**
- Consumes: `disease.severity._evaluate_condition`.
- Produces: `ARCHETYPE_EXPRESSION_VARS: frozenset[str]`, `ARCHETYPE_RESERVED_CONDITIONS: frozenset[str]`, `_eval_archetype_condition(condition, profile, patient) -> bool`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/modules/clinical_course/test_archetype_modifiers.py
from types import SimpleNamespace
import pytest
from clinosim.modules.clinical_course.engine import (
    _eval_archetype_condition, _apply_archetype_modifiers,
    ARCHETYPE_EXPRESSION_VARS, ARCHETYPE_RESERVED_CONDITIONS,
)
pytestmark = pytest.mark.unit


def _profile(immune=0.5, treat=1.0):
    return SimpleNamespace(immune_reactivity=immune, treatment_sensitivity=treat)


def _patient(age=60, chronic=None):
    return SimpleNamespace(age=age, chronic_conditions=chronic or [], current_medications=[],
                           bmi=22.0, smoking_status="never", alcohol_use="none")


@pytest.mark.parametrize("cond,prof,pat,expected", [
    ("age >= 80", _profile(), _patient(age=82), True),
    ("age >= 80", _profile(), _patient(age=70), False),
    ("immune_reactivity < 0.3", _profile(immune=0.2), _patient(), True),
    ("immune_reactivity < 0.3", _profile(immune=0.5), _patient(), False),
    ("treatment_sensitivity > 1.2", _profile(treat=1.5), _patient(), True),
    ("diabetes", _profile(), _patient(chronic=["E11"]), True),   # named -> severity reuse
    ("diabetes", _profile(), _patient(chronic=[]), False),
])
def test_eval_condition(cond, prof, pat, expected):
    assert _eval_archetype_condition(cond, prof, pat) is expected


def test_reserved_intrinsic_and_unknown_return_false():
    assert "tpa_received" in ARCHETYPE_RESERVED_CONDITIONS
    assert _eval_archetype_condition("tpa_received", _profile(), _patient()) is False
    assert _eval_archetype_condition("prior_dka_episodes >= 2", _profile(), _patient()) is False


def test_apply_modifiers_shifts_probs():
    probs = {"smooth_recovery": 0.55, "treatment_resistant": 0.08, "gradual_deterioration": 0.05}
    mods = [{"condition": "age >= 80", "effect": {"gradual_deterioration": 0.08, "smooth_recovery": -0.12}}]
    out = _apply_archetype_modifiers(dict(probs), mods, _profile(), _patient(age=85))
    assert out["gradual_deterioration"] == pytest.approx(0.05 + 0.08)
    assert out["smooth_recovery"] == pytest.approx(0.55 - 0.12)


def test_apply_modifiers_inactive_noop():
    probs = {"smooth_recovery": 0.55, "gradual_deterioration": 0.05}
    mods = [{"condition": "age >= 80", "effect": {"gradual_deterioration": 0.08}}]
    assert _apply_archetype_modifiers(dict(probs), mods, _profile(), _patient(age=50)) == probs
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`/`ImportError`)

Run: `python -m pytest tests/unit/modules/clinical_course/test_archetype_modifiers.py -q`

- [ ] **Step 3: Implement**

```python
# clinosim/modules/clinical_course/engine.py — add near the top after imports
import re
from clinosim.modules.disease.severity import _evaluate_condition as _severity_condition

ARCHETYPE_EXPRESSION_VARS: frozenset[str] = frozenset(
    {"age", "immune_reactivity", "treatment_sensitivity", "prior_dka_episodes"}
)

# Disease sub-type / scenario-specific conditions used only in archetype_modifiers,
# not derivable from patient/profile. KNOWN (validation won't raise) but skipped.
ARCHETYPE_RESERVED_CONDITIONS: frozenset[str] = frozenset({
    "dysphagia_known", "troponin_elevated_and_rv_dysfunction", "tpa_received",
    "injection_drug_use", "antiviral_within_48h", "prerenal_etiology",
    "active_infection", "hematoma_volume_above_30mL", "acalculous_cholecystitis",
    "prior_vte", "iliofemoral_location", "symptom_duration_over_72h",
    "symptom_duration_over_48h", "prior_stroke", "peptic_ulcer_history",
    "anterior_wall_MI", "prior_abdominal_surgery", "hernia_incarcerated",
    "dementia_advanced", "poor_functional_status", "prior_icu_admission",
    "prior_icu_for_asthma", "medication_noncompliance", "sepsis",
    "home_oxygen_use", "FEV1_below_30", "atrial_fibrillation", "urinary_catheter",
    "hepatocellular_carcinoma", "obesity_bmi_over_30", "obesity", "dementia",
    "heart_failure", "hyperthyroidism", "prior_MI",
})

_EXPR_RE = re.compile(r"^\s*(\w+)\s*(<=|>=|<|>|==)\s*(-?\d+(?:\.\d+)?)\s*$")
_OPS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
}


def _eval_archetype_condition(condition: str, profile, patient) -> bool:
    m = _EXPR_RE.match(condition or "")
    if m:
        var, op, num = m.group(1), m.group(2), float(m.group(3))
        if var == "age":
            val = float(getattr(patient, "age", 0))
        elif var in ("immune_reactivity", "treatment_sensitivity"):
            val = float(getattr(profile, var, 0.0))
        else:
            return False  # prior_dka_episodes etc. not modeled -> skip
        return bool(_OPS[op](val, num))
    # Named condition: reuse the severity comorbidity vocabulary; reserved-intrinsic
    # and unknown fall through to False.
    return _severity_condition(condition, patient)


def _apply_archetype_modifiers(probs: dict, modifiers: list, profile, patient) -> dict:
    for mod in modifiers or []:
        if not _eval_archetype_condition(mod.get("condition", ""), profile, patient):
            continue
        for arch, delta in (mod.get("effect") or {}).items():
            if arch in probs:
                probs[arch] = probs[arch] + float(delta)
    return probs
```
Add `from typing import Any` if not present. Move `import re` to the top import block.

- [ ] **Step 4: Run — expect PASS**

Run: `python -m pytest tests/unit/modules/clinical_course/test_archetype_modifiers.py -q`

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/clinical_course/engine.py tests/unit/modules/clinical_course/test_archetype_modifiers.py
git commit -m "feat(archetype FP-YAML-2b): archetype_modifiers condition evaluator + applier"
```

---

### Task 2: rewire select_archetype to use YAML modifiers

**Files:**
- Modify: `clinosim/modules/clinical_course/engine.py` (`select_archetype`)
- Modify: `clinosim/modules/disease/protocol.py` (`archetype_modifiers` field)
- Modify: `clinosim/simulator/inpatient.py:126` (call site)
- Test: `tests/unit/modules/clinical_course/test_select_archetype_modifiers.py`

**Interfaces:**
- Produces: `select_archetype(severity, profile, rng, protocol_archetypes=None, protocol_modifiers=None, patient=None) -> str`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/modules/clinical_course/test_select_archetype_modifiers.py
from types import SimpleNamespace
import numpy as np
import pytest
from clinosim.modules.clinical_course.engine import select_archetype
pytestmark = pytest.mark.unit


def _profile(immune=0.5, treat=1.0):
    return SimpleNamespace(immune_reactivity=immune, treatment_sensitivity=treat)


def _patient(age):
    return SimpleNamespace(age=age, chronic_conditions=[], current_medications=[],
                           bmi=22.0, smoking_status="never", alcohol_use="none")


ARCHS = {
    "smooth_recovery": {"probability": 0.6},
    "gradual_deterioration": {"probability": 0.2},
    "treatment_resistant": {"probability": 0.2},
}
MODS = [{"condition": "age >= 80",
         "effect": {"gradual_deterioration": 0.30, "smooth_recovery": -0.30}}]


def test_yaml_modifier_raises_deterioration_for_elderly():
    def rate(age):
        rng = np.random.default_rng(11)
        picks = [select_archetype("moderate", _profile(), rng, protocol_archetypes=ARCHS,
                                  protocol_modifiers=MODS, patient=_patient(age)) for _ in range(400)]
        return picks.count("gradual_deterioration") / len(picks)
    assert rate(85) > rate(50)


def test_deterministic():
    rng1 = np.random.default_rng(5); rng2 = np.random.default_rng(5)
    a = select_archetype("moderate", _profile(), rng1, protocol_archetypes=ARCHS,
                         protocol_modifiers=MODS, patient=_patient(85))
    b = select_archetype("moderate", _profile(), rng2, protocol_archetypes=ARCHS,
                         protocol_modifiers=MODS, patient=_patient(85))
    assert a == b
```

- [ ] **Step 2: Run — expect FAIL** (unexpected `protocol_modifiers` kwarg)

- [ ] **Step 3: Implement**

In `select_archetype`, add params `protocol_modifiers: list | None = None, patient=None`, and replace the "Patient profile modifiers" block (the two `if profile.immune_reactivity`/`if profile.treatment_sensitivity` clauses) with:
```python
    # Patient risk-factor modifiers from the disease YAML (FP-YAML-2b), replacing the
    # former hardcoded immune_reactivity/treatment_sensitivity heuristics.
    if protocol_modifiers:
        probs = _apply_archetype_modifiers(probs, protocol_modifiers, profile, patient)
```
Add `archetype_modifiers: list[dict[str, Any]] = []` to `DiseaseProtocol`. At `inpatient.py:126` add `protocol_modifiers=protocol.archetype_modifiers or None, patient=patient`.

- [ ] **Step 4: Run — expect PASS**

Run: `python -m pytest tests/unit/modules/clinical_course/test_select_archetype_modifiers.py -q`

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/clinical_course/engine.py clinosim/modules/disease/protocol.py clinosim/simulator/inpatient.py tests/unit/modules/clinical_course/test_select_archetype_modifiers.py
git commit -m "feat(archetype FP-YAML-2b): select_archetype applies YAML modifiers; DiseaseProtocol field + call site"
```

---

### Task 3: fail-loud archetype_modifiers validation at load

**Files:**
- Modify: `clinosim/modules/clinical_course/engine.py` (`_validate_archetype_modifiers`)
- Modify: `clinosim/modules/disease/protocol.py` (call it)
- Test: `tests/unit/modules/clinical_course/test_archetype_modifiers_validation.py`

**Interfaces:**
- Produces: `_validate_archetype_modifiers(disease_id, modifiers, archetype_names) -> None`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/modules/clinical_course/test_archetype_modifiers_validation.py
import glob, os
import pytest
from clinosim.modules.clinical_course.engine import _validate_archetype_modifiers
from clinosim.modules.disease.protocol import load_disease_protocol
pytestmark = pytest.mark.unit

_IDS = [os.path.basename(f)[:-5]
        for f in glob.glob("clinosim/modules/disease/reference_data/*.yaml")]
_ARCH = {"smooth_recovery", "gradual_deterioration", "treatment_resistant"}


def test_all_real_yamls_validate():
    for d in _IDS:
        load_disease_protocol(d)  # must not raise


def test_effect_key_not_in_archetypes_raises():
    with pytest.raises(ValueError):
        _validate_archetype_modifiers("x", [{"condition": "age >= 80",
            "effect": {"nonexistent_archetype": 0.1}}], _ARCH)


def test_unknown_condition_raises():
    with pytest.raises(ValueError):
        _validate_archetype_modifiers("x", [{"condition": "made_up_thing",
            "effect": {"smooth_recovery": 0.1}}], _ARCH)


def test_nonnumeric_delta_raises():
    with pytest.raises(ValueError):
        _validate_archetype_modifiers("x", [{"condition": "age >= 80",
            "effect": {"smooth_recovery": "lots"}}], _ARCH)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# clinosim/modules/clinical_course/engine.py
def _validate_archetype_modifiers(disease_id: str, modifiers: list, archetype_names) -> None:
    known_named = ARCHETYPE_RESERVED_CONDITIONS  # severity vocabulary checked via parse below
    from clinosim.modules.disease.severity import KNOWN_MODIFIER_CONDITIONS
    for mod in modifiers or []:
        cond = mod.get("condition", "")
        if not _EXPR_RE.match(cond) and cond not in known_named and cond not in KNOWN_MODIFIER_CONDITIONS:
            raise ValueError(f"{disease_id}: unknown archetype_modifier condition {cond!r}")
        for arch, delta in (mod.get("effect") or {}).items():
            if arch not in archetype_names:
                raise ValueError(
                    f"{disease_id}: archetype_modifier effect targets {arch!r} "
                    f"not in the disease's archetypes {sorted(archetype_names)}"
                )
            if not isinstance(delta, (int, float)):
                raise ValueError(f"{disease_id}: non-numeric archetype_modifier delta for {arch!r}")
```
In `load_disease_protocol` (after `_validate_severity_block`):
```python
    from clinosim.modules.clinical_course.engine import _validate_archetype_modifiers
    _arch_names = set((data.get("course_archetypes") or {}).keys()) or {
        "smooth_recovery", "dip_then_recovery", "plateau_then_recovery",
        "treatment_resistant", "gradual_deterioration", "sudden_deterioration"}
    _validate_archetype_modifiers(disease_id, data.get("archetype_modifiers", []), _arch_names)
```
Watch for an import cycle: `clinical_course.engine` imports `disease.severity` (fine); `disease.protocol` importing `clinical_course.engine` at call time (inside the function, like `_validate_severity_block`) avoids a top-level cycle.

- [ ] **Step 4: Run — expect PASS** (incl. all 23 real YAMLs validating)

- [ ] **Step 5: ruff/mypy + commit**

```bash
ruff format clinosim/modules/clinical_course/engine.py && ruff check clinosim/modules/clinical_course/engine.py && mypy clinosim/modules/clinical_course/engine.py
git add clinosim/modules/clinical_course/engine.py clinosim/modules/disease/protocol.py tests/unit/modules/clinical_course/test_archetype_modifiers_validation.py
git commit -m "feat(archetype FP-YAML-2b): fail-loud archetype_modifiers validation at load"
```

---

### Task 4: full suite, golden regen, docs

- [ ] **Step 1: unit + integration**

Run: `python -m pytest -m unit -q && python -m pytest -m integration -q`. Fix real regressions (not golden drift).

- [ ] **Step 2: e2e**

Run: `python -m pytest -m e2e -q`. Property tests should pass; update a bound only if it hard-coded the old archetype distribution and the new one is clinically sensible.

- [ ] **Step 3: regenerate + read goldens (AD-66)**

Run: `python -m clinosim.simulator.cli regenerate-goldens --all --provider template && python -m clinosim.simulator.cli regenerate-goldens --all --provider mock`. Profiles use forced-archetype → expect byte-unchanged; if any change, investigate (forced path should bypass select_archetype). `git diff --stat`; run `python -m pytest -m regression -q`.

- [ ] **Step 4: audit**

Run: `python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US -o /tmp/us && python -m clinosim.simulator.cli audit run -d /tmp/us` (+ JP). Expect 0 FAIL.

- [ ] **Step 5: docs + commit**

DESIGN.md AD note (archetype_modifiers wiring, sibling to AD-67); registry FP-YAML-2 archetype portion → DONE; README dependency note (`clinical_course` → `disease.severity`). Commit code + goldens together.

---

## Self-Review

- Coverage: evaluator (T1) / rewire + field + call site (T2) / validation (T3) / suite+golden+docs (T4). Reserved-intrinsic deferral documented. `plateau` non-issue documented (self-consistency validation).
- Types: `_eval_archetype_condition(cond, profile, patient)->bool`, `_apply_archetype_modifiers(dict,list,profile,patient)->dict`, `select_archetype(..., protocol_modifiers, patient)->str`, `_validate_archetype_modifiers(id, list, set)->None` consistent.
- Determinism: no new rng draws; probs change → golden regen. Import cycle avoided via in-function imports in protocol.py.
</content>
