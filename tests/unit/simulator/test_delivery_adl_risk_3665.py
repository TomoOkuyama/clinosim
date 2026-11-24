"""A delivery admission records ADL (Barthel) assessments per hospital day, so
the nursing enricher derives the Braden and Morse scores (Issue #3665)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.locale.loader import load_perinatal_config
from clinosim.modules.observation.nursing_enricher import enrich_nursing
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.enrichers import register_builtin_enrichers
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.config import SimulatorConfig
from clinosim.types.patient import PatientProfile
from tests.unit.simulator.test_perinatal_complication_coding import _CESAREAN, _VAGINAL

pytestmark = pytest.mark.unit


def _mother(pid: str, country: str, *, config: bool = True, age: int = 30):
    register_builtin_enrichers()
    return simulate_delivery_encounter(
        patient=PatientProfile(patient_id=pid, sex="F", age=age),
        visit_date=datetime(2025, 7, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        country=country,
        config=SimulatorConfig(country=country, snapshot_date="2026-01-01", random_seed=7) if config else None,
        hospital_ops={},
    )[0]


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(("pid", "mode"), [(_VAGINAL, "vaginal"), (_CESAREAN, "cesarean")])
def test_delivery_has_adl_per_hospital_day_and_risk_scores(pid: str, mode: str, country: str) -> None:
    rec = _mother(pid, country)
    # the post-records stage derives the risk scores from the ADL rows
    enrich_nursing(SimpleNamespace(records=[rec], master_seed=7))
    enc = rec.encounters[0]
    first, last = enc.admission_datetime.date(), enc.discharge_datetime.date()
    days = [(first + timedelta(days=i)) for i in range((last - first).days + 1)]
    assert [a.date for a in rec.adl_assessments] == days
    scores = [a.barthel_score for a in rec.adl_assessments]
    assert scores == sorted(scores) and scores[-1] >= 90
    cfg = load_perinatal_config()["maternal_adl"][mode]
    assert scores[0] == min(cfg["barthel_by_day"][0], 100)
    for a in rec.adl_assessments:
        assert a.barthel_score == sum(
            (a.feeding, a.bathing, a.grooming, a.dressing, a.bowel_control, a.bladder_control)
            + (a.toilet_use, a.transfers, a.mobility, a.stairs)
        )
    assert [r.date for r in rec.nursing_risk_assessments] == days
    assert all(r.braden_total > 0 and r.morse_total >= 0 for r in rec.nursing_risk_assessments)


def test_a_cesarean_starts_lower_than_a_vaginal_delivery() -> None:
    assert (
        _mother(_CESAREAN, "US").adl_assessments[0].barthel_score
        < _mother(_VAGINAL, "US").adl_assessments[0].barthel_score
    )


def test_adl_does_not_move_the_other_data_of_the_record() -> None:
    a, b = _mother(_VAGINAL, "US", config=False), _mother(_VAGINAL, "US", config=False)
    assert a.vital_signs == b.vital_signs and a.adl_assessments == b.adl_assessments
    assert [o.order_id for o in a.orders] == [o.order_id for o in b.orders]


def test_a_chronic_functional_cap_lowers_the_ceiling() -> None:
    """The premorbid ceiling of a staged chronic condition (dementia) still caps the score."""
    from clinosim.types.patient import ChronicCondition

    patient = PatientProfile(patient_id=_VAGINAL, sex="F", age=30)
    patient.chronic_conditions = [ChronicCondition(code="F00", stage="CDR 3")]
    rec = simulate_delivery_encounter(
        patient=patient,
        visit_date=datetime(2025, 7, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        country="US",
        hospital_ops={},
    )[0]
    assert max(a.barthel_score for a in rec.adl_assessments) < 100
