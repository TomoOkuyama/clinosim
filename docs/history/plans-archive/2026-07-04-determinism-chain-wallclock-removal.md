# Determinism Chain: Wall-Clock Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate every reachable `datetime.now()`/`date.today()` read from the clinosim simulation pipeline so that the same seed + config produces byte-identical structural CIF output regardless of wall-clock execution time, while closing off the same bug class in currently-dead dataclass fields.

**Architecture:** Two independent classes of fix, both touching `clinosim/types/clinical.py`, `clinosim/types/encounter.py`, `clinosim/types/procedure.py`, and `clinosim/modules/diagnosis/engine.py`:
1. **Sentinel-default sweep** (mechanical, zero call-site churn): every `default_factory=datetime.now`/`date.today` becomes a fixed, obviously-fake sentinel constant (`datetime(1970, 1, 1)` / `date(1970, 1, 1)`). This alone eliminates all wall-clock reads; dataclass field order and every existing call site (including ~100+ test constructions) are untouched because a `default_factory` is still present.
2. **Live-value threading** (targeted, ~6 call sites): the two fields that are actually read downstream and serialized into structural CIF — `PhysiologicalState.timestamp` and `PrescriptionRecord.issue_date` — get the real, correct, deterministic value assigned explicitly at each production call site, overriding the sentinel.

Everything else discovered during investigation (`StateChangeDirective.timestamp`, `DifferentialDiagnosis.timestamp`, `Encounter.admission_datetime`, `OrderResult.result_datetime`, `MedicationAdministration.scheduled_datetime`, `Order.ordered_datetime`, `VitalSignRecord.timestamp`, `ProcedureRecord.start_datetime`/`end_datetime`, `RehabSession.session_date`, `ADLAssessment.date`, `NursingRiskAssessment.date`, `IntakeOutputRecord.date`, `ImmunizationRecord.occurrence_date`, `ClinicalImpressionRecord.date`) is confirmed dead (always overridden explicitly, or — for `StateChangeDirective.timestamp`/`DifferentialDiagnosis.timestamp` — never read by any consumer at all) and needs only the sentinel-default fix.

**Tech Stack:** Python 3.11+, `dataclasses`, `pytest` (unit/integration/e2e markers), no new dependencies.

## Global Constraints

- Formatter: ruff. Type checking: mypy (strict mode). Line length: 100.
- AD-16: deterministic with seed — never introduce a new wall-clock or unseeded-RNG read.
- AD-30: CIF stores codes only, not display text — not touched by this chain, but do not regress it incidentally.
- No comments explaining *what* code does; only *why*, and only when non-obvious (project CLAUDE.md convention).
- Run `pytest -x -q` (unit + integration, <2 min) after every task before committing. Run `pytest -m e2e` once at the end (Task 7).
- Every new/edited public function needs no docstring changes beyond what's shown in the steps below unless explicitly stated.
- Source of design decisions: `docs/superpowers/specs/2026-07-04-determinism-chain-wallclock-removal-design.md`.

---

### Task 1: Sentinel-default sweep across the four wall-clock-default files

**Files:**
- Modify: `clinosim/types/clinical.py`
- Modify: `clinosim/types/encounter.py`
- Modify: `clinosim/types/procedure.py`
- Modify: `clinosim/modules/diagnosis/engine.py`
- Test: `tests/unit/test_wallclock_sentinel_defaults.py` (new)

**Interfaces:**
- Produces: a fixed sentinel constant `_UNSET_DATETIME = datetime(1970, 1, 1)` (and, in `clinical.py`/`encounter.py`, `_UNSET_DATE = date(1970, 1, 1)`) defined once per file, module-private (not exported). No public API changes — field types and names are unchanged, only their `default_factory` callable changes.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_wallclock_sentinel_defaults.py`:

```python
"""Verify dataclass fields that used to default to datetime.now()/date.today()
no longer read the wall clock (determinism chain, 2026-07-04).

Each assertion constructs the class with no args (or the minimal args needed)
and checks the timestamp/date field equals the fixed sentinel — proving the
default is a constant, not a live wall-clock call. See
docs/superpowers/specs/2026-07-04-determinism-chain-wallclock-removal-design.md.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit

_SENTINEL_DATETIME = datetime(1970, 1, 1)
_SENTINEL_DATE = date(1970, 1, 1)


def test_physiological_state_timestamp_sentinel():
    from clinosim.types.clinical import PhysiologicalState
    assert PhysiologicalState().timestamp == _SENTINEL_DATETIME


def test_state_change_directive_timestamp_sentinel():
    from clinosim.types.clinical import StateChangeDirective
    assert StateChangeDirective().timestamp == _SENTINEL_DATETIME


def test_clinical_impression_record_date_sentinel():
    from clinosim.types.clinical import ClinicalImpressionRecord
    assert ClinicalImpressionRecord().date == _SENTINEL_DATE


def test_encounter_admission_datetime_sentinel():
    from clinosim.types.encounter import Encounter
    assert Encounter().admission_datetime == _SENTINEL_DATETIME


def test_order_result_result_datetime_sentinel():
    from clinosim.types.encounter import OrderResult
    assert OrderResult().result_datetime == _SENTINEL_DATETIME


def test_medication_administration_scheduled_datetime_sentinel():
    from clinosim.types.encounter import MedicationAdministration
    assert MedicationAdministration().scheduled_datetime == _SENTINEL_DATETIME


def test_prescription_record_issue_date_sentinel():
    from clinosim.types.encounter import PrescriptionRecord
    assert PrescriptionRecord().issue_date == _SENTINEL_DATETIME


def test_order_ordered_datetime_sentinel():
    from clinosim.types.encounter import Order
    assert Order().ordered_datetime == _SENTINEL_DATETIME


def test_vital_sign_record_timestamp_sentinel():
    from clinosim.types.encounter import VitalSignRecord
    assert VitalSignRecord().timestamp == _SENTINEL_DATETIME


def test_adl_assessment_date_sentinel():
    from clinosim.types.encounter import ADLAssessment
    assert ADLAssessment().date == _SENTINEL_DATE


def test_nursing_risk_assessment_date_sentinel():
    from clinosim.types.encounter import NursingRiskAssessment
    assert NursingRiskAssessment().date == _SENTINEL_DATE


def test_intake_output_record_date_sentinel():
    from clinosim.types.encounter import IntakeOutputRecord
    assert IntakeOutputRecord().date == _SENTINEL_DATE


def test_immunization_record_occurrence_date_sentinel():
    from clinosim.types.encounter import ImmunizationRecord
    assert ImmunizationRecord().occurrence_date == _SENTINEL_DATE


def test_procedure_record_start_end_datetime_sentinel():
    from clinosim.types.procedure import ProcedureRecord
    rec = ProcedureRecord()
    assert rec.start_datetime == _SENTINEL_DATETIME
    assert rec.end_datetime == _SENTINEL_DATETIME


def test_rehab_session_session_date_sentinel():
    from clinosim.types.procedure import RehabSession
    assert RehabSession().session_date == _SENTINEL_DATETIME


def test_differential_diagnosis_timestamp_sentinel():
    from clinosim.modules.diagnosis.engine import DifferentialDiagnosis
    assert DifferentialDiagnosis().timestamp == _SENTINEL_DATETIME


def test_update_differential_no_longer_touches_wall_clock():
    """update_differential() used to overwrite .timestamp with datetime.now()
    on every call — that assignment is now removed entirely (dead field)."""
    from clinosim.modules.diagnosis.engine import (
        initialize_differential,
        update_differential,
    )
    diff = initialize_differential()
    before = diff.timestamp
    diff = update_differential(diff, [("chest_xray_consolidation", True)])
    assert diff.timestamp == before == _SENTINEL_DATETIME
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wallclock_sentinel_defaults.py -v`
Expected: every test FAILs (sentinel constants don't exist yet / fields still default to wall-clock, so equality with a fixed 1970 value fails).

- [ ] **Step 3: Edit `clinosim/types/clinical.py`**

Change the import line and add the sentinels right after it:

```python
from dataclasses import dataclass, field
from datetime import date, datetime

# Deliberately obvious non-real sentinel — replaces the former datetime.now()/
# date.today() default that made byte-diff output depend on wall-clock
# execution time (determinism chain, 2026-07-04). Fields using this default
# are either always overridden by the caller or never read downstream; if
# this value surfaces in real output, that indicates a missing override.
_UNSET_DATETIME = datetime(1970, 1, 1)
_UNSET_DATE = date(1970, 1, 1)
```

Then in `PhysiologicalState`:
```python
    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)
```
(was `field(default_factory=datetime.now)`)

In `StateChangeDirective`:
```python
    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)
```
(was `field(default_factory=datetime.now)`)

In `ClinicalImpressionRecord`:
```python
    date: date = field(default_factory=lambda: _UNSET_DATE)
```
(was `field(default_factory=date.today)`)

- [ ] **Step 4: Edit `clinosim/types/encounter.py`**

Change the import line and add the sentinels right after it:

```python
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from clinosim.types.triage import TriageData

# See clinosim/types/clinical.py for rationale (determinism chain, 2026-07-04).
_UNSET_DATETIME = datetime(1970, 1, 1)
_UNSET_DATE = date(1970, 1, 1)
```

Then change these six fields (all currently `field(default_factory=datetime.now)`) to `field(default_factory=lambda: _UNSET_DATETIME)`:
- `Encounter.admission_datetime`
- `OrderResult.result_datetime`
- `MedicationAdministration.scheduled_datetime`
- `PrescriptionRecord.issue_date`
- `Order.ordered_datetime`
- `VitalSignRecord.timestamp`

And change these four fields (all currently `field(default_factory=date.today)`) to `field(default_factory=lambda: _UNSET_DATE)`:
- `ADLAssessment.date`
- `NursingRiskAssessment.date`
- `IntakeOutputRecord.date`
- `ImmunizationRecord.occurrence_date`

- [ ] **Step 5: Edit `clinosim/types/procedure.py`**

Change the import line and add the sentinel:

```python
from dataclasses import dataclass, field
from datetime import datetime

# See clinosim/types/clinical.py for rationale (determinism chain, 2026-07-04).
_UNSET_DATETIME = datetime(1970, 1, 1)

__all__ = ["ProcedureRecord", "RehabSession"]
```

Then change these three fields (all currently `field(default_factory=datetime.now)`) to `field(default_factory=lambda: _UNSET_DATETIME)`:
- `ProcedureRecord.start_datetime`
- `ProcedureRecord.end_datetime`
- `RehabSession.session_date`

- [ ] **Step 6: Edit `clinosim/modules/diagnosis/engine.py`**

Add the sentinel after the imports (near `_HERE = Path(__file__).resolve().parent`):

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from clinosim.codes import lookup

# See clinosim/types/clinical.py for rationale (determinism chain, 2026-07-04).
_UNSET_DATETIME = datetime(1970, 1, 1)

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
```

Change `DifferentialDiagnosis.timestamp`:
```python
    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)
```
(was `field(default_factory=datetime.now)`)

Then in `update_differential()`, delete the dead wall-clock reassignment. Find:
```python
        candidate.probability *= lr
                candidate.evidence.append(
                    f"{finding_name}: {'(+)' if is_positive else '(-)'} LR={lr}"
                )

    # Normalize
    total = sum(c.probability for c in diff.candidates)
    if total > 0:
        for c in diff.candidates:
            c.probability /= total

    # Sort
    diff.candidates.sort(key=lambda c: -c.probability)

    # Check confirmation
    top = diff.candidates[0]
    if top.probability >= confirmation_threshold:
        diff.confirmed = True
        diff.working_diagnosis = top.disease_code
    elif top.probability >= 0.5:
        diff.working_diagnosis = top.disease_code

    diff.timestamp = datetime.now()
    return diff
```
Replace the final two lines with just:
```python
    elif top.probability >= 0.5:
        diff.working_diagnosis = top.disease_code

    return diff
```
i.e. delete the `diff.timestamp = datetime.now()` line entirely. `DifferentialDiagnosis.timestamp` is confirmed unread by any consumer (verified: no code outside its own class definition and this one assignment ever accesses `.timestamp` on a `DifferentialDiagnosis`), so no replacement value is needed.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/test_wallclock_sentinel_defaults.py -v`
Expected: all 17 tests PASS.

- [ ] **Step 8: Run the full unit + integration suite to confirm no regression**

Run: `pytest -m "unit or integration" -q`
Expected: all pass (this sweep touches only default *values*, not signatures or call sites, so no existing test should break — the ~100+ test call sites gathered during investigation construct these classes without passing the timestamp field, and now simply receive `_UNSET_DATETIME`/`_UNSET_DATE` instead of a wall-clock value, which none of them assert against).

- [ ] **Step 9: Commit**

```bash
git add clinosim/types/clinical.py clinosim/types/encounter.py clinosim/types/procedure.py clinosim/modules/diagnosis/engine.py tests/unit/test_wallclock_sentinel_defaults.py
git commit -m "fix(determinism): replace datetime.now()/date.today() defaults with fixed sentinels"
```

---

### Task 2: Thread real deterministic values into `PhysiologicalState.timestamp`

**Files:**
- Modify: `clinosim/simulator/inpatient.py:169-170` (`_simulate_patient`) and `:1724-1725` (`_simulate_unknown_condition`)
- Modify: `clinosim/simulator/outpatient.py:122-124` (`_simulate_outpatient_visit`)
- Modify: `clinosim/simulator/emergency.py:118-120` (`_simulate_ed_visit`)
- Modify: `clinosim/modules/device/engine.py:94-104` (`_peak_state_for_encounter`)
- Test: `tests/unit/test_physiology.py` (add one test)

**Interfaces:**
- Consumes: `_UNSET_DATETIME` sentinel now in place from Task 1 (no signature changes to `initialize_state()` — the fix assigns `.timestamp` directly on the returned `PhysiologicalState` instance at each call site, which is simpler and lower-risk than adding a new required parameter: it needs no RNG-draw-order changes, since `admission_time`/`visit_date`/`visit_time` are assigned to `.timestamp` *after* they are computed, wherever in the function that already happens).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_physiology.py` (append near the other `initialize_state` tests — search the file for `def test_initialize_state` to find the right section):

```python
def test_initialize_state_timestamp_is_sentinel_not_wall_clock():
    """initialize_state() itself must not read the wall clock — callers are
    responsible for overwriting .timestamp with a real deterministic value
    right after this call returns (determinism chain, 2026-07-04)."""
    from datetime import datetime
    from clinosim.modules.physiology.engine import initialize_state
    from clinosim.types.patient import PatientPhysiologicalProfile

    profile = PatientPhysiologicalProfile()
    state = initialize_state(profile, [], "p1")
    assert state.timestamp == datetime(1970, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_physiology.py::test_initialize_state_timestamp_is_sentinel_not_wall_clock -v`
Expected: FAIL (before Task 1's sentinel swap this would read wall-clock `datetime.now()`; if Task 1 already landed, this specific assertion should actually already PASS — this test is a regression guard for the *combination* of Task 1 + Task 2 not accidentally threading a value inside `initialize_state()` itself). If it already passes at this point, proceed directly to Step 3 (still add the test — it guards against a future regression where someone "fixes" `initialize_state()` by giving it a wall-clock-reading default again).

- [ ] **Step 3: Thread `admission_time` in `clinosim/simulator/inpatient.py` (`_simulate_patient`)**

Find (around line 168-171):
```python
    adm_minute = int(rng.integers(0, 60))
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               adm_hour, adm_minute)
    chief_complaint = _disease_chief_complaint(protocol, country=config.country)
```
Replace with:
```python
    adm_minute = int(rng.integers(0, 60))
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               adm_hour, adm_minute)
    state.timestamp = admission_time
    chief_complaint = _disease_chief_complaint(protocol, country=config.country)
```

- [ ] **Step 4: Thread `admission_time` in `clinosim/simulator/inpatient.py` (`_simulate_unknown_condition`)**

Find (around line 1721-1726):
```python
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    complaint = event.disease_id.replace("unknown_", "").replace("_", " ")
```
Replace with:
```python
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    state.timestamp = admission_time
    complaint = event.disease_id.replace("unknown_", "").replace("_", " ")
```

- [ ] **Step 5: Thread `visit_date` in `clinosim/simulator/outpatient.py`**

Find (around line 122-125):
```python
    baseline = patient.baseline_vitals
    _state = initialize_state(patient.physiological_profile, patient.chronic_conditions,
                              patient.patient_id)
    vit_time = visit_date + timedelta(minutes=5)
```
Replace with:
```python
    baseline = patient.baseline_vitals
    _state = initialize_state(patient.physiological_profile, patient.chronic_conditions,
                              patient.patient_id)
    _state.timestamp = visit_date
    vit_time = visit_date + timedelta(minutes=5)
```

- [ ] **Step 6: Thread `visit_time` in `clinosim/simulator/emergency.py`**

Find (around line 118-120):
```python
    baseline_values = BASELINE_LAB_NORMALS
    _state = initialize_state(patient.physiological_profile, patient.chronic_conditions,
                              patient.patient_id)
```
Replace with:
```python
    baseline_values = BASELINE_LAB_NORMALS
    _state = initialize_state(patient.physiological_profile, patient.chronic_conditions,
                              patient.patient_id)
    _state.timestamp = visit_time
```

- [ ] **Step 7: Fix the `device/engine.py` fallback**

Find (around line 94-104):
```python
def _peak_state_for_encounter(
    record: CIFPatientRecord, encounter: Encounter
) -> PhysiologicalState:
    """Pick a representative PhysiologicalState for the encounter.

    Phase 1 simplification: use the first recorded state; falls back to a
    default PhysiologicalState when the patient has none.
    """
    if record.physiological_states:
        return record.physiological_states[0]
    return PhysiologicalState()
```
Replace with:
```python
def _peak_state_for_encounter(
    record: CIFPatientRecord, encounter: Encounter
) -> PhysiologicalState:
    """Pick a representative PhysiologicalState for the encounter.

    Phase 1 simplification: use the first recorded state; falls back to a
    default PhysiologicalState when the patient has none.
    """
    if record.physiological_states:
        return record.physiological_states[0]
    return PhysiologicalState(timestamp=encounter.admission_datetime)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/unit/test_physiology.py::test_initialize_state_timestamp_is_sentinel_not_wall_clock -v`
Expected: PASS.

- [ ] **Step 9: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add clinosim/simulator/inpatient.py clinosim/simulator/outpatient.py clinosim/simulator/emergency.py clinosim/modules/device/engine.py tests/unit/test_physiology.py
git commit -m "fix(determinism): thread deterministic admission/visit time into PhysiologicalState.timestamp"
```

---

### Task 3: Thread real deterministic values into `PrescriptionRecord.issue_date`

**Files:**
- Modify: `clinosim/simulator/inpatient.py:357-360` (call site) and `:1618-1671` (`_build_discharge_rx` definition)
- Modify: `clinosim/simulator/outpatient.py:210-216`
- Test: `tests/e2e/test_alpha_golden.py` (add one test — `run_alpha` exercises `_build_discharge_rx` end-to-end)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_build_discharge_rx()` gains a new required positional parameter `admission_time: datetime`, inserted right after `prescriber_id` in the signature. This is a private (`_`-prefixed) function with exactly one call site in production code (verified during investigation) and zero test call sites, so this is a safe, contained signature change.

- [ ] **Step 1: Write the failing test**

Add to `tests/e2e/test_alpha_golden.py`, inside `class TestAlphaGolden:` (after `test_reproducibility`):

```python
    def test_discharge_prescription_issue_date_is_deterministic(self, alpha_result):
        record = alpha_result.patients[0]
        assert record.discharge_prescription is not None
        assert record.discharge_prescription.issue_date != _SENTINEL_DATETIME
        result2 = run_alpha(SimulatorConfig(random_seed=42))
        assert (
            result2.patients[0].discharge_prescription.issue_date
            == record.discharge_prescription.issue_date
        )
```

And add the import/constant near the top of the file (after the existing imports):
```python
from datetime import datetime

_SENTINEL_DATETIME = datetime(1970, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_alpha_golden.py::TestAlphaGolden::test_discharge_prescription_issue_date_is_deterministic -v -m e2e`
Expected: FAIL — `issue_date` currently equals whatever `datetime.now()` returned at generation time (or, after Task 1 lands first, equals the `_UNSET_DATETIME` sentinel, which the first assertion `!= _SENTINEL_DATETIME` catches either way).

- [ ] **Step 3: Update `_build_discharge_rx()` signature and body in `clinosim/simulator/inpatient.py`**

Find (around line 1618-1626):
```python
def _build_discharge_rx(
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    prescriber_id: str,
    rng: np.random.Generator,
    country_key: str = "japan",
    final_renal_function: float = 1.0,
) -> PrescriptionRecord:
    """Build discharge prescription from protocol.
```
Replace with:
```python
def _build_discharge_rx(
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    prescriber_id: str,
    admission_time: datetime,
    rng: np.random.Generator,
    country_key: str = "japan",
    final_renal_function: float = 1.0,
) -> PrescriptionRecord:
    """Build discharge prescription from protocol.
```

Find (around line 1666-1671):
```python
    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
        items=items,
    )
```
Replace with:
```python
    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
        issue_date=admission_time,
        items=items,
    )
```

- [ ] **Step 4: Update the sole call site in `clinosim/simulator/inpatient.py`**

Find (around line 355-360):
```python
    # Discharge prescription
    final_renal = state.renal_function if state else 1.0
    discharge_rx = _build_discharge_rx(
        patient, disease_id, protocol, attending_id, rng,
        country_key=country_key, final_renal_function=final_renal,
    ) if not death_occurred else None
```
Replace with:
```python
    # Discharge prescription
    final_renal = state.renal_function if state else 1.0
    discharge_rx = _build_discharge_rx(
        patient, disease_id, protocol, attending_id, admission_time, rng,
        country_key=country_key, final_renal_function=final_renal,
    ) if not death_occurred else None
```

(`admission_time` is already in scope in `_simulate_patient` at this point — set at line ~169, used throughout the function. `issue_date=admission_time` is a deliberate simplification over the true discharge datetime — see Note below.)

**Note on precision:** the real prescription issue date is closer to discharge than admission, but `encounter.discharge_datetime` is not finalized until after this call (it's set conditionally later, including a `None` case for in-progress/snapshot-truncated encounters per AD-32). Reusing `admission_time` — already deterministic and in scope — is a strict correctness improvement over the previous `datetime.now()` (which had zero relationship to simulated time at all) without the added complexity/risk of reordering the snapshot-status logic. This precision gap is out of scope for this chain; if closer semantic accuracy is wanted later, track it as a follow-up TODO item, not part of this fix.

- [ ] **Step 5: Update the outpatient renewal call site in `clinosim/simulator/outpatient.py`**

Find (around line 210-216):
```python
    # Prescription renewal
    rx = None
    if spec.get("prescriptions_renewed") and patient.current_medications:
        rx = PrescriptionRecord(
            prescription_id=f"RX-{patient.patient_id}-OPD",
            prescriber_id=encounter.attending_physician_id,
            items=[{"drug": med, "duration_days": 30} for med in patient.current_medications],
        )
```
Replace with:
```python
    # Prescription renewal
    rx = None
    if spec.get("prescriptions_renewed") and patient.current_medications:
        rx = PrescriptionRecord(
            prescription_id=f"RX-{patient.patient_id}-OPD",
            prescriber_id=encounter.attending_physician_id,
            issue_date=visit_date,
            items=[{"drug": med, "duration_days": 30} for med in patient.current_medications],
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/e2e/test_alpha_golden.py::TestAlphaGolden::test_discharge_prescription_issue_date_is_deterministic -v -m e2e`
Expected: PASS.

- [ ] **Step 7: Run the full unit + integration suite, plus this e2e file**

Run: `pytest -m "unit or integration" -q && pytest tests/e2e/test_alpha_golden.py -m e2e -v`
Expected: all pass. (If any other test directly calls `_build_discharge_rx(` with positional args, it will now fail to compile — investigation found zero such test call sites, so none are expected to break; if one surfaces, add `admission_time=datetime(2026, 1, 1)` or similar to that call.)

- [ ] **Step 8: Commit**

```bash
git add clinosim/simulator/inpatient.py clinosim/simulator/outpatient.py tests/e2e/test_alpha_golden.py
git commit -m "fix(determinism): thread deterministic admission/visit time into PrescriptionRecord.issue_date"
```

---

### Task 4: `immunization/enricher.py` — fail loud instead of `date.today()` fallback

**Files:**
- Modify: `clinosim/modules/immunization/enricher.py`
- Test: `tests/integration/test_immunization_enricher.py` (add one test)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_as_of(ctx, rec)` now raises `ValueError` instead of returning `date.today()` when neither `ctx.config.snapshot_date` nor any encounter's `admission_datetime` is available. No signature change.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_immunization_enricher.py`:

```python
def test_as_of_raises_when_no_deterministic_reference():
    """No snapshot_date AND no encounters with a valid admission_datetime is a
    caller/test-setup gap, not a real simulation path — fail loud instead of
    silently falling back to date.today() (determinism chain, 2026-07-04)."""
    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    from datetime import date

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p1", age=80, sex="F",
                                date_of_birth=date(1946, 3, 1)),
        encounters=[],
    )
    with pytest.raises(ValueError, match="snapshot_date"):
        enrich_immunizations(_ctx([rec], snapshot=None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_immunization_enricher.py::test_as_of_raises_when_no_deterministic_reference -v`
Expected: FAIL (currently returns `date.today()` silently instead of raising).

- [ ] **Step 3: Edit `_as_of()` in `clinosim/modules/immunization/enricher.py`**

Find:
```python
def _as_of(ctx, rec) -> date:
    snap = _get(_get(ctx, "config"), "snapshot_date", None) if _get(ctx, "config") else None
    if snap:
        y, m, d = (int(x) for x in str(snap).split("-"))
        return date(y, m, d)
    # else: latest encounter admission date, else today
    encs = _get(rec, "encounters", []) or []
    dates = []
    for e in encs:
        adm = _get(e, "admission_datetime")
        if isinstance(adm, datetime):
            dates.append(adm.date())
    return max(dates) if dates else date.today()
```
Replace with:
```python
def _as_of(ctx, rec) -> date:
    snap = _get(_get(ctx, "config"), "snapshot_date", None) if _get(ctx, "config") else None
    if snap:
        y, m, d = (int(x) for x in str(snap).split("-"))
        return date(y, m, d)
    # else: latest encounter admission date
    encs = _get(rec, "encounters", []) or []
    dates = []
    for e in encs:
        adm = _get(e, "admission_datetime")
        if isinstance(adm, datetime):
            dates.append(adm.date())
    if dates:
        return max(dates)
    raise ValueError(
        "immunization _as_of(): no deterministic date reference available — "
        "ctx.config.snapshot_date is unset AND the record has no encounters "
        "with a valid admission_datetime. The CLI always resolves "
        "snapshot_date (default: today, resolved once at invocation) before "
        "any record is processed, so this indicates a caller/test setup gap, "
        "not a real simulation path."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_immunization_enricher.py -v`
Expected: all tests in the file PASS, including the new one and the two pre-existing ones (`test_enricher_fills_immunizations`, `test_enricher_deterministic` — both already supply either a `snapshot` or an encounter with `admission_datetime`, so neither hits the new `raise`).

- [ ] **Step 5: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/immunization/enricher.py tests/integration/test_immunization_enricher.py
git commit -m "fix(determinism): immunization _as_of() fails loud instead of date.today() fallback"
```

---

### Task 5: Blood type sampling — extract helper + wrap with `normalize_probabilities`

**Files:**
- Modify: `clinosim/modules/population/engine.py`
- Test: `tests/unit/test_population_types.py` (add tests — or a new small file if that one doesn't fit; check first)

**Interfaces:**
- Produces: `_sample_blood_type(demo: dict, rng: np.random.Generator) -> str`, a new private module-level function in `clinosim/modules/population/engine.py`, mirroring the existing `_sample_age_band(demo: dict, rng: np.random.Generator) -> tuple[int, int]` and `_sample_surname(name_data: dict, rng: np.random.Generator) -> dict` pattern in the same file.
- Consumes: `normalize_probabilities` from `clinosim.modules._shared` (already imported in this file).

- [ ] **Step 1: Check where population unit tests live**

Run: `grep -n "^def test\|^class" tests/unit/test_population_types.py | head -20`

If this file tests dataclasses only (not `engine.py` sampling functions), create `tests/unit/test_population_engine_sampling.py` instead — mirror whichever convention the grep reveals. The steps below assume the new file `tests/unit/test_population_engine_sampling.py`; adjust the target file if `test_population_types.py` already contains `engine.py` function tests.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_population_engine_sampling.py`:

```python
"""Unit tests for population/engine.py private sampling helpers.

_sample_blood_type added by the determinism chain (2026-07-04) to route
YAML-sourced blood_type weights through normalize_probabilities(fallback=
"raise"), matching the sibling _sample_age_band / _sample_surname pattern
in this file and closing the one YAML-sourced rng.choice(p=...) call site
that bypassed it (0.40+0.30+0.20+0.10 sums to 0.9999999999999999 in float64).
"""
from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit


def test_sample_blood_type_returns_valid_key():
    from clinosim.modules.population.engine import _sample_blood_type
    demo = {"blood_type": {"A": 0.40, "O": 0.30, "B": 0.20, "AB": 0.10}}
    rng = np.random.default_rng(0)
    result = _sample_blood_type(demo, rng)
    assert result in {"A", "O", "B", "AB"}


def test_sample_blood_type_deterministic_with_seed():
    from clinosim.modules.population.engine import _sample_blood_type
    demo = {"blood_type": {"A": 0.40, "O": 0.30, "B": 0.20, "AB": 0.10}}
    r1 = _sample_blood_type(demo, np.random.default_rng(42))
    r2 = _sample_blood_type(demo, np.random.default_rng(42))
    assert r1 == r2


def test_sample_blood_type_uses_default_when_demo_missing_key():
    from clinosim.modules.population.engine import _sample_blood_type
    rng = np.random.default_rng(0)
    result = _sample_blood_type({}, rng)
    assert result in {"O", "A", "B", "AB"}


def test_sample_blood_type_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_blood_type
    demo = {"blood_type": {"A": 0.0, "O": 0.0}}
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_blood_type(demo, rng)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_population_engine_sampling.py -v`
Expected: FAIL with `ImportError: cannot import name '_sample_blood_type'`.

- [ ] **Step 4: Add `_sample_blood_type()` to `clinosim/modules/population/engine.py`**

Add near `_sample_age_band` (after it, around line 474):

```python
def _sample_blood_type(demo: dict, rng: np.random.Generator) -> str:
    bt = demo.get("blood_type", {"O": 0.44, "A": 0.42, "B": 0.10, "AB": 0.04})
    keys = list(bt.keys())
    weights = normalize_probabilities([bt[k] for k in keys], fallback="raise")
    idx = int(rng.choice(len(keys), p=weights))
    return keys[idx]
```

- [ ] **Step 5: Replace the inline sampling at the call site**

Find (around line 144-145):
```python
            bt = demo.get("blood_type", {"O": 0.44, "A": 0.42, "B": 0.10, "AB": 0.04})
            blood_type = str(rng.choice(list(bt.keys()), p=list(bt.values())))
```
Replace with:
```python
            blood_type = _sample_blood_type(demo, rng)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_population_engine_sampling.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 7: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass. (`_sample_blood_type` is a pure drop-in replacement for the two inline lines it replaces — same RNG draw shape (`rng.choice` over the same key list), so no downstream determinism shift for any patient whose blood_type weights already summed cleanly to 1.0.)

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/population/engine.py tests/unit/test_population_engine_sampling.py
git commit -m "fix(determinism): route blood_type sampling through normalize_probabilities"
```

---

### Task 6: End-to-end determinism regression test

**Files:**
- Modify: `tests/e2e/test_alpha_golden.py`

**Interfaces:**
- Consumes: `run_alpha`, `SimulatorConfig` (already imported in this file). Depends on Task 2 and Task 3 landing first (this test asserts the outcome of both).

- [ ] **Step 1: Write the test**

Add to `class TestAlphaGolden:` in `tests/e2e/test_alpha_golden.py`, after the test added in Task 3:

```python
    def test_state_and_prescription_timestamps_reproducible_across_runs(self, alpha_result):
        """Two independent run_alpha(seed=42) calls, with real wall-clock time
        elapsed between them, must produce byte-identical
        physiological_states[].timestamp and discharge_prescription.issue_date.
        This is the end-to-end proof that the determinism chain (2026-07-04)
        closed both byte-diff-measured live fields — if either still read
        datetime.now() under the hood, this test would be flaky (values would
        differ by however many milliseconds/seconds elapsed between the two
        calls below)."""
        result2 = run_alpha(SimulatorConfig(random_seed=42))
        r1 = alpha_result.patients[0]
        r2 = result2.patients[0]

        assert [s.timestamp for s in r1.physiological_states] == \
            [s.timestamp for s in r2.physiological_states]

        assert r1.discharge_prescription is not None
        assert r2.discharge_prescription is not None
        assert r1.discharge_prescription.issue_date == r2.discharge_prescription.issue_date
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/e2e/test_alpha_golden.py::TestAlphaGolden::test_state_and_prescription_timestamps_reproducible_across_runs -v -m e2e`
Expected: PASS (Tasks 2 and 3 already made both fields deterministic; this test formalizes that as a standing regression guard rather than a one-off manual check).

- [ ] **Step 3: Run the full e2e suite**

Run: `pytest -m e2e -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_alpha_golden.py
git commit -m "test(determinism): e2e regression guard for physiological_states + prescription issue_date"
```

---

### Task 7: Final verification sweep

**Files:** none modified (verification only, plus a possible cleanup commit if the grep in Step 1 finds an unexpected hit)

- [ ] **Step 1: Grep for any remaining reachable wall-clock reads**

Run:
```bash
grep -rn "datetime\.now()\|date\.today()" clinosim/ --include="*.py"
```

Expected remaining hits, and only these (confirm each matches one of these categories — if anything else appears, it's a gap and must be fixed before proceeding):
- `clinosim/simulator/cli.py` — the `--end` flag's documented default resolution ("today" when omitted), a single legitimate wall-clock read at the program's entry boundary, resolved once into `config.snapshot_date`.
- Any `generated_at`/`generation_timestamp` provenance field assignment (narrative version manifest, CIF export metadata) — intentionally non-deterministic by design, per the spec's out-of-scope section.
- The sentinel constant definitions themselves do NOT call `datetime.now()`/`date.today()` (they call `datetime(1970, 1, 1)`/`date(1970, 1, 1)`, fixed literals) — these will not appear in this grep at all.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -x -q`
Expected: all unit + integration + e2e tests pass (the full ~234+ test suite, unit+integration ~2 min, e2e golden ~8 min per project convention).

- [ ] **Step 3: Run `clinosim audit run` on a small US + JP cohort**

Run:
```bash
python -m clinosim.simulator.cli generate --population 50 --country US --seed 42 -o /tmp/determinism_audit_us
python -m clinosim.simulator.cli audit run --cif-dir /tmp/determinism_audit_us/cif
python -m clinosim.simulator.cli generate --population 50 --country JP --seed 42 -o /tmp/determinism_audit_jp
python -m clinosim.simulator.cli audit run --cif-dir /tmp/determinism_audit_jp/cif
```
(Adjust the exact CLI subcommand/flags to match current `clinosim` CLI usage if it has drifted — check `python -m clinosim.simulator.cli --help` and `python -m clinosim.simulator.cli audit --help` first if these exact flags don't match.)

Expected: no new clinical-axis or silent_no_op-axis failures compared to a baseline run on `master` before this branch's changes (a FAIL here would indicate this chain's timestamp changes shifted some clinically-meaningful derived value in an unexpected way — investigate before proceeding if so).

- [ ] **Step 4: Run the regression golden suite**

Run: `pytest -m regression -q`
Expected: all pass unchanged (this chain does not touch narrative rendering — `cif/narratives/**` — only structural CIF fields; the AD-66 golden suite diffs narratives only, confirmed during investigation, so no golden regeneration is expected to be needed. If any golden test fails, that's a signal this chain had an unexpected side effect on narrative content — investigate rather than blindly regenerating goldens per AD-66 Rule 2.)

- [ ] **Step 5: Update `TODO.md`**

Remove the now-completed entry:
```markdown
### ★★ Determinism chain: wall-clock removal (extends session-30 TODO)

Byte-diff-measured live fields: `discharge_prescription.issue_date` +
`physiological_states[].timestamp` (+ metadata generation_timestamp, by design). New finds:
`diagnosis/engine.py:173 datetime.now()` (live in inpatient path), `immunization/enricher.py:30
date.today()` fallback, `default_factory=datetime.now` across `types/clinical.py` /
`types/encounter.py` / `types/procedure.py`. ALSO: fix `locale/jp/demographics.yaml` blood_type
weights (sum = 0.9999999999999999) then wrap population blood_type sampling with
`normalize_probabilities(fallback="raise")` (the one site R6 had to skip byte-safely).
Outcome: full byte-diff incl. structural CIF.
```
from `TODO.md`. If `TODO.md` has a "Recently completed" or changelog-style section at the top, add a one-line entry there instead of just deleting (follow whatever convention the file already uses — check the top of `TODO.md` before editing).

- [ ] **Step 6: Commit**

```bash
git add TODO.md
git commit -m "docs: mark determinism chain wall-clock removal complete in TODO.md"
```

---

## Post-plan note for the executing agent

After Task 7, hand off to `superpowers:finishing-a-development-branch` to decide on PR vs direct merge (this repo's established pattern per `docs/design-guides/project-concept-and-design.md` and prior chains — see memory `feedback_iterative_adversarial_review.md` for whether a 5-lens adversarial review pass is warranted before merge for a chain of this size touching 4 type files + 5 simulator/module files).
