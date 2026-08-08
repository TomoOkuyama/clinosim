# Family History (FamilyMemberHistory) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synthesize first-degree-relative disease history per patient (heritability × locale prevalence, correlated with the patient's own chronic conditions) and emit FHIR `FamilyMemberHistory` + CSV.

**Architecture:** Mirror the immunization Base feature. New `clinosim/modules/family_history/` (engine + reference_data + enricher), locale prevalence YAML (US/JP), an AD-56 `post_records` enricher with a `person_id`-derived sub-seed (master stream unperturbed), a typed CIF list, a registered FHIR builder, and a CSV writer.

**Tech Stack:** Python 3.11, numpy, PyYAML, pytest.

## Global Constraints

- Determinism (AD-16): generation uses `derive_sub_seed(master_seed, _FH_SEED_OFFSET, person_id)` — never the master generator; no master draw consumed.
- AD-30: CIF stores codes only (ICD base codes + v3-RoleCode), no display text.
- English-first codes (AD-33): every new code in `codes/data/*.yaml` has an `en` field; `ja` optional.
- Authoritative codes only: new cancer ICD codes verified vs NLM ICD-10-CM / WHO ICD-10.
- Stable across encounters: family history seeded by `person_id`, identical for every encounter of a patient; de-duped at FHIR/CSV write.

---

### Task 1: Type + reference data + locale prevalence

**Files:**
- Create: `clinosim/types/family_history.py`
- Create: `clinosim/modules/family_history/__init__.py`
- Create: `clinosim/modules/family_history/reference_data/family_history.yaml`
- Create: `clinosim/locale/us/family_history_prevalence.yaml`
- Create: `clinosim/locale/jp/family_history_prevalence.yaml`
- Test: `tests/unit/test_family_history_data.py`

**Interfaces:**
- Produces: `FamilyMemberHistoryRecord(relationship: str, sex: str, deceased: bool, condition_codes: list[str])`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_family_history_data.py
import pytest, yaml
from pathlib import Path
from clinosim.types.family_history import FamilyMemberHistoryRecord

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[2] / "clinosim"

def test_record_construction():
    r = FamilyMemberHistoryRecord(relationship="MTH", sex="female",
                                  deceased=False, condition_codes=["E11"])
    assert r.relationship == "MTH" and r.condition_codes == ["E11"]

def test_reference_data_shape():
    d = yaml.safe_load(open(_ROOT / "modules/family_history/reference_data/family_history.yaml"))
    assert set(d["conditions"]) == {"E11","I10","I25","I63","I64","E78","C50","C18","C34","C61"}
    assert d["relationships"]["MTH"]["en"] == "Mother"
    assert d["conditions"]["C61"]["sex"] == "male"      # prostate
    assert d["conditions"]["C50"]["sex"] == "female"    # breast

@pytest.mark.parametrize("country", ["us", "jp"])
def test_prevalence_data_shape(country):
    d = yaml.safe_load(open(_ROOT / f"locale/{country}/family_history_prevalence.yaml"))
    # every condition has age-banded prevalence with male/female rows
    for code in ["E11","I10","C50"]:
        bands = d["prevalence"][code]
        assert "40-59" in bands and "female" in bands["40-59"]
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_family_history_data.py -v` → FAIL (module/files missing).

- [ ] **Step 3: Create the type**

```python
# clinosim/types/family_history.py
"""Family history of disease — first-degree relative records (AD-55 Base).

Codes only (AD-30): relationship is an HL7 v3-RoleCode (MTH/FTH/NSIB), conditions
are ICD base codes. Display is resolved at output time.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class FamilyMemberHistoryRecord:
    relationship: str                 # v3-RoleCode: MTH | FTH | NSIB
    sex: str                          # "male" | "female"
    deceased: bool = False
    condition_codes: list[str] = field(default_factory=list)  # ICD base codes
```

- [ ] **Step 4: Create `modules/family_history/__init__.py`** (empty package marker).

- [ ] **Step 5: Create the reference data** (country-neutral biology)

```yaml
# clinosim/modules/family_history/reference_data/family_history.yaml
# Relationship codes (HL7 v3-RoleCode) with display.
relationships:
  MTH: {en: "Mother", ja: "母"}
  FTH: {en: "Father", ja: "父"}
  NSIB: {en: "Sibling", ja: "兄弟姉妹"}

# Sibling count distribution (weights for 0,1,2).
sibling_count_weights: [0.4, 0.4, 0.2]

# Relative age derivation from the patient's age (years).
parent_age_offset: {min: 25, max: 35}     # parent is patient_age + [25,35]
sibling_age_offset: {min: -12, max: 12}

# Probability a parent of derived age `a` is deceased: clamp((a-60)/40, 0, 0.9).
parent_deceased_base_age: 60
parent_deceased_span: 40
parent_deceased_max: 0.9

# Conditions: heritability multiplier (applied to a relative's prevalence when the
# PATIENT carries the same base code) + optional sex restriction.
conditions:
  E11: {heritability: 2.0}            # diabetes
  I10: {heritability: 1.8}            # hypertension
  I25: {heritability: 2.0}            # coronary artery disease
  I63: {heritability: 1.5}            # ischemic stroke
  I64: {heritability: 1.5}            # stroke, unspecified
  E78: {heritability: 1.8}            # dyslipidemia
  C50: {heritability: 2.0, sex: female}   # breast cancer
  C18: {heritability: 1.8}            # colorectal cancer
  C34: {heritability: 1.5}            # lung cancer
  C61: {heritability: 2.0, sex: male}     # prostate cancer
```

- [ ] **Step 6: Create the US prevalence data** (lifetime prevalence in a relative; literature-approximate, audit-refined — these are epidemiological rates, not codes)

```yaml
# clinosim/locale/us/family_history_prevalence.yaml
# Base lifetime prevalence of each condition in a first-degree relative,
# by age band and sex. Approximate US adult epidemiology; refined by audit.
prevalence:
  E11:  {40-59: {male: 0.11, female: 0.10}, 60-120: {male: 0.22, female: 0.20}}
  I10:  {40-59: {male: 0.32, female: 0.30}, 60-120: {male: 0.60, female: 0.62}}
  I25:  {40-59: {male: 0.08, female: 0.04}, 60-120: {male: 0.22, female: 0.14}}
  I63:  {40-59: {male: 0.02, female: 0.02}, 60-120: {male: 0.09, female: 0.09}}
  I64:  {40-59: {male: 0.01, female: 0.01}, 60-120: {male: 0.04, female: 0.04}}
  E78:  {40-59: {male: 0.34, female: 0.34}, 60-120: {male: 0.40, female: 0.45}}
  C50:  {40-59: {male: 0.00, female: 0.04}, 60-120: {male: 0.00, female: 0.11}}
  C18:  {40-59: {male: 0.01, female: 0.01}, 60-120: {male: 0.04, female: 0.04}}
  C34:  {40-59: {male: 0.01, female: 0.01}, 60-120: {male: 0.06, female: 0.05}}
  C61:  {40-59: {male: 0.01, female: 0.00}, 60-120: {male: 0.13, female: 0.00}}
```

- [ ] **Step 7: Create the JP prevalence data** (JP epidemiology: lower CAD/breast/prostate, higher stroke/gastric-adjacent; same condition set)

```yaml
# clinosim/locale/jp/family_history_prevalence.yaml
prevalence:
  E11:  {40-59: {male: 0.12, female: 0.07}, 60-120: {male: 0.20, female: 0.14}}
  I10:  {40-59: {male: 0.30, female: 0.25}, 60-120: {male: 0.58, female: 0.60}}
  I25:  {40-59: {male: 0.04, female: 0.02}, 60-120: {male: 0.12, female: 0.07}}
  I63:  {40-59: {male: 0.03, female: 0.02}, 60-120: {male: 0.12, female: 0.11}}
  I64:  {40-59: {male: 0.01, female: 0.01}, 60-120: {male: 0.05, female: 0.05}}
  E78:  {40-59: {male: 0.30, female: 0.30}, 60-120: {male: 0.38, female: 0.42}}
  C50:  {40-59: {male: 0.00, female: 0.03}, 60-120: {male: 0.00, female: 0.07}}
  C18:  {40-59: {male: 0.01, female: 0.01}, 60-120: {male: 0.05, female: 0.04}}
  C34:  {40-59: {male: 0.01, female: 0.01}, 60-120: {male: 0.06, female: 0.04}}
  C61:  {40-59: {male: 0.00, female: 0.00}, 60-120: {male: 0.08, female: 0.00}}
```

- [ ] **Step 8: Run, verify pass** — `pytest tests/unit/test_family_history_data.py -v` → PASS.

- [ ] **Step 9: Commit** — `git add clinosim/types/family_history.py clinosim/modules/family_history/ clinosim/locale/us/family_history_prevalence.yaml clinosim/locale/jp/family_history_prevalence.yaml tests/unit/test_family_history_data.py && git commit -m "feat(family-history): types + reference/prevalence data"`

---

### Task 2: Generation engine (TDD)

**Files:**
- Create: `clinosim/modules/family_history/engine.py`
- Test: `tests/unit/test_family_history_engine.py`

**Interfaces:**
- Consumes: `FamilyMemberHistoryRecord`; reference data + prevalence dicts.
- Produces:
  - `load_reference() -> dict`
  - `load_prevalence(country: str) -> dict`
  - `generate_family_history(patient_age: int, patient_conditions: list[str], country: str, rng: np.random.Generator) -> list[FamilyMemberHistoryRecord]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_family_history_engine.py
import numpy as np, pytest
from clinosim.modules.family_history.engine import generate_family_history

pytestmark = pytest.mark.unit

def _gen(conditions, seed=1, age=70, country="US"):
    return generate_family_history(age, conditions, country, np.random.default_rng(seed))

def test_always_has_mother_and_father():
    fams = _gen([])
    rels = {f.relationship for f in fams}
    assert "MTH" in rels and "FTH" in rels

def test_deterministic():
    a = _gen(["E11"], seed=5); b = _gen(["E11"], seed=5)
    assert [(f.relationship, f.sex, f.deceased, f.condition_codes) for f in a] == \
           [(f.relationship, f.sex, f.deceased, f.condition_codes) for f in b]

def test_sex_restriction_prostate_male_only():
    # C61 must never appear on a female relative across many samples.
    for s in range(200):
        for f in _gen(["C61"], seed=s):
            if f.sex == "female":
                assert "C61" not in f.condition_codes

def test_sex_restriction_breast_female_only():
    for s in range(200):
        for f in _gen(["C50"], seed=s):
            if f.sex == "male":
                assert "C50" not in f.condition_codes

def test_heritability_boost_raises_parental_rate():
    # Patients WITH E11 should yield a higher parental-E11 rate than without.
    def parental_e11_rate(conditions):
        hits = tot = 0
        for s in range(400):
            for f in _gen(conditions, seed=s):
                if f.relationship in ("MTH", "FTH"):
                    tot += 1; hits += ("E11" in f.condition_codes)
        return hits / tot
    assert parental_e11_rate(["E11"]) > parental_e11_rate([]) * 1.3

def test_jp_us_differ():
    # Loading the JP table must change rates (e.g. C61 lower in JP).
    def prostate_rate(country):
        hits = tot = 0
        for s in range(400):
            for f in generate_family_history(75, [], country, np.random.default_rng(s)):
                if f.sex == "male" and f.relationship == "FTH":
                    tot += 1; hits += ("C61" in f.condition_codes)
        return hits / max(tot, 1)
    assert prostate_rate("JP") < prostate_rate("US")
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_family_history_engine.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement the engine**

```python
# clinosim/modules/family_history/engine.py
"""Family history generation (AD-55 Base). Pure + seeded; codes only (AD-30)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.types.family_history import FamilyMemberHistoryRecord

_HERE = Path(__file__).resolve().parent
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=1)
def load_reference() -> dict:
    with open(_HERE / "reference_data" / "family_history.yaml") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=4)
def load_prevalence(country: str) -> dict:
    key = "jp" if str(country).upper() == "JP" else "us"
    with open(_LOCALE / key / "family_history_prevalence.yaml") as f:
        return (yaml.safe_load(f) or {}).get("prevalence", {})


def _prevalence(prev: dict, code: str, sex: str, age: int) -> float:
    bands = prev.get(code, {})
    for band, rows in bands.items():
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return float(rows.get(sex, 0.0))
    return 0.0


def _relative(prev: dict, conditions: dict, patient_codes: set[str],
              relationship: str, sex: str, age: int, deceased: bool,
              rng: np.random.Generator) -> FamilyMemberHistoryRecord:
    codes: list[str] = []
    for code, cfg in conditions.items():
        if cfg.get("sex") and cfg["sex"] != sex:
            continue
        p = _prevalence(prev, code, sex, age)
        if code in patient_codes:
            p = min(1.0, p * float(cfg.get("heritability", 1.0)))
        if rng.random() < p:
            codes.append(code)
    return FamilyMemberHistoryRecord(relationship=relationship, sex=sex,
                                     deceased=deceased, condition_codes=codes)


def generate_family_history(patient_age: int, patient_conditions: list[str],
                            country: str, rng: np.random.Generator
                            ) -> list[FamilyMemberHistoryRecord]:
    ref = load_reference()
    prev = load_prevalence(country)
    conditions = ref["conditions"]
    # Patient's own conditions reduced to base ICD codes for heritability matching.
    patient_codes = {c.split(".")[0].upper() for c in (patient_conditions or [])}

    po = ref["parent_age_offset"]
    out: list[FamilyMemberHistoryRecord] = []
    for rel, sex in (("MTH", "female"), ("FTH", "male")):
        age = patient_age + int(rng.integers(po["min"], po["max"] + 1))
        dp = min(ref["parent_deceased_max"],
                 max(0.0, (age - ref["parent_deceased_base_age"]) / ref["parent_deceased_span"]))
        deceased = rng.random() < dp
        out.append(_relative(prev, conditions, patient_codes, rel, sex, age, deceased, rng))

    n_sib = int(rng.choice([0, 1, 2], p=ref["sibling_count_weights"]))
    so = ref["sibling_age_offset"]
    for _ in range(n_sib):
        sex = "male" if rng.random() < 0.5 else "female"
        age = max(0, patient_age + int(rng.integers(so["min"], so["max"] + 1)))
        out.append(_relative(prev, conditions, patient_codes, "NSIB", sex, age, False, rng))
    return out
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/unit/test_family_history_engine.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add clinosim/modules/family_history/engine.py tests/unit/test_family_history_engine.py && git commit -m "feat(family-history): seeded generation engine"`

---

### Task 3: Cancer ICD codes (authoritative)

**Files:**
- Modify: `clinosim/codes/data/icd-10-cm.yaml`
- Modify: `clinosim/codes/data/icd-10.yaml`
- Test: `tests/unit/test_family_history_codes.py`

**Interfaces:**
- Produces: ICD entries for `C50/C18/C34/C61` resolvable via `lookup(system, code, lang)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_family_history_codes.py
import pytest
from clinosim.codes import lookup
pytestmark = pytest.mark.unit

@pytest.mark.parametrize("code", ["C50", "C18", "C34", "C61"])
def test_cancer_codes_resolve_us_and_jp(code):
    en = lookup("icd-10-cm", code, "en"); assert en and en != code
    who = lookup("icd-10", code, "en");   assert who and who != code
    assert lookup("icd-10-cm", code, "ja")  # JA present
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_family_history_codes.py -v` → FAIL (codes missing / display == code).

- [ ] **Step 3: Add the codes** — verify each vs NLM ICD-10-CM API (`clinicaltables.nlm.nih.gov/api/icd10cm`) and WHO ICD-10 before adding. Add to `codes/data/icd-10-cm.yaml` and `codes/data/icd-10.yaml` under `codes:` (category-level C-codes are valid WHO; for CM, category headers are non-billable but acceptable for family-history display since these are NOT emitted as billable patient Conditions):

```yaml
# both files, en + ja (official terms)
  C18: {en: "Malignant neoplasm of colon", ja: "結腸の悪性新生物"}
  C34: {en: "Malignant neoplasm of bronchus and lung", ja: "気管支および肺の悪性新生物"}
  C50: {en: "Malignant neoplasm of breast", ja: "乳房の悪性新生物"}
  C61: {en: "Malignant neoplasm of prostate", ja: "前立腺の悪性新生物"}
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/unit/test_family_history_codes.py -v` → PASS; also `pytest tests/unit/test_diagnosis_code_coverage.py -v` (ensure no coverage regression).

- [ ] **Step 5: Commit** — `git add clinosim/codes/data/icd-10-cm.yaml clinosim/codes/data/icd-10.yaml tests/unit/test_family_history_codes.py && git commit -m "feat(codes): add C18/C34/C50/C61 cancer ICD for family history"`

---

### Task 4: Enricher wiring (post_records, person sub-seed)

**Files:**
- Create: `clinosim/modules/family_history/enricher.py`
- Modify: `clinosim/simulator/enrichers.py` (register in `register_builtin_enrichers`)
- Test: `tests/integration/test_family_history_enricher.py`

**Interfaces:**
- Consumes: `generate_family_history`, `EnricherContext`, `derive_sub_seed`.
- Produces: each record gets `record["family_history"] = list[FamilyMemberHistoryRecord]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_family_history_enricher.py
import pytest
from clinosim.modules.family_history.enricher import enrich_family_history

pytestmark = pytest.mark.integration

class _Ctx:
    def __init__(self, records):
        self.config = type("C", (), {"country": "US"})()
        self.master_seed = 42
        self.population = None
        self.records = records

def _rec(pid, age, conditions):
    return {"patient": {"patient_id": pid, "age": age, "chronic_conditions": conditions}}

def test_enricher_populates_family_history():
    rec = _rec("P1", 70, ["E11"])
    enrich_family_history(_Ctx([rec]))
    fh = rec["family_history"]
    assert fh and {f.relationship for f in fh} >= {"MTH", "FTH"}

def test_stable_across_encounters_same_person():
    # Same person_id in two encounter records -> identical family history.
    r1, r2 = _rec("P1", 70, ["E11"]), _rec("P1", 70, ["E11"])
    enrich_family_history(_Ctx([r1, r2]))
    key = lambda fh: [(f.relationship, f.sex, f.deceased, f.condition_codes) for f in fh]
    assert key(r1["family_history"]) == key(r2["family_history"])
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/integration/test_family_history_enricher.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement the enricher** (mirror `immunization/enricher.py`)

```python
# clinosim/modules/family_history/enricher.py
"""Family history enricher (AD-55 Base, AD-56 post_records).

Seeded by person_id so the family history is identical across a patient's
encounters and the main simulation stream is untouched (AD-16).
"""
from __future__ import annotations

import numpy as np

from clinosim.modules.family_history.engine import generate_family_history
from clinosim.simulator.seeding import derive_sub_seed

_FH_SEED_OFFSET = 0x4648  # "FH"


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enrich_family_history(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 0) or 0) if patient else 0
        conditions = _get(patient, "chronic_conditions", []) if patient else []
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, _FH_SEED_OFFSET, pid or "x"))
        fams = generate_family_history(age, conditions, country, rng)
        if isinstance(rec, dict):
            rec["family_history"] = fams
        else:
            rec.family_history = fams
```

- [ ] **Step 4: Register the enricher** — in `clinosim/simulator/enrichers.py` `register_builtin_enrichers()`, after the immunization block:

```python
    # Family history (AD-55 Base): first-degree relative disease history. Always-on.
    from clinosim.modules.family_history.enricher import enrich_family_history

    register_enricher(
        Enricher(
            name="family_history",
            stage=POST_RECORDS,
            order=40,
            enabled=lambda c: True,
            run=enrich_family_history,
        )
    )
```

- [ ] **Step 5: Run, verify pass** — `pytest tests/integration/test_family_history_enricher.py -v` → PASS.

- [ ] **Step 6: Commit** — `git add clinosim/modules/family_history/enricher.py clinosim/simulator/enrichers.py tests/integration/test_family_history_enricher.py && git commit -m "feat(family-history): post_records enricher (person sub-seed)"`

---

### Task 5: FHIR FamilyMemberHistory builder

**Files:**
- Create: `clinosim/modules/output/_fhir_family_history.py`
- Modify: `clinosim/modules/output/fhir_r4_adapter.py` (facade import + `_BUNDLE_BUILDERS` list)
- Test: `tests/integration/test_fhir_family_history.py`

**Interfaces:**
- Consumes: `BundleContext`, `_build_diagnosis_codeable_concept`, `get_system_uri`, `load_reference`.
- Produces: `_build_family_history(ctx: BundleContext) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_fhir_family_history.py
import pytest
from clinosim.modules.output.fhir_r4_adapter import BundleContext, _build_family_history
from clinosim.types.family_history import FamilyMemberHistoryRecord

pytestmark = pytest.mark.integration

def _ctx(country="US"):
    fams = [FamilyMemberHistoryRecord("MTH", "female", True, ["E11", "C50"]),
            FamilyMemberHistoryRecord("FTH", "male", False, ["I25"])]
    return BundleContext(record={"family_history": fams}, country=country, roster_map={},
                         hospital_config={}, patient_data={}, patient_id="pat-1",
                         is_readmission=False, prior_encounter_id=None, primary_dx_code="",
                         admit_dx_code="", admit_dx_system="icd-10-cm", primary_enc_id="enc-1",
                         patient_sex="female")

def test_builds_one_resource_per_relative():
    res = _build_family_history(_ctx())
    assert len(res) == 2
    r0 = res[0]
    assert r0["resourceType"] == "FamilyMemberHistory"
    assert r0["status"] == "completed"
    assert r0["patient"] == {"reference": "Patient/pat-1"}
    assert r0["relationship"]["coding"][0]["code"] == "MTH"
    assert r0["deceasedBoolean"] is True
    # condition[].code resolves ICD (never display == code)
    codes = [c["code"]["coding"][0]["code"] for c in r0["condition"]]
    assert "E11" in codes

def test_unique_ids():
    res = _build_family_history(_ctx())
    ids = [r["id"] for r in res]
    assert len(ids) == len(set(ids))

def test_jp_localized_relationship():
    res = _build_family_history(_ctx("JP"))
    assert res[0]["relationship"]["coding"][0]["display"] == "母"
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/integration/test_fhir_family_history.py -v` → FAIL (builder missing).

- [ ] **Step 3: Implement the builder**

```python
# clinosim/modules/output/_fhir_family_history.py
"""FHIR FamilyMemberHistory builder (AD-55 Base, AD-56 builder registry)."""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.modules.family_history.engine import load_reference
from clinosim.modules.output._fhir_common import BundleContext, _build_diagnosis_codeable_concept


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _build_family_history(ctx: BundleContext) -> list[dict]:
    fams = ctx.record.get("family_history") or []
    if not fams:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    icd_system_key = "icd-10" if ctx.country == "JP" else "icd-10-cm"
    rel_display = load_reference()["relationships"]
    out: list[dict] = []
    for i, fam in enumerate(fams):
        rel = _get(fam, "relationship", "")
        disp = rel_display.get(rel, {})
        res: dict[str, Any] = {
            "resourceType": "FamilyMemberHistory",
            "id": f"fmh-{ctx.patient_id}-{i:02d}",
            "status": "completed",
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "relationship": {"coding": [{
                "system": get_system_uri("hl7-v3-rolecode"),
                "code": rel,
                "display": disp.get(lang, disp.get("en", rel)),
            }]},
            "deceasedBoolean": bool(_get(fam, "deceased", False)),
        }
        # NOTE: FamilyMemberHistory.sex is optional and would require a new gender
        # system URI; omitted here (kept in CIF/CSV) to avoid a hardcoded URI.
        conditions = []
        for code in _get(fam, "condition_codes", []) or []:
            conditions.append({"code": _build_diagnosis_codeable_concept(code, icd_system_key, ctx.country)})
        if conditions:
            res["condition"] = conditions
        out.append(res)
    return out
```

- [ ] **Step 4: Register the builder** — in `fhir_r4_adapter.py`, add the facade import near the other `_fhir_*` builder imports and append to the `_BUNDLE_BUILDERS` list:

```python
from clinosim.modules.output._fhir_family_history import _build_family_history  # noqa: F401
```
```python
# inside the _BUNDLE_BUILDERS = [ ... ] list
    _build_family_history,
```

- [ ] **Step 5: Run, verify pass** — `pytest tests/integration/test_fhir_family_history.py -v` → PASS; resolve the gender-system note so no hardcoded URI remains (`grep -n '"system": "http' clinosim/modules/output/_fhir_family_history.py` → none except via `get_system_uri`).

- [ ] **Step 6: Commit** — `git add clinosim/modules/output/_fhir_family_history.py clinosim/modules/output/fhir_r4_adapter.py tests/integration/test_fhir_family_history.py && git commit -m "feat(fhir): FamilyMemberHistory builder"`

---

### Task 6: CSV output

**Files:**
- Modify: `clinosim/modules/output/csv_adapter.py`
- Test: `tests/unit/test_family_history_csv.py`

**Interfaces:**
- Produces: `family_history.csv` (patient_id, relationship, sex, deceased, condition_code).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_family_history_csv.py
import csv, os, pytest
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
pytestmark = pytest.mark.unit

def test_family_history_csv_written(tmp_path):
    records = [{"patient": {"patient_id": "P1"},
                "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
                "family_history": [
                    {"relationship": "MTH", "sex": "female", "deceased": True, "condition_codes": ["E11", "C50"]},
                ]}]
    convert_cif_to_csv(records, str(tmp_path), country="US")
    path = os.path.join(str(tmp_path), "family_history.csv")
    assert os.path.exists(path)
    rows = list(csv.DictReader(open(path)))
    assert {"E11", "C50"} == {r["condition_code"] for r in rows}
    assert rows[0]["relationship"] == "MTH" and rows[0]["patient_id"] == "P1"
```

(Confirm `convert_cif_to_csv`'s actual signature first — match the existing call used by other CSV tests; adjust the invocation if it differs.)

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_family_history_csv.py -v` → FAIL (no file).

- [ ] **Step 3: Implement** — add an `fh_rows` accumulator next to `imm_rows`, one row per (relative × condition); de-dup per patient_id (write only the first encounter's family history, like the patient-level resources):

```python
        # Family history (one row per relative-condition; patient-level, de-duped)
        if patient_id not in _fh_seen:
            _fh_seen.add(patient_id)
            for fam in record.get("family_history", []):
                rel = fam.get("relationship") if isinstance(fam, dict) else getattr(fam, "relationship", "")
                sex = fam.get("sex") if isinstance(fam, dict) else getattr(fam, "sex", "")
                dec = fam.get("deceased") if isinstance(fam, dict) else getattr(fam, "deceased", False)
                codes = fam.get("condition_codes") if isinstance(fam, dict) else getattr(fam, "condition_codes", [])
                for code in codes or []:
                    fh_rows.append({"patient_id": patient_id, "relationship": rel,
                                    "sex": sex, "deceased": dec, "condition_code": code})
```

with `_fh_seen: set[str] = set()` and `fh_rows: list[dict] = []` initialized near the other row lists, and `_write_csv(os.path.join(output_dir, "family_history.csv"), fh_rows)` added to the write block.

- [ ] **Step 4: Run, verify pass** — `pytest tests/unit/test_family_history_csv.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add clinosim/modules/output/csv_adapter.py tests/unit/test_family_history_csv.py && git commit -m "feat(csv): family_history.csv output"`

---

### Task 7: Determinism + audit + module README

**Files:**
- Create: `clinosim/modules/family_history/README.md`
- (verification only otherwise)

- [ ] **Step 1: byte-diff (master stream unperturbed)** — generate US `-p 3000 -s 99` on `master` and on the branch; `diff -rq` the `fhir_r4/` trees. Expected: only `FamilyMemberHistory.ndjson` is new; every pre-existing NDJSON byte-identical (manifest transactionTime aside). If any other resource differs, the sub-seed leaked into the master stream — fix before proceeding.

- [ ] **Step 2: Generation audit** — `python -m clinosim.simulator.cli generate -p 3000 --country US ... ` then a script over CIF: mean conditions per relative, % of patients whose diabetic status raises parental DM rate (heritability sanity), confirm `C61` never on female / `C50` never on male relatives, and JP vs US prostate/breast rate difference. Numbers should look clinical (parents mostly have ≥0 conditions, common conditions HTN/dyslipidemia most frequent).

- [ ] **Step 3: Write the module README** — `clinosim/modules/family_history/README.md` (Japanese w/ English terms, per project convention): purpose, data files (reference_data + locale prevalence), `generate_family_history` API, enricher stage/seed, FHIR/CSV outputs, dependencies (`types/family_history`, `codes`, `locale`, `simulator/seeding`).

- [ ] **Step 4: Full suite** — `pytest -m unit -q` and `pytest -m integration -q` green; `pytest -m e2e -q` green (e2e golden unchanged — family history adds a new resource only; if golden CIF gains a `family_history` key the golden may need a re-bless, inspect and confirm intended).

- [ ] **Step 5: Commit + PR** — `git add clinosim/modules/family_history/README.md && git commit -m "docs(family-history): module README + audit"`; push; open PR summarizing the audit (mean relatives/conditions, heritability sanity, byte-diff result).
