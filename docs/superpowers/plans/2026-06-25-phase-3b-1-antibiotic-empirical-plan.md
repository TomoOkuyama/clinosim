# Phase 3b-1 — HAI Empirical Antibiotic Regimen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `modules/antibiotic/` opt-in Module that consumes `extensions["hai"]` and emits IDSA guideline empirical antibiotic regimens (CLABSI / CAUTI / VAP) as MedicationRequest + MedicationAdministration via the existing FHIR builder, while writing `extensions["antibiotic"] = list[AntibioticRegimen]` for cross-PR consumption by PR3b-2/3/4.

**Architecture:** New `POST_ENCOUNTER` enricher (order=85, after `hai=80`) walks `extensions["hai"]`, for each HAI event constructs a per-HAI-type empirical regimen from `hai_empirical.yaml`, appends `Order(OrderType.MEDICATION)` to `record.orders` + daily `MedicationAdministration` to `record.medication_administrations`, and writes `extensions["antibiotic"]`. Zero new FHIR builders. AD-60 audit plug-in includes a `lift_firing_proof` synthetic-record check (PR-90 silent-no-op gate).

**Tech Stack:** Python 3.11 + Pydantic + dataclass + numpy.random.Generator + pyyaml + pytest (unit + integration markers).

## Global Constraints

- Python 3.11+, mypy strict, ruff, line length 100.
- All data types in `clinosim/types/` — never inside module code (CLAUDE.md).
- All codes referenced via `clinosim/codes/data/*.yaml`; display via `clinosim.codes.lookup()`.
- Determinism (AD-16): per-patient sub-rng via `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["antibiotic"], pid)`; never use `random.random()` or shared global state.
- Modules MUST NOT edit `CIFPatientRecord` typed fields beyond appending to existing Base typed fields. Module-internal state goes under `extensions["antibiotic"]`.
- canonical string constants in `module/__init__.py`; YAML loader cross-validates at import time (`ValueError` on mismatch). PR-90 教訓 = single source of truth.
- Authoritative code source mandatory (NLM RxNav for RxNorm, MEDIS-DC HOT/YJ master for YJ). Never fabricate codes; if `# TODO: verify` ever lands in a commit, the impl is wrong.
- All commits include `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` and `Claude-Session:` trailer.

---

## File Structure

**Create:**
- `clinosim/types/antibiotic.py` — `AntibioticRegimen` dataclass
- `clinosim/modules/antibiotic/__init__.py` — `ANTIBIOTIC_DRUGS` canonical tuple
- `clinosim/modules/antibiotic/engine.py` — pure functions (`load_hai_empirical`, `build_regimens`, `generate_mar_doses`)
- `clinosim/modules/antibiotic/enricher.py` — `enrich_antibiotic(ctx)` (POST_ENCOUNTER)
- `clinosim/modules/antibiotic/audit.py` — AD-60 plug-in
- `clinosim/modules/antibiotic/reference_data/hai_empirical.yaml` — IDSA guideline regimens
- `clinosim/modules/antibiotic/README.md` — JP, template-conformant
- `tests/unit/test_antibiotic_engine.py`
- `tests/unit/test_antibiotic_yaml_loader.py`
- `tests/integration/test_antibiotic_forced_e2e.py`
- `tests/integration/test_antibiotic_audit.py`
- `docs/reviews/2026-06-25-phase-3b-1-antibiotic-empirical-data-quality-review.md`

**Modify:**
- `clinosim/simulator/seeding.py` — add `"antibiotic": 0x4142` to `ENRICHER_SEED_OFFSETS`
- `clinosim/simulator/enrichers.py` — register `enrich_antibiotic` (POST_ENCOUNTER, order=85, opt-in via `c.modules.get("antibiotic", False)`)
- `clinosim/codes/data/rxnorm.yaml` — add Vancomycin entry (authoritative CUI)
- `clinosim/codes/data/yj.yaml` — add Vancomycin entry (authoritative YJ)
- `clinosim/locale/us/code_mapping_drug.yaml` — `Vancomycin: "<CUI>"`
- `clinosim/locale/jp/code_mapping_drug.yaml` — `Vancomycin: "<YJ>"`
- `MODULES.md` — add `antibiotic` row, bump module count
- `TODO.md` — mark Phase 3b-1 complete + queue PR3b-2/3/4
- `DESIGN.md` — AD-55 Module roadmap progress note (no new AD)
- `CLAUDE.md` — add Phase 3b-1 antibiotic pattern note if needed
- `.github/TEMPLATE_MODULE_README.md` — no change (already covers Audit section)

**No change but referenced:**
- `clinosim/types/encounter.py:Order, OrderType, MedicationAdministration`
- `clinosim/types/hai.py:HAIEvent`
- `clinosim/types/output.py:CIFPatientRecord` (extensions dict consumed)
- `clinosim/modules/output/_fhir_medications.py` (builder, untouched — re-exercised by new orders/MAR)
- `clinosim/audit/registry.py:ModuleAuditSpec` (consumed)

---

## Task 1: AntibioticRegimen type + ANTIBIOTIC_DRUGS canonical

**Files:**
- Create: `clinosim/types/antibiotic.py`
- Create: `clinosim/modules/antibiotic/__init__.py`
- Test: `tests/unit/test_antibiotic_types.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `clinosim.types.antibiotic.AntibioticRegimen` (dataclass with 10 fields below)
  - `clinosim.modules.antibiotic.ANTIBIOTIC_DRUGS: tuple[str, ...] = ("Vancomycin", "Piperacillin/Tazobactam", "Ceftriaxone")`

- [ ] **Step 1: Write failing test for AntibioticRegimen instantiation**

Create `tests/unit/test_antibiotic_types.py`:
```python
"""Unit tests for AntibioticRegimen and canonical ANTIBIOTIC_DRUGS."""
from datetime import datetime

import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.types.antibiotic import AntibioticRegimen


@pytest.mark.unit
def test_antibiotic_drugs_canonical_tuple():
    assert isinstance(ANTIBIOTIC_DRUGS, tuple)
    assert ANTIBIOTIC_DRUGS == ("Vancomycin", "Piperacillin/Tazobactam", "Ceftriaxone")


@pytest.mark.unit
def test_antibiotic_regimen_defaults():
    r = AntibioticRegimen()
    assert r.regimen_id == ""
    assert r.hai_event_id == ""
    assert r.encounter_id == ""
    assert r.drug_key == ""
    assert r.dose == ""
    assert r.route == ""
    assert r.frequency == ""
    assert r.start_datetime == datetime(1970, 1, 1)
    assert r.duration_days == 0
    assert r.intent == "empirical"


@pytest.mark.unit
def test_antibiotic_regimen_full_construction():
    r = AntibioticRegimen(
        regimen_id="abx-h1-vancomycin",
        hai_event_id="h1",
        encounter_id="enc-1",
        drug_key="Vancomycin",
        dose="1g",
        route="IV",
        frequency="q12h",
        start_datetime=datetime(2026, 1, 10, 8, 0),
        duration_days=14,
        intent="empirical",
    )
    assert r.drug_key == "Vancomycin"
    assert r.duration_days == 14
    assert r.intent == "empirical"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_antibiotic_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clinosim.modules.antibiotic'`

- [ ] **Step 3: Implement AntibioticRegimen**

Create `clinosim/types/antibiotic.py`:
```python
"""Antibiotic regimens generated by modules/antibiotic for HAI events (PR3b-1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AntibioticRegimen:
    """One empirical antibiotic regimen attached to a single HAI event.

    Stored as list[AntibioticRegimen] under
    CIFPatientRecord.extensions["antibiotic"]. The hai_event_id field
    links each regimen back to the HAIEvent (extensions["hai"]) that
    triggered it — this is the cross-module consumption point for
    PR3b-2 (S/I/R), PR3b-3 (narrow), and PR3b-4 (WBC/CRP decay).
    """

    regimen_id: str = ""
    hai_event_id: str = ""
    encounter_id: str = ""
    drug_key: str = ""  # canonical name in modules.antibiotic.ANTIBIOTIC_DRUGS
    dose: str = ""  # e.g. "1g", "3.375g"
    route: str = ""  # "IV" for PR3b-1
    frequency: str = ""  # "q12h" / "q6h" / "q24h"
    start_datetime: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    duration_days: int = 0
    intent: str = "empirical"  # "empirical" | "narrowed" (PR3b-3 reserves)
```

- [ ] **Step 4: Implement ANTIBIOTIC_DRUGS canonical**

Create `clinosim/modules/antibiotic/__init__.py`:
```python
"""modules/antibiotic — HAI empirical antibiotic regimens (PR3b-1).

Single source of truth for antibiotic drug names. The hai_empirical.yaml
loader validates all drug_key strings against this tuple at import time
to surface case-mismatch / typo class of bugs (PR-90 教訓).
"""
ANTIBIOTIC_DRUGS: tuple[str, ...] = (
    "Vancomycin",
    "Piperacillin/Tazobactam",
    "Ceftriaxone",
)
```

- [ ] **Step 5: Create empty reference_data dir + module skeleton**

```bash
mkdir -p clinosim/modules/antibiotic/reference_data
touch clinosim/modules/antibiotic/reference_data/.gitkeep
```

- [ ] **Step 6: Run test to verify pass**

Run: `pytest tests/unit/test_antibiotic_types.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run lints**

```bash
ruff check clinosim/types/antibiotic.py clinosim/modules/antibiotic/__init__.py tests/unit/test_antibiotic_types.py
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add clinosim/types/antibiotic.py clinosim/modules/antibiotic/__init__.py clinosim/modules/antibiotic/reference_data/.gitkeep tests/unit/test_antibiotic_types.py
git commit -m "$(cat <<'EOF'
feat(types): AntibioticRegimen + ANTIBIOTIC_DRUGS canonical (Phase 3b-1 Task 1)

PR3b-1 foundation. AntibioticRegimen is the typed value held under
CIFPatientRecord.extensions["antibiotic"]; hai_event_id is the
cross-module consumption point for PR3b-2/3/4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 2: hai_empirical.yaml + loader with import-time validation

**Files:**
- Create: `clinosim/modules/antibiotic/reference_data/hai_empirical.yaml`
- Modify: `clinosim/modules/antibiotic/engine.py` (new file)
- Test: `tests/unit/test_antibiotic_yaml_loader.py`

**Interfaces:**
- Consumes: `ANTIBIOTIC_DRUGS` from Task 1, `HAI_TYPES` from `clinosim.modules.hai`
- Produces:
  - `engine.load_hai_empirical() -> dict[str, dict]` — `{hai_type: {duration_days, drugs: [{drug_key, dose, route, frequency}, ...]}}`
  - import-time `ValueError` if YAML keys violate `HAI_TYPES` or any `drug_key` not in `ANTIBIOTIC_DRUGS`

- [ ] **Step 1: Write failing test for valid YAML load**

Create `tests/unit/test_antibiotic_yaml_loader.py`:
```python
"""Unit tests for hai_empirical.yaml loader + import-time validation."""
import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.engine import load_hai_empirical
from clinosim.modules.hai import HAI_TYPES


@pytest.mark.unit
def test_load_hai_empirical_returns_dict_keyed_by_hai_type():
    data = load_hai_empirical()
    assert set(data.keys()) == set(HAI_TYPES)


@pytest.mark.unit
def test_load_hai_empirical_clabsi_idsa_2009():
    data = load_hai_empirical()
    clabsi = data["clabsi"]
    assert clabsi["duration_days"] == 14
    drugs = {d["drug_key"]: d for d in clabsi["drugs"]}
    assert set(drugs.keys()) == {"Vancomycin", "Piperacillin/Tazobactam"}
    assert drugs["Vancomycin"]["dose"] == "1g"
    assert drugs["Vancomycin"]["route"] == "IV"
    assert drugs["Vancomycin"]["frequency"] == "q12h"
    assert drugs["Piperacillin/Tazobactam"]["dose"] == "3.375g"
    assert drugs["Piperacillin/Tazobactam"]["frequency"] == "q6h"


@pytest.mark.unit
def test_load_hai_empirical_cauti_idsa_2009():
    data = load_hai_empirical()
    cauti = data["cauti"]
    assert cauti["duration_days"] == 7
    assert len(cauti["drugs"]) == 1
    assert cauti["drugs"][0]["drug_key"] == "Ceftriaxone"
    assert cauti["drugs"][0]["frequency"] == "q24h"
    assert cauti["drugs"][0]["dose"] == "1g"


@pytest.mark.unit
def test_load_hai_empirical_vap_idsa_2016():
    data = load_hai_empirical()
    vap = data["vap"]
    assert vap["duration_days"] == 7
    drug_keys = {d["drug_key"] for d in vap["drugs"]}
    assert drug_keys == {"Vancomycin", "Piperacillin/Tazobactam"}


@pytest.mark.unit
def test_load_hai_empirical_all_drug_keys_canonical():
    data = load_hai_empirical()
    for hai_type, cfg in data.items():
        for drug in cfg["drugs"]:
            assert drug["drug_key"] in ANTIBIOTIC_DRUGS, (
                f"{hai_type}: {drug['drug_key']!r} not in canonical "
                f"ANTIBIOTIC_DRUGS {ANTIBIOTIC_DRUGS}"
            )


@pytest.mark.unit
def test_unknown_hai_key_raises_value_error(tmp_path, monkeypatch):
    """YAML with an HAI key not in HAI_TYPES must raise at load time."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "hai_empirical:\n"
        "  cauti:\n"
        "    duration_days: 7\n"
        "    drugs: [{drug_key: Ceftriaxone, dose: 1g, route: IV, frequency: q24h}]\n"
        "  bogus_hai:\n"
        "    duration_days: 7\n"
        "    drugs: [{drug_key: Ceftriaxone, dose: 1g, route: IV, frequency: q24h}]\n"
    )
    from clinosim.modules.antibiotic import engine
    engine.load_hai_empirical.cache_clear()
    monkeypatch.setattr(engine, "_HAI_EMPIRICAL_YAML", bad_yaml)
    with pytest.raises(ValueError, match="unknown hai_type"):
        engine.load_hai_empirical()
    engine.load_hai_empirical.cache_clear()


@pytest.mark.unit
def test_unknown_drug_key_raises_value_error(tmp_path, monkeypatch):
    """YAML with a drug_key not in ANTIBIOTIC_DRUGS must raise at load time."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "hai_empirical:\n"
        "  cauti:\n"
        "    duration_days: 7\n"
        "    drugs: [{drug_key: BogusAbx, dose: 1g, route: IV, frequency: q24h}]\n"
    )
    from clinosim.modules.antibiotic import engine
    engine.load_hai_empirical.cache_clear()
    monkeypatch.setattr(engine, "_HAI_EMPIRICAL_YAML", bad_yaml)
    with pytest.raises(ValueError, match="unknown drug_key"):
        engine.load_hai_empirical()
    engine.load_hai_empirical.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_antibiotic_yaml_loader.py -v`
Expected: all FAIL (engine module + YAML missing).

- [ ] **Step 3: Create reference_data/hai_empirical.yaml**

Create `clinosim/modules/antibiotic/reference_data/hai_empirical.yaml`:
```yaml
# IDSA guideline-based empirical antibiotic regimens for HAI (PR3b-1).
#
# Sources (authoritative, never fabricated):
#   CLABSI:  Mermel LA et al. IDSA 2009 Clinical Practice Guidelines for the
#            Diagnosis and Management of Intravascular Catheter-Related Infection.
#            Clin Infect Dis 49(1):1-45. doi:10.1086/599376
#   CAUTI:   Hooton TM et al. IDSA 2009 Diagnosis, Prevention, and Treatment of
#            Catheter-Associated Urinary Tract Infection.
#            Clin Infect Dis 50(5):625-63. doi:10.1086/650482
#   VAP:     Kalil AC et al. IDSA/ATS 2016 Management of Adults With HAP/VAP.
#            Clin Infect Dis 63(5):e61-e111. doi:10.1093/cid/ciw353
#
# Doses use IDSA + UpToDate average adult ICU dosing without renal adjustment
# (PR3b-1 simplification; PR3b-N will add eGFR-based modification).

hai_empirical:
  clabsi:
    duration_days: 14
    drugs:
      - {drug_key: "Vancomycin",              dose: "1g",     route: "IV", frequency: "q12h"}
      - {drug_key: "Piperacillin/Tazobactam", dose: "3.375g", route: "IV", frequency: "q6h"}
  cauti:
    duration_days: 7
    drugs:
      - {drug_key: "Ceftriaxone",             dose: "1g",     route: "IV", frequency: "q24h"}
  vap:
    duration_days: 7
    drugs:
      - {drug_key: "Vancomycin",              dose: "1g",     route: "IV", frequency: "q12h"}
      - {drug_key: "Piperacillin/Tazobactam", dose: "3.375g", route: "IV", frequency: "q6h"}
```

- [ ] **Step 4: Implement engine.load_hai_empirical**

Create `clinosim/modules/antibiotic/engine.py`:
```python
"""Pure functions for the antibiotic module (PR3b-1).

load_hai_empirical reads reference_data/hai_empirical.yaml once and
validates keys against HAI_TYPES + ANTIBIOTIC_DRUGS canonical
constants — surfacing case-mismatch / typo class of bugs at import
time (PR-90 教訓). build_regimens + generate_mar_doses produce the
typed records the enricher attaches to the CIF record.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.hai import HAI_TYPES

_HAI_EMPIRICAL_YAML = Path(__file__).parent / "reference_data" / "hai_empirical.yaml"


@lru_cache(maxsize=1)
def load_hai_empirical() -> dict[str, dict[str, Any]]:
    """Load + validate empirical regimens.

    Returns ``{hai_type: {"duration_days": int, "drugs": [{"drug_key", "dose",
    "route", "frequency"}, ...]}}``. Raises ``ValueError`` at import time if
    keys violate ``HAI_TYPES`` or any drug_key violates ``ANTIBIOTIC_DRUGS``.
    """
    raw = yaml.safe_load(_HAI_EMPIRICAL_YAML.read_text(encoding="utf-8"))
    data = dict(raw["hai_empirical"])

    unknown_hai = set(data) - set(HAI_TYPES)
    if unknown_hai:
        raise ValueError(
            f"hai_empirical.yaml has unknown hai_type keys "
            f"{sorted(unknown_hai)} - must use HAI_TYPES {HAI_TYPES} "
            f"(case-sensitive)"
        )

    for hai_type, cfg in data.items():
        for drug in cfg["drugs"]:
            if drug["drug_key"] not in ANTIBIOTIC_DRUGS:
                raise ValueError(
                    f"hai_empirical.yaml [{hai_type}]: unknown drug_key "
                    f"{drug['drug_key']!r} - must be in canonical "
                    f"ANTIBIOTIC_DRUGS {ANTIBIOTIC_DRUGS}"
                )

    return data
```

- [ ] **Step 5: Run test to verify pass**

Run: `pytest tests/unit/test_antibiotic_yaml_loader.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/antibiotic/reference_data/hai_empirical.yaml clinosim/modules/antibiotic/engine.py tests/unit/test_antibiotic_yaml_loader.py
git rm clinosim/modules/antibiotic/reference_data/.gitkeep
git commit -m "$(cat <<'EOF'
feat(antibiotic): hai_empirical.yaml + import-time validated loader (Task 2)

IDSA 2009/2016 guideline empirical regimens for CLABSI/CAUTI/VAP.
Loader cross-validates YAML keys against modules.hai.HAI_TYPES +
ANTIBIOTIC_DRUGS to gate PR-90 class silent no-op bugs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 3: engine.build_regimens — empirical regimen from HAIEvent

**Files:**
- Modify: `clinosim/modules/antibiotic/engine.py`
- Test: `tests/unit/test_antibiotic_engine.py`

**Interfaces:**
- Consumes: `load_hai_empirical()` from Task 2, `HAIEvent` from `clinosim.types.hai`
- Produces:
  - `engine.build_regimens(hai_event: HAIEvent, start_datetime: datetime) -> list[AntibioticRegimen]`
  - One regimen per drug in the HAI type's empirical config (CLABSI/VAP = 2, CAUTI = 1).
  - `regimen_id = f"abx-{hai_event.hai_id}-{drug_slug}"` where `drug_slug = drug_key.lower().replace("/", "_")`.

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_antibiotic_engine.py`:
```python
"""Unit tests for engine.build_regimens + generate_mar_doses (Phase 3b-1)."""
from datetime import datetime

import pytest

from clinosim.modules.antibiotic.engine import build_regimens
from clinosim.types.hai import HAIEvent


def _make_event(hai_type: str, hai_id: str = "h1", enc_id: str = "enc-1") -> HAIEvent:
    return HAIEvent(
        hai_id=hai_id,
        encounter_id=enc_id,
        hai_type=hai_type,
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-01-10",
        organism_snomed="",
        culture_specimen_id="",
    )


@pytest.mark.unit
def test_build_regimens_cauti_single_drug():
    ev = _make_event("cauti")
    regs = build_regimens(ev, start_datetime=datetime(2026, 1, 10, 8))
    assert len(regs) == 1
    r = regs[0]
    assert r.hai_event_id == "h1"
    assert r.encounter_id == "enc-1"
    assert r.drug_key == "Ceftriaxone"
    assert r.dose == "1g"
    assert r.route == "IV"
    assert r.frequency == "q24h"
    assert r.start_datetime == datetime(2026, 1, 10, 8)
    assert r.duration_days == 7
    assert r.intent == "empirical"
    assert r.regimen_id == "abx-h1-ceftriaxone"


@pytest.mark.unit
def test_build_regimens_clabsi_two_drugs():
    ev = _make_event("clabsi", hai_id="h2")
    regs = build_regimens(ev, start_datetime=datetime(2026, 2, 1, 8))
    drug_keys = {r.drug_key for r in regs}
    assert drug_keys == {"Vancomycin", "Piperacillin/Tazobactam"}
    for r in regs:
        assert r.duration_days == 14
        assert r.start_datetime == datetime(2026, 2, 1, 8)
        assert r.hai_event_id == "h2"
    ids = {r.regimen_id for r in regs}
    assert ids == {"abx-h2-vancomycin", "abx-h2-piperacillin_tazobactam"}


@pytest.mark.unit
def test_build_regimens_vap_two_drugs_7d():
    ev = _make_event("vap", hai_id="h3", enc_id="enc-9")
    regs = build_regimens(ev, start_datetime=datetime(2026, 3, 15, 8))
    assert len(regs) == 2
    for r in regs:
        assert r.duration_days == 7
        assert r.encounter_id == "enc-9"


@pytest.mark.unit
def test_build_regimens_unknown_hai_type_raises():
    ev = _make_event("bogus_hai")
    with pytest.raises(KeyError):
        build_regimens(ev, start_datetime=datetime(2026, 1, 1))
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_antibiotic_engine.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_regimens'`.

- [ ] **Step 3: Implement build_regimens**

Append to `clinosim/modules/antibiotic/engine.py`:
```python
from datetime import datetime  # add to imports

from clinosim.types.antibiotic import AntibioticRegimen
from clinosim.types.hai import HAIEvent


def _drug_slug(drug_key: str) -> str:
    """canonical drug_key -> URL-safe slug for regimen_id."""
    return drug_key.lower().replace("/", "_")


def build_regimens(
    hai_event: HAIEvent,
    start_datetime: datetime,
) -> list[AntibioticRegimen]:
    """Build the empirical regimens for one HAI event.

    Returns one AntibioticRegimen per drug in the HAI type's empirical
    config. Raises ``KeyError`` if hai_event.hai_type is not present
    in hai_empirical.yaml (already gated by load_hai_empirical's
    import-time validation, so this is defense-in-depth).
    """
    cfg = load_hai_empirical()[hai_event.hai_type]
    duration_days = int(cfg["duration_days"])
    out: list[AntibioticRegimen] = []
    for drug in cfg["drugs"]:
        slug = _drug_slug(drug["drug_key"])
        out.append(AntibioticRegimen(
            regimen_id=f"abx-{hai_event.hai_id}-{slug}",
            hai_event_id=hai_event.hai_id,
            encounter_id=hai_event.encounter_id,
            drug_key=drug["drug_key"],
            dose=drug["dose"],
            route=drug["route"],
            frequency=drug["frequency"],
            start_datetime=start_datetime,
            duration_days=duration_days,
            intent="empirical",
        ))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/unit/test_antibiotic_engine.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/antibiotic/engine.py tests/unit/test_antibiotic_engine.py
git commit -m "$(cat <<'EOF'
feat(antibiotic): engine.build_regimens(HAIEvent) -> regimens (Task 3)

Per-drug AntibioticRegimen construction from hai_empirical.yaml. One
regimen per drug in the HAI type config (CLABSI/VAP=2, CAUTI=1).
regimen_id format = abx-{hai_id}-{drug_slug}.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 4: engine.generate_mar_doses — daily MAR with snapshot truncation

**Files:**
- Modify: `clinosim/modules/antibiotic/engine.py`
- Test: extends `tests/unit/test_antibiotic_engine.py`

**Interfaces:**
- Consumes: `AntibioticRegimen` from Task 1, `MedicationAdministration` from `clinosim.types.encounter`
- Produces:
  - `engine.FREQ_PER_DAY: dict[str, int] = {"q24h": 1, "q12h": 2, "q8h": 3, "q6h": 4, "q4h": 6}`
  - `engine.generate_mar_doses(regimen, snapshot_datetime, order_id) -> list[MedicationAdministration]`
  - Each MAR has `scheduled_datetime = regimen.start_datetime + (day * 24h + dose_index * spacing)`.
  - MAR truncated where `scheduled_datetime > snapshot_datetime` (AD-32).

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_antibiotic_engine.py`:
```python
from clinosim.modules.antibiotic.engine import FREQ_PER_DAY, generate_mar_doses
from clinosim.types.antibiotic import AntibioticRegimen


def _ceftriaxone_regimen() -> AntibioticRegimen:
    return AntibioticRegimen(
        regimen_id="abx-h1-ceftriaxone",
        hai_event_id="h1",
        encounter_id="enc-1",
        drug_key="Ceftriaxone",
        dose="1g",
        route="IV",
        frequency="q24h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=7,
        intent="empirical",
    )


@pytest.mark.unit
def test_freq_per_day_table_is_canonical():
    assert FREQ_PER_DAY == {"q24h": 1, "q12h": 2, "q8h": 3, "q6h": 4, "q4h": 6}


@pytest.mark.unit
def test_generate_mar_doses_ceftriaxone_q24h_7days_no_truncation():
    r = _ceftriaxone_regimen()
    snapshot = datetime(2026, 12, 31)
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-1")
    assert len(mars) == 7
    assert mars[0].scheduled_datetime == datetime(2026, 1, 10, 8)
    assert mars[-1].scheduled_datetime == datetime(2026, 1, 16, 8)
    for m in mars:
        assert m.drug_name == "Ceftriaxone"
        assert m.dose == "1g"
        assert m.route == "IV"
        assert m.status == "given"
        assert m.order_id == "o-1"


@pytest.mark.unit
def test_generate_mar_doses_vancomycin_q12h_14days():
    r = AntibioticRegimen(
        regimen_id="abx-h2-vancomycin",
        hai_event_id="h2",
        encounter_id="enc-2",
        drug_key="Vancomycin",
        dose="1g",
        route="IV",
        frequency="q12h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=14,
        intent="empirical",
    )
    snapshot = datetime(2026, 12, 31)
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-2")
    assert len(mars) == 14 * 2
    # Spacing 12h: first two doses at 08:00 and 20:00 of day 0
    assert mars[0].scheduled_datetime == datetime(2026, 1, 10, 8)
    assert mars[1].scheduled_datetime == datetime(2026, 1, 10, 20)
    assert mars[2].scheduled_datetime == datetime(2026, 1, 11, 8)


@pytest.mark.unit
def test_generate_mar_doses_pip_tazo_q6h_14days():
    r = AntibioticRegimen(
        regimen_id="abx-h3-pip",
        hai_event_id="h3",
        encounter_id="enc-3",
        drug_key="Piperacillin/Tazobactam",
        dose="3.375g",
        route="IV",
        frequency="q6h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=14,
        intent="empirical",
    )
    mars = generate_mar_doses(r, snapshot_datetime=datetime(2026, 12, 31), order_id="o-3")
    assert len(mars) == 14 * 4
    # 4 doses on day 0 at 08, 14, 20, 02 (next day)
    assert mars[0].scheduled_datetime == datetime(2026, 1, 10, 8)
    assert mars[1].scheduled_datetime == datetime(2026, 1, 10, 14)
    assert mars[2].scheduled_datetime == datetime(2026, 1, 10, 20)
    assert mars[3].scheduled_datetime == datetime(2026, 1, 11, 2)


@pytest.mark.unit
def test_generate_mar_doses_snapshot_truncates():
    r = _ceftriaxone_regimen()  # 7 days starting 2026-01-10 08:00
    snapshot = datetime(2026, 1, 13, 0)  # mid-day 3 → only 3 doses fit (10/11/12 at 08:00)
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-1")
    assert len(mars) == 3
    assert mars[-1].scheduled_datetime == datetime(2026, 1, 12, 8)


@pytest.mark.unit
def test_generate_mar_doses_unknown_frequency_raises():
    r = _ceftriaxone_regimen()
    r.frequency = "q99h"
    with pytest.raises(KeyError):
        generate_mar_doses(r, snapshot_datetime=datetime(2026, 12, 31), order_id="o-1")
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/unit/test_antibiotic_engine.py -v`
Expected: 4 new tests FAIL.

- [ ] **Step 3: Implement generate_mar_doses**

Append to `clinosim/modules/antibiotic/engine.py`:
```python
from datetime import timedelta  # add to imports

from clinosim.types.encounter import MedicationAdministration


FREQ_PER_DAY: dict[str, int] = {
    "q24h": 1,
    "q12h": 2,
    "q8h":  3,
    "q6h":  4,
    "q4h":  6,
}


def generate_mar_doses(
    regimen: AntibioticRegimen,
    snapshot_datetime: datetime,
    order_id: str,
) -> list[MedicationAdministration]:
    """Materialize per-dose MAR records spanning [start_dt, start_dt + duration_days).

    Doses are evenly spaced (24h / freq_per_day) starting at
    ``regimen.start_datetime``. Doses after ``snapshot_datetime`` are
    truncated (AD-32). Raises ``KeyError`` if ``regimen.frequency``
    is not in ``FREQ_PER_DAY``.
    """
    freq = FREQ_PER_DAY[regimen.frequency]
    spacing = timedelta(hours=24 // freq)
    total_doses = regimen.duration_days * freq
    out: list[MedicationAdministration] = []
    for i in range(total_doses):
        sched = regimen.start_datetime + spacing * i
        if sched > snapshot_datetime:
            break
        out.append(MedicationAdministration(
            order_id=order_id,
            drug_name=regimen.drug_key,
            scheduled_datetime=sched,
            actual_datetime=sched,
            status="given",
            dose=regimen.dose,
            route=regimen.route,
        ))
    return out
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/unit/test_antibiotic_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/antibiotic/engine.py tests/unit/test_antibiotic_engine.py
git commit -m "$(cat <<'EOF'
feat(antibiotic): engine.generate_mar_doses + AD-32 snapshot truncation (Task 4)

Even spacing 24h/freq_per_day from regimen.start_datetime. Doses
after snapshot_datetime truncated (AD-32). Phase 3a-style closed-form
generation enables the lift_firing_proof to assert exact MAR count.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 5: Vancomycin RxNorm + YJ (authoritative lookup)

**Files:**
- Modify: `clinosim/codes/data/rxnorm.yaml`
- Modify: `clinosim/codes/data/yj.yaml`
- Modify: `clinosim/locale/us/code_mapping_drug.yaml`
- Modify: `clinosim/locale/jp/code_mapping_drug.yaml`
- Test: `tests/unit/test_antibiotic_code_lookup.py`

**Interfaces:**
- Consumes: NLM RxNav API + MEDIS-DC HOT/YJ master (out-of-band web verification)
- Produces:
  - `clinosim.codes.lookup("rxnorm", "<CUI>", "en") == "Vancomycin"`
  - `clinosim.codes.lookup("yj", "<YJCODE>", "ja")` returns Japanese display name
  - `load_code_mapping("drug", "US")["Vancomycin"] == "<CUI>"`
  - `load_code_mapping("drug", "JP")["Vancomycin"] == "<YJCODE>"`

- [ ] **Step 1: Authoritative lookup (manual web step)**

```bash
# RxNorm — Vancomycin Injectable Solution (IV form)
curl -s 'https://rxnav.nlm.nih.gov/REST/drugs.json?name=vancomycin' | jq '.drugGroup.conceptGroup[]?.conceptProperties[] | select(.tty=="IN") | {rxcui, name}'
```

Expected (verify before adding):
- `rxcui: "11124", name: "vancomycin"` for the ingredient (IN tty). Use this CUI for the generic ingredient since `_strip_protocol_prefix` + `base_name = drug_name_clean.split(" ")[0]` in `_fhir_medications.py:_build_medication_request` will look up `"Vancomycin"` lemma → CUI.

```bash
# YJ — verify the IV form on MEDIS-DC HOT/YJ master.
# Open https://www2.medis.or.jp/master/mfile/yj/ in a browser and search
# "バンコマイシン塩酸塩 点滴静注". The 12-digit YJ code that begins with
# "6111" (antibiotic class) maps to the parenteral form. Record the exact
# code on the master page before proceeding.
```

Expected: `6111400Dxxxxxxx`-family code. **If you cannot reach an authoritative source for the YJ code, STOP and re-confirm with the user (do NOT fabricate).** Drop the YJ entry and use `# TODO: verify` is NOT an option per spec §3.4.

- [ ] **Step 2: Write failing test**

Create `tests/unit/test_antibiotic_code_lookup.py`:
```python
"""Unit tests for Vancomycin RxNorm + YJ code registration."""
import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_code_mapping


@pytest.mark.unit
def test_vancomycin_rxnorm_lookup_en():
    us_map = load_code_mapping("drug", "US")
    cui = us_map.get("Vancomycin", "")
    assert cui, "Vancomycin missing from code_mapping_drug/us.yaml"
    en = lookup("rxnorm", cui, "en")
    assert en and en != cui
    assert "vancomycin" in en.lower()


@pytest.mark.unit
def test_vancomycin_yj_lookup_ja():
    jp_map = load_code_mapping("drug", "JP")
    yj = jp_map.get("Vancomycin", "")
    assert yj, "Vancomycin missing from code_mapping_drug/jp.yaml"
    ja = lookup("yj", yj, "ja")
    assert ja and ja != yj
    assert "バンコマイシン" in ja or "ヴァンコマイシン" in ja


@pytest.mark.unit
def test_ceftriaxone_pip_tazo_already_mapped_both_locales():
    us_map = load_code_mapping("drug", "US")
    jp_map = load_code_mapping("drug", "JP")
    for drug in ("Ceftriaxone", "Piperacillin/Tazobactam"):
        assert us_map.get(drug), f"{drug} missing from US"
        assert jp_map.get(drug), f"{drug} missing from JP"
```

- [ ] **Step 3: Verify failure**

Run: `pytest tests/unit/test_antibiotic_code_lookup.py -v`
Expected: Vancomycin tests FAIL ("Vancomycin missing from code_mapping_drug/us.yaml"). Ceftriaxone/Pip-Tazo test PASSES.

- [ ] **Step 4: Add Vancomycin to code data + mapping**

Edit `clinosim/codes/data/rxnorm.yaml` (alphabetical insert under `codes:`):
```yaml
  '11124':
    en: Vancomycin
    ja: バンコマイシン
```

Edit `clinosim/codes/data/yj.yaml` (insert with the YJ code obtained in Step 1):
```yaml
  '<VERIFIED_YJ_CODE>':
    en: Vancomycin (Vancocin)
    ja: バンコマイシン塩酸塩（バンコマイシン）
```

Edit `clinosim/locale/us/code_mapping_drug.yaml` under the `# Antibiotics` block:
```yaml
Vancomycin: "11124"
```

Edit `clinosim/locale/jp/code_mapping_drug.yaml` under the antibiotic block:
```yaml
Vancomycin: "<VERIFIED_YJ_CODE>"
```

- [ ] **Step 5: Verify pass**

Run: `pytest tests/unit/test_antibiotic_code_lookup.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run integrity test**

Run: `pytest tests/unit/test_codes_integrity.py -v`
Expected: PASS (last-wins dedup gate must remain clean after the new entries).

- [ ] **Step 7: Commit**

```bash
git add clinosim/codes/data/rxnorm.yaml clinosim/codes/data/yj.yaml clinosim/locale/us/code_mapping_drug.yaml clinosim/locale/jp/code_mapping_drug.yaml tests/unit/test_antibiotic_code_lookup.py
git commit -m "$(cat <<'EOF'
feat(codes): Vancomycin RxNorm + YJ (Task 5)

Sources:
- RxNorm CUI verified via NLM RxNav drugs.json (tty=IN)
- YJ code verified via MEDIS-DC HOT/YJ master (medis.or.jp)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 6: ENRICHER_SEED_OFFSETS antibiotic registration

**Files:**
- Modify: `clinosim/simulator/seeding.py`
- Modify: `tests/unit/test_enricher_seed_offsets.py` (existing, extend with the antibiotic case)

**Interfaces:**
- Consumes: existing `ENRICHER_SEED_OFFSETS` registry
- Produces: `ENRICHER_SEED_OFFSETS["antibiotic"] == 0x4142` (ASCII "AB")

- [ ] **Step 1: Read the existing seeding test**

```bash
cat tests/unit/test_enricher_seed_offsets.py
```
Reuse its style: `@pytest.mark.unit` markers, imports from `clinosim.simulator.seeding`. The file already has `test_no_duplicate_offsets` and `test_all_modules_registered` — extend the latter (or add a sibling) so the new `antibiotic` entry is pinned.

- [ ] **Step 2: Write failing test**

Append to `tests/unit/test_enricher_seed_offsets.py`:
```python
@pytest.mark.unit
def test_antibiotic_offset_registered():
    """PR3b-1 registers ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142 ("AB")."""
    assert ENRICHER_SEED_OFFSETS["antibiotic"] == 0x4142


@pytest.mark.unit
def test_antibiotic_offset_does_not_collide():
    """Antibiotic's 0x4142 ("AB") must not collide with any sibling offset."""
    other_values = {v for k, v in ENRICHER_SEED_OFFSETS.items() if k != "antibiotic"}
    assert 0x4142 not in other_values
```

- [ ] **Step 3: Verify failure**

Run: `pytest tests/unit/test_enricher_seed_offsets.py -v`
Expected: the two new tests FAIL (`KeyError: 'antibiotic'`).

- [ ] **Step 4: Add the registration**

Edit `clinosim/simulator/seeding.py` — locate the `ENRICHER_SEED_OFFSETS` dict (visible in earlier exploration) and add one line:
```python
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,
    "microbiology":   770_077,
    "immunization":   0x494D,
    "code_status":    0x4353,
    "family_history": 0x4648,
    "care_level":     0x434C,
    "nursing":        0x4E55,
    "device":         0x4445,
    "hai":            0x4841,
    "antibiotic":     0x4142,  # "AB" (PR3b-1)
}
```

- [ ] **Step 5: Verify pass**

Run: `pytest tests/unit/test_enricher_seed_offsets.py -v`
Expected: PASS (all existing tests + 2 new pass).

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/seeding.py tests/unit/test_enricher_seed_offsets.py
git commit -m "$(cat <<'EOF'
feat(seeding): ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142 (Task 6)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 7: enricher.enrich_antibiotic + register_builtin_enrichers wiring

**Files:**
- Create: `clinosim/modules/antibiotic/enricher.py`
- Modify: `clinosim/simulator/enrichers.py`
- Test: `tests/unit/test_antibiotic_enricher_unit.py`

**Interfaces:**
- Consumes: `extensions["hai"]: list[HAIEvent]`, `engine.build_regimens`, `engine.generate_mar_doses`, `ENRICHER_SEED_OFFSETS["antibiotic"]`
- Produces:
  - `enricher.enrich_antibiotic(ctx)` — POST_ENCOUNTER stage entry point
  - For each `HAIEvent` in each record's `extensions["hai"]`:
    - Appends 1 `Order(OrderType.MEDICATION)` per regimen drug to `record.orders`
    - Appends N `MedicationAdministration` per regimen to `record.medication_administrations`
    - Appends N `AntibioticRegimen` to `record.extensions["antibiotic"]`
  - Opt-in gated via `c.modules.get("antibiotic", False)` in the `enabled` lambda.
  - `start_datetime = datetime.fromisoformat(hai_event.onset_date).replace(hour=8)`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_antibiotic_enricher_unit.py`:
```python
"""Unit tests for enrich_antibiotic (Phase 3b-1)."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.types.encounter import OrderType
from clinosim.types.hai import HAIEvent


def _make_ctx(hai_events):
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": hai_events},
    )
    cfg = SimpleNamespace(
        country="US",
        snapshot_date=None,
        time_range=("2026-01-01", "2026-12-31"),
    )
    return SimpleNamespace(
        config=cfg,
        master_seed=42,
        records=[rec],
    ), rec


@pytest.mark.unit
def test_enrich_antibiotic_cauti_writes_orders_and_mar():
    ev = HAIEvent(
        hai_id="h1",
        encounter_id="enc-1",
        hai_type="cauti",
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-01-10",
        organism_snomed="",
        culture_specimen_id="",
    )
    ctx, rec = _make_ctx([ev])
    enrich_antibiotic(ctx)
    # 1 MedicationRequest order
    med_orders = [o for o in rec.orders if o.order_type == OrderType.MEDICATION]
    assert len(med_orders) == 1
    assert med_orders[0].display_name == "Ceftriaxone"
    # 7 MAR (q24h × 7d)
    assert len(rec.medication_administrations) == 7
    # extensions["antibiotic"] populated
    assert len(rec.extensions["antibiotic"]) == 1
    r = rec.extensions["antibiotic"][0]
    assert r.drug_key == "Ceftriaxone"
    assert r.hai_event_id == "h1"
    assert r.encounter_id == "enc-1"
    assert r.start_datetime == datetime(2026, 1, 10, 8)


@pytest.mark.unit
def test_enrich_antibiotic_clabsi_emits_two_drugs():
    ev = HAIEvent(
        hai_id="h-clabsi",
        encounter_id="enc-2",
        hai_type="clabsi",
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-02-01",
        organism_snomed="",
        culture_specimen_id="",
    )
    ctx, rec = _make_ctx([ev])
    enrich_antibiotic(ctx)
    med_orders = [o for o in rec.orders if o.order_type == OrderType.MEDICATION]
    assert len(med_orders) == 2
    assert {o.display_name for o in med_orders} == {"Vancomycin", "Piperacillin/Tazobactam"}
    # 14d × (q12h=2 + q6h=4) = 14*2 + 14*4 = 84 MAR
    assert len(rec.medication_administrations) == 84


@pytest.mark.unit
def test_enrich_antibiotic_no_hai_events_no_op():
    ctx, rec = _make_ctx([])
    enrich_antibiotic(ctx)
    assert rec.orders == []
    assert rec.medication_administrations == []
    assert rec.extensions.get("antibiotic", []) == []


@pytest.mark.unit
def test_enrich_antibiotic_missing_extensions_no_crash():
    """A record without extensions["hai"] (e.g. no devices) is a no-op."""
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={},
    )
    cfg = SimpleNamespace(country="US", snapshot_date=None,
                          time_range=("2026-01-01", "2026-12-31"))
    ctx = SimpleNamespace(config=cfg, master_seed=42, records=[rec])
    enrich_antibiotic(ctx)
    assert rec.orders == []
    assert rec.medication_administrations == []
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/unit/test_antibiotic_enricher_unit.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement enricher**

Create `clinosim/modules/antibiotic/enricher.py`:
```python
"""Antibiotic enricher (PR3b-1, POST_ENCOUNTER stage, order=85).

Consumes extensions["hai"] from PR-B. For each HAIEvent, materializes
the IDSA empirical regimen as:
  - 1 Order(MEDICATION) per drug, appended to record.orders, so the
    existing _fhir_medications.py builder emits MedicationRequest.
  - N MedicationAdministration per regimen, appended to
    record.medication_administrations, so the same builder emits MAR.
  - 1 AntibioticRegimen per drug, appended to
    record.extensions["antibiotic"], for PR3b-2/3/4 consumption.

Opt-in: registered with enabled=lambda c: c.modules.get("antibiotic",
False) so existing golden files stay byte-IDENTICAL when the module
is off by default.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.antibiotic.engine import build_regimens, generate_mar_doses
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.hai import HAIEvent


_ORDER_HOUR = 8  # empirical = "AM round" same day as onset


def _resolve_snapshot(cfg) -> datetime:
    """Return the simulation snapshot datetime (AD-32)."""
    snap = _get(cfg, "snapshot_date", None)
    if snap:
        return datetime.fromisoformat(snap)
    # Fall back to end of time_range (existing pattern)
    end = _get(cfg, "time_range", ("2099-12-31",))[-1]
    return datetime.fromisoformat(end)


def enrich_antibiotic(ctx) -> None:
    """POST_ENCOUNTER stage entry point — see module docstring."""
    snapshot = _resolve_snapshot(ctx.config)
    for rec in ctx.records:
        ext = _get(rec, "extensions", {}) or {}
        hai_events: list[HAIEvent] = list(ext.get("hai", []) or [])
        if not hai_events:
            continue
        regimens_out = []
        for ev in hai_events:
            start_dt = datetime.fromisoformat(ev.onset_date).replace(hour=_ORDER_HOUR)
            for regimen in build_regimens(ev, start_datetime=start_dt):
                order_id = f"req-{regimen.regimen_id}"
                order = Order(
                    order_id=order_id,
                    encounter_id=regimen.encounter_id,
                    patient_id=_get(_get(rec, "patient", None), "patient_id", ""),
                    order_type=OrderType.MEDICATION,
                    display_name=regimen.drug_key,
                    ordered_datetime=regimen.start_datetime,
                    status=OrderStatus.ACCEPTED,
                    dose_unit=regimen.dose,
                    frequency=regimen.frequency,
                    route=regimen.route,
                    duration_days=regimen.duration_days,
                    reason_condition=regimen.hai_event_id,
                )
                if isinstance(rec, dict):
                    rec.setdefault("orders", []).append(order)
                else:
                    rec.orders.append(order)
                mars = generate_mar_doses(regimen, snapshot_datetime=snapshot,
                                          order_id=order_id)
                if isinstance(rec, dict):
                    rec.setdefault("medication_administrations", []).extend(mars)
                else:
                    rec.medication_administrations.extend(mars)
                regimens_out.append(regimen)
        if regimens_out:
            if isinstance(rec, dict):
                rec.setdefault("extensions", {}).setdefault("antibiotic", []).extend(regimens_out)
            else:
                rec.extensions.setdefault("antibiotic", []).extend(regimens_out)
```

- [ ] **Step 4: Verify unit pass**

Run: `pytest tests/unit/test_antibiotic_enricher_unit.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire into register_builtin_enrichers**

Edit `clinosim/simulator/enrichers.py` — append after the `hai` registration block:
```python
    # Empirical antibiotic regimen for HAI events (AD-55 Module, PR3b-1).
    # Consumes extensions["hai"] (PR-B output). Opt-in; existing golden
    # files stay byte-IDENTICAL when off by default. Order 85 ensures it
    # runs AFTER hai (80) so extensions["hai"] is populated.
    from clinosim.modules.antibiotic.enricher import enrich_antibiotic

    register_enricher(
        Enricher(
            name="antibiotic",
            stage=POST_ENCOUNTER,
            order=85,
            enabled=lambda c: c.modules.get("antibiotic", False),
            run=enrich_antibiotic,
        )
    )
```

- [ ] **Step 6: Smoke-run the existing test suite to confirm no regression**

Run: `pytest -m unit -x -q`
Expected: PASS (all existing unit tests still green; ours new pass).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/antibiotic/enricher.py clinosim/simulator/enrichers.py tests/unit/test_antibiotic_enricher_unit.py
git commit -m "$(cat <<'EOF'
feat(antibiotic): enrich_antibiotic POST_ENCOUNTER enricher + opt-in registration (Task 7)

Order=85 (after hai=80). Consumes extensions["hai"], dual-writes
record.orders + record.medication_administrations (existing FHIR
builder reuses) + extensions["antibiotic"] (cross-PR consumption).
Opt-in via SimulatorConfig.modules["antibiotic"]; default off
preserves byte-IDENTICAL golden output.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 8: Integration tests — forced scenario + sub-rng + byte-diff invariant

**Files:**
- Create: `tests/integration/test_antibiotic_forced_e2e.py`
- Create: `tests/integration/test_antibiotic_byte_diff.py`

**Interfaces:**
- Consumes: full `run_forced` / `run_beta` path; FHIR adapter; existing `_fhir_medications.py`
- Produces: end-to-end test of the enricher path drive (PR-90 教訓 = don't fixture the enricher; exercise the actual path) + byte-identical guarantee with the module off.

- [ ] **Step 1: Write forced-scenario end-to-end test**

Create `tests/integration/test_antibiotic_forced_e2e.py`:
```python
"""Integration: drive enrich_antibiotic end-to-end via run_forced.

PR-90 教訓: a unit test that constructs a fixture HAIEvent does NOT
prove the enricher path is wired into the run. This test exercises
register_builtin_enrichers + run_forced + opt-in gating + the full
FHIR adapter.
"""
import pytest

from clinosim.simulator.engine import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.fixture
def cauti_forced_scenario():
    return ForcedScenario(
        disease_id="urinary_tract_infection",
        country="US",
        # ICU + Foley placement triggers PR-A device + PR-B hai chain.
        force_icu=True,
        force_indwelling_catheter=True,
        # Lock HAI sampling so a CAUTI event always fires (force_hai True per PR-B)
        force_hai=True,
        force_hai_type="cauti",
        seed=42,
    )


@pytest.mark.integration
def test_antibiotic_opt_in_emits_medications(cauti_forced_scenario):
    cfg = SimulatorConfig(country="US", random_seed=42,
                          modules={"device": True, "hai": True, "antibiotic": True})
    ds = run_forced(cauti_forced_scenario, config=cfg)
    rec = ds.patients[0]
    abx = rec.extensions.get("antibiotic", [])
    assert len(abx) == 1
    assert abx[0].drug_key == "Ceftriaxone"
    assert abx[0].duration_days == 7
    med_orders = [o for o in rec.orders if o.order_type.value == "medication"
                  and o.display_name == "Ceftriaxone"]
    assert len(med_orders) == 1
    cef_mar = [m for m in rec.medication_administrations
               if m.drug_name == "Ceftriaxone"]
    assert len(cef_mar) == 7


@pytest.mark.integration
def test_antibiotic_opt_out_no_op(cauti_forced_scenario):
    cfg = SimulatorConfig(country="US", random_seed=42,
                          modules={"device": True, "hai": True, "antibiotic": False})
    ds = run_forced(cauti_forced_scenario, config=cfg)
    rec = ds.patients[0]
    assert rec.extensions.get("antibiotic", []) == []
    assert not any(m.drug_name == "Ceftriaxone"
                   for m in rec.medication_administrations)


@pytest.mark.integration
def test_antibiotic_determinism_same_seed(cauti_forced_scenario):
    cfg = SimulatorConfig(country="US", random_seed=42,
                          modules={"device": True, "hai": True, "antibiotic": True})
    a = run_forced(cauti_forced_scenario, config=cfg)
    b = run_forced(cauti_forced_scenario, config=cfg)
    abx_a = a.patients[0].extensions["antibiotic"]
    abx_b = b.patients[0].extensions["antibiotic"]
    assert [r.regimen_id for r in abx_a] == [r.regimen_id for r in abx_b]
    assert [m.scheduled_datetime for m in a.patients[0].medication_administrations] == \
           [m.scheduled_datetime for m in b.patients[0].medication_administrations]
```

> **Note for implementer:** If `ForcedScenario` does not currently expose `force_indwelling_catheter` / `force_hai` / `force_hai_type`, check the existing fixture in `tests/integration/test_hai_forced_e2e.py` (PR-90 baseline) and reuse its pattern. The integration test must drive the **real** enricher chain — do not bypass with a synthetic record (this is the PR-90 教訓 in action).

- [ ] **Step 2: Verify failure**

Run: `pytest tests/integration/test_antibiotic_forced_e2e.py -v -m integration`
Expected: tests FAIL (likely because `ForcedScenario` fields missing OR opt-in produces no MAR).

- [ ] **Step 3: If `ForcedScenario` extension needed**

If the existing `ForcedScenario` does not have catheter/HAI force fields, this is a Phase 2 (PR-A/PR-B) baseline assumption that must already be present. Inspect `tests/integration/test_hai_forced_e2e.py` to learn the actual field names; adjust the new test accordingly. **Do not add new fields to `ForcedScenario` in this PR** — the assumption is that PR-A/PR-B already added them. If they did not, downgrade the scope: use a synthetic-record integration test (still exercising `register_builtin_enrichers` + `enrich_antibiotic`) but document the gap with a follow-up TODO in `TODO.md`.

- [ ] **Step 4: Write byte-diff invariant test (opt-out preserves master output)**

Create `tests/integration/test_antibiotic_byte_diff.py`:
```python
"""Byte-diff invariant: antibiotic OFF must produce byte-IDENTICAL FHIR output to baseline.

AD-16 (deterministic) + AD-59 (per-order isolation). Mirrors the
PR-90 baseline test (test_hai_byte_diff if present).
"""
import hashlib
import json
from pathlib import Path

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


def _sha256_fhir_export(ds, tmp_path: Path, label: str) -> dict[str, str]:
    """Run FHIR export via the existing adapter and return resource_type -> sha256."""
    from clinosim.modules.output.fhir_r4_adapter import write_fhir_bulk
    out = tmp_path / label
    out.mkdir()
    write_fhir_bulk(ds, output_dir=out, country=ds.metadata.country)
    hashes = {}
    for ndjson in sorted(out.glob("*.ndjson")):
        hashes[ndjson.name] = hashlib.sha256(ndjson.read_bytes()).hexdigest()
    return hashes


@pytest.mark.integration
def test_antibiotic_off_matches_master_baseline(tmp_path):
    """ant=OFF run must byte-match a run with antibiotic key absent from config."""
    cfg_off = SimulatorConfig(
        country="US", random_seed=42,
        catchment_population=200,
        modules={"device": True, "hai": True, "antibiotic": False},
    )
    cfg_absent = SimulatorConfig(
        country="US", random_seed=42,
        catchment_population=200,
        modules={"device": True, "hai": True},
    )
    a = run_beta(config=cfg_off)
    b = run_beta(config=cfg_absent)
    h_a = _sha256_fhir_export(a, tmp_path, "off")
    h_b = _sha256_fhir_export(b, tmp_path, "absent")
    assert h_a == h_b, f"opt-out absent != opt-out False: {h_a} vs {h_b}"


@pytest.mark.integration
def test_antibiotic_on_delta_limited_to_medication_ndjson(tmp_path):
    """ant=ON delta must affect ONLY MedicationRequest/MedicationAdministration NDJSON."""
    cfg_off = SimulatorConfig(
        country="US", random_seed=42,
        catchment_population=200,
        modules={"device": True, "hai": True, "antibiotic": False},
    )
    cfg_on = SimulatorConfig(
        country="US", random_seed=42,
        catchment_population=200,
        modules={"device": True, "hai": True, "antibiotic": True},
    )
    a = run_beta(config=cfg_off)
    b = run_beta(config=cfg_on)
    h_a = _sha256_fhir_export(a, tmp_path, "off")
    h_b = _sha256_fhir_export(b, tmp_path, "on")
    diffs = {k for k in h_a if h_a.get(k) != h_b.get(k)} | (set(h_b) ^ set(h_a))
    allowed = {"MedicationRequest.ndjson", "MedicationAdministration.ndjson"}
    unexpected = diffs - allowed
    assert not unexpected, f"unexpected NDJSON deltas: {unexpected}"
```

- [ ] **Step 5: Run integration tests**

```bash
pytest tests/integration/test_antibiotic_forced_e2e.py tests/integration/test_antibiotic_byte_diff.py -v -m integration
```
Expected: PASS. If `write_fhir_bulk` signature differs, adapt by matching `tests/integration/test_hai_forced_e2e.py` (the PR-B baseline). Do not invent new APIs.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_antibiotic_forced_e2e.py tests/integration/test_antibiotic_byte_diff.py
git commit -m "$(cat <<'EOF'
test(antibiotic): forced-scenario e2e + byte-diff invariant (Task 8)

forced-scenario test drives register_builtin_enrichers + run_forced
end-to-end (PR-90 教訓). byte-diff test pins opt-in OFF to
byte-IDENTICAL master output and opt-in ON delta to
MedicationRequest/Administration NDJSON only.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 9: AD-60 audit plug-in — modules/antibiotic/audit.py

**Files:**
- Create: `clinosim/modules/antibiotic/audit.py`
- Test: `tests/integration/test_antibiotic_audit.py`

**Interfaces:**
- Consumes: `ModuleAuditSpec`, `register_audit_module` from `clinosim.audit.registry`; `HAI_TYPES`, `ANTIBIOTIC_DRUGS`
- Produces:
  - import-time `register_audit_module(ModuleAuditSpec(name="antibiotic", ...))`
  - `lift_firing_proof` returns a dict the AD-60 silent_no_op axis asserts against

- [ ] **Step 1: Read the canonical HAI audit plug-in**

Open `clinosim/modules/hai/audit.py` and use it as the structural template. Replicate the file shape (registered checks docstring + spec instantiation).

- [ ] **Step 2: Write failing test**

Create `tests/integration/test_antibiotic_audit.py`:
```python
"""Integration: clinosim audit run --module antibiotic should PASS all 4 axes."""
import pytest

from clinosim.audit.engine import run_audit
from clinosim.audit.registry import discover, get_registered


@pytest.mark.integration
def test_antibiotic_module_registered():
    discover()
    assert "antibiotic" in get_registered()


@pytest.mark.integration
def test_antibiotic_lift_firing_proof_passes_silent_no_op_axis():
    """The synthetic-record proof must report all expected actions fired.

    PR-90 教訓: this is the load-bearing gate that catches
    canonical-string mismatches, silent get-with-default lookups, and
    enricher-not-wired bugs.
    """
    discover()
    spec = get_registered()["antibiotic"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    # The proof is expected to side-effect on a synthetic record, then
    # return a dict comparing actual vs expected — see modules/antibiotic/
    # audit.py docstring for the exact shape.
    assert proof["ext_antibiotic_count"] == 1
    assert proof["ext_antibiotic_drug"] == "Ceftriaxone"
    assert proof["ext_antibiotic_duration_days"] == 7
    assert proof["orders_medication_count"] == 1
    assert proof["mar_count"] == 7
    assert proof["mar_drug"] == "Ceftriaxone"
```

- [ ] **Step 3: Verify failure**

Run: `pytest tests/integration/test_antibiotic_audit.py -v -m integration`
Expected: FAIL (`antibiotic` not registered).

- [ ] **Step 4: Implement audit plug-in**

Create `clinosim/modules/antibiotic/audit.py`:
```python
"""Antibiotic audit — second per-Module AD-60 plug-in.

Mirrors modules/hai/audit.py but the lift_firing_proof exercises the
real enricher path (enrich_antibiotic) against a synthetic CAUTI
HAIEvent, asserting:
  - extensions["antibiotic"] has exactly 1 regimen
  - regimen.drug_key == "Ceftriaxone", duration_days == 7
  - record.orders has 1 MEDICATION order with display_name "Ceftriaxone"
  - record.medication_administrations has 7 MAR entries (q24h × 7d)

This is the load-bearing PR-90 silent-no-op gate for PR3b-1.

Registered checks:
- canonical_constants: HAI_TYPES + ANTIBIOTIC_DRUGS cross-validate
  against hai_empirical.yaml at import time (via load_hai_empirical).
- structural_obs_codes: empty for PR3b-1 (no Observations emitted).
  PR3b-2 will add susceptibility LOINC codes here.
- clinical_acceptance: per-HAI-type expected drug set + duration +
  min_mar_per_event.
- lift_firing_proof: see _build_synthetic_proof below.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.hai import HAIEvent

_HAI_EMPIRICAL_YAML = Path(__file__).parent / "reference_data" / "hai_empirical.yaml"


def _build_synthetic_proof():
    """Drive enrich_antibiotic against a synthetic CAUTI record."""
    ev = HAIEvent(
        hai_id="h-cauti-proof",
        encounter_id="enc-proof",
        hai_type=HAI_TYPES[1],  # "cauti" — canonical, NEVER literal string
        source_device_id="d1",
        icd10_code="T83.511A",
        snomed_code="68566005",
        onset_date="2026-01-10",
        organism_snomed="112283007",
        culture_specimen_id="s1",
    )
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p-proof"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": [ev]},
    )
    cfg = SimpleNamespace(
        country="US",
        snapshot_date=None,
        time_range=("2026-01-01", "2026-12-31"),
    )
    ctx = SimpleNamespace(config=cfg, master_seed=42, records=[rec])
    enrich_antibiotic(ctx)

    abx = rec.extensions.get("antibiotic", [])
    med_orders = [o for o in rec.orders if o.order_type.value == "medication"]
    mar = rec.medication_administrations
    return {
        "ext_antibiotic_count": len(abx),
        "ext_antibiotic_drug": abx[0].drug_key if abx else None,
        "ext_antibiotic_duration_days": abx[0].duration_days if abx else None,
        "orders_medication_count": len(med_orders),
        "mar_count": len(mar),
        "mar_drug": mar[0].drug_name if mar else None,
        "mar_first_dt": mar[0].scheduled_datetime if mar else None,
        "mar_last_dt": mar[-1].scheduled_datetime if mar else None,
        "expected": {
            "ext_antibiotic_count": 1,
            "ext_antibiotic_drug": "Ceftriaxone",
            "ext_antibiotic_duration_days": 7,
            "orders_medication_count": 1,
            "mar_count": 7,
            "mar_drug": "Ceftriaxone",
            "mar_first_dt": datetime(2026, 1, 10, 8),
            "mar_last_dt": datetime(2026, 1, 16, 8),
        },
    }


register_audit_module(
    ModuleAuditSpec(
        name="antibiotic",
        canonical_constants={
            "hai_type": HAI_TYPES,
            "drug_key": ANTIBIOTIC_DRUGS,
        },
        yaml_keys_to_validate={
            str(_HAI_EMPIRICAL_YAML): ("hai_empirical",),
        },
        clinical_acceptance={
            "clabsi": {
                "icd10_code": "T80.211A",
                "expected_drugs": ("Vancomycin", "Piperacillin/Tazobactam"),
                "expected_duration_days": 14,
                "min_mar_per_event": 14 * 2 + 14 * 4,  # Vanc q12h + Pip-Tazo q6h
            },
            "cauti": {
                "icd10_code": "T83.511A",
                "expected_drugs": ("Ceftriaxone",),
                "expected_duration_days": 7,
                "min_mar_per_event": 7,
            },
            "vap": {
                "icd10_code": "J95.851",
                "expected_drugs": ("Vancomycin", "Piperacillin/Tazobactam"),
                "expected_duration_days": 7,
                "min_mar_per_event": 7 * 2 + 7 * 4,
            },
        },
        lift_firing_proof=_build_synthetic_proof,
    )
)
```

- [ ] **Step 5: Verify pass**

Run: `pytest tests/integration/test_antibiotic_audit.py -v -m integration`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the audit CLI for a smoke check**

```bash
python -m clinosim audit run --module antibiotic --format text
```
Expected: structural / clinical / jp_language / silent_no_op axes report on the antibiotic module (clinical may WARN if no recent generation, that's fine for smoke).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/antibiotic/audit.py tests/integration/test_antibiotic_audit.py
git commit -m "$(cat <<'EOF'
feat(audit): modules/antibiotic/audit.py — AD-60 second per-Module plug-in (Task 9)

lift_firing_proof drives enrich_antibiotic against a synthetic
CAUTI HAIEvent and asserts the closed-form Ceftriaxone q24h × 7d
output — the load-bearing PR-90 silent-no-op gate for PR3b-1.
Canonical HAI_TYPES + ANTIBIOTIC_DRUGS cross-validate
hai_empirical.yaml at import. clinical_acceptance defines
per-HAI-type expected drugs + duration + min_mar_per_event.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 10: README.md (JP, template-conformant)

**Files:**
- Create: `clinosim/modules/antibiotic/README.md`

**Interfaces:** documentation only

- [ ] **Step 1: Read the template + a recent reference**

Open `.github/TEMPLATE_MODULE_README.md` and `clinosim/modules/hai/README.md` (the most recent peer). Mirror their section ordering exactly: Overview / Responsibility / Dependencies / Consumers / Public API / Data structures / Reference data / Determinism / Audit / Test / 主要ファイル一覧.

- [ ] **Step 2: Write the README**

Create `clinosim/modules/antibiotic/README.md`:
```markdown
# antibiotic Module(AD-55 Module、Phase 3b-1)

> HAI 発症後の **経験的抗菌薬投与** を IDSA guideline に従って生成する opt-in モジュール。
> `extensions["hai"]` を consume し、`record.orders`(MedicationRequest)+ `record.medication_administrations`(MAR)+ `extensions["antibiotic"]` の 3 経路に書き込む。

## 概要

- POST_ENCOUNTER stage、order=85(`hai=80` の後)
- 既存 `_fhir_medications.py` builder を再利用(新 FHIR builder ゼロ)
- 後続 PR3b-2(S/I/R)/ PR3b-3(narrow)/ PR3b-4(decay)が `extensions["antibiotic"]` を consume

## 役割

CLABSI / CAUTI / VAP の 3 HAI type に対し、IDSA guideline に沿う経験的レジメン(organism-agnostic)を materialize する:

| HAI type | レジメン | duration | 出典 |
|---|---|---|---|
| CLABSI | Vancomycin q12h + Piperacillin/Tazobactam q6h | 14 days | IDSA 2009 (Mermel LA et al., CID 49:1-45) |
| CAUTI | Ceftriaxone q24h | 7 days | IDSA 2009 (Hooton TM et al., CID 50:625-63) |
| VAP | Vancomycin q12h + Piperacillin/Tazobactam q6h | 7 days | IDSA/ATS 2016 (Kalil AC et al., CID 63:e61-e111) |

## Dependencies(他モジュール)

- `clinosim/types/antibiotic.py` — `AntibioticRegimen`
- `clinosim/types/encounter.py` — `Order`, `OrderType`, `MedicationAdministration`
- `clinosim/types/hai.py` — `HAIEvent`(`extensions["hai"]` で consume)
- `clinosim/modules/hai/__init__.py` — `HAI_TYPES`(YAML cross-validation)
- `clinosim/modules/_shared.py` — `get_attr_or_key`
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142`
- `clinosim/audit/registry.py` — `ModuleAuditSpec`, `register_audit_module`
- `clinosim/codes/data/{rxnorm,yj}.yaml` — drug 表示の照合先
- `clinosim/locale/{us,jp}/code_mapping_drug.yaml` — drug_key → RxNorm/YJ

## Consumers(本モジュールを使う側)

- `clinosim/modules/output/_fhir_medications.py` — `record.orders`(MedicationRequest)+ `record.medication_administrations`(MAR)を読んで FHIR resource を emit
- `clinosim/modules/output/_fhir_csv.py` — 同 fields の CSV 出力
- 後続 PR(将来):
  - PR3b-2: `extensions["antibiotic"][i].drug_key` × organism antibiogram → `MicrobiologyResult.susceptibilities` を populate
  - PR3b-3: `extensions["antibiotic"][i].intent == "empirical"` を読んで narrow への de-escalation 候補を選定
  - PR3b-4: `extensions["antibiotic"][i].start_datetime` を WBC/CRP forward-delta decay の起点として使用

## Public API

- `clinosim.modules.antibiotic.ANTIBIOTIC_DRUGS: tuple[str, ...]` — canonical drug name tuple
- `clinosim.modules.antibiotic.engine.load_hai_empirical()` — YAML loader + import-time validation
- `clinosim.modules.antibiotic.engine.build_regimens(hai_event, start_datetime)` — HAIEvent → `list[AntibioticRegimen]`
- `clinosim.modules.antibiotic.engine.generate_mar_doses(regimen, snapshot_datetime, order_id)` — regimen → `list[MedicationAdministration]`(snapshot truncation 適用)
- `clinosim.modules.antibiotic.enricher.enrich_antibiotic(ctx)` — POST_ENCOUNTER entry point

## データ構造

`AntibioticRegimen`(`clinosim/types/antibiotic.py`):

```python
@dataclass
class AntibioticRegimen:
    regimen_id: str
    hai_event_id: str         # ← cross-module 連結ポイント
    encounter_id: str
    drug_key: str             # canonical(ANTIBIOTIC_DRUGS member)
    dose: str
    route: str
    frequency: str            # q24h / q12h / q6h
    start_datetime: datetime  # HAI onset_date の 08:00
    duration_days: int        # IDSA: CLABSI/VAP=14, CAUTI=7
    intent: str               # "empirical"(将来 "narrowed" を追加)
```

`extensions["antibiotic"] = list[AntibioticRegimen]` で保持。

## Reference data

- `reference_data/hai_empirical.yaml` — IDSA guideline ベース、HAI type × drugs × dose/route/freq/duration
- 出典は YAML 内コメントに明記。impl 時に NLM RxNav / MEDIS-DC HOT/YJ master で照合済

## Determinism(AD-16)

- per-patient sub-rng: `derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["antibiotic"]=0x4142, patient_id)`
- PR3b-1 は確率的サンプリングを行わない(全 HAI に同じ empirical レジメン適用)→ sub-rng は将来用に予約
- main RNG 不動 = 既存 golden file は opt-in OFF default で byte-IDENTICAL

## Audit(AD-60)

- 同 PR で `audit.py` を新規追加(本格運用 2 例目)
- canonical_constants: `HAI_TYPES` + `ANTIBIOTIC_DRUGS`
- yaml_keys_to_validate: `hai_empirical.yaml` の `hai_empirical` キー
- clinical_acceptance: per-HAI-type expected drugs + duration + min_mar_per_event
- lift_firing_proof: 合成 CAUTI record を `enrich_antibiotic` で drive、closed-form delta(Ceftriaxone q24h × 7d = 7 MAR)と完全一致照合 = PR-90 class silent no-op gate

## Test

- `tests/unit/test_antibiotic_types.py`
- `tests/unit/test_antibiotic_yaml_loader.py`
- `tests/unit/test_antibiotic_engine.py`
- `tests/unit/test_antibiotic_enricher_unit.py`
- `tests/unit/test_antibiotic_code_lookup.py`
- `tests/unit/test_enricher_seed_offsets.py` (extended with 2 antibiotic-specific cases)
- `tests/integration/test_antibiotic_forced_e2e.py`
- `tests/integration/test_antibiotic_byte_diff.py`
- `tests/integration/test_antibiotic_audit.py`

## 主要ファイル一覧

```
clinosim/modules/antibiotic/
  __init__.py             # ANTIBIOTIC_DRUGS canonical
  engine.py               # load_hai_empirical / build_regimens / generate_mar_doses
  enricher.py             # enrich_antibiotic (POST_ENCOUNTER, order=85)
  audit.py                # AD-60 plug-in
  reference_data/
    hai_empirical.yaml    # IDSA 2009/2016 guideline
  README.md               # 本ファイル
```
```

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/antibiotic/README.md
git commit -m "$(cat <<'EOF'
docs(antibiotic): module README (Task 10)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 11: Cross-cutting docs sync + DQR generation

**Files:**
- Modify: `MODULES.md` (add antibiotic row, bump count)
- Modify: `TODO.md` (mark Phase 3b-1 complete, queue PR3b-2/3/4)
- Modify: `DESIGN.md` (AD-55 Module roadmap progress note)
- Modify: `CLAUDE.md` (if a Phase 3b-1 pattern note is warranted)
- Create: `docs/reviews/2026-06-25-phase-3b-1-antibiotic-empirical-data-quality-review.md`

**Interfaces:** documentation only

- [ ] **Step 1: Inspect current state of each doc to make targeted edits**

```bash
grep -nE "^\|.*hai\s*\|" MODULES.md | head -3
grep -nE "Phase 3b|antibiotic" TODO.md | head -5
grep -nE "AD-55 Module|AD-56|AD-60" DESIGN.md | head -8
grep -nE "Phase 3a|forward-delta|POST_ENCOUNTER" CLAUDE.md | head -8
```

- [ ] **Step 2: Update MODULES.md**

Locate the module table row for `hai` and add an `antibiotic` row immediately after (preserve column alignment). Also bump any "N modules" count in the header text.

- [ ] **Step 3: Update TODO.md**

Mark Phase 3a/b roadmap line:
- `[x] Phase 3b-1 = HAI empirical antibiotic regimen` (this PR)
- `[ ] Phase 3b-2 = culture S/I/R metadata`
- `[ ] Phase 3b-3 = narrow / de-escalation`
- `[ ] Phase 3b-4 = WBC/CRP forward-delta decay`

- [ ] **Step 4: Update DESIGN.md**

Append a short note to the AD-55 Module section confirming `antibiotic` is the second per-Module audit plug-in (after `hai`) under AD-60, and that the dual-write storage strategy is established as the AD-55 Module reference pattern for opt-in modules consuming upstream extensions.

- [ ] **Step 5: Update CLAUDE.md (if warranted)**

Only update if a new architectural rule emerged (it likely did NOT — the patterns are all reuse). If anything, add one line under "確立 patterns": `**Empirical regimen pattern** (PR3b-1): opt-in Module consumes extensions["hai"], dual-writes Base typed fields + extensions["antibiotic"], reuses existing _fhir_medications builder.`

- [ ] **Step 6: Generate DQR**

Run a small generation + audit pass at p=2000:
```bash
python -m clinosim generate --country US --population 2000 --seed 42 --output /tmp/abx_dqr_us --modules antibiotic,device,hai
python -m clinosim generate --country JP --population 2000 --seed 42 --output /tmp/abx_dqr_jp --modules antibiotic,device,hai
python -m clinosim audit run --input /tmp/abx_dqr_us --module antibiotic --format text > /tmp/abx_audit_us.txt
python -m clinosim audit run --input /tmp/abx_dqr_jp --module antibiotic --format text > /tmp/abx_audit_jp.txt
```

(If the exact CLI flags differ from above, inspect `clinosim audit --help` and `clinosim generate --help` and adapt; the principle is to drive `clinosim audit run` end-to-end against newly-generated data.)

- [ ] **Step 7: Write DQR report**

Create `docs/reviews/2026-06-25-phase-3b-1-antibiotic-empirical-data-quality-review.md` capturing:
- Generation parameters (US/JP p=2000 seed=42 modules=antibiotic+device+hai)
- 4-axis result per audit run (structural / clinical / jp_language / silent_no_op)
- HAI event count, antibiotic event count, MAR count by HAI type (cohort medians)
- byte-diff supplementary verification (opt-in OFF vs absent = byte-IDENTICAL across 37 NDJSON)
- Per-HAI-type clinical_acceptance comparison: actual vs spec §4 expected
- WARN/FAIL items (Poisson rare-event WARN at p=2000 is acceptable)

- [ ] **Step 8: Final smoke run of full test suite**

```bash
pytest -m unit -x -q
pytest -m integration -x -q
```
Expected: all green (target: existing 726 + new ~20 unit + ~6 integration ≈ ~752 tests).

- [ ] **Step 9: Commit docs sync + DQR**

```bash
git add MODULES.md TODO.md DESIGN.md CLAUDE.md docs/reviews/2026-06-25-phase-3b-1-antibiotic-empirical-data-quality-review.md
git commit -m "$(cat <<'EOF'
docs(phase3b-1): MODULES/TODO/DESIGN/CLAUDE sync + DQR report (Task 11)

DQR PASS at US/JP p=2000 across 4 AD-60 axes including
silent_no_op (lift_firing_proof exercising end-to-end enricher path).
Per-HAI-type clinical_acceptance: CAUTI 7-MAR / CLABSI 84-MAR /
VAP 42-MAR observed cohort matches spec §4 closed-form expected.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

---

## Task 12: PR preparation + post-merge xhigh review trigger

**Files:** none new

**Interfaces:** none

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/phase-3b-1-antibiotic-empirical
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(antibiotic): Phase 3b-1 HAI empirical antibiotic regimen + AD-60 audit plug-in 2" --body "$(cat <<'EOF'
## Summary

- PR3b-1 of the Phase 3b 4-PR HAI antibiotic chain (empirical → S/I/R → narrow → decay)
- New opt-in Module `modules/antibiotic/` consumes `extensions["hai"]`, emits IDSA-guideline empirical regimens
- Dual-write storage: `record.orders` (MedicationRequest) + `record.medication_administrations` (MAR) + `extensions["antibiotic"]` (cross-PR consumption)
- `modules/antibiotic/audit.py` = AD-60 framework second per-Module plug-in with lift_firing_proof (PR-90 silent-no-op gate)
- Zero new FHIR builders (reuses `_fhir_medications.py`)

## Verification

- [x] Unit + integration tests green (`pytest -m unit/integration -x -q`)
- [x] `clinosim audit run --module antibiotic` PASS (structural / clinical / jp_language / silent_no_op)
- [x] byte-diff: opt-in OFF vs absent = byte-IDENTICAL across all NDJSON (p=2000 US + JP)
- [x] byte-diff: opt-in ON delta limited to MedicationRequest.ndjson + MedicationAdministration.ndjson
- [x] DQR report `docs/reviews/2026-06-25-phase-3b-1-antibiotic-empirical-data-quality-review.md`
- [x] All docs synced: MODULES.md / TODO.md / DESIGN.md / CLAUDE.md / `modules/antibiotic/README.md`
- [x] Authoritative code source: NLM RxNav (Vancomycin RxNorm) + MEDIS-DC HOT/YJ master (Vancomycin YJ)

## Test plan

- [ ] Reviewer: skim `docs/superpowers/specs/2026-06-25-phase-3b-1-antibiotic-empirical-design.md` for design intent
- [ ] Reviewer: verify Vancomycin RxNorm + YJ codes against NLM RxNav + MEDIS-DC (commit links to verification)
- [ ] Reviewer: confirm lift_firing_proof in `modules/antibiotic/audit.py` exercises the actual enricher path
- [ ] Reviewer: spot-check `medication_requests.ndjson` for JP locale Japanese display

🤖 Generated with [Claude Code](https://claude.com/claude-code)
https://claude.ai/code/session_01BPCNtAC7fmvNV8Ndy61T2j
EOF
)"
```

- [ ] **Step 3: Wait for user PR review + xhigh review trigger**

Per memory `feedback_xhigh_review_lessons`, this PR should receive an **xhigh code review BEFORE merge**. test 緑 + byte-diff + DQR PASS は ship-ready ではない(PR-90 教訓)。

User-driven step: trigger `/code-review ultra <PR#>` after the PR is open and CI green; do NOT merge until xhigh findings are addressed.

- [ ] **Step 4: After merge, sync master**

```bash
git checkout master
git pull
git log -1 --oneline
```

---

## Self-Review (this plan vs the spec)

### Spec coverage check

| Spec section | Coverage |
|---|---|
| §1 Phase 3b overview + PR3b-1 scope | Task 1-9 implement; §11 confirms PR3b-2/3/4 surface preserved (`intent="empirical"`, `hai_event_id`) |
| §2 Module structure + dataflow | Task 1 (types), Task 2 (engine + YAML), Task 7 (enricher + register_builtin_enrichers POST_ENCOUNTER order=85) |
| §3.1 Per-HAI single empirical (IDSA) | Task 2 YAML content |
| §3.2 Storage = dual write | Task 7 enricher writes all 3 paths |
| §3.3 Established patterns | Task 6 (sub-rng), Task 1 (canonical const), Task 7 (cross-module consumption), Task 7 (reuse `_fhir_medications`), Task 5 (coding), Task 7 (POST_ENCOUNTER/85), Task 4 (snapshot trunc) |
| §3.4 Authoritative code lookup | Task 5 Step 1 + Step 4 + commit message source citations |
| §4 AD-60 audit plug-in | Task 9 full spec; lift_firing_proof closed-form Ceftriaxone q24h × 7d |
| §5 Test plan | Task 1-9 unit + integration; Task 11 audit; Task 8 byte-diff |
| §6 Existing-code improvements | Implementer-judgement: noted `_FREQ_PER_DAY` shared helper is **deferred** to keep Task 4 scope tight; left as TODO (not blocking PR3b-1) |
| §7 Risks | Mitigation embedded throughout (canonical const Task 1, YAML validate Task 2, lift_firing_proof Task 9, opt-in default off Task 7, byte-diff Task 8) |
| §8 Success criteria | All 9 checkboxes in spec §8 map to Task 8, 9, 11, 12 deliverables |
| §A YAML sketch | Task 2 Step 3 verbatim |
| §B Cross-PR surface | Task 1 reserves `intent` field; Task 7 sets `hai_event_id` from HAIEvent.hai_id |

Coverage gap noted:
- Spec §6 row 1 (`_FREQ_PER_DAY` to `_shared.py`) is **not** part of this PR per Task 4 simplification (a local `FREQ_PER_DAY` is defined in `engine.py`). Acceptable: §6 explicitly marks this as "improver's discretion".

### Placeholder scan

- Searched for `TBD`/`TODO`/`FIXME`/"Add appropriate"/"Similar to Task N": **none present** in plan body (TODO appears in file names and intentional contexts: feedback memory name, spec.§6 row 3 deferred-to-Phase-3b-2, etc.)
- All steps include concrete code blocks where code is needed.

### Type consistency check

- `AntibioticRegimen(regimen_id, hai_event_id, encounter_id, drug_key, dose, route, frequency, start_datetime, duration_days, intent)` — used identically in Task 1, 3, 4, 7, 9, README.
- `ANTIBIOTIC_DRUGS = ("Vancomycin", "Piperacillin/Tazobactam", "Ceftriaxone")` — verbatim in Task 1, 2, 9, README.
- `enrich_antibiotic(ctx)` signature — Task 7 def + Task 9 import + Task 11 audit smoke.
- `load_hai_empirical()` — Task 2 def + Task 3 caller + Task 9 import via YAML path.
- `build_regimens(hai_event, start_datetime)` (not `build_regimen` — plural) — Task 3 def + Task 7 caller + Task 9 indirect via enricher.
- `generate_mar_doses(regimen, snapshot_datetime, order_id)` — Task 4 def + Task 7 caller + Task 9 indirect.
- `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142` — Task 6 def + README.

All names match across tasks. No drift detected.

### Scope check

- Single PR-shippable plan, ~12 tasks, ~750 LOC including tests.
- No second subsystem entangled; PR3b-2/3/4 are deliberately deferred (spec §1 + Appendix B preserve API surface).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-25-phase-3b-1-antibiotic-empirical-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
