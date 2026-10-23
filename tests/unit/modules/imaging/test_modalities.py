"""Unit tests for clinosim.modules.imaging modalities YAML loader/validator.

META #1805 Phase C: display_en/display_ja on each modality were retired.
Displays live in clinosim/codes/data/dicom-modality.yaml and resolve
via code_lookup("dicom-modality", code, lang) at emit time.
"""

from __future__ import annotations

from clinosim.codes import lookup as code_lookup
from clinosim.modules.imaging.engine import load_modalities


def test_modalities_loads_cr_and_ct():
    m = load_modalities()
    assert "CR" in m
    assert "CT" in m


def test_modality_cr_has_required_fields():
    m = load_modalities()
    cr = m["CR"]
    assert cr["dicom_code"] == "CR"
    # CR = 1 view = 1 instance
    assert cr["typical_instances_per_view_range"] == [1, 1]
    assert "chest" in cr["default_views_by_body_site"]


def test_dicom_modality_authority_displays_match_pre_fix_strings():
    """META #1805 Phase C: the retired display_en/display_ja now
    resolve through the dicom-modality authority yaml. Pin the EN+JA
    for the six supported modalities so byte-level FHIR output is
    unchanged for pre-fix cohorts."""
    expected = {
        "CR": ("Plain X-ray", "単純X線撮影"),
        "CT": ("Computed Tomography", "コンピュータ断層撮影"),
        "MR": ("Magnetic Resonance Imaging", "磁気共鳴画像"),
        "US": ("Ultrasound", "超音波検査"),
        "XA": ("X-Ray Angiography", "血管造影撮影"),
        "ECG": ("Electrocardiography", "心電図検査"),
    }
    for code, (en, ja) in expected.items():
        assert code_lookup("dicom-modality", code, "en") == en, f"{code} EN drift"
        assert code_lookup("dicom-modality", code, "ja") == ja, f"{code} JA drift"


def test_every_modality_resolves_in_authority():
    """Shape invariant: every modality in modalities.yaml has a
    matching entry in the dicom-modality authority."""
    for mod_key in load_modalities():
        en = code_lookup("dicom-modality", mod_key, "en")
        assert en and en != mod_key, f"{mod_key} missing EN in dicom-modality authority"


def test_modality_ct_has_per_body_site_instance_range():
    m = load_modalities()
    ct = m["CT"]
    assert ct["dicom_code"] == "CT"
    assert ct["typical_instances_per_series_range"]["head"] == [180, 280]
    assert ct["typical_instances_per_series_range"]["chest"] == [220, 340]


def test_modalities_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls return same object."""
    assert load_modalities() is load_modalities()
