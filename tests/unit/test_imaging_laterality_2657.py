"""Issue #2657: paired-structure studies carry their side; spine studies name the region."""

from __future__ import annotations

import pytest

from clinosim.modules.imaging.engine import imaging_laterality, imaging_procedure_loinc
from clinosim.modules.imaging.inference import infer_imaging_metadata

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "site", "snomed", "loinc"),
    [
        ("Cervical_Spine_Xray", "cervical_spine", "122494005", "36669-0"),
        ("Lumbar_Xray", "lumbar_spine", "122496007", "36670-8"),
        ("Spine_Xray_AP_Lateral", "lumbar_spine", "122496007", "36670-8"),
        ("MRI_Lumbar", "lumbar_spine", "122496007", "24968-0"),
        ("Spine_MRI", "lumbar_spine", "122496007", "24968-0"),
    ],
)
def test_a_spine_study_names_its_region(name: str, site: str, snomed: str, loinc: str) -> None:
    meta = infer_imaging_metadata(name)
    assert meta is not None and (meta["body_site_key"], meta["body_site_snomed"]) == (site, snomed)
    assert imaging_procedure_loinc(meta["modality"], site, meta["views"], meta["contrast"]) == loinc


@pytest.mark.parametrize("site", ["wrist", "hand", "hip", "knee", "ankle", "foot", "shoulder", "leg"])
def test_a_paired_structure_has_a_stable_side(site: str) -> None:
    side = imaging_laterality("ENC-1", site)
    assert side in ("left", "right")
    assert imaging_laterality("ENC-1", site) == side
    sides = {imaging_laterality(f"ENC-{i}", site) for i in range(40)}
    assert sides == {"left", "right"}


@pytest.mark.parametrize("site", ["chest", "head", "abdomen", "kidney", "lumbar_spine", "heart"])
def test_an_unpaired_or_bilateral_study_has_no_side(site: str) -> None:
    assert imaging_laterality("ENC-1", site) == ""


def test_one_stay_images_one_side() -> None:
    assert len({imaging_laterality("ENC-7", s) for s in ("hip", "wrist", "knee")}) == 1
