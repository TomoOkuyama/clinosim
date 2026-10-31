"""JP drug codes are full YJ products from the drug catalog, chosen by route (Issue #2347).

The legacy ``locale/jp/code_mapping_drug.yaml`` held 7-digit values that were
the first seven characters of YJ codes (MHLW ingredient prefixes) and were
emitted under the MEDIS HOT7 URI. Every JP drug code now comes from
``codes/data/drugs.yaml`` ``codes.yj`` — one YJ product per route class,
listed in the MHLW YJ master and the clinosim-shipped JP YJ CodeSystem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.codes.drugs import all_drug_ids, jp_drug_code, resolve_drug, route_class

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT = json.loads((_ROOT / "clinosim/codes/authoritative/yj_mhlw_snapshot.json").read_text(encoding="utf-8"))


def _catalog_codes() -> set[str]:
    return {c for d in all_drug_ids() for c in resolve_drug(d).yj_by_route.values()}


def test_legacy_jp_drug_code_file_is_retired() -> None:
    assert not (_ROOT / "clinosim/locale/jp/code_mapping_drug.yaml").exists()


def test_every_catalog_yj_code_is_in_the_mhlw_master_snapshot() -> None:
    assert _catalog_codes() == set(_SNAPSHOT["codes"])


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("PO", "oral"),
        ("SL", "oral"),
        ("IV", "injection"),
        ("sc", "injection"),
        ("IM", "injection"),
        ("NEB", "inhalation"),
        ("inhaled", "inhalation"),
        ("PR", "rectal"),
        ("OPH", "topical"),
        ("intravesical", "intravesical"),
        ("", ""),
        ("non-pharmacologic", ""),
    ],
)
def test_route_class(route: str, expected: str) -> None:
    assert route_class(route) == expected


def test_the_route_picks_the_product_form() -> None:
    # YJ ingredient numbers 400-699 are injections, 001-399 internal use.
    iv, po = jp_drug_code("Furosemide", "IV"), jp_drug_code("Furosemide", "PO")
    assert iv and po and 400 <= int(iv[4:7]) < 700 and int(po[4:7]) < 400
    # Vancomycin given IV was coded as the oral powder (6113001).
    vanc = jp_drug_code("Vancomycin", "IV")
    assert vanc and vanc.startswith("6113400")
    # A drug with no listed product for the route has no code.
    assert jp_drug_code("Cefmetazole", "PO") is None
    # Several route classes and no route: no guess.
    assert jp_drug_code("Furosemide") is None


def test_single_ingredient_drugs_are_not_coded_as_combinations() -> None:
    # Amlodipine was coded 2149114, the valsartan/amlodipine combination.
    code = jp_drug_code("Amlodipine", "PO")
    assert code and "・" not in _SNAPSHOT["codes"][code]["ingredient"]
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        if "/" in rec.names["en"] or "-" in rec.names["en"]:
            continue  # combination products by name
        for c in rec.yj_by_route.values():
            assert "配合" not in _SNAPSHOT["codes"][c]["product"], (drug_id, c)
