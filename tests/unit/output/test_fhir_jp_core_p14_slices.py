"""JP Core P1-4 slice fix pin tests(session 50 iris4h-ai feedback P1-4)。

adv-1 code review CRITICAL finding: session 50 初版で
`Observation.category:first` の CodeSystem URI を推測で書いてしまい
(`http://jpfhir.jp/fhir/observation-category`)、実 JP Core 1.2.0 spec
の fixedUri と不一致で HAPI Validator が silent-no-op。実 spec URI
(`JP_SimpleObservationCategory_CS`)に修正 + 本 test で URI を pin して
再発防止。

session 53 iris4h-ai feedback F-2 + B: 従来 prepend 方式(HL7 secondary
slice 残存)から in-place replace 方式に変更。HL7 URL + session 49
fabricated URL の両方を JP CS URL に置換、code は保持、eCS `category
max=1` 制約にも適合。

同時に MedicationRequest / MedicationAdministration の
identifier:rpNumber + orderInRp slice の URI も pin テストで守る。

URI 出典:iris4h-ai/jp_core/package/StructureDefinition-jp-*.json の
`fixedUri`(spec 直接引用、推測ではない)。
"""

from __future__ import annotations

from typing import Any

import pytest

# JP Core 1.2.0 実 spec で固定されている system URI
JP_OBSERVATION_CATEGORY_SYSTEM = "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"
JP_MEDICATION_RP_GROUP_SYSTEM = "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber"
JP_MEDICATION_ADMIN_INDEX_SYSTEM = "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex"


def test_observation_category_first_uri_pinned_to_spec():
    """`_JP_OBSERVATION_CATEGORY_SYSTEM` が実 JP Core spec の
    `JP_SimpleObservationCategory_CS` に一致していること(推測 URI に
    差し戻す変更を規制)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _JP_OBSERVATION_CATEGORY_SYSTEM,
    )

    assert _JP_OBSERVATION_CATEGORY_SYSTEM == JP_OBSERVATION_CATEGORY_SYSTEM


def test_convert_hl7_observation_category_to_jp_replaces_hl7_url():
    """`_convert_hl7_observation_category_to_jp` は HL7 URL を in-place で
    JP CS URL に置換する(code は保持、prepend しない)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _convert_hl7_observation_category_to_jp,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory",
                    }
                ],
            }
        ],
    }
    _convert_hl7_observation_category_to_jp(resource)
    # category は 1 個(eCS max=1 適合)、system は JP CS、code + display 保持
    assert len(resource["category"]) == 1
    cod = resource["category"][0]["coding"][0]
    assert cod["system"] == JP_OBSERVATION_CATEGORY_SYSTEM
    assert cod["code"] == "laboratory"
    assert cod["display"] == "Laboratory"


def test_convert_hl7_observation_category_replaces_fabricated_url():
    """session 49 fabricated URL `http://jpfhir.jp/fhir/observation-category`
    (session 51 で spec fixedUri 訂正済だが古い regen data に残存)も
    defensive normalize で JP CS URL に置換。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _convert_hl7_observation_category_to_jp,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://jpfhir.jp/fhir/observation-category",
                        "code": "social-history",
                    }
                ],
            }
        ],
    }
    _convert_hl7_observation_category_to_jp(resource)
    cod = resource["category"][0]["coding"][0]
    assert cod["system"] == JP_OBSERVATION_CATEGORY_SYSTEM
    assert cod["code"] == "social-history"


def test_convert_hl7_observation_category_idempotent():
    """既に JP CS URL の resource は no-op。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _convert_hl7_observation_category_to_jp,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": JP_OBSERVATION_CATEGORY_SYSTEM,
                        "code": "laboratory",
                    }
                ],
            }
        ],
    }
    before = [c["coding"][0]["system"] for c in resource["category"]]
    _convert_hl7_observation_category_to_jp(resource)
    after = [c["coding"][0]["system"] for c in resource["category"]]
    assert before == after


def test_convert_hl7_observation_category_skips_non_observation():
    """Observation 以外の resource には触れない。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _convert_hl7_observation_category_to_jp,
    )

    resource = {"resourceType": "Encounter", "category": [{"coding": []}]}
    _convert_hl7_observation_category_to_jp(resource)
    assert resource == {"resourceType": "Encounter", "category": [{"coding": []}]}


@pytest.mark.parametrize(
    "hl7_code",
    [
        "laboratory",
        "vital-signs",
        "imaging",
        "procedure",
        "social-history",
    ],
)
def test_convert_hl7_observation_category_preserves_codes(hl7_code):
    """HL7 code はそのまま JP CS URL 下で保持される
    (JP_SimpleObservationCategory_CS は HL7 と code 語彙が概ね一致)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _convert_hl7_observation_category_to_jp,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": hl7_code,
                    }
                ],
            }
        ],
    }
    _convert_hl7_observation_category_to_jp(resource)
    assert resource["category"][0]["coding"][0]["system"] == JP_OBSERVATION_CATEGORY_SYSTEM
    assert resource["category"][0]["coding"][0]["code"] == hl7_code


def test_medication_request_jp_identifier_slice_uris_pinned():
    """MedicationRequest.identifier:rpNumber + orderInRp system URIs pinned to spec."""
    from clinosim.modules.output._fhir_medications import _build_medication_request

    order = {
        "order_id": "ORD-1",
        "display_name": "Test drug",
        "order_type": "medication",
        "ordered_datetime": "2026-06-01T09:00:00",
        "clinical_intent": "test",
    }
    resource = _build_medication_request(
        order,
        patient_id="pt1",
        country="JP",
        encounter_id="enc1",
        primary_dx_code="",
        rp_number="7",
        order_in_rp="3",
    )
    ids = resource.get("identifier", [])
    systems = {i["system"]: i["value"] for i in ids}
    assert systems[JP_MEDICATION_RP_GROUP_SYSTEM] == "7"
    assert systems[JP_MEDICATION_ADMIN_INDEX_SYSTEM] == "3"


def test_medication_request_us_no_jp_identifier_slice():
    """US output は JP identifier slice を emit しない。"""
    from clinosim.modules.output._fhir_medications import _build_medication_request

    order = {
        "order_id": "ORD-1",
        "display_name": "Test drug",
        "order_type": "medication",
        "ordered_datetime": "2026-06-01T09:00:00",
        "clinical_intent": "test",
    }
    resource = _build_medication_request(
        order,
        patient_id="pt1",
        country="US",
        encounter_id="enc1",
        primary_dx_code="",
    )
    # identifier field は US では絶対に emit されない or JP URI を含まない
    for i in resource.get("identifier", []):
        assert JP_MEDICATION_RP_GROUP_SYSTEM not in i.get("system", "")
        assert JP_MEDICATION_ADMIN_INDEX_SYSTEM not in i.get("system", "")


def test_build_order_in_rp_map_per_encounter_numbering():
    """`_build_order_in_rp_map` は encounter 内 medication order の
    出現順を 1-based で orderInRp に割当てる。"""
    from clinosim.modules.output.fhir_r4_adapter import _build_order_in_rp_map

    orders = [
        {"order_id": "O1", "order_type": "medication", "display_name": "A", "encounter_id": "enc-x"},
        {"order_id": "O2", "order_type": "medication", "display_name": "B", "encounter_id": "enc-x"},
        {
            "order_id": "O3",
            "order_type": "medication",
            "display_name": "C",
            "encounter_id": "enc-y",
        },  # different encounter
        {
            "order_id": "OL1",
            "order_type": "lab",
            "display_name": "Lab",
            "encounter_id": "enc-x",
        },  # not medication → skip
    ]
    result = _build_order_in_rp_map(orders)
    assert result == {"O1": 1, "O2": 2, "O3": 1}


def test_build_order_in_rp_map_deterministic_across_calls():
    """同 orders を 2 回渡すと同 dict を返す(MR と MA が同 map を使う根拠)。"""
    from clinosim.modules.output.fhir_r4_adapter import _build_order_in_rp_map

    orders = [
        {"order_id": f"O{i}", "order_type": "medication", "display_name": "d", "encounter_id": "e1"} for i in range(5)
    ]
    a = _build_order_in_rp_map(orders)
    b = _build_order_in_rp_map(orders)
    assert a == b
