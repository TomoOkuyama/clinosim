"""JP Core Observation.category normalization pin tests。

これまでの経緯:
- 初版で `Observation.category:first` の CodeSystem URI を推測で書いた
  ため(`http://jpfhir.jp/fhir/observation-category`)HAPI Validator が
  silent-no-op。実 JP Core 1.2.0 spec fixedUri
  `JP_SimpleObservationCategory_CS` に修正 + 本 test で URI を pin して
  再発防止(このルールが「spec fixedUri 直接引用」に発展)。
- 従来 prepend 方式(HL7 secondary slice 残存)から in-place replace
  方式に変更。HL7 URL + fabricated URL の両方を JP CS URL に置換、code
  は保持、eCS `category max=1` 制約にも適合。
- iris4h-ai feedback V5 発見 A' + H により、JP CS 側 display 誤り(155k
  error)+ HL7 base Vital Signs profile の VSCat slice 欠如(89k error)
  が判明。normalization を拡張:display 省略 + vital-signs のみ HL7
  category coding を再併記(2 coding)、他 category は JP CS 単独維持。

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
HL7_OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
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


def test_normalize_laboratory_category_emits_jp_cs_alone_without_display():
    """laboratory category は JP CS 単独 coding + display 省略。
    `JP_Observation_LabResult_eCS` の `category max=1` 制約に適合。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": HL7_OBSERVATION_CATEGORY_SYSTEM,
                        "code": "laboratory",
                        "display": "検体検査",
                    }
                ],
                "text": "検体検査",
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    cat = resource["category"][0]
    assert len(cat["coding"]) == 1
    cod = cat["coding"][0]
    assert cod == {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"}
    # text field は日本語ラベルを保持(feedback Option 1:display 省略 +
    # 日本語は text で保持、翻訳の自由度は text の方が高い)。
    assert cat["text"] == "検体検査"


def test_normalize_vital_signs_category_dual_coding_without_display():
    """vital-signs category は HL7 + JP CS の 2 coding。両方 display 省略。
    HL7 base Vital Signs profile の VSCat slice discriminator を満たす。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": HL7_OBSERVATION_CATEGORY_SYSTEM,
                        "code": "vital-signs",
                        "display": "バイタルサイン",
                    }
                ],
                "text": "バイタルサイン",
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    cat = resource["category"][0]
    assert cat["coding"] == [
        {"system": HL7_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs"},
        {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs"},
    ]
    assert cat["text"] == "バイタルサイン"


def test_normalize_fabricated_url_replaced():
    """過去 clinosim 版の fabricated URL
    `http://jpfhir.jp/fhir/observation-category`(古い regen data に残存
    しうる)も defensive normalize で JP CS URL に置換。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
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
    _normalize_jp_observation_category(resource)
    assert resource["category"][0]["coding"] == [
        {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "social-history"},
    ]


def test_normalize_is_idempotent_for_laboratory():
    """正規化後の laboratory 状態を再度 normalize しても同一結果。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"},
                ],
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    after_first = [dict(c) for c in resource["category"][0]["coding"]]
    _normalize_jp_observation_category(resource)
    after_second = [dict(c) for c in resource["category"][0]["coding"]]
    assert after_first == after_second


def test_normalize_ecs_profile_forces_dual_coding_for_lab():
    """`JP_Observation_LabResult_eCS` profile を含む Observation は
    laboratory category でも HL7 + JP CS の dual coding を emit する
    (fhir-jp-validator feedback 2026-07-16 §"【最優先 3】" 対応)。

    `category:first` slice discriminator が LabResult_eCS では HL7
    observation-category を要求するため、JP CS 単独では slice が
    満たされない。同時に JP_Observation_Common が併記されている場合の
    JP CS coding 要件も dual coding で満たす。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "meta": {
            "profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult",
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
                "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS",
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": JP_OBSERVATION_CATEGORY_SYSTEM,
                        "code": "laboratory",
                    }
                ],
                "text": "検体検査",
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    cat = resource["category"][0]
    # Both HL7 and JP CS codings emitted (dual satisfy both profiles' slices)
    assert cat["coding"] == [
        {"system": HL7_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"},
        {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"},
    ]
    # text field preserved (feedback Option 1)
    assert cat["text"] == "検体検査"


def test_normalize_non_ecs_lab_still_jp_cs_alone():
    """eCS profile なしの Observation は従来通り JP CS 単独 coding。
    (Common single-coding は non-eCS observation の base binding として
    引き続き正しい形。regression 防衛)"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "meta": {
            "profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
            ]
        },
        "category": [
            {
                "coding": [
                    {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "social-history"},
                ],
                "text": "社会歴",
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    cat = resource["category"][0]
    assert cat["coding"] == [
        {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "social-history"},
    ]


def test_normalize_ecs_profile_idempotent():
    """eCS Observation を 2 回 normalize しても HL7 + JP CS 2 coding
    のまま維持(重複追加しない)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "meta": {
            "profile": [
                "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS",
            ]
        },
        "category": [
            {
                "coding": [
                    {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"},
                ],
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    after_first = [dict(c) for c in resource["category"][0]["coding"]]
    _normalize_jp_observation_category(resource)
    after_second = [dict(c) for c in resource["category"][0]["coding"]]
    assert after_first == after_second
    assert len(after_first) == 2


def test_normalize_is_idempotent_for_vital_signs():
    """正規化後の vital-signs 状態(HL7 + JP CS 2 coding)を再度
    normalize しても 2 coding のまま維持(重複追加しない)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {"system": HL7_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs"},
                    {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs"},
                ],
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    assert resource["category"][0]["coding"] == [
        {"system": HL7_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs"},
        {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs"},
    ]


def test_normalize_preserves_non_category_coding():
    """observation-category 以外の system(独自 CodeSystem 等)は preserve。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    custom_coding = {
        "system": "http://example.com/CodeSystem/custom-category",
        "code": "custom-lab",
    }
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {"system": HL7_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"},
                    custom_coding,
                ],
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    # 独自 coding は先頭にそのまま残り、JP CS coding が末尾に追加。
    assert resource["category"][0]["coding"] == [
        custom_coding,
        {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": "laboratory"},
    ]


def test_normalize_skips_non_observation():
    """Observation 以外の resource には触れない。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource = {"resourceType": "Encounter", "category": [{"coding": []}]}
    _normalize_jp_observation_category(resource)
    assert resource == {"resourceType": "Encounter", "category": [{"coding": []}]}


@pytest.mark.parametrize(
    ("hl7_code", "expected_dual_coding"),
    [
        ("laboratory", False),
        ("vital-signs", True),
        ("imaging", False),
        ("procedure", False),
        ("social-history", False),
        ("survey", False),
        ("exam", False),
    ],
)
def test_normalize_dual_coding_only_for_vital_signs(hl7_code, expected_dual_coding):
    """vital-signs のみ HL7 + JP CS の 2 coding、他 code は JP CS 単独。
    (Lab eCS `category max=1` 制約を保持するため vital-signs 以外は 1 coding)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _normalize_jp_observation_category,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": HL7_OBSERVATION_CATEGORY_SYSTEM,
                        "code": hl7_code,
                    }
                ],
            }
        ],
    }
    _normalize_jp_observation_category(resource)
    codings = resource["category"][0]["coding"]
    if expected_dual_coding:
        assert codings == [
            {"system": HL7_OBSERVATION_CATEGORY_SYSTEM, "code": hl7_code},
            {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": hl7_code},
        ]
    else:
        assert codings == [
            {"system": JP_OBSERVATION_CATEGORY_SYSTEM, "code": hl7_code},
        ]


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
