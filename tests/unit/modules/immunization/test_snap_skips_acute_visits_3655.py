"""A routine dose is not given at a febrile or acute-illness visit (Issue #3655)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization.enricher import (
    _align_to_encounters,
    acute_visit_encounter_ids,
)
from clinosim.modules.pediatric.calendar import is_acute_illness_condition
from clinosim.types.encounter import ImmunizationRecord, VitalSignRecord

pytestmark = pytest.mark.unit


def _enc(enc_id: str, adm: datetime) -> SimpleNamespace:
    return SimpleNamespace(encounter_id=enc_id, admission_datetime=adm, encounter_type="outpatient")


def _record(enc: SimpleNamespace, visit_type: str, condition: str, temp: float | None = None) -> SimpleNamespace:
    vitals = [VitalSignRecord(timestamp=enc.admission_datetime.replace(minute=5), temperature_celsius=temp)]
    return SimpleNamespace(
        encounters=[enc],
        condition_event=SimpleNamespace(visit_type=visit_type, visit_condition_id=condition),
        vital_signs=vitals if temp is not None else [],
    )


def test_acute_illness_helper_covers_the_presentation_visits() -> None:
    for cond in ("pediatric_uri", "pediatric_otitis_media", "pediatric_bronchiolitis", "pediatric_injury"):
        assert is_acute_illness_condition(cond)
    for cond in ("well_child_infant", "immunization_infant", "I10", "", "flu_vaccination"):
        assert not is_acute_illness_condition(cond)


def test_acute_pediatric_visit_and_febrile_visit_are_excluded() -> None:
    acute = _enc("ENC-ACUTE", datetime(2026, 9, 20, 10, 0))
    fever = _enc("ENC-FEVER", datetime(2026, 9, 21, 10, 0))
    well = _enc("ENC-WELL", datetime(2026, 9, 22, 10, 0))
    cool = _enc("ENC-COOL", datetime(2026, 9, 23, 10, 0))
    records = [
        _record(acute, "pediatric_visit", "pediatric_uri"),
        _record(fever, "chronic_followup", "I10", temp=38.0),
        _record(well, "pediatric_visit", "well_child_early", temp=36.8),
        _record(cool, "chronic_followup", "I10", temp=37.9),
    ]
    assert acute_visit_encounter_ids(records) == {"ENC-ACUTE", "ENC-FEVER"}


def test_dose_snaps_to_the_well_visit_not_the_nearer_acute_visit() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    acute = _enc("ENC-ACUTE", datetime(2026, 10, 2, 10, 0))
    well = _enc("ENC-WELL", datetime(2026, 10, 20, 10, 0))
    out = _align_to_encounters([imm], [acute, well], excluded_encounter_ids=frozenset({"ENC-ACUTE"}))
    assert out[0].encounter_id == "ENC-WELL"
    assert out[0].occurrence_date == date(2026, 10, 20)


def test_only_a_febrile_visit_in_range_leaves_the_dose_unlinked() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    acute = _enc("ENC-ACUTE", datetime(2026, 10, 2, 10, 0))
    out = _align_to_encounters([imm], [acute], excluded_encounter_ids=frozenset({"ENC-ACUTE"}))
    assert out[0].encounter_id == ""
    assert out[0].occurrence_date == date(2026, 10, 1)


def test_without_exclusions_behaviour_is_unchanged() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    acute = _enc("ENC-ACUTE", datetime(2026, 10, 2, 10, 0))
    out = _align_to_encounters([imm], [acute])
    assert out[0].encounter_id == "ENC-ACUTE"
