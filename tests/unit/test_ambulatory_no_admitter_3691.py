"""Issue #3691: ADM / DIS participants only on IMP and EMER Encounters."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import _set_participants

pytestmark = pytest.mark.unit


def _types(class_code: str, **enc: str) -> list[str]:
    res: dict = {}
    base = {"attending_physician_id": "DR-1", "discharge_datetime": "2026-03-01T10:00:00"}
    _set_participants(res, {**base, **enc}, class_code, "US")
    return [p["type"][0]["coding"][0]["code"] for p in res.get("participant", [])]


def test_ambulatory_has_only_the_attending_even_with_explicit_ids() -> None:
    assert _types("AMB") == ["ATND"]
    assert _types("AMB", admitting_physician_id="DR-1", discharging_physician_id="DR-1") == ["ATND"]


@pytest.mark.parametrize("class_code", ["IMP", "EMER"])
def test_imp_and_emer_keep_attending_admitter_and_discharger(class_code: str) -> None:
    assert _types(class_code) == ["ATND", "ADM", "DIS"]
    assert _types(class_code, admitting_physician_id="DR-2", discharging_physician_id="DR-3") == ["ATND", "ADM", "DIS"]
