"""Issue #2655: every imaging study resolves to the body site imaged and a procedure code."""

from __future__ import annotations

import pytest

from clinosim.modules.imaging.engine import _resolve_imaging_procedure_code_key, load_body_sites, load_modalities
from clinosim.modules.imaging.inference import infer_imaging_metadata

pytestmark = pytest.mark.unit

CASES = [
    ("Ankle_Xray", "CR", "ankle", "70258002", "36294-7"),
    ("Foot_Xray", "CR", "foot", "56459004", "36305-1"),
    ("Shoulder_Xray_Post_Reduction", "CR", "shoulder", "16982005", "37840-6"),
    ("Shoulder_Xray_AP_Lateral", "CR", "shoulder", "16982005", "37840-6"),
    ("Echocardiogram", "US", "heart", "80891009", "59281-6"),
    ("Echocardiography_TTE", "US", "heart", "80891009", "59281-6"),
    ("Coronary_angiography", "XA", "coronary_artery", "41801008", "37174-0"),
    ("Carotid_ultrasound", "US", "carotid_artery", "69105007", "24616-5"),
    ("MRCP", "MR", "biliary_tract", "34707002", "58740-2"),
    ("Bladder_ultrasound", "US", "urinary_bladder", "89837001", "25019-1"),
]


@pytest.mark.parametrize(("name", "modality", "site", "snomed", "loinc"), CASES)
def test_the_study_has_its_body_site_and_procedure_code(
    name: str, modality: str, site: str, snomed: str, loinc: str
) -> None:
    meta = infer_imaging_metadata(name)
    assert meta is not None
    assert (meta["modality"], meta["body_site_key"], meta["body_site_snomed"]) == (modality, site, snomed)
    key = _resolve_imaging_procedure_code_key(modality, site, meta["views"], meta["contrast"])
    assert load_body_sites()[site]["procedure_codes"][key]["loinc"] == loinc


@pytest.mark.parametrize(("name", "modality", "site", "snomed", "loinc"), CASES)
def test_the_study_has_a_series(name: str, modality: str, site: str, snomed: str, loinc: str) -> None:
    """A series needs views (and, for per-series modalities, an instance range)."""
    meta = infer_imaging_metadata(name)
    assert meta is not None and meta["views"]
    mod = load_modalities()[modality]
    if "typical_instances_per_series_range" in mod:
        assert site in mod["typical_instances_per_series_range"]
