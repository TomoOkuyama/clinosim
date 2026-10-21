"""Phase 4e cycle-2 regression — annual oncology surveillance fires even
when the chronic_visit's primary disease_id is a non-cancer comorbidity.

Pre-fix (Phase 4e horizontal) only emitted procedures from the single
``followup_spec`` the engine passed in — the spec for ``event.disease_id``,
which equals the ``primary_code`` picked by ``generate_healthcare_calendar``
as ``conditions_with_spec[0][0]`` (yaml iteration order of
``demographics.yaml::chronic_prevalence``). A C34 lung-cancer patient who
also carries I10 (hypertension), E78 (dyslipidemia) etc. gets I10 (or the
earliest yaml-order comorbidity) as primary — the I10 chronic_followup
block has no ``procedures:`` entry so the dispatcher never emits CT 71250.
Surfaced by the p=2000 US seed=42 5-year audit — C34 CT chest fired 0
times across 10 patient-years while sibling cancer families (C50 / C18 /
C16 / C22) fired at ~70-100 % of patient-years.

The fix: the engine's chronic_visit branch now unions ``procedures:`` from
every ``patient.chronic_conditions`` entry that has a chronic_followup
block, not just the primary. Dedup still tracked per-patient per-year via
the existing ``_phase4e_annual_procedures_emitted`` attribute.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import ChronicCondition, PatientProfile


def _patient(code: str, sex: str, age: int, extra_codes: list[str]) -> PatientProfile:
    return PatientProfile(
        patient_id=f"POP-{code}-NONPRIMARY-001",
        sex=sex,
        age=age,
        date_of_birth=date(2026 - age, 1, 1),
        chronic_conditions=[ChronicCondition(code=c) for c in extra_codes + [code]],
    )


@pytest.mark.parametrize(
    "cancer_code,cpt,sex,age,primary_code",
    [
        ("C34", "71250", "M", 67, "I10"),  # lung CT during HTN-primary visit
        ("C50", "77067", "F", 54, "I10"),  # mammography during HTN-primary visit
        ("C18", "45378", "F", 65, "E78"),  # colonoscopy during dyslipidemia visit
        ("C16", "43235", "M", 62, "I10"),  # EGD during HTN-primary visit
    ],
)
def test_annual_cancer_surveillance_fires_when_primary_is_comorbidity(cancer_code, cpt, sex, age, primary_code):
    """A chronic_visit whose primary disease_id is a non-cancer comorbidity
    (e.g. I10, E78) must still emit the patient's cancer annual-surveillance
    procedure. Pre-fix: 0 fires for the audit's p=2000 C34 cohort."""
    fu = load_chronic_followup()
    primary_spec = fu.get(primary_code)
    cancer_spec = fu.get(cancer_code)
    assert primary_spec, f"{primary_code} missing"
    assert cancer_spec, f"{cancer_code} missing"
    patient = _patient(cancer_code, sex, age, extra_codes=[primary_code])
    rec = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 3, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code=primary_code,
        followup_spec=primary_spec,
        country="US",
    )
    codes = {p.procedure_code for p in rec.procedures}
    assert cpt in codes, f"{cancer_code} patient on primary={primary_code} visit missing {cpt}; got {codes}"


def test_c34_ct_dedupes_within_same_year_across_nonprimary_visits():
    """Dedup still fires once per calendar year even when the carrier is a
    non-cancer primary — the dispatcher's per-patient per-year map tracks
    by SNOMED, not by visit disease_id."""
    fu = load_chronic_followup()
    i10_spec = fu.get("I10")
    patient = _patient("C34", "M", 67, extra_codes=["I10"])
    rec1 = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 3, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="I10",
        followup_spec=i10_spec,
        country="US",
    )
    assert "71250" in {p.procedure_code for p in rec1.procedures}
    # Second I10-primary visit in the same year must not re-emit CT.
    rec2 = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 7, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        chronic_code="I10",
        followup_spec=i10_spec,
        country="US",
    )
    assert "71250" not in {p.procedure_code for p in rec2.procedures}
