"""Issue #2654: the study performed matches the order (region and contrast)."""

from __future__ import annotations

import pytest

from clinosim.modules.imaging.engine import _resolve_imaging_procedure_code_key, load_body_sites
from clinosim.modules.imaging.inference import infer_imaging_metadata

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("order", "site", "contrast", "loinc"),
    [
        ("CT_abdomen_pelvis_with_contrast", "abdomen_pelvis", True, "36813-4"),
        ("CT_abdomen_pelvis", "abdomen_pelvis", False, "36952-0"),
        ("CT_abdomen_pelvis_with_contrast_repeat", "abdomen_pelvis", True, "36813-4"),
        ("CT abdomen with contrast", "abdomen", True, "79103-8"),
        ("CT abdomen", "abdomen", False, "36424-0"),
    ],
)
def test_the_study_follows_the_order_name(order: str, site: str, contrast: bool, loinc: str) -> None:
    meta = infer_imaging_metadata(order)
    assert meta is not None
    assert (meta["body_site_key"], meta["contrast"]) == (site, contrast)
    key = _resolve_imaging_procedure_code_key(meta["modality"], site, meta["views"], meta["contrast"])
    assert load_body_sites()[site]["procedure_codes"][key]["loinc"] == loinc


def test_a_non_contrast_order_is_not_read_as_contrast() -> None:
    for name in ("CT head noncontrast", "CT abdomen non-contrast", "CT abdomen without contrast"):
        meta = infer_imaging_metadata(name)
        assert meta is not None and meta["contrast"] is False, name
