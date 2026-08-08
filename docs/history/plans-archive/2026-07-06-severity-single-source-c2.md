# Severity Single Source of Truth (hybrid c2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make disease-YAML `severity.distribution` × `modifiers` the single canonical severity source (retiring locale `severity_beta`/`severity_minimum`), with one owner for the category↔score boundary and the minimum.

**Architecture:** A new `clinosim/modules/disease/severity.py` owns severity sampling and the category↔score boundary. `population/engine.py` calls `sample_severity(protocol, person, rng)` at population time (supplying both the category and the continuous score the hospitalization gate needs); `inpatient.py` re-derives the category via `category_from_score`; `emergency.py` shares the categorical-sampling primitive. Locale demographics become incidence-only.

**Tech Stack:** Python 3.11, numpy Generator RNG, Pydantic (DiseaseProtocol), pytest (unit/integration/e2e/regression markers), ruff, mypy strict.

## Global Constraints

- Determinism (AD-16): all randomness via the passed `numpy.random.Generator`; no `random.random()`, no `datetime.now()` in generation paths.
- Canonical helpers only: `normalize_probabilities(p, fallback="raise")` for every YAML-sourced `rng.choice(p=)`; `is_jp`/`is_us`/`resolve_lang`; `load_disease_protocol` for disease YAML.
- Types live in `clinosim/types/`; module code holds no new dataclass/BaseModel. Severity sampling returns plain `tuple[str, float]` / `str` (no new type).
- fail-loud validation at load time (`_validate_*`); no silent `dict.get` fall-through for external vocabularies.
- `@lru_cache` loader returns are shared read-only — never mutate.
- Line length 100; ruff-format new files; mypy strict must pass for new/edited files.
- This is a new-feature-class change: byte-diff intentionally broken for the inpatient path; regenerate goldens (AD-66 Rule 1) and clinically read the diff (Rule 2). Commit YAML + goldens together.
- Boundary consistency is load-bearing: `category_from_score` and `SEVERITY_SCORE_RANGES` must agree exactly (`>= 0.7` severe, `>= 0.3` moderate, else mild; ranges mild `[0,0.3)`, moderate `[0.3,0.7)`, severe `[0.7,1.0]`).

---

### Task 1: severity module — boundary + score ranges

**Files:**
- Create: `clinosim/modules/disease/severity.py`
- Test: `tests/unit/modules/disease/test_severity_boundary.py`

**Interfaces:**
- Produces: `SEVERITY_CATEGORIES: tuple[str,str,str]`, `SEVERITY_SCORE_RANGES: dict[str, tuple[float,float]]`, `category_from_score(score: float) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/modules/disease/test_severity_boundary.py
import pytest
from clinosim.modules.disease.severity import (
    SEVERITY_CATEGORIES, SEVERITY_SCORE_RANGES, category_from_score,
)
pytestmark = pytest.mark.unit


def test_categories_and_ranges_consistent():
    assert SEVERITY_CATEGORIES == ("mild", "moderate", "severe")
    assert SEVERITY_SCORE_RANGES["mild"] == (0.0, 0.3)
    assert SEVERITY_SCORE_RANGES["moderate"] == (0.3, 0.7)
    assert SEVERITY_SCORE_RANGES["severe"] == (0.7, 1.0)


@pytest.mark.parametrize("score,cat", [
    (0.0, "mild"), (0.29, "mild"), (0.3, "moderate"), (0.5, "moderate"),
    (0.69, "moderate"), (0.7, "severe"), (0.99, "severe"), (1.0, "severe"),
])
def test_category_from_score_boundaries(score, cat):
    assert category_from_score(score) == cat


def test_every_range_maps_back_to_its_category():
    # The lower bound of each range must classify as that category.
    for cat, (lo, _hi) in SEVERITY_SCORE_RANGES.items():
        assert category_from_score(lo) == cat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/modules/disease/test_severity_boundary.py -q`
Expected: FAIL (module `clinosim.modules.disease.severity` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# clinosim/modules/disease/severity.py
"""Severity sampling + the canonical category<->score boundary (FP-SEV-MODEL, c2).

The disease module owns the severity distribution (disease-YAML `severity.distribution`
+ `modifiers`), so it owns severity sampling. This module is the SINGLE definition of
the mild/moderate/severe category boundary and the continuous score each category maps
to (used by the population-time hospitalization gate).
"""
from __future__ import annotations

SEVERITY_CATEGORIES: tuple[str, str, str] = ("mild", "moderate", "severe")

# Half-open ranges (upper-inclusive on severe). category_from_score is exactly
# consistent with these so a uniform draw inside a range re-derives its category.
SEVERITY_SCORE_RANGES: dict[str, tuple[float, float]] = {
    "mild": (0.0, 0.3),
    "moderate": (0.3, 0.7),
    "severe": (0.7, 1.0),
}


def category_from_score(score: float) -> str:
    """Map a continuous severity score in [0,1] to its category."""
    if score >= 0.7:
        return "severe"
    if score >= 0.3:
        return "moderate"
    return "mild"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/modules/disease/test_severity_boundary.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/disease/severity.py tests/unit/modules/disease/test_severity_boundary.py
git commit -m "feat(severity FP-SEV-MODEL): canonical category<->score boundary"
```

---

### Task 2: modifier-condition vocabulary + evaluation

**Files:**
- Modify: `clinosim/modules/disease/severity.py`
- Test: `tests/unit/modules/disease/test_severity_modifiers.py`

**Interfaces:**
- Consumes: `PersonRecord` (from `clinosim.types.population`): fields `age`, `sex`, `chronic_conditions: list[str]`, `current_medications: list[str]`, `bmi`, `smoking_status`, `alcohol_use`.
- Produces: `EVALUABLE_CONDITIONS: frozenset[str]`, `RESERVED_INTRINSIC_CONDITIONS: frozenset[str]`, `KNOWN_MODIFIER_CONDITIONS: frozenset[str]` (= union), `_evaluate_condition(condition: str, person) -> bool`, `_apply_modifiers(dist: dict[str,float], modifiers: list[dict], person) -> dict[str,float]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/modules/disease/test_severity_modifiers.py
import pytest
from types import SimpleNamespace
from clinosim.modules.disease.severity import (
    _evaluate_condition, _apply_modifiers,
    KNOWN_MODIFIER_CONDITIONS, EVALUABLE_CONDITIONS, RESERVED_INTRINSIC_CONDITIONS,
)
pytestmark = pytest.mark.unit


def _person(**kw):
    base = dict(age=60, sex="M", chronic_conditions=[], current_medications=[],
                bmi=22.0, smoking_status="never", alcohol_use="none")
    base.update(kw)
    return SimpleNamespace(**base)


def test_vocabulary_partition():
    # evaluable and reserved are disjoint; union is the known set.
    assert EVALUABLE_CONDITIONS.isdisjoint(RESERVED_INTRINSIC_CONDITIONS)
    assert KNOWN_MODIFIER_CONDITIONS == EVALUABLE_CONDITIONS | RESERVED_INTRINSIC_CONDITIONS


@pytest.mark.parametrize("cond,person_kw,expected", [
    ("age_over_75", dict(age=80), True),
    ("age_over_75", dict(age=70), False),
    ("age_over_65", dict(age=66), True),
    ("diabetes", dict(chronic_conditions=["E11"]), True),
    ("diabetes", dict(chronic_conditions=[]), False),
    ("heart_failure", dict(chronic_conditions=["I50"]), True),
    ("CKD", dict(chronic_conditions=["N18"]), True),
    ("COPD", dict(chronic_conditions=["J44"]), True),
    ("obesity", dict(bmi=32.0), True),
    ("smoking_current", dict(smoking_status="current"), True),
])
def test_evaluable_conditions(cond, person_kw, expected):
    assert _evaluate_condition(cond, _person(**person_kw)) is expected


def test_reserved_intrinsic_never_fires():
    # An intrinsic condition is KNOWN but always evaluates False (skipped this chain).
    assert "anterior_wall_MI" in RESERVED_INTRINSIC_CONDITIONS
    assert _evaluate_condition("anterior_wall_MI", _person()) is False


def test_apply_modifiers_shifts_named_category():
    dist = {"mild": 0.0, "moderate": 0.65, "severe": 0.35}
    mods = [{"condition": "age_over_75", "moderate_multiplier": 0.8, "severe_multiplier": 1.5}]
    out = _apply_modifiers(dist, mods, _person(age=80))
    assert out["severe"] == pytest.approx(0.35 * 1.5)
    assert out["moderate"] == pytest.approx(0.65 * 0.8)
    assert out["mild"] == 0.0


def test_apply_modifiers_inactive_condition_is_noop():
    dist = {"mild": 0.1, "moderate": 0.6, "severe": 0.3}
    mods = [{"condition": "age_over_75", "severe_multiplier": 2.0}]
    out = _apply_modifiers(dist, mods, _person(age=50))
    assert out == dist
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/modules/disease/test_severity_modifiers.py -q`
Expected: FAIL (names not defined).

- [ ] **Step 3: Write minimal implementation**

First enumerate the real vocabulary (implementation step 0):
Run `python3 -c "import glob,yaml,collections; c=collections.Counter(); [c.update(m['condition'] for m in (yaml.safe_load(open(f)).get('severity') or {}).get('modifiers',[]) or [] if isinstance(m,dict)) for f in glob.glob('clinosim/modules/disease/reference_data/*.yaml')]; print(sorted(c))"`
and place every returned condition into exactly one of the two sets below (evaluable if it maps to a PersonRecord field, reserved-intrinsic otherwise). The lists below are the session-38 enumeration; reconcile against the command output and move any newly-added condition into the correct set.

```python
# append to clinosim/modules/disease/severity.py
from clinosim.types.population import PersonRecord  # noqa: F401  (type reference)

# ICD-code prefixes used by evaluable comorbidity conditions.
_COND_ICD_PREFIXES: dict[str, tuple[str, ...]] = {
    "diabetes": ("E11", "E10"),
    "heart_failure": ("I50",),
    "CKD": ("N18",),
    "N18": ("N18",),
    "COPD": ("J44",),
    "liver_cirrhosis": ("K74",),
    "hypertension_uncontrolled": ("I10",),
    "atrial_fibrillation": ("I48",),
    "I48": ("I48",),
    "prior_MI": ("I25", "I21"),
    "prior_stroke_or_TIA": ("I63", "I64", "G45"),
    "peripheral_vascular_disease": ("I73",),
    "valvular_heart_disease": ("I34", "I35", "I05", "I06"),
    "hyperthyroidism": ("E05",),
    "dementia": ("F00", "F01", "F03", "G30"),
    "dementia_advanced": ("F00", "F01", "F03", "G30"),
    "osteoporosis": ("M80", "M81"),
    "active_cancer": ("C",),
    "malignancy": ("C",),
    "metastatic_cancer": ("C77", "C78", "C79", "C80"),
    "colorectal_cancer": ("C18", "C19", "C20"),
    "hepatocellular_carcinoma": ("C22",),
    "alcohol_dependence": ("F10",),
    "alcohol_dependence_active": ("F10",),
}

_AGE_OVER: dict[str, int] = {
    "age_over_65": 65, "age_over_75": 75, "age_over_80": 80, "age_over_85": 85,
}

# Conditions that map to a real PersonRecord attribute and are evaluated this chain.
EVALUABLE_CONDITIONS: frozenset[str] = frozenset(
    set(_COND_ICD_PREFIXES)
    | set(_AGE_OVER)
    | {"age_under_5", "obesity", "obesity_bmi_over_30", "smoking_current",
       "multiple_comorbidities"}
)

# Disease sub-type / scenario-specific conditions not derivable from PersonRecord.
# KNOWN (validation does not raise) but always evaluate False this chain. Reserved
# for the deferred scenario-flag mechanism (see plan Task notes / TODO).
RESERVED_INTRINSIC_CONDITIONS: frozenset[str] = frozenset({
    "anterior_wall_MI", "saddle_embolus", "iliofemoral_location", "bilateral_dvt",
    "phlegmasia_signs", "intraventricular_hemorrhage", "acalculous", "gcs_below_8",
    "APACHE_II_above_8", "FEV1_below_30", "hypercapnia_baseline",
    "first_presentation_T1DM", "delayed_presentation", "coagulopathy",
    "multiple_levels", "neurological_deficit", "hernia_incarcerated", "WPW_syndrome",
    "sepsis", "prior_abdominal_surgery", "urinary_obstruction", "urinary_catheter",
    "symptom_duration_over_48h", "symptom_duration_over_72h", "immunosuppressed",
    "anticoagulant_use", "chronic_steroid_use", "home_oxygen_use", "pregnancy",
    "medication_noncompliance", "poor_functional_status", "prior_icu_admission",
    "prior_icu_for_asthma", "active_cancer_treatment",
})

KNOWN_MODIFIER_CONDITIONS: frozenset[str] = (
    EVALUABLE_CONDITIONS | RESERVED_INTRINSIC_CONDITIONS
)


def _has_icd(person, prefixes: tuple[str, ...]) -> bool:
    codes = getattr(person, "chronic_conditions", []) or []
    return any(str(c).startswith(prefixes) for c in codes)


def _evaluate_condition(condition: str, person) -> bool:
    if condition in _AGE_OVER:
        return int(getattr(person, "age", 0)) >= _AGE_OVER[condition]
    if condition == "age_under_5":
        return int(getattr(person, "age", 999)) < 5
    if condition in ("obesity", "obesity_bmi_over_30"):
        return float(getattr(person, "bmi", 0.0)) >= 30.0
    if condition == "smoking_current":
        return getattr(person, "smoking_status", "never") == "current"
    if condition == "multiple_comorbidities":
        return len(getattr(person, "chronic_conditions", []) or []) >= 3
    if condition in _COND_ICD_PREFIXES:
        return _has_icd(person, _COND_ICD_PREFIXES[condition])
    return False  # reserved-intrinsic or unknown -> not fired here


def _apply_modifiers(dist: dict[str, float], modifiers: list[dict], person) -> dict[str, float]:
    out = dict(dist)
    for mod in modifiers or []:
        cond = mod.get("condition", "")
        if not _evaluate_condition(cond, person):
            continue
        for cat in SEVERITY_CATEGORIES:
            mult = mod.get(f"{cat}_multiplier")
            if mult is not None:
                out[cat] = out.get(cat, 0.0) * float(mult)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/modules/disease/test_severity_modifiers.py -q`
Expected: PASS. (If a real YAML condition is missing from both sets, the Task 4 validator will later fail — that is intended; add it to the correct set here.)

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/disease/severity.py tests/unit/modules/disease/test_severity_modifiers.py
git commit -m "feat(severity FP-SEV-MODEL): modifier vocabulary + person evaluation"
```

---

### Task 3: sample_severity + sample_severity_category

**Files:**
- Modify: `clinosim/modules/disease/severity.py`
- Test: `tests/unit/modules/disease/test_severity_sampling.py`

**Interfaces:**
- Consumes: `SEVERITY_CATEGORIES`, `SEVERITY_SCORE_RANGES`, `_apply_modifiers`, `normalize_probabilities`.
- Produces: `sample_severity_category(distribution: dict[str,float], modifiers: list[dict], person, rng, minimum: str | None) -> str`; `sample_severity(protocol, person, rng) -> tuple[str, float]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/modules/disease/test_severity_sampling.py
import pytest
import numpy as np
from types import SimpleNamespace
from clinosim.modules.disease.severity import (
    sample_severity_category, sample_severity, SEVERITY_SCORE_RANGES, category_from_score,
)
pytestmark = pytest.mark.unit


def _person(**kw):
    base = dict(age=60, sex="M", chronic_conditions=[], current_medications=[],
                bmi=22.0, smoking_status="never", alcohol_use="none")
    base.update(kw)
    return SimpleNamespace(**base)


def _protocol(distribution, modifiers=None, minimum=None):
    sev = {"distribution": distribution}
    if modifiers is not None:
        sev["modifiers"] = modifiers
    return SimpleNamespace(severity=sev, minimum_severity=minimum)


def test_category_follows_distribution():
    rng = np.random.default_rng(42)
    dist = {"mild": 0.0, "moderate": 1.0, "severe": 0.0}
    cats = [sample_severity_category(dist, [], _person(), rng, None) for _ in range(200)]
    assert set(cats) == {"moderate"}


def test_minimum_clamp_excludes_below():
    rng = np.random.default_rng(1)
    dist = {"mild": 0.9, "moderate": 0.1, "severe": 0.0}
    cats = [sample_severity_category(dist, [], _person(), rng, "moderate") for _ in range(200)]
    assert "mild" not in cats  # clamped up to the minimum


def test_modifier_raises_severe_rate():
    dist = {"mild": 0.2, "moderate": 0.6, "severe": 0.2}
    mods = [{"condition": "age_over_75", "severe_multiplier": 3.0}]
    rng = np.random.default_rng(7)
    old = _person(age=50); young = [sample_severity_category(dist, mods, old, rng, None) for _ in range(500)]
    rng = np.random.default_rng(7)
    elderly = [sample_severity_category(dist, mods, _person(age=80), rng, None) for _ in range(500)]
    assert elderly.count("severe") > young.count("severe")


def test_sample_severity_score_within_category_range():
    rng = np.random.default_rng(3)
    for _ in range(300):
        cat, score = sample_severity(_protocol({"mild": 0.34, "moderate": 0.33, "severe": 0.33}), _person(), rng)
        lo, hi = SEVERITY_SCORE_RANGES[cat]
        assert lo <= score < hi or (cat == "severe" and score <= hi)
        assert category_from_score(score) == cat  # round-trip consistency


def test_sample_severity_deterministic():
    p = _protocol({"mild": 0.34, "moderate": 0.33, "severe": 0.33})
    a = sample_severity(p, _person(), np.random.default_rng(99))
    b = sample_severity(p, _person(), np.random.default_rng(99))
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/modules/disease/test_severity_sampling.py -q`
Expected: FAIL (sampling functions not defined).

- [ ] **Step 3: Write minimal implementation**

```python
# append to clinosim/modules/disease/severity.py
import numpy as np  # noqa: E402  (grouped with existing imports at top in final form)
from clinosim.modules._shared import normalize_probabilities  # noqa: E402

_ORDER = SEVERITY_CATEGORIES  # ("mild","moderate","severe"), fixed rank


def _clamp_minimum(dist: dict[str, float], minimum: str | None) -> dict[str, float]:
    if not minimum:
        return dict(dist)
    min_idx = _ORDER.index(minimum)
    return {c: (dist.get(c, 0.0) if i >= min_idx else 0.0) for i, c in enumerate(_ORDER)}


def sample_severity_category(distribution, modifiers, person, rng, minimum) -> str:
    dist = _apply_modifiers(dict(distribution), modifiers or [], person)
    dist = _clamp_minimum(dist, minimum)
    weights = normalize_probabilities([max(0.0, dist.get(c, 0.0)) for c in _ORDER], fallback="raise")
    return str(rng.choice(_ORDER, p=weights))


def sample_severity(protocol, person, rng) -> tuple[str, float]:
    sev = getattr(protocol, "severity", {}) or {}
    distribution = sev.get("distribution", {})
    modifiers = sev.get("modifiers", [])
    minimum = getattr(protocol, "minimum_severity", None)
    category = sample_severity_category(distribution, modifiers, person, rng, minimum)
    lo, hi = SEVERITY_SCORE_RANGES[category]
    return category, float(rng.uniform(lo, hi))
```
Move the `import numpy as np` and `from clinosim.modules._shared import normalize_probabilities` to the top import block and drop the `# noqa` when finalizing (ruff will flag E402 otherwise).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/modules/disease/test_severity_sampling.py -q`
Expected: PASS.

- [ ] **Step 5: Ruff + mypy the new module**

Run: `ruff format clinosim/modules/disease/severity.py && ruff check clinosim/modules/disease/severity.py && mypy clinosim/modules/disease/severity.py`
Expected: no errors on `severity.py`.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/disease/severity.py tests/unit/modules/disease/test_severity_sampling.py
git commit -m "feat(severity FP-SEV-MODEL): sample_severity + shared category primitive"
```

---

### Task 4: fail-loud severity-block validation at protocol load

**Files:**
- Modify: `clinosim/modules/disease/severity.py` (add `_validate_severity_block`)
- Modify: `clinosim/modules/disease/protocol.py` (call it in `load_disease_protocol`)
- Test: `tests/unit/modules/disease/test_severity_validation.py`

**Interfaces:**
- Consumes: `KNOWN_MODIFIER_CONDITIONS`, `SEVERITY_CATEGORIES`.
- Produces: `_validate_severity_block(disease_id: str, severity: dict, minimum_severity: str | None) -> None` (raises `ValueError`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/modules/disease/test_severity_validation.py
import glob, os
import pytest
from clinosim.modules.disease.severity import _validate_severity_block
from clinosim.modules.disease.protocol import load_disease_protocol
pytestmark = pytest.mark.unit

_IDS = [os.path.basename(f)[:-5]
        for f in glob.glob("clinosim/modules/disease/reference_data/*.yaml")]


def test_all_real_disease_severity_blocks_valid():
    # Every shipped disease YAML must pass validation (guards the vocabulary sets).
    for d in _IDS:
        load_disease_protocol(d)  # must not raise


def test_bad_distribution_raises():
    with pytest.raises(ValueError):
        _validate_severity_block("x", {"distribution": {"mild": 0.0, "moderate": 0.0, "severe": 0.0}}, None)


def test_unknown_modifier_condition_raises():
    with pytest.raises(ValueError):
        _validate_severity_block("x", {
            "distribution": {"mild": 0.3, "moderate": 0.4, "severe": 0.3},
            "modifiers": [{"condition": "totally_made_up", "severe_multiplier": 2.0}],
        }, None)


def test_bad_minimum_raises():
    with pytest.raises(ValueError):
        _validate_severity_block("x", {"distribution": {"mild": 0.3, "moderate": 0.4, "severe": 0.3}}, "critical")


def test_nonpositive_multiplier_raises():
    with pytest.raises(ValueError):
        _validate_severity_block("x", {
            "distribution": {"mild": 0.3, "moderate": 0.4, "severe": 0.3},
            "modifiers": [{"condition": "age_over_75", "severe_multiplier": 0.0}],
        }, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/modules/disease/test_severity_validation.py -q`
Expected: FAIL (`_validate_severity_block` not defined). `test_all_real...` may also fail if a real condition is missing from the vocabulary sets — if so, add it to the correct set in Task 2's module (evaluable vs reserved).

- [ ] **Step 3: Write minimal implementation**

```python
# append to clinosim/modules/disease/severity.py
def _validate_severity_block(disease_id: str, severity: dict, minimum_severity: str | None) -> None:
    dist = (severity or {}).get("distribution", {})
    missing = [c for c in SEVERITY_CATEGORIES if c not in dist]
    if missing:
        raise ValueError(f"{disease_id}: severity.distribution missing {missing}")
    vals = [float(dist[c]) for c in SEVERITY_CATEGORIES]
    if any(v < 0 for v in vals):
        raise ValueError(f"{disease_id}: negative severity.distribution weight {vals}")
    if sum(vals) <= 0:
        raise ValueError(f"{disease_id}: severity.distribution sums to 0")
    if minimum_severity is not None and minimum_severity not in SEVERITY_CATEGORIES:
        raise ValueError(f"{disease_id}: minimum_severity {minimum_severity!r} not a category")
    for mod in severity.get("modifiers", []) or []:
        cond = mod.get("condition", "")
        if cond not in KNOWN_MODIFIER_CONDITIONS:
            raise ValueError(
                f"{disease_id}: unknown severity modifier condition {cond!r} "
                f"(add to EVALUABLE_CONDITIONS or RESERVED_INTRINSIC_CONDITIONS)"
            )
        for cat in SEVERITY_CATEGORIES:
            mult = mod.get(f"{cat}_multiplier")
            if mult is not None and float(mult) <= 0:
                raise ValueError(f"{disease_id}: non-positive {cat}_multiplier for {cond!r}")
```

```python
# clinosim/modules/disease/protocol.py — in load_disease_protocol, after building the model:
#   from clinosim.modules.disease.severity import _validate_severity_block
#   _validate_severity_block(disease_id, data.get("severity", {}), protocol.minimum_severity)
# (import at top of file; call just before `return protocol`.)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/modules/disease/test_severity_validation.py -q`
Expected: PASS. If `test_all_real_disease_severity_blocks_valid` fails on an unknown condition, add that condition to the correct vocabulary set (Task 2) and re-run.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/disease/severity.py clinosim/modules/disease/protocol.py tests/unit/modules/disease/test_severity_validation.py
git commit -m "feat(severity FP-SEV-MODEL): fail-loud severity-block validation at load"
```

---

### Task 5: wire population/engine to sample_severity; remove locale severity_beta

**Files:**
- Modify: `clinosim/modules/population/engine.py:361-366`
- Modify: `clinosim/locale/us/demographics.yaml`, `clinosim/locale/jp/demographics.yaml` (remove `severity_beta` / `severity_minimum` from each `disease_incidence` entry)
- Modify: `clinosim/modules/population/README.md` (declare disease dependency)
- Test: `tests/integration/test_population_severity_source.py`

**Interfaces:**
- Consumes: `sample_severity` (Task 3), `load_disease_protocol`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_population_severity_source.py
import numpy as np
import pytest
pytestmark = pytest.mark.integration


def test_population_severity_matches_disease_distribution():
    """A disease with a mild:0 distribution (e.g. acute_mi) must never produce a
    hospitalized inpatient severity that categorizes as mild — proving the sampled
    severity comes from the disease YAML, not the old comorbidity-blind beta."""
    from clinosim.modules.population.engine import generate_population
    from clinosim.modules.disease.severity import category_from_score
    pop = generate_population(4000, "US", np.random.default_rng(42))
    mi_events = [e for p in pop for e in getattr(p, "_events", [])] if False else []
    # generate_population returns PersonRecords; severity lives on LifeEvent from
    # generate_monthly_events. Use the events API the codebase exposes:
    from clinosim.modules.population.engine import generate_monthly_events
    events = []
    for person in pop:
        events += generate_monthly_events(person, 2024, 6, "US", np.random.default_rng(1))
    mi = [e for e in events if e.disease_id == "acute_mi"]
    if not mi:
        pytest.skip("no acute_mi events at this seed/size")
    assert all(category_from_score(e.severity) != "mild" for e in mi)
```
Note: adjust the event-collection call to the actual `generate_monthly_events` signature (check `clinosim/simulator/engine.py:124-142` for how it is invoked) before running; the assertion (no mild acute_mi) is the real check.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_population_severity_source.py -q`
Expected: FAIL — today `severity_beta` can produce a score < 0.3 for acute_mi (comorbidity-blind), so some MI events categorize as mild.

- [ ] **Step 3: Implement**

In `clinosim/modules/population/engine.py`, replace lines 361-366:
```python
            # Severity from the disease-YAML distribution (FP-SEV-MODEL, c2).
            from clinosim.modules.disease.protocol import load_disease_protocol
            from clinosim.modules.disease.severity import sample_severity
            protocol = load_disease_protocol(disease_id)
            _category, severity = sample_severity(protocol, person, rng)
```
(Keep the existing `severity` float variable name so lines 368-395 — hospitalization gate + `LifeEvent(severity=severity)` — are unchanged. Move the two imports to the top of the file per ruff.)

Then remove `severity_beta:` and `severity_minimum:` lines from every `disease_incidence` entry in both `clinosim/locale/us/demographics.yaml` and `clinosim/locale/jp/demographics.yaml`. Update `clinosim/modules/population/README.md` Dependencies to list `disease`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_population_severity_source.py -q`
Expected: PASS.

- [ ] **Step 5: Prove zero dangling severity_beta readers**

Run: `grep -rn "severity_beta\|severity_minimum" clinosim/ --include="*.py"`
Expected: NO matches in `.py` (only the removed YAML). If any `.py` still reads them, fix that reader now.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/population/engine.py clinosim/modules/population/README.md clinosim/locale/us/demographics.yaml clinosim/locale/jp/demographics.yaml tests/integration/test_population_severity_source.py
git commit -m "feat(severity FP-SEV-MODEL): population draws severity from disease YAML; retire severity_beta"
```

---

### Task 6: inpatient.py — category_from_score, drop duplicate minimum clamp

**Files:**
- Modify: `clinosim/simulator/inpatient.py:117-124`
- Test: `tests/unit/test_inpatient_severity_category.py`

**Interfaces:**
- Consumes: `category_from_score` (Task 1).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inpatient_severity_category.py
import inspect
import pytest
import clinosim.simulator.inpatient as ip
pytestmark = pytest.mark.unit


def test_inpatient_uses_category_from_score_helper():
    src = inspect.getsource(ip)
    assert "category_from_score(event.severity)" in src
    # The hardcoded 0.7/0.3 boundary must be gone from the severity derivation.
    assert 'event.severity > 0.7' not in src


def test_inpatient_no_longer_clamps_minimum_severity_locally():
    # minimum is now owned by sample_severity; the local clamp block is removed.
    src = inspect.getsource(ip)
    assert "severity_order = [" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_inpatient_severity_category.py -q`
Expected: FAIL (old hardcoded branch + clamp still present).

- [ ] **Step 3: Implement**

In `clinosim/simulator/inpatient.py`, replace the else-branch at lines 116-124:
```python
    else:
        from clinosim.modules.disease.severity import category_from_score
        severity = category_from_score(event.severity)
```
(delete the `minimum_severity` clamp block 118-124 entirely; move the import to the top of the file). Keep the `if forced_severity:` branch at 114-115 unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_inpatient_severity_category.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/inpatient.py tests/unit/test_inpatient_severity_category.py
git commit -m "refactor(severity FP-SEV-MODEL): inpatient uses category_from_score, drops duplicate minimum clamp"
```

---

### Task 7: emergency.py — shared categorical primitive

**Files:**
- Modify: `clinosim/simulator/emergency.py:74-88`
- Test: `tests/integration/test_ed_severity_distribution_preserved.py`

**Interfaces:**
- Consumes: `sample_severity_category` (Task 3).

- [ ] **Step 1: Write the failing test (distribution-preservation, not byte)**

```python
# tests/integration/test_ed_severity_distribution_preserved.py
import json, subprocess
from pathlib import Path
import pytest
pytestmark = pytest.mark.integration


def _ed_severity_counts(out: Path):
    enc = out / "fhir_r4" / "Encounter.ndjson"
    rows = [json.loads(l) for l in enc.read_text().splitlines() if l] if enc.exists() else []
    # ED encounters carry severity via the triage path; count by encounter class "EMER".
    from collections import Counter
    c = Counter()
    for r in rows:
        if (r.get("class") or {}).get("code") == "EMER":
            c[r.get("id", "")[:0]] += 1  # placeholder; see note
    return len(rows)


def test_ed_cohort_runs_and_produces_encounters(tmp_path):
    out = tmp_path / "out"
    cmd = ["python", "-m", "clinosim.simulator.cli", "generate",
           "-p", "300", "-s", "7", "--country", "US", "--format", "fhir-r4", "-o", str(out)]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert (out / "fhir_r4" / "Encounter.ndjson").exists()
```
Note: this smoke test guards that the ED path still runs after the change. The real distribution-preservation check is Step 4 (compare severity category counts on a fixed seed before/after the code change using a scratch script, since goldens for the whole cohort regenerate in Task 8).

- [ ] **Step 2: Run test to verify it fails / baseline**

Before editing emergency.py, capture the baseline ED severity distribution:
Run: `python -m clinosim.simulator.cli generate -p 300 -s 7 --country US --format fhir-r4 -o /tmp/ed_before && python3 -c "import json;from collections import Counter;rows=[json.loads(l) for l in open('/tmp/ed_before/fhir_r4/Encounter.ndjson')];print('encounters',len(rows))"`
Record the count. (Run the smoke test: it should PASS today — it only checks the run succeeds.)

- [ ] **Step 3: Implement**

In `clinosim/simulator/emergency.py`, replace lines 76-83:
```python
        from clinosim.modules.disease.severity import sample_severity_category
        sev_dist = protocol.get("severity_distribution", {})
        severity = sample_severity_category(sev_dist, [], patient, rng, None)
```
(keep the `ed_stay_hours` lookup that follows using `severity`; keep the `else` default branch for `protocol is None`).

- [ ] **Step 4: Verify ED distribution preserved (statistical, not byte)**

Run the same cohort into `/tmp/ed_after`, compare severity category counts:
Run: `python -m clinosim.simulator.cli generate -p 300 -s 7 --country US --format fhir-r4 -o /tmp/ed_after` then diff the ED severity category distribution (via a scratch script reading triage levels or Encounter severity) between before/after. Expected: category counts within a few percent (tiny normalize float perturbation may flip a handful of boundary draws; a large shift means a bug).

- [ ] **Step 5: Run smoke test**

Run: `python -m pytest tests/integration/test_ed_severity_distribution_preserved.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/emergency.py tests/integration/test_ed_severity_distribution_preserved.py
git commit -m "refactor(severity FP-SEV-MODEL): ED uses shared categorical severity primitive"
```

---

### Task 8: downstream audit, full suite, golden regeneration

**Files:**
- Modify: regenerated goldens under `tests/fixtures/patient_profiles/*.golden.json` + `*.llm-mock.golden.json`
- Modify: `DESIGN.md` (new ADR), `docs/design-notes/2026-07-06-fix-point-registry.md` (FP-SEV-MODEL → DONE), `TODO.md` (deferred: reserved-intrinsic modifiers)

- [ ] **Step 1: Re-grep severity consumers, confirm each API-compatible or fixed**

Run: `grep -rn "\.severity\b\|event.severity\|encounter.severity" clinosim/ --include="*.py" | grep -v "severity_score\|Severity\b\|reaction"`
For each hit outside the tasks above, confirm it consumes a category string / float whose type is unchanged. Document the list in the commit message. Fix any genuine breakage here.

- [ ] **Step 2: Run unit + integration**

Run: `python -m pytest -m unit -q && python -m pytest -m integration -q`
Expected: PASS. Fix any real regressions (not golden drift — that is Step 4).

- [ ] **Step 3: Run e2e (property-based)**

Run: `python -m pytest -m e2e -q`
Expected: PASS. If a property threshold fails (e.g. archetype-variety, severity mix), inspect: it likely hard-coded an old-distribution expectation — update the property bound to the new (disease-YAML-driven) distribution only if clinically sensible.

- [ ] **Step 4: Regenerate + clinically read goldens (AD-66)**

Run: `python -m clinosim.simulator.cli regenerate-goldens --all --provider template && python -m clinosim.simulator.cli regenerate-goldens --all --provider mock`
Then `git diff --stat tests/fixtures/patient_profiles/` and READ a sample of each changed golden: severity mix / LOS / archetype / imaging rates should shift toward disease-YAML distributions; structural identity (patient/encounter ids) stable; no empty/placeholder narratives introduced. Run `python -m pytest -m regression -q` to confirm green.

- [ ] **Step 5: Audit run on production cohorts**

Run: `python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US -o /tmp/us && python -m clinosim.simulator.cli audit run -d /tmp/us` (and JP). Expected: audit green (no new FAIL).

- [ ] **Step 6: Docs + registry + commit**

Add ADR to `DESIGN.md` (severity single-source: disease YAML canonical, locale incidence-only, `severity.py` owner, category↔score boundary). Mark FP-SEV-MODEL DONE in the registry. Add a TODO.md entry for the reserved-intrinsic modifier mechanism (scenario-flag evaluation of `anterior_wall_MI` etc.). Commit code + goldens together:
```bash
git add -A
git commit -m "feat(severity FP-SEV-MODEL): regenerate goldens + ADR + downstream audit

All gates green: unit / integration / e2e / regression / audit. Goldens shift
toward disease-YAML severity distributions (AD-66 diff read). Reserved-intrinsic
modifiers filed as TODO."
```

---

## Self-Review

- **Spec coverage:** severity.py owner (T1-T4) ✓; population wiring + severity_beta removal (T5) ✓; inpatient boundary + minimum unification (T6) ✓; ED shared primitive (T7) ✓; downstream audit + goldens + ADR (T8) ✓; validation fail-loud (T4) ✓; modifier firing test (T3) ✓; determinism/golden strategy (T8) ✓; scope-deferred reserved-intrinsic (T2 sets + T8 TODO) ✓.
- **Types:** `sample_severity -> tuple[str,float]`, `sample_severity_category -> str`, `category_from_score(float)->str`, `_apply_modifiers(dict,list,person)->dict` consistent across tasks.
- **Determinism:** every draw via passed `rng`; imports moved to top (no per-call import cost concern for correctness, but finalize to satisfy ruff).
- **Known follow-ups (documented, not gaps):** reserved-intrinsic modifiers (T8 TODO); exact per-condition PersonRecord mapping reconciled in T2 step 3 against the enumeration command.
</content>
