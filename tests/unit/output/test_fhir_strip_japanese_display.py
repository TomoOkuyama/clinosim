"""iris4h-ai feedback V4/V5 P2 A pin tests。

`_strip_japanese_display_on_english_only_systems` が英語 display のみを
持つ standard CodeSystem(LOINC / SNOMED / HL7 terminology / DICOM /
UCUM / HL7 FHIR sid)の Coding.display から日本語文字を落とすことを
検証する。JP-specific CodeSystem(JP Core / JP-CLINS / MEDIS HOT /
YJ code / clinosim custom)は preserve される。

「英語 display 保有 CodeSystem」の判定は URI prefix allowlist で行われる
ため、prefix 一覧の pin test も併置(spec 変更なく allowlist を狭める
変更を規制)。
"""

from __future__ import annotations

from typing import Any

import pytest


def test_english_only_prefix_allowlist_pinned():
    """allowlist prefix セットが期待通り。ここを狭めると
    HAPI Validator "Wrong Display Name" error が再発するため
    pin test で規制。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES,
    )

    assert set(_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES) == {
        "http://loinc.org",
        "http://snomed.info/sct",
        "http://terminology.hl7.org/",
        "http://hl7.org/fhir/",
        "http://dicom.nema.org/",
        "http://unitsofmeasure.org",
    }


@pytest.mark.parametrize(
    ("system", "display"),
    [
        ("http://loinc.org", "外来経過記録（SOAP）"),
        ("http://loinc.org", "バーセルインデックス合計スコア"),
        ("http://snomed.info/sct", "多量飲酒者"),
        ("http://snomed.info/sct", "医師"),
        ("http://terminology.hl7.org/CodeSystem/referencerange-meaning", "正常範囲"),
        ("http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "正常"),
        ("http://terminology.hl7.org/CodeSystem/v3-ActCode", "外来"),
        ("http://terminology.hl7.org/CodeSystem/condition-clinical", "解消"),
        ("http://terminology.hl7.org/CodeSystem/observation-category", "バイタルサイン"),
        ("http://hl7.org/fhir/sid/icd-10", "2型糖尿病"),
        ("http://hl7.org/fhir/sid/cvx", "インフルエンザ（分割・4価・保存剤なし）"),
        ("http://dicom.nema.org/resources/ontology/DCM", "磁気共鳴画像"),
    ],
)
def test_english_only_systems_strip_japanese_display(system, display):
    """英語 display のみの CodeSystem では日本語 display を削除する。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "code": {
            "coding": [
                {"system": system, "code": "X-1", "display": display},
            ],
            "text": display,
        },
    }
    _strip_japanese_display_on_english_only_systems(resource)
    cod = resource["code"]["coding"][0]
    assert cod == {"system": system, "code": "X-1"}
    # text field は元のまま保持(feedback Option 1:human-readable label は text で)。
    assert resource["code"]["text"] == display


@pytest.mark.parametrize(
    "system",
    [
        "http://jpfhir.jp/fhir/core/CodeSystem/JP_ConditionSeverity_CS",
        "http://jpfhir.jp/fhir/clins/CodeSystem/document-section",
        "http://medis.or.jp/CodeSystem/master-HOT7",
        "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code",
        "urn:oid:1.2.392.200119.4.1005",
        "http://clinosim.example.org/CodeSystem/occupation-category",
    ],
)
def test_jp_specific_systems_preserve_japanese_display(system):
    """JP-specific CodeSystem は日本語 display を preserve する
    (JP Core / JP-CLINS / MEDIS / YJ / clinosim custom には正規な
    日本語 display 定義がある or 独自 display 使用が想定されている)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "code": {
            "coding": [
                {"system": system, "code": "X-1", "display": "軽度"},
            ],
        },
    }
    _strip_japanese_display_on_english_only_systems(resource)
    cod = resource["code"]["coding"][0]
    assert cod == {"system": system, "code": "X-1", "display": "軽度"}


def test_english_display_on_standard_system_preserved():
    """既に英語 display の Coding には触れない(US output に本 walker
    が呼ばれるパスは無いが、defensive で ASCII display は preserve)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "code": {
            "coding": [
                {"system": "http://loinc.org", "code": "34131-3", "display": "Discharge summary"},
            ],
        },
    }
    _strip_japanese_display_on_english_only_systems(resource)
    cod = resource["code"]["coding"][0]
    assert cod == {"system": "http://loinc.org", "code": "34131-3", "display": "Discharge summary"}


def test_walker_handles_bare_coding_field():
    """ImagingStudy.series[].modality のような CodeableConcept でない
    Coding-typed field(coding[] にラップされていない直接 Coding)も
    strip 対象になる。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "ImagingStudy",
        "series": [
            {
                "uid": "1.2.3",
                "modality": {
                    "system": "http://dicom.nema.org/resources/ontology/DCM",
                    "code": "MR",
                    "display": "磁気共鳴画像",
                },
                "bodySite": {
                    "system": "http://snomed.info/sct",
                    "code": "69536005",
                    "display": "頭部",
                },
            }
        ],
    }
    _strip_japanese_display_on_english_only_systems(resource)
    assert resource["series"][0]["modality"] == {
        "system": "http://dicom.nema.org/resources/ontology/DCM",
        "code": "MR",
    }
    assert resource["series"][0]["bodySite"] == {
        "system": "http://snomed.info/sct",
        "code": "69536005",
    }


def test_walker_recursion_covers_deep_nesting():
    """AllergyIntolerance.reaction[].manifestation[].coding[] のような
    深い nesting でも Coding 単位で strip する。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "reaction": [
            {
                "manifestation": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "247472004",
                                "display": "発疹",
                            }
                        ],
                        "text": "発疹",
                    }
                ]
            }
        ],
    }
    _strip_japanese_display_on_english_only_systems(resource)
    m = resource["reaction"][0]["manifestation"][0]
    assert m["coding"][0] == {"system": "http://snomed.info/sct", "code": "247472004"}
    # 元 text は無傷。
    assert m["text"] == "発疹"


def test_walker_is_idempotent():
    """既に display 剥ぎ済みの resource に再度 walker を通しても no-op。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "34131-3"}],
        },
    }
    _strip_japanese_display_on_english_only_systems(resource)
    assert resource["code"]["coding"] == [{"system": "http://loinc.org", "code": "34131-3"}]
    _strip_japanese_display_on_english_only_systems(resource)
    assert resource["code"]["coding"] == [{"system": "http://loinc.org", "code": "34131-3"}]


def test_walker_ignores_identifier_shape():
    """Identifier は `system` + `value` を持ち `code` を持たない。
    Coding とは異なるため walker は触れない(誤削除防止)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "http://loinc.org",
                "value": "any-value",
                "type": {"text": "任意タイプ"},
            }
        ],
    }
    _strip_japanese_display_on_english_only_systems(resource)
    ident = resource["identifier"][0]
    # value / type field は無傷、display key も存在しないので walker は No-op。
    assert ident == {
        "system": "http://loinc.org",
        "value": "any-value",
        "type": {"text": "任意タイプ"},
    }


def test_walker_no_op_when_display_absent():
    """display key が無ければ何もしない(既に stripped 済 or 未設定)。"""
    from clinosim.modules.output.fhir_r4_adapter import (
        _strip_japanese_display_on_english_only_systems,
    )

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "34131-3"}],
        },
    }
    before = {"code": {"coding": [dict(c) for c in resource["code"]["coding"]]}}
    _strip_japanese_display_on_english_only_systems(resource)
    assert resource["code"] == before["code"]
