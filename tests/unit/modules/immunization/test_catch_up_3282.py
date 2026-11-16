"""Issue #3282: a child behind on a series is caught up at the kindergarten
and adolescent vaccination visits, and the visit label names no vaccines.

Catch-up continues the series with its next dose (never a restart) when the
visit age is within the series' catch-up age limit
(``catch_up_max_age_days``: CDC catch-up schedule for the US, the 予防接種法施行令
target ages for JP) and the series' minimum interval since the last dose
holds. A series with a charted refusal is not caught up.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization.engine import load_schedule
from clinosim.modules.immunization.visits import (
    VaccinationVisit,
    bind_to_vaccination_visits,
    vaccination_visits_by_patient,
)
from clinosim.modules.pediatric.calendar import catch_up_visit_reasons, load_pediatric_schedule
from clinosim.types.encounter import Encounter, EncounterType, ImmunizationRecord

pytestmark = pytest.mark.unit

_DOB = date(2019, 2, 1)
_KG_DAY = date(2024, 6, 10)  # 5 y 4 m


def _child(dob: date = _DOB) -> SimpleNamespace:
    return SimpleNamespace(patient_id="C1", age=5, sex="M", date_of_birth=dob, chronic_conditions=[])


def _visit(day: date = _KG_DAY, catch_up: bool = True) -> VaccinationVisit:
    return VaccinationVisit(encounter_id="ENC-KG", day=day, is_flu=False, catch_up=catch_up)


def _dose(cvx: str, day: date, number: int, status: str = "completed") -> ImmunizationRecord:
    return ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=day, dose_number=number, status=status)


def _bind(recs: list, visit: VaccinationVisit, schedule: dict, dob: date = _DOB) -> list:
    return bind_to_vaccination_visits(
        recs,
        [visit],
        _child(dob),
        schedule,
        as_of=date(2025, 12, 31),
        sim_start=date(2023, 1, 1),
        flu_visit_candidate=False,
        nurse="N1",
    )


def _us(*names: str) -> dict:
    schedule = load_schedule("US")
    return {n: schedule[n] for n in names}


def _at_visit(out: list) -> list[tuple[str, int | None, str]]:
    return sorted((r.vaccine_cvx, r.dose_number, r.status) for r in out if r.encounter_id == "ENC-KG")


def test_a_child_behind_on_dtap_gets_the_next_dose_at_the_kindergarten_visit() -> None:
    """POP-002541 of the issue: DTaP 1-2 in infancy, nothing since."""
    recs = [_dose("20", date(2019, 4, 3), 1), _dose("20", date(2019, 6, 5), 2)]
    out = _bind(recs, _visit(), _us("pediatric_dtap"))
    assert _at_visit(out) == [("20", 3, "completed")]
    new = next(r for r in out if r.encounter_id == "ENC-KG")
    assert new.occurrence_date == _KG_DAY
    assert new.administered_by == "N1"
    assert "-202406-" in new.lot_number


def test_a_visit_without_catch_up_keeps_the_series_unrestarted() -> None:
    recs = [_dose("20", date(2019, 4, 3), 1), _dose("20", date(2019, 6, 5), 2)]
    out = _bind(recs, _visit(catch_up=False), _us("pediatric_dtap"))
    assert _at_visit(out) == [("20", 5, "not-done")]


def test_an_unvaccinated_child_starts_mmr_at_the_kindergarten_visit() -> None:
    out = _bind([], _visit(), _us("pediatric_mmr"))
    assert _at_visit(out) == [("03", 1, "completed")]


def test_a_series_with_a_charted_refusal_is_not_caught_up() -> None:
    recs = [_dose("20", date(2019, 4, 3), 1), _dose("20", date(2019, 6, 5), 2, status="not-done")]
    out = _bind(recs, _visit(), _us("pediatric_dtap"))
    assert [(r.dose_number, r.status) for r in out if r.encounter_id == "ENC-KG" and r.status == "completed"] == []


def test_dtap_is_not_caught_up_from_age_seven() -> None:
    """CDC catch-up: DTaP covers 4 months-6 years; from 7 years Tdap/Td is used."""
    dob = date(2016, 1, 1)
    recs = [_dose("20", date(2016, 3, 3), 1), _dose("20", date(2016, 5, 5), 2)]
    out = _bind(recs, _visit(day=date(2024, 6, 10)), _us("pediatric_dtap"), dob=dob)
    assert all(r.status != "completed" or r.encounter_id != "ENC-KG" for r in out)


def test_catch_up_keeps_the_minimum_interval_since_the_last_dose() -> None:
    """DTaP dose 4 comes at least 6 months after dose 3."""
    recs = [
        _dose("20", date(2019, 4, 3), 1),
        _dose("20", date(2019, 6, 5), 2),
        _dose("20", date(2024, 3, 1), 3),
    ]
    out = _bind(recs, _visit(), _us("pediatric_dtap"))
    assert [r for r in out if r.encounter_id == "ENC-KG" and r.status == "completed"] == []


def test_series_without_a_catch_up_limit_are_not_caught_up() -> None:
    """Hib / PCV / rotavirus: a late start changes the number of doses (CDC
    catch-up notes), so they are not continued dose by dose."""
    out = _bind([], _visit(), _us("pediatric_hib", "pediatric_pcv13", "pediatric_rotavirus"))
    assert [r for r in out if r.status == "completed"] == []


def test_one_catch_up_dose_per_series_and_in_window_doses_first() -> None:
    recs = [_dose("03", date(2020, 2, 3), 1)]
    recs += [_dose("20", date(2019, 4, 3), 1), _dose("20", date(2019, 6, 5), 2)]
    out = _bind(recs, _visit(), _us("pediatric_dtap", "pediatric_mmr"))
    assert _at_visit(out) == [("03", 2, "completed"), ("20", 3, "completed")]


def test_jp_dtap_ipv_booster_is_caught_up_before_90_months() -> None:
    """予防接種法施行令: 第1期は生後2月から生後90月に至るまで。"""
    schedule = {"dtap_ipv": load_schedule("JP")["pediatric_dtap_ipv"]}
    recs = [
        _dose("106", date(2019, 5, 2), 1),
        _dose("106", date(2019, 6, 1), 2),
        _dose("106", date(2019, 7, 1), 3),
    ]
    out = _bind(recs, _visit(), schedule)
    assert _at_visit(out) == [("106", 4, "completed")]
    late = _bind(recs, _visit(day=date(2026, 9, 1)), schedule)  # 7 y 7 m
    assert [r for r in late if r.encounter_id == "ENC-KG" and r.status == "completed"] == []


def test_catch_up_limits_in_the_schedules() -> None:
    us = load_schedule("US")
    assert us["pediatric_dtap"]["catch_up_max_age_days"] < 7 * 366
    for name in ("pediatric_ipv", "pediatric_mmr", "pediatric_varicella", "pediatric_hepb", "pediatric_hepa"):
        assert 18 * 365 < us[name]["catch_up_max_age_days"] < 19 * 366
    for name in ("pediatric_hib", "pediatric_pcv13", "pediatric_rotavirus"):
        assert "catch_up_max_age_days" not in us[name]
    jp = load_schedule("JP")
    assert {n for n, v in jp.items() if "catch_up_max_age_days" in v} == {"pediatric_dtap_ipv", "pediatric_je"}
    for v in list(us.values()) + list(jp.values()):
        if "catch_up_max_age_days" in v:
            assert v["frequency"] == "pediatric_series"
            assert isinstance(v["catch_up_max_age_days"], int)


def test_kindergarten_and_adolescent_visits_catch_up_and_name_no_vaccine() -> None:
    schedule = load_pediatric_schedule()
    flagged = {k for k, v in schedule.items() if v.get("catch_up")}
    assert flagged == {"immunization_kindergarten", "immunization_adolescent"}
    vaccine_words = ("DTaP", "IPV", "MMR", "varicella", "Tdap", "HPV", "MCV4", "DPT", "MR", "水痘", "髄膜炎菌")
    for key in flagged:
        reason = schedule[key]["visit_reason"]
        assert schedule[key]["vaccination"]
        for text in reason.values():
            assert not any(w in text for w in vaccine_words), text
    reasons = catch_up_visit_reasons()
    assert schedule["immunization_kindergarten"]["visit_reason"]["ja"] in reasons
    assert schedule["immunization_infant"]["visit_reason"]["en"] not in reasons


def test_vaccination_visits_carry_the_catch_up_flag_from_the_visit_reason() -> None:
    schedule = load_pediatric_schedule()

    def _rec(eid: str, chief: str):
        enc = Encounter(
            encounter_id=eid,
            encounter_type=EncounterType.OUTPATIENT,
            admission_datetime=datetime(2024, 11, 1, 9),
            chief_complaint=chief,
        )
        return SimpleNamespace(
            patient=SimpleNamespace(patient_id="P1"),
            encounters=[enc],
            clinical_diagnosis=SimpleNamespace(admission_diagnosis_code="Z23"),
        )

    visits = vaccination_visits_by_patient(
        [
            _rec("E-KG", schedule["immunization_kindergarten"]["visit_reason"]["ja"]),
            _rec("E-INF", schedule["immunization_infant"]["visit_reason"]["en"]),
        ]
    )["P1"]
    assert sorted((v.encounter_id, v.catch_up) for v in visits) == [("E-INF", False), ("E-KG", True)]
