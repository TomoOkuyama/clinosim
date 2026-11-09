"""JP-marketed drugs carry their YJ codes (Issue #3013).

Each code was checked against the MHLW drug-price list (薬価基準収載品目リスト,
applied 2026-06-12) and the MEDIS YJ CodeSystem (`codes/authoritative`).
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import drug_display, jp_drug_code
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("drug", "route", "yj"),
    [
        ("midazolam", "IV", "1124401A1052"),  # ドルミカム注射液10mg
        ("norepinephrine", "IV", "2451401A1034"),  # (局)ノルアドレナリン注射液
        ("sodium_polystyrene_sulfonate", "PO", "2190009A1048"),  # ケイキサレート散
        ("lidocaine", "infiltration", "1214400A7055"),  # キシロカイン注ポリアンプ1%
        ("tetanus_toxoid", "IM", "6322400X2072"),  # 沈降破傷風トキソイド「ビケン」
        ("butylscopolamine", "IV", "1242401A1315"),  # ブスコパン注20mg
        ("diphenhydramine", "IV", "4411400A1033"),  # ジフェンヒドラミン塩酸塩注10mg「日新」
        ("mannitol", "IV", "2190400A5037"),  # (局)D-マンニトール注射液
    ],
)
def test_a_jp_marketed_drug_has_its_yj_code(drug: str, route: str, yj: str) -> None:
    assert jp_drug_code(drug, route) == yj


def test_jp_midazolam_injection_is_coded_on_a_medication_request() -> None:
    concept, _ = _resolve_medication_concept("Midazolam 2mg", order_code="", country="JP", route="IV")
    assert concept["coding"][0]["code"] == "1124401A1052"


def test_norepinephrine_has_its_japanese_generic_name() -> None:
    assert drug_display("norepinephrine", "ja") == "ノルアドレナリン"


@pytest.mark.parametrize("drug", ["ferrous_fumarate", "calcium_carbonate_vitamin_d"])
def test_a_drug_with_no_jp_product_has_no_yj_code(drug: str) -> None:
    assert jp_drug_code(drug, "PO") is None
