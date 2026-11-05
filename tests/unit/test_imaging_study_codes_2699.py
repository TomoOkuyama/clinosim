"""Issue #2699: each imaging study is coded as the study done."""

from __future__ import annotations

import pytest

from clinosim.modules.imaging.engine import imaging_procedure_loinc
from clinosim.modules.imaging.inference import infer_imaging_metadata

pytestmark = pytest.mark.unit


def _loinc(name: str) -> str:
    meta = infer_imaging_metadata(name)
    assert meta is not None, name
    return imaging_procedure_loinc(meta["modality"], meta["body_site_key"], meta["views"], meta["contrast"])


@pytest.mark.parametrize(
    ("name", "loinc"),
    [
        ("Chest_Xray", "42272-5"),  # PA and lateral (the 2-view default)
        ("Chest_Xray_PA_Lateral", "42272-5"),
        ("Chest_Xray_PA", "36554-4"),  # single view
        ("Chest_Xray_portable", "36572-6"),  # portable AP
        ("CT_angiography_head_neck", "37498-3"),
        ("MRA_intracranial", "36881-1"),
        ("CT_Head", "30799-1"),
        ("MRI_brain_DWI", "30657-1"),
    ],
)
def test_the_study_code_is_the_study_done(name: str, loinc: str) -> None:
    assert _loinc(name) == loinc


def test_an_affected_area_xray_is_not_coded_as_chest() -> None:
    meta = infer_imaging_metadata("Xray_affected_area")
    assert meta is None or meta["body_site_key"] != "chest"


def test_an_order_with_explicit_views_matches_its_order_code() -> None:
    assert imaging_procedure_loinc("CR", "chest", ["PA", "Lateral"], False) == "42272-5"
