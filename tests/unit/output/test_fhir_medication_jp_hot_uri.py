"""JP MedicationRequest / MedicationAdministration system URI pin tests。

session 53 iris4h-ai feedback F-1:従来 `urn:oid:1.2.392.100495.20.2.74`
(HOT9 OID)を全 drug code に固定 emit していたため、実 code 形式
(HOT7 / YJ12)と URI が一致せず jpfhir-terminology 2.2606.0 で ~53k info。
本 test で code 形式ごとの JP Core NamingSystem URI 割当を pin する。

URI 出典:iris4h-ai/jp_core/package/NamingSystem-*.json の fixedUri
(spec 直接引用、推測ではない)。
"""

from __future__ import annotations

from typing import Any

import pytest

# JP Core NamingSystem 実 spec fixedUri
MEDIS_HOT7_URI = "http://medis.or.jp/CodeSystem/master-HOT7"
MEDIS_HOT9_URI = "http://medis.or.jp/CodeSystem/master-HOT9"
MEDIS_HOT13_URI = "http://medis.or.jp/CodeSystem/master-HOT13"
JP_YJ_CODE_URI = "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"


@pytest.mark.parametrize(
    "code,expected_uri",
    [
        ("6131002", MEDIS_HOT7_URI),  # 7-digit HOT7
        ("614900412", MEDIS_HOT9_URI),  # 9-digit HOT9
        ("1234567890123", MEDIS_HOT13_URI),  # 13-digit HOT13
        ("6139504G1028", JP_YJ_CODE_URI),  # 12-char YJ
        ("1242002F1330", JP_YJ_CODE_URI),
        ("2355002X1016", JP_YJ_CODE_URI),
    ],
)
def test_resolve_jp_drug_system_uri_per_format(code: str, expected_uri: str) -> None:
    from clinosim.modules.output._fhir_medications import _resolve_jp_drug_system_uri

    assert _resolve_jp_drug_system_uri(code) == expected_uri


def test_resolve_jp_drug_system_uri_fallback_for_unknown_format() -> None:
    """認識外 format は HOT9 URI にフォールバック(将来の code 追加時の safe default)。"""
    from clinosim.modules.output._fhir_medications import _resolve_jp_drug_system_uri

    assert _resolve_jp_drug_system_uri("weird_code") == MEDIS_HOT9_URI
    assert _resolve_jp_drug_system_uri("12345") == MEDIS_HOT9_URI  # 5-digit not registered


def _build_mr(code: str, country: str = "JP") -> dict[str, Any]:
    from clinosim.modules.output._fhir_medications import _build_medication_request

    order = {
        "order_id": "ORD-1",
        "display_name": "Test drug",
        "order_type": "medication",
        "order_code": code,
        "ordered_datetime": "2026-06-01T09:00:00",
        "clinical_intent": "test",
    }
    return _build_medication_request(
        order,
        patient_id="pt1",
        country=country,
        encounter_id="enc1",
        primary_dx_code="",
    )


def test_medication_request_jp_hot7_uri() -> None:
    """7-digit HOT7 code → MEDIS HOT7 URI。"""
    mr = _build_mr("6131002")
    coding = mr["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == MEDIS_HOT7_URI
    assert coding["code"] == "6131002"


def test_medication_request_jp_yj12_uri() -> None:
    """12-char YJ code → JP YJ code URI。"""
    mr = _build_mr("6139504G1028")
    coding = mr["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == JP_YJ_CODE_URI
    assert coding["code"] == "6139504G1028"


def test_medication_request_course_of_therapy_display_matches_hl7_terminology() -> None:
    """`courseOfTherapyType.coding[].display` must match the authoritative R4
    HL7 terminology CodeSystem `medicationrequest-course-of-therapy` — verified
    against `hl7.terminology.r4#7.2.0`. The hyphenated `Continuous long-term
    therapy` variant produced 854 v4 fullset errors; the canonical form is
    `Continuous long term therapy` (no hyphen)."""
    mr = _build_mr("6131002")
    coding = mr["courseOfTherapyType"]["coding"][0]
    assert coding["system"] == "http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy"
    assert coding["code"] in ("continuous", "acute")
    if coding["code"] == "continuous":
        assert coding["display"] == "Continuous long term therapy"
    else:
        assert coding["display"] == "Short course (acute) therapy"


def test_medication_request_us_keeps_rxnorm() -> None:
    """US output は RxNorm URI を維持(HOT/YJ dispatch は JP-only)。"""
    from clinosim.codes import get_system_uri

    mr = _build_mr("12345", country="US")
    coding = mr["medicationCodeableConcept"]["coding"][0]
    # RxNorm URI(clinosim/codes/loader.py の "rxnorm" キー)
    assert coding["system"] == get_system_uri("rxnorm")


def _build_ma(code: str, country: str = "JP") -> dict[str, Any]:
    from clinosim.modules.output._fhir_medications import _build_medication_admin

    mar = {
        "mar_id": "MAR-1",
        "drug_name": "Test drug",
        "code_yj": code,
        "administration_datetime": "2026-06-01T10:00:00",
        "dose": "1 tablet",
        "route": "oral",
        "status": "given",
    }
    return _build_medication_admin(
        mar,
        patient_id="pt1",
        index=1,
        country=country,
        encounter_id="enc1",
    )


def test_medication_administration_jp_hot7_uri() -> None:
    """MA builder も同 helper で JP HOT7 URI dispatch。"""
    ma = _build_ma("6131002")
    coding = ma["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == MEDIS_HOT7_URI
    assert coding["code"] == "6131002"


def test_medication_administration_jp_yj12_uri() -> None:
    """MA builder も 12-char YJ code → YJ URI。"""
    ma = _build_ma("6139504G1028")
    coding = ma["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == JP_YJ_CODE_URI


def test_medication_administration_us_keeps_rxnorm() -> None:
    """MA US output は RxNorm URI 維持。"""
    from clinosim.codes import get_system_uri

    ma = _build_ma("6131002", country="US")
    coding_list = ma["medicationCodeableConcept"].get("coding", [])
    if coding_list:
        # US の code_yj は US では resolve されない可能性あるが、emit された場合 RxNorm URI
        assert coding_list[0]["system"] == get_system_uri("rxnorm")
