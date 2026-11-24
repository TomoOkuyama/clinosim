"""A delivery stay admitted under its complication (Issue #3661) still gets the
obstetric exam of its mode of delivery, from the record's delivery extension."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.context import _delivery_extension
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_physical_examination,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from tests.unit.modules.document.narrative.test_admission_hp_complete_3245 import _delivery_ctx

pytestmark = pytest.mark.unit
_GEN = TemplateNarrativeGenerator()


@pytest.mark.parametrize(("mode", "contractions"), [("vaginal", True), ("cesarean", False)])
def test_complicated_delivery_keeps_its_obstetric_exam(mode: str, contractions: bool) -> None:
    ctx = _delivery_ctx("en", "O14.9")
    ctx.delivery = {"mode": mode, "gestational_age_days": 276, "complication_codes": ["O14.9"]}
    text = build_physical_examination(_GEN, ctx)[0]
    assert "Obstetric: gravid uterus, fundal height consistent with 39w3d gestation" in text, text
    assert ("contractions palpable" in text) == contractions
    ja = _delivery_ctx("ja", "O14.9")
    ja.delivery = ctx.delivery
    assert "産科: 妊娠子宮を触知し" in build_physical_examination(_GEN, ja)[0]


def test_a_stay_with_neither_delivery_extension_nor_delivery_code_has_no_obstetric_exam() -> None:
    text = build_physical_examination(_GEN, _delivery_ctx("en", "O14.9"))[0]
    assert "Obstetric:" not in text


def test_delivery_extension_projection() -> None:
    assert _delivery_extension(SimpleNamespace(extensions={"delivery": {"mode": "vaginal"}})) == {"mode": "vaginal"}
    assert _delivery_extension(SimpleNamespace(extensions={})) == {}
    assert _delivery_extension({"extensions": None}) == {}
