"""The sampled newborn P-chapter conditions reach the birth encounter
diagnosis and are conditioned on the record (Issue #3669): P07.3 / P22.0 only
for a preterm gestational age, P59.9 only for a measured bilirubin at or above
the documentation threshold."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.locale.loader import load_perinatal_config
from clinosim.modules.newborn import build_bilirubin_observations, enrich_newborn
from clinosim.modules.newborn.engine import load_newborn_config
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import _sample_newborn_conditions, simulate_delivery_encounter
from clinosim.types.patient import PatientProfile, TemporalStatePeriod
from tests.unit.modules.newborn.test_bilirubin_cchd_ophthalmic import _newborn_record

pytestmark = pytest.mark.unit
_DAY = date(2025, 7, 15)
_TERM, _PRETERM = 280, 250


def _codes(pid: str, ga: int | None) -> list[str]:
    return [c.code for c in _sample_newborn_conditions(pid, _DAY, ga)[1]]


def test_preterm_codes_never_fire_at_term_and_do_fire_below_37_weeks() -> None:
    term = {c for i in range(3000) for c in _codes(f"M{i}", _TERM)}
    assert not term & {"P07.3", "P22.0"}
    preterm = [_codes(f"M{i}", _PRETERM) for i in range(3000)]
    assert 0.04 < sum("P07.3" in c for c in preterm) / 3000 < 0.11
    assert any("P22.0" in c for c in preterm)
    assert not any("P22.0" in c and "P07.3" not in c for c in preterm)


def test_an_unknown_gestational_age_does_not_assert_preterm() -> None:
    assert not {c for i in range(1000) for c in _codes(f"M{i}", None)} & {"P07.3", "P22.0"}


def test_jaundice_is_not_an_independent_draw() -> None:
    assert not any("P59.9" in _codes(f"M{i}", ga) for i in range(1500) for ga in (_TERM, _PRETERM))


def test_the_gate_does_not_move_the_stream_of_the_other_conditions() -> None:
    """Suppressing a preterm code keeps every draw, so the other sampled conditions are the same."""
    for i in range(300):
        a = [c.code for c in _sample_newborn_conditions(f"M{i}", _DAY, _TERM)[0]]
        b = [c.code for c in _sample_newborn_conditions(f"M{i}", _DAY, _PRETERM)[0]]
        assert a == b


def _preterm_mother(pid: str) -> PatientProfile:
    patient = PatientProfile(patient_id=pid, sex="F", age=30)
    delivery = datetime(2025, 7, 15, 10, 0)
    lmp = delivery.date() - timedelta(days=_PRETERM)
    patient.state_periods = [
        TemporalStatePeriod(
            state_type="pregnancy",
            start_date=lmp,
            end_date=None,
            outcome="",
            metadata={
                "lmp": lmp,
                "edd": lmp + timedelta(days=280),
                "planned_delivery_date": delivery.date(),
                "complications": [],
            },
            period_seq=0,
        )
    ]
    return patient


def test_every_sampled_code_is_a_diagnosis_of_the_birth_encounter() -> None:
    seen = set()
    for i in range(1, 400):
        mother = _preterm_mother(f"POP-{i:06d}")
        baby = simulate_delivery_encounter(
            patient=mother,
            visit_date=datetime(2025, 7, 15, 10, 0),
            roster=StaffRoster(),
            rng=np.random.default_rng(1),
            country="US",
            hospital_ops={},
        )[1]
        history = {c.code for c in baby.patient.perinatal_history} - {"Z38.0"}
        working = {d["disease_id"] for d in baby.clinical_diagnosis.working_diagnoses}
        assert history == working
        assert baby.clinical_diagnosis.admission_diagnosis_code == "Z38.0"
        seen |= working
    assert {"P07.3", "P22.0"} <= seen


def _with_bilirubin(pid: str):
    rec = _newborn_record(pid)
    rec.clinical_diagnosis.admission_diagnosis_code = "Z38.0"
    return rec


def _peak(pid: str) -> float:
    return max(e["value_mg_dl"] for e in build_bilirubin_observations(_newborn_record(pid)))


def test_jaundice_follows_the_measured_peak() -> None:
    threshold = float(load_newborn_config()["bilirubin"]["documentation_threshold_mg_dl"])
    high = low = 0
    for i in range(400):
        pid = f"POP-{i:06d}-BABY"
        rec = _with_bilirubin(pid)
        enrich_newborn(SimpleNamespace(records=[rec], config=SimpleNamespace(country="US"), roster=None))
        has = "P59.9" in {c.code for c in rec.patient.perinatal_history}
        in_dx = "P59.9" in {d["disease_id"] for d in rec.clinical_diagnosis.working_diagnoses}
        assert has == in_dx == (_peak(pid) >= threshold), pid
        high += has
        low += not has
    assert high > 20 and low > 20
    # run again: not duplicated
    enrich_newborn(SimpleNamespace(records=[rec], config=SimpleNamespace(country="US"), roster=None))
    assert [c.code for c in rec.patient.perinatal_history].count("P59.9") <= 1


def test_the_threshold_and_rows_are_configured() -> None:
    assert float(load_newborn_config()["bilirubin"]["documentation_threshold_mg_dl"]) > 0
    rows = {r["code"]: r for r in load_perinatal_config()["newborn_conditions"]}
    assert rows["P07.3"]["gestational_weeks_below"] == 37
    assert rows["P59.9"]["derived_from"] == "bilirubin"
