"""Issue #3467: the ED note of a via-ED admission names the drugs given in the
ED window, including those of a safety-rule order that has no order set."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_workup
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.triage.engine import admitted_ed_stay
from clinosim.types.encounter import MedicationAdministration
from tests.unit.modules.document.narrative.test_ed_note_content_3244 import _ctx

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_ADMISSION = datetime(2025, 11, 20, 19, 35)
_ED_START = _ADMISSION - admitted_ed_stay()


def _mar(name: str, when: datetime, status: str = "given") -> MedicationAdministration:
    return MedicationAdministration(
        order_id=f"O-{name}", drug_name=name, scheduled_datetime=when, actual_datetime=when, status=status
    )


def _order(name: str, when: datetime, order_set: str = "") -> dict:
    return {
        "order_id": f"O-{name}",
        "encounter_id": "ENC-1",
        "order_type": "medication",
        "display_name": name,
        "ordered_datetime": when.isoformat(),
        "order_set": order_set,
    }


def _workup(lang: str, orders: list, medications: list) -> str:
    ctx = _ctx("low_back_pain", lang, orders=orders, medications=medications)
    ctx.encounter.encounter_type.value = "inpatient"
    ctx.encounter.admission_datetime = _ADMISSION
    ctx.authored_datetime = _ADMISSION
    return build_ed_workup(_GEN, ctx)[0]


def _case(lang: str) -> str:
    inside = _ED_START + timedelta(minutes=70)
    return _workup(
        lang,
        orders=[
            _order("Furosemide 40mg IV", _ED_START + timedelta(minutes=10), "admission_initial"),
            _order("Calcium Gluconate 1g IV", inside),
            _order("Heparin 5000 units SC", _ADMISSION + timedelta(hours=1), "daily"),
        ],
        medications=[
            _mar("Furosemide", _ED_START + timedelta(minutes=15)),
            _mar("Calcium Gluconate", inside + timedelta(minutes=5)),
            _mar("Insulin", inside + timedelta(minutes=10)),
            _mar("Patiromer", inside + timedelta(minutes=20), status="held"),
            _mar("Aspirin", _ADMISSION),
            _mar("Heparin", _ADMISSION + timedelta(hours=2)),
        ],
    )


def test_the_ed_window_drugs_are_listed_once() -> None:
    text = _case("en")
    assert text.count("Furosemide") == 1, text
    assert "Calcium Gluconate" in text and "Insulin" in text, text


def test_drugs_outside_the_window_or_not_given_are_not_listed() -> None:
    text = _case("en")
    for name in ("Aspirin", "Heparin", "Patiromer"):
        assert name not in text, text


def test_the_japanese_note_names_the_drugs_in_japanese() -> None:
    text = _case("ja")
    assert "Insulin" not in text and "Calcium" not in text, text
