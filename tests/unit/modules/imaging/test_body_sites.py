"""Unit tests for body_sites YAML loader/validator.

META #1805 Phase B: top-level body_site display_en / display_ja fields
retired. Displays live in clinosim/codes/data/snomed-ct.yaml and
resolve at emit time via code_lookup("snomed-ct", bs.snomed, lang).
Nested procedure_codes[*].display_en/ja are COMPOSITE procedure
descriptions (not a direct code SoT) and remain.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.imaging.engine import _validate_body_sites, load_body_sites


def test_body_sites_loads_chest_and_head():
    bs = load_body_sites()
    assert "chest" in bs
    assert "head" in bs


def test_chest_has_cr_and_ct_procedure_codes():
    bs = load_body_sites()
    chest = bs["chest"]
    assert chest["snomed"] == "51185008"
    assert "CR_PA_Lateral" in chest["procedure_codes"]
    assert "CT_non_contrast" in chest["procedure_codes"]


def test_head_has_ct_non_contrast_procedure_code():
    bs = load_body_sites()
    head = bs["head"]
    assert head["snomed"] == "69536005"
    assert "CT_non_contrast" in head["procedure_codes"]
    code = head["procedure_codes"]["CT_non_contrast"]
    assert code["loinc"] == "30799-1"
    assert code["cpt"] == "70450"


# ----------------------------------------------------------------------------
# META #1805 Phase B: top-level displays flow through snomed-ct.yaml authority
# ----------------------------------------------------------------------------


def test_every_body_site_snomed_resolves_in_authority_with_en_ja():
    """Every top-level body_site SNOMED pointer must resolve against
    snomed-ct.yaml authority with EN+JA — this is the invariant that
    unblocks retiring the per-row display_en/display_ja fields."""
    bs = load_body_sites()
    offenders = []
    for key, row in bs.items():
        snomed = row.get("snomed", "")
        en = code_lookup("snomed-ct", snomed, "en")
        ja = code_lookup("snomed-ct", snomed, "ja")
        if not en or en == snomed:
            offenders.append(f"{key} ({snomed}) missing EN")
        if not ja or ja == snomed:
            offenders.append(f"{key} ({snomed}) missing JA")
    assert not offenders, "; ".join(offenders)


def test_chest_display_resolves_via_authority():
    """Pre-fix the yaml said display_ja = '胸部' inline; post-fix the
    same value comes from the SNOMED authority."""
    bs = load_body_sites()
    chest = bs["chest"]
    assert code_lookup("snomed-ct", chest["snomed"], "ja") == "胸部"


def test_validate_body_sites_raises_on_unregistered_snomed():
    # CO-1 continuation (session 43): SUPPORTED_BODY_SITES expanded to 10
    # sites; mock data must include all so the drift check passes and the
    # per-site SNOMED validation runs. Post-#1805 Phase B: top-level
    # display_en/display_ja fields retired from the required set; nested
    # procedure_codes[*] fields stay.
    def _stub(snomed: str) -> dict:
        return {
            "snomed": snomed,
            "procedure_codes": {
                "stub_proc": {
                    "loinc": "24725-4",
                    "cpt": "70450",
                    "jp_k_code": "K002",
                    "display_en": "stub",
                    "display_ja": "stub",
                },
            },
        }

    data = {
        "body_sites": {
            "chest": {
                "snomed": "99999999999",  # not registered — triggers the SNOMED check
                "procedure_codes": {
                    "cr": {
                        "loinc": "36554-4",
                        "cpt": "71046",
                        "jp_k_code": "K001",
                        "display_en": "X-ray",
                        "display_ja": "X線",
                    },
                },
            },
            "head": _stub("69536005"),
            "abdomen": _stub("818983003"),
            "kidney": _stub("64033007"),
            "leg": _stub("61685007"),
            "skin": _stub("39937001"),
            "hand": _stub("85562004"),
            "hip": _stub("29836001"),
            "spine": _stub("421060004"),
            "wrist": _stub("8205005"),
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_body_sites(data)
