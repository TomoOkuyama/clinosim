"""Issue #3688: the newborn H&P plan and the discharge summary list a vaccine
given during the birth stay (the US hepatitis B birth dose)."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.document.narrative._hospital_course import newborn_prophylaxis_sentence, stay_vaccines
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import newborn_plan_items
from tests.unit.modules.document.narrative.test_newborn_documents_3260 import _ctx

pytestmark = pytest.mark.unit

_HEPB = {"vaccine_cvx": "08", "occurrence_date": date(2026, 1, 26), "encounter_id": "ENC-1", "status": "completed"}


def _with(lang: str, imms: list[dict]):
    ctx = _ctx(lang)
    ctx.immunizations = imms
    return ctx


def test_discharge_course_lists_the_birth_dose_with_its_day_of_life() -> None:
    line, _ = newborn_prophylaxis_sentence(_with("en", [_HEPB]))
    assert "Hep B" in line and "day of life 0" in line, line


def test_discharge_course_ja() -> None:
    line, _ = newborn_prophylaxis_sentence(_with("ja", [_HEPB]))
    assert "日齢0" in line and "B型肝炎" in line, line


def test_h_and_p_plan_lists_the_vaccine() -> None:
    items = newborn_plan_items(_with("en", [_HEPB]))
    assert any(i.startswith("Vaccine at birth: Hep B") for i in items), items
    assert any("出生時のワクチン接種: B型肝炎" in i for i in newborn_plan_items(_with("ja", [_HEPB])))


def test_no_immunization_no_vaccine_line() -> None:
    assert stay_vaccines(_with("en", [])) == []
    assert not any("Vaccine" in i for i in newborn_plan_items(_with("en", [])))


def test_a_dose_of_another_encounter_or_not_completed_is_ignored() -> None:
    other = {**_HEPB, "encounter_id": "ENC-VAX-9"}
    refused = {**_HEPB, "status": "not-done"}
    assert stay_vaccines(_with("en", [other, refused])) == []
