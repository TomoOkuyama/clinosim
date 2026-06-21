# Code Status (resuscitation status) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assign a 4-tier code status to serious encounters (inpatient always; ED if deceased/icu_transferred) and emit a FHIR `Observation` with a SNOMED value.

**Architecture:** Mirror the family_history Base feature. New `clinosim/modules/code_status/` (engine + reference_data), `locale/{us,jp}/code_status_rates.yaml`, an AD-56 `post_records` enricher seeded by `encounter_id` (master stream unperturbed), a typed `CIFPatientRecord.code_status` field, a registered FHIR builder, and a CSV writer.

**Tech Stack:** Python 3.11, numpy, PyYAML, pytest.

## Global Constraints

- Determinism (AD-16): `derive_sub_seed(master_seed, _CS_SEED_OFFSET, encounter_id)`; no master draw consumed.
- AD-30: CIF stores the SNOMED code only.
- Authoritative codes (AD-33/26): SNOMED values verified vs the SNOMED CT browser/Snowstorm API; `# TODO: verify` on any code not confirmed (never fabricate).
- Encounter gate: assign iff `encounter_type == "inpatient"` OR (`encounter_type == "emergency"` AND (`deceased` OR `icu_transferred`)); outpatient never.

---

### Task 1: CIF field + reference data + locale rates

**Files:**
- Modify: `clinosim/types/output.py` (add `code_status: str = ""` to `CIFPatientRecord`)
- Create: `clinosim/modules/code_status/__init__.py`
- Create: `clinosim/modules/code_status/reference_data/code_status.yaml`
- Create: `clinosim/locale/us/code_status_rates.yaml`
- Create: `clinosim/locale/jp/code_status_rates.yaml`
- Test: `tests/unit/test_code_status_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_code_status_data.py
import pytest, yaml
from pathlib import Path
from clinosim.types.output import CIFPatientRecord

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[2] / "clinosim"

def test_cif_field_default():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(CIFPatientRecord)}
    assert "code_status" in fields

def test_reference_tiers():
    d = yaml.safe_load(open(_ROOT / "modules/code_status/reference_data/code_status.yaml"))
    assert d["tiers"][0]["key"] == "full_code"
    assert [t["key"] for t in d["tiers"]] == ["full_code", "dnr", "dnr_dni", "comfort"]
    assert all(t.get("snomed") for t in d["tiers"])
    assert d["observable_snomed"]

@pytest.mark.parametrize("country", ["us", "jp"])
def test_rates_shape(country):
    d = yaml.safe_load(open(_ROOT / f"locale/{country}/code_status_rates.yaml"))
    for ctx in ("routine", "icu", "terminal"):
        bands = d["weights"][ctx]
        for band, w in bands.items():
            assert len(w) == 4 and abs(sum(w) - 1.0) < 1e-6
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_code_status_data.py -v` → FAIL.

- [ ] **Step 3: Add the CIF field** — in `clinosim/types/output.py`, after the `immunizations`/`family_history` fields on `CIFPatientRecord`:

```python
    code_status: str = ""  # AD-55 Base: SNOMED resuscitation-status code (codes only)
```

- [ ] **Step 4: Create `modules/code_status/__init__.py`** (empty).

- [ ] **Step 5: Create reference data** (country-neutral; SNOMED candidates, verified in Task 3)

```yaml
# clinosim/modules/code_status/reference_data/code_status.yaml
# Resuscitation-status observable + 4-tier values. SNOMED codes verified in the
# codes task (Snowstorm API); `# TODO: verify` marks unconfirmed candidates.
observable_snomed: "304251008"   # Resuscitation status  # TODO: verify
age_bands: ["0-49", "50-69", "70-84", "85-120"]
tiers:
  - {key: "full_code", snomed: "304252001", en: "For resuscitation", ja: "蘇生処置を行う"}
  - {key: "dnr",       snomed: "304253006", en: "Not for resuscitation", ja: "蘇生処置を行わない（DNAR）"}
  - {key: "dnr_dni",   snomed: "304253006", en: "Not for resuscitation, not for intubation", ja: "蘇生・挿管を行わない"}  # TODO: verify (DNI granularity)
  - {key: "comfort",   snomed: "103735009", en: "Comfort care (palliative)", ja: "緩和ケア（コンフォート）"}  # TODO: verify
```

- [ ] **Step 6: Create US rates**

```yaml
# clinosim/locale/us/code_status_rates.yaml
# 4-tier weights [full_code, dnr, dnr_dni, comfort] by context x age band.
weights:
  routine:
    "0-49":   [0.99, 0.01, 0.00, 0.00]
    "50-69":  [0.96, 0.03, 0.005, 0.005]
    "70-84":  [0.85, 0.10, 0.03, 0.02]
    "85-120": [0.70, 0.18, 0.07, 0.05]
  icu:
    "0-49":   [0.95, 0.03, 0.01, 0.01]
    "50-69":  [0.88, 0.07, 0.03, 0.02]
    "70-84":  [0.65, 0.18, 0.10, 0.07]
    "85-120": [0.45, 0.25, 0.15, 0.15]
  terminal:
    "0-49":   [0.55, 0.20, 0.10, 0.15]
    "50-69":  [0.40, 0.22, 0.13, 0.25]
    "70-84":  [0.20, 0.25, 0.15, 0.40]
    "85-120": [0.10, 0.22, 0.18, 0.50]
```

- [ ] **Step 7: Create JP rates** (higher Full Code default; DNAR culture, comfort documented differently)

```yaml
# clinosim/locale/jp/code_status_rates.yaml
weights:
  routine:
    "0-49":   [0.995, 0.005, 0.00, 0.00]
    "50-69":  [0.98, 0.015, 0.003, 0.002]
    "70-84":  [0.90, 0.07, 0.02, 0.01]
    "85-120": [0.78, 0.14, 0.05, 0.03]
  icu:
    "0-49":   [0.97, 0.02, 0.005, 0.005]
    "50-69":  [0.92, 0.05, 0.02, 0.01]
    "70-84":  [0.72, 0.16, 0.07, 0.05]
    "85-120": [0.55, 0.22, 0.12, 0.11]
  terminal:
    "0-49":   [0.62, 0.20, 0.08, 0.10]
    "50-69":  [0.48, 0.24, 0.10, 0.18]
    "70-84":  [0.28, 0.28, 0.14, 0.30]
    "85-120": [0.15, 0.27, 0.16, 0.42]
```

- [ ] **Step 8: Run, verify pass** — `pytest tests/unit/test_code_status_data.py -v` → PASS.

- [ ] **Step 9: Commit** — `git add clinosim/types/output.py clinosim/modules/code_status/ clinosim/locale/us/code_status_rates.yaml clinosim/locale/jp/code_status_rates.yaml tests/unit/test_code_status_data.py && git commit -m "feat(code-status): CIF field + reference/rate data"`

---

### Task 2: Assignment engine (TDD)

**Files:**
- Create: `clinosim/modules/code_status/engine.py`
- Test: `tests/unit/test_code_status_engine.py`

**Interfaces:**
- Produces:
  - `load_reference() -> dict`, `load_rates(country) -> dict`
  - `assign_code_status(age: int, context: str, country: str, rng: np.random.Generator) -> str` (returns the SNOMED code of the sampled tier)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_code_status_engine.py
import numpy as np, pytest
from clinosim.modules.code_status.engine import assign_code_status, load_reference

pytestmark = pytest.mark.unit
_TIERS = {t["key"]: t["snomed"] for t in load_reference()["tiers"]}
_FULL = _TIERS["full_code"]

def _rate_non_full(age, context, country="US", n=600):
    nf = 0
    for s in range(n):
        if assign_code_status(age, context, country, np.random.default_rng(s)) != _FULL:
            nf += 1
    return nf / n

def test_returns_valid_snomed():
    code = assign_code_status(80, "icu", "US", np.random.default_rng(1))
    assert code in set(_TIERS.values())

def test_deterministic():
    a = assign_code_status(80, "terminal", "US", np.random.default_rng(3))
    b = assign_code_status(80, "terminal", "US", np.random.default_rng(3))
    assert a == b

def test_terminal_more_non_full_than_routine():
    assert _rate_non_full(80, "terminal") > _rate_non_full(80, "routine")

def test_elderly_more_non_full_than_young_routine():
    assert _rate_non_full(90, "routine") > _rate_non_full(30, "routine")

def test_jp_routine_more_full_code_than_us():
    # JP routine has higher Full Code default at the same age band.
    assert _rate_non_full(75, "routine", "JP") < _rate_non_full(75, "routine", "US")
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_code_status_engine.py -v` → FAIL.

- [ ] **Step 3: Implement the engine**

```python
# clinosim/modules/code_status/engine.py
"""Code status (resuscitation status) assignment (AD-55 Base). Pure + seeded."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

_HERE = Path(__file__).resolve().parent
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=1)
def load_reference() -> dict:
    with open(_HERE / "reference_data" / "code_status.yaml") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=4)
def load_rates(country: str) -> dict:
    key = "jp" if str(country).upper() == "JP" else "us"
    with open(_LOCALE / key / "code_status_rates.yaml") as f:
        return (yaml.safe_load(f) or {}).get("weights", {})


def _age_band(age: int, bands: list[str]) -> str:
    for band in bands:
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return band
    return bands[-1]


def assign_code_status(age: int, context: str, country: str,
                       rng: np.random.Generator) -> str:
    """Return the SNOMED code of the sampled tier for (age, context).

    context: "routine" | "icu" | "terminal". Deterministic for a given rng.
    """
    ref = load_reference()
    rates = load_rates(country)
    tiers = ref["tiers"]
    band = _age_band(int(age), ref["age_bands"])
    weights = rates.get(context, rates["routine"]).get(band)
    if not weights:
        weights = rates["routine"][ref["age_bands"][-1]]
    idx = int(rng.choice(len(tiers), p=weights))
    return str(tiers[idx]["snomed"])
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/unit/test_code_status_engine.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add clinosim/modules/code_status/engine.py tests/unit/test_code_status_engine.py && git commit -m "feat(code-status): seeded assignment engine"`

---

### Task 3: SNOMED codes (verify + add)

**Files:**
- Modify: `clinosim/codes/data/snomed-ct.yaml`
- (possibly) Modify: `clinosim/modules/code_status/reference_data/code_status.yaml` (correct any code that verification changes)
- Test: `tests/unit/test_code_status_codes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_code_status_codes.py
import pytest
from clinosim.codes import lookup
from clinosim.modules.code_status.engine import load_reference

pytestmark = pytest.mark.unit

def test_all_tier_codes_resolve():
    ref = load_reference()
    for t in ref["tiers"]:
        disp = lookup("snomed-ct", t["snomed"], "en")
        assert disp and disp != t["snomed"]
    assert lookup("snomed-ct", ref["observable_snomed"], "en")
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_code_status_codes.py -v` → FAIL (codes not in snomed-ct.yaml).

- [ ] **Step 3: Verify + add codes** — query the Snowstorm public API for each candidate, e.g.:

```bash
curl -s "https://browser.ihtsdotools.org/snowstorm/snomed-ct/MAIN/concepts/304252001" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pt',{}).get('term'))"
```

For each of `304251008` (observable), `304252001`, `304253006`, `103735009`, and the DNR+DNI concept: confirm the preferred term. If a candidate is wrong or has no clean concept (likely DNR+DNI), pick the closest authoritative concept and keep a `# TODO: verify` comment in both `snomed-ct.yaml` and `code_status.yaml`. Then add to `codes/data/snomed-ct.yaml` under `codes:` (EN + JA), e.g.:

```yaml
  # === Resuscitation / code status (AD-55 Base) ===
  "304251008": {en: "Resuscitation status", ja: "蘇生ステータス"}
  "304252001": {en: "For resuscitation", ja: "蘇生処置を行う"}
  "304253006": {en: "Not for resuscitation", ja: "蘇生処置を行わない（DNAR）"}
  "103735009": {en: "Palliative care", ja: "緩和ケア"}
```

(If DNR+DNI keeps `304253006`, the tier display still differs via `code_status.yaml`; the FHIR value coding uses the SNOMED PT. Document the DNI limitation in a comment.)

- [ ] **Step 4: Run, verify pass** — `pytest tests/unit/test_code_status_codes.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add clinosim/codes/data/snomed-ct.yaml clinosim/modules/code_status/reference_data/code_status.yaml tests/unit/test_code_status_codes.py && git commit -m "feat(codes): SNOMED resuscitation-status codes for code status"`

---

### Task 4: Enricher wiring (post_records, encounter gate, encounter sub-seed)

**Files:**
- Create: `clinosim/modules/code_status/enricher.py`
- Modify: `clinosim/simulator/enrichers.py`
- Test: `tests/integration/test_code_status_enricher.py`

**Interfaces:**
- Produces: each qualifying record gets `record.code_status = <snomed>`; others stay `""`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_code_status_enricher.py
import pytest
from clinosim.modules.code_status.enricher import enrich_code_status

pytestmark = pytest.mark.integration

class _Ctx:
    def __init__(self, records, country="US"):
        self.config = type("C", (), {"country": country})()
        self.master_seed = 42
        self.population = None
        self.records = records

def _rec(eid, etype, age, deceased=False, icu=False):
    return {"patient": {"patient_id": "P", "age": age},
            "encounters": [{"encounter_id": eid, "encounter_type": etype}],
            "deceased": deceased, "icu_transferred": icu}

def test_inpatient_always_assigned():
    r = _rec("E1", "inpatient", 70)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"]

def test_outpatient_never_assigned():
    r = _rec("E2", "outpatient", 70)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"] == ""

def test_ed_routine_not_assigned():
    r = _rec("E3", "emergency", 70)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"] == ""

def test_ed_terminal_assigned():
    r = _rec("E4", "emergency", 70, deceased=True)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"]

def test_stable_for_encounter():
    r1, r2 = _rec("E5", "inpatient", 80), _rec("E5", "inpatient", 80)
    enrich_code_status(_Ctx([r1, r2]))
    assert r1["code_status"] == r2["code_status"]
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/integration/test_code_status_enricher.py -v` → FAIL.

- [ ] **Step 3: Implement the enricher**

```python
# clinosim/modules/code_status/enricher.py
"""Code status enricher (AD-55 Base, AD-56 post_records).

Seeded by encounter_id so the value is stable within an encounter and the main
simulation stream is untouched (AD-16). Assigned only to serious encounters.
"""
from __future__ import annotations

import numpy as np

from clinosim.modules.code_status.engine import assign_code_status
from clinosim.simulator.seeding import derive_sub_seed

_CS_SEED_OFFSET = 0x4353  # "CS"


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _qualifies(encounter_type: str, deceased: bool, icu: bool) -> bool:
    if encounter_type == "inpatient":
        return True
    if encounter_type == "emergency":
        return bool(deceased or icu)
    return False


def enrich_code_status(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        encs = _get(rec, "encounters", []) or []
        enc = encs[0] if encs else None
        etype = _get(enc, "encounter_type", "") if enc else ""
        eid = _get(enc, "encounter_id", "") if enc else ""
        deceased = bool(_get(rec, "deceased", False))
        icu = bool(_get(rec, "icu_transferred", False))
        code = ""
        if eid and _qualifies(etype, deceased, icu):
            patient = _get(rec, "patient")
            age = int(_get(patient, "age", 0) or 0) if patient else 0
            context = "terminal" if deceased else ("icu" if icu else "routine")
            rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, _CS_SEED_OFFSET, eid))
            code = assign_code_status(age, context, country, rng)
        if isinstance(rec, dict):
            rec["code_status"] = code
        else:
            rec.code_status = code
```

- [ ] **Step 4: Register the enricher** — in `clinosim/simulator/enrichers.py` `register_builtin_enrichers()`, after the family_history block:

```python
    # Code status (AD-55 Base): resuscitation status on serious encounters. Always-on.
    from clinosim.modules.code_status.enricher import enrich_code_status

    register_enricher(
        Enricher(
            name="code_status",
            stage=POST_RECORDS,
            order=50,
            enabled=lambda c: True,
            run=enrich_code_status,
        )
    )
```

- [ ] **Step 5: Run, verify pass** — `pytest tests/integration/test_code_status_enricher.py -v` → PASS.

- [ ] **Step 6: Commit** — `git add clinosim/modules/code_status/enricher.py clinosim/simulator/enrichers.py tests/integration/test_code_status_enricher.py && git commit -m "feat(code-status): post_records enricher (encounter gate + sub-seed)"`

---

### Task 5: FHIR Observation builder

**Files:**
- Create: `clinosim/modules/output/_fhir_code_status.py`
- Modify: `clinosim/modules/output/fhir_r4_adapter.py` (facade import + `_BUNDLE_BUILDERS`)
- Test: `tests/integration/test_fhir_code_status.py`

**Interfaces:**
- Produces: `_build_code_status(ctx: BundleContext) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_fhir_code_status.py
import pytest
from clinosim.modules.output.fhir_r4_adapter import BundleContext, _build_code_status

pytestmark = pytest.mark.integration

def _ctx(code="304253006", country="US"):
    return BundleContext(record={"code_status": code,
                                 "encounters": [{"encounter_id": "enc-1",
                                                 "admission_datetime": "2026-05-01T09:00:00"}]},
                         country=country, roster_map={}, hospital_config={}, patient_data={},
                         patient_id="pat-1", is_readmission=False, prior_encounter_id=None,
                         primary_dx_code="", admit_dx_code="", admit_dx_system="icd-10-cm",
                         primary_enc_id="enc-1", patient_sex="male")

def test_builds_observation():
    res = _build_code_status(_ctx())
    assert len(res) == 1
    o = res[0]
    assert o["resourceType"] == "Observation"
    assert o["status"] == "final"
    assert o["category"][0]["coding"][0]["code"] == "survey"
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "304253006"
    assert o["encounter"] == {"reference": "Encounter/enc-1"}

def test_empty_when_no_code_status():
    ctx = _ctx(code="")
    assert _build_code_status(ctx) == []
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/integration/test_fhir_code_status.py -v` → FAIL.

- [ ] **Step 3: Implement the builder**

```python
# clinosim/modules/output/_fhir_code_status.py
"""FHIR code-status (resuscitation status) Observation builder (AD-55 Base)."""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, lookup as code_lookup
from clinosim.modules.code_status.engine import load_reference
from clinosim.modules.output._fhir_common import BundleContext, _survey_category


def _build_code_status(ctx: BundleContext) -> list[dict]:
    code = ctx.record.get("code_status") or ""
    if not code:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    enc = ctx.primary_enc_id
    observable = load_reference()["observable_snomed"]
    snomed_uri = get_system_uri("snomed-ct")

    def _coding(c: str) -> dict[str, Any]:
        d: dict[str, Any] = {"system": snomed_uri, "code": c}
        disp = code_lookup("snomed-ct", c, lang)
        if disp and disp != c:
            d["display"] = disp
        return d

    encs = ctx.record.get("encounters") or []
    admit = encs[0].get("admission_datetime") if encs else None
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"codestatus-{enc or ctx.patient_id}",
        "status": "final",
        "category": _survey_category(),
        "code": {"coding": [_coding(observable)]},
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        "valueCodeableConcept": {"coding": [_coding(code)]},
    }
    if enc:
        obs["encounter"] = {"reference": f"Encounter/{enc}"}
    if isinstance(admit, str):
        obs["effectiveDateTime"] = admit
    return [obs]
```

- [ ] **Step 4: Register the builder** — in `fhir_r4_adapter.py`, add the facade import beside the other `_fhir_*` builder imports and append to `_BUNDLE_BUILDERS`:

```python
from clinosim.modules.output._fhir_code_status import _build_code_status  # noqa: F401
```
```python
    _build_family_history,
    _build_code_status,
```

- [ ] **Step 5: Run, verify pass** — `pytest tests/integration/test_fhir_code_status.py -v` → PASS; `grep -n '"system": "http' clinosim/modules/output/_fhir_code_status.py` → none (URIs via get_system_uri).

- [ ] **Step 6: Commit** — `git add clinosim/modules/output/_fhir_code_status.py clinosim/modules/output/fhir_r4_adapter.py tests/integration/test_fhir_code_status.py && git commit -m "feat(fhir): code-status Observation builder"`

---

### Task 6: CSV output

**Files:**
- Modify: `clinosim/modules/output/csv_adapter.py`
- Test: `tests/unit/test_code_status_csv.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_code_status_csv.py
import csv, json, os, pytest
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
pytestmark = pytest.mark.unit

def _write_cif(cif_dir, record):
    pdir = os.path.join(cif_dir, "structural", "patients"); os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "P1.json"), "w") as f: json.dump(record, f)

def test_code_status_csv_written(tmp_path):
    cif, out = str(tmp_path / "cif"), str(tmp_path / "out")
    _write_cif(cif, {"patient": {"patient_id": "P1"},
                     "encounters": [{"encounter_id": "E1", "encounter_type": "inpatient"}],
                     "code_status": "304253006"})
    convert_cif_to_csv(cif, out, country="US")
    path = os.path.join(out, "code_status.csv")
    assert os.path.exists(path)
    rows = list(csv.DictReader(open(path)))
    assert rows[0]["patient_id"] == "P1" and rows[0]["code"] == "304253006"
    assert rows[0]["encounter_id"] == "E1"
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/unit/test_code_status_csv.py -v` → FAIL.

- [ ] **Step 3: Implement** — add `cs_rows: list[dict] = []` near the other row lists; in the per-record loop (after the family-history block) append one row when `code_status` is set; add the write call:

```python
        # Code status (one row per qualifying encounter)
        cs = record.get("code_status")
        if cs:
            enc0 = (record.get("encounters") or [{}])[0]
            cs_rows.append({"patient_id": patient_id,
                            "encounter_id": enc0.get("encounter_id", ""),
                            "code": cs,
                            "display": code_lookup("snomed-ct", cs, "en")})
```

(Use the module's existing display-lookup helper if present; else import `from clinosim.codes import lookup as code_lookup` at the top of csv_adapter.py.) Add `_write_csv(os.path.join(output_dir, "code_status.csv"), cs_rows)` to the write block.

- [ ] **Step 4: Run, verify pass** — `pytest tests/unit/test_code_status_csv.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add clinosim/modules/output/csv_adapter.py tests/unit/test_code_status_csv.py && git commit -m "feat(csv): code_status.csv output"`

---

### Task 7: Determinism + audit + README

**Files:**
- Create: `clinosim/modules/code_status/README.md`

- [ ] **Step 1: byte-diff** — generate US `-p 3000 -s 99` on `master` and on the branch; `diff -rq` the `fhir_r4/` trees. Expected: only `Observation.ndjson` differs (the new code-status Observations); all other resources byte-identical. If anything else differs, the sub-seed leaked — fix.

- [ ] **Step 2: Confirm only code-status Observations changed** — load both `Observation.ndjson`, assert the id-set delta is exactly the `codestatus-*` ids and no pre-existing Observation changed.

- [ ] **Step 3: Generation audit** — over CIF: tier distribution overall and by context/age; confirm Full Code dominant overall, DNR/Comfort concentrated in elderly + ICU/terminal; outpatient encounters have empty code_status; ED non-critical empty.

- [ ] **Step 4: Write the module README** — `clinosim/modules/code_status/README.md` (Japanese w/ English terms): purpose, encounter gate, data files, `assign_code_status` API, enricher stage/seed, FHIR/CSV outputs, dependencies.

- [ ] **Step 5: Full suite** — `pytest -m unit -q`, `pytest -m integration -q`, `pytest -m e2e -q` green (e2e golden: code status adds a new Observation type + a CIF key; inspect any golden change and confirm intended).

- [ ] **Step 6: Commit + PR** — README commit; push; open PR with the audit (tier distribution, byte-diff result).
