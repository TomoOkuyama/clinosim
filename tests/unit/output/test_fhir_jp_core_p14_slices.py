"""JP Core P1-4 slice fix pin tests(session 50 iris4h-ai feedback P1-4)。

adv-1 code review CRITICAL finding: session 50 初版で
`Observation.category:first` の CodeSystem URI を推測で書いてしまい
(`http://jpfhir.jp/fhir/observation-category`)、実 JP Core 1.2.0 spec
の fixedUri と不一致で HAPI Validator が silent-no-op。実 spec URI
(`JP_SimpleObservationCategory_CS`)に修正 + 本 test で URI を pin して
再発防止。

同時に MedicationRequest / MedicationAdministration の
identifier:rpNumber + orderInRp slice の URI も pin テストで守る。

URI 出典:iris4h-ai/jp_core/package/StructureDefinition-jp-*.json の
`fixedUri`(spec 直接引用、推測ではない)。
"""

from __future__ import annotations

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


def test_inject_jp_observation_category_first_uses_spec_uri():
    """`_inject_jp_observation_category_first` は spec URI で prepend する。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _inject_jp_observation_category_first,
    )

    resource = {
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
    _inject_jp_observation_category_first(resource)
    # First slice は JP CodeSystem
    first = resource["category"][0]
    assert first["coding"][0]["system"] == JP_OBSERVATION_CATEGORY_SYSTEM
    assert first["coding"][0]["code"] == "laboratory"
    # 既存 HL7 slice は second として保持
    second = resource["category"][1]
    assert "hl7.org" in second["coding"][0]["system"]


def test_inject_jp_observation_category_first_idempotent():
    """既に JP-first slice ある場合は再挿入しない。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _inject_jp_observation_category_first,
    )

    resource = {
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
    original = [c["coding"][0]["system"] for c in resource["category"]]
    _inject_jp_observation_category_first(resource)
    after = [c["coding"][0]["system"] for c in resource["category"]]
    assert original == after


def test_inject_jp_observation_category_skips_non_observation():
    """Observation 以外の resource には触れない。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _inject_jp_observation_category_first,
    )

    resource = {"resourceType": "Encounter", "category": [{"coding": []}]}
    _inject_jp_observation_category_first(resource)
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
def test_inject_jp_observation_category_preserves_hl7_codes(hl7_code):
    """HL7 code はそのまま JP slice の code として再利用される
    (JP_SimpleObservationCategory_CS は HL7 と code 語彙が概ね一致)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _inject_jp_observation_category_first,
    )

    resource = {
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
    _inject_jp_observation_category_first(resource)
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
