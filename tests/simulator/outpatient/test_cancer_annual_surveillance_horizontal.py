"""Phase 4e horizontal extension — annual oncology surveillance for
C34 lung, C18 colon, C16 gastric, C22 liver cancer follow-up.

Pure-yaml extension of the Phase 4e `annual` frequency pattern
(piloted on C50 breast cancer mammography). Each cancer family gets a
single annual-imaging/endoscopy Procedure that fires at most once per
patient per calendar year, backed by an NCCN v2024 surveillance
recommendation.

Clinical basis per family:
* C34 lung — low-dose CT chest annually post-dx (NCCN v3.2024 NSCLC
  survivorship §FOLL-A). CPT 71250, SNOMED 169069000.
* C18 colon — colonoscopy annually year 1 post-dx (NCCN v3.2024 Colon
  Cancer §COL-E). CPT 45378, SNOMED 73761001.
* C16 gastric — EGD annually post-dx (NCCN v2.2024 Gastric Cancer
  §GAST-D). CPT 43235, SNOMED 76009000.
* C22 liver (HCC) — abdominal US semi-annually post-dx (NCCN v2.2024
  HCC §HCC-G). CPT 76700, SNOMED 45036003. (We ship `annual` here;
  semi-annual cadence tracked under #1701 残 as a future enhancement
  once a `semi_annual` frequency lands.)
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile


CASES = [
    ("C34", "71250", "F", 68),  # lung CT
    ("C18", "45378", "F", 65),  # colonoscopy
    ("C16", "43235", "M", 62),  # EGD
    ("C22", "76700", "M", 60),  # abdominal US
]


def _patient(code: str, sex: str, age: int) -> PatientProfile:
    return PatientProfile(
        patient_id=f"POP-{code}-001",
        sex=sex,
        age=age,
        date_of_birth=date(2026 - age, 1, 1),
    )


def _visit(patient, code, spec, visit_date, rng_seed=0):
    return _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=visit_date,
        roster=StaffRoster(),
        rng=np.random.default_rng(rng_seed),
        chronic_code=code,
        followup_spec=spec,
        country="US",
    )


@pytest.mark.parametrize("code,cpt,sex,age", CASES)
def test_annual_surveillance_fires_at_first_visit_in_year(code, cpt, sex, age):
    """Each cancer family emits its annual surveillance procedure on
    the first visit in a calendar year."""
    spec = load_chronic_followup().get(code)
    assert spec, f"{code} block missing"
    patient = _patient(code, sex, age)
    rec = _visit(patient, code, spec, datetime(2024, 3, 15, 10, 0))
    codes = {p.procedure_code for p in rec.procedures}
    assert cpt in codes


@pytest.mark.parametrize("code,cpt,sex,age", CASES)
def test_annual_surveillance_dedupes_within_same_year(code, cpt, sex, age):
    """Second visit same year must NOT re-emit the annual procedure."""
    spec = load_chronic_followup().get(code)
    assert spec, f"{code} block missing"
    patient = _patient(code, sex, age)
    _visit(patient, code, spec, datetime(2024, 3, 15, 10, 0))
    rec2 = _visit(patient, code, spec, datetime(2024, 6, 15, 10, 0), rng_seed=1)
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert cpt not in codes2


@pytest.mark.parametrize("code,cpt,sex,age", CASES)
def test_annual_surveillance_re_fires_next_year(code, cpt, sex, age):
    """A visit in a new calendar year re-emits the annual procedure."""
    spec = load_chronic_followup().get(code)
    assert spec, f"{code} block missing"
    patient = _patient(code, sex, age)
    _visit(patient, code, spec, datetime(2024, 12, 15, 10, 0))
    rec2 = _visit(patient, code, spec, datetime(2025, 2, 15, 10, 0), rng_seed=1)
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert cpt in codes2
