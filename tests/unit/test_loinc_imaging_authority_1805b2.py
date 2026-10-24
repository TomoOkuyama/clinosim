"""Phase B.2 Part 1 of META #1805: LOINC imaging-procedure authority.

Pre-fix the 19 imaging LOINC codes used by the simulator's
ImagingStudy / ServiceRequest emit path lived nowhere in
``clinosim/codes/data/loinc.yaml`` — the only EN+JA source was the
inline ``display_en`` / ``display_ja`` fields on
``clinosim/modules/imaging/reference_data/body_sites.yaml::
procedure_codes[*]``.

Fix (Part 1): register all 19 codes in loinc.yaml with their current
clinosim composite display strings. A follow-up PR (Part 2) will
swap the emit-side display source to ``code_lookup("loinc", code,
lang)`` and retire the inline fields; Part 1 ships the authority
only, which byte-preserves current FHIR output and unblocks the
display migration.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup

pytestmark = pytest.mark.unit


_EXPECTED = {
    # EN = LOINC Long Common Name (authoritative via NLM / Regenstrief
    # 2.82 snapshot). JA = clinosim-curated translation of the current
    # emit-time composite label.
    "36572-6": ("XR Chest AP", "胸部単純X線撮影 正面・側面"),
    "29252-4": ("CT Chest WO contrast", "胸部CT 単純"),
    "24628-0": ("CT Chest W contrast IV", "胸部CT 造影"),
    "30799-1": ("CT Head WO contrast", "頭部CT 単純"),
    "24725-4": ("CT Head", "頭部CT"),
    "30657-1": ("MR Brain WO contrast", "頭部MRI 単純"),
    "24799-9": ("XR Abdomen AP", "腹部単純X線撮影 正面"),
    "37636-8": ("XR Abdomen Views", "腹部単純X線撮影 臥位・立位"),
    "41806-1": ("CT Abdomen", "腹部CT 単純"),
    "24558-9": ("US Abdomen", "腹部超音波検査"),
    "38036-0": ("US Kidney", "腎臓超音波検査"),
    "99607-4": ("US.doppler Lower extremity vein - bilateral for venous mapping", "下肢静脈超音波検査（DVT評価）"),
    "80861-8": ("US Lower extremity soft tissue", "軟部組織超音波検査"),
    "24722-1": ("XR Hand 3 Views", "手部単純X線撮影 3方向"),
    "36663-3": ("XR Hip 2 Views", "股関節単純X線撮影 正面・側面"),
    "44203-8": ("Portable XR Cervical and thoracic and lumbar spine Views", "脊椎単純X線撮影 正面・側面"),
    "24932-6": ("CT Cervical spine", "脊椎CT 単純"),
    "24968-0": ("MR Lumbar spine", "脊椎MRI 単純"),
    "24619-9": ("XR Wrist Views", "手関節単純X線撮影 3方向"),
}


@pytest.mark.parametrize("code,expected", _EXPECTED.items())
def test_loinc_imaging_code_resolves_en_ja(code: str, expected: tuple[str, str]) -> None:
    """Every imaging LOINC used by body_sites.yaml procedure_codes
    now resolves EN+JA against the loinc.yaml authority."""
    en_expected, ja_expected = expected
    assert code_lookup("loinc", code, "en") == en_expected, f"{code} EN mismatch"
    assert code_lookup("loinc", code, "ja") == ja_expected, f"{code} JA mismatch"


def test_19_imaging_codes_registered() -> None:
    """Shape invariant: all 19 unique LOINC codes used by
    body_sites.yaml procedure_codes are now in the authority. The
    count pins against future accidental deletion."""
    missing = [code for code in _EXPECTED if not code_lookup("loinc", code, "en")]
    assert not missing, "codes missing from authority: " + ", ".join(missing)
    assert len(_EXPECTED) == 19, "Phase B.2 Part 1 target: 19 codes"
