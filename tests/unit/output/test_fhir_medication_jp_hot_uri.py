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
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_jp_drug_system_uri

    assert _resolve_jp_drug_system_uri(code) == expected_uri


def test_resolve_jp_drug_system_uri_fallback_for_unknown_format() -> None:
    """認識外 format は HOT9 URI にフォールバック(将来の code 追加時の safe default)。"""
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_jp_drug_system_uri

    assert _resolve_jp_drug_system_uri("weird_code") == MEDIS_HOT9_URI
    assert _resolve_jp_drug_system_uri("12345") == MEDIS_HOT9_URI  # 5-digit not registered


def _build_mr(code: str, country: str = "JP") -> dict[str, Any]:
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request

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
    """12-char YJ code → JP YJ code URI. Issue #1220: replaced tx-server-
    fragment-based gate with the clinosim-shipped MEDIS full CS
    (``content=complete``, 23,923 concepts). Any real MHLW YJ code passes.
    """
    # 1112700X1038 = （局）ハロタン (全身麻酔薬)、MEDIS 医薬品HOTマスター
    # 2026-08-31 版に収録。
    mr = _build_mr("1112700X1038")
    coding = mr["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == JP_YJ_CODE_URI
    assert coding["code"] == "1112700X1038"


def test_medication_request_jp_emits_full_yj_codes() -> None:
    """Issue #1220: the tx-server-fragment-based gate (Issue #283) was
    replaced by the clinosim-shipped full JP national YJ CodeSystem
    (``JP_MedicationCodeYJ_CS_full.json``, ``content=complete``, MEDIS-
    sourced, 23,923 concepts). Every clinosim yj.yaml code was curated
    to a real MHLW YJ code and passes the new ``_is_yj_code_valid`` gate,
    so the ``codingYJ`` slice always carries the real code — no
    ``nocoded`` downgrade for cardiovascular / respiratory / oncology
    codes previously outside the tx-server fragment.
    """
    from clinosim.modules.output.fhir_r4.medications.medications import (
        _JP_MEDICATION_CODE_NOCODED_CS,
        _JP_YJ_CODE_URI,
        _is_yj_code_valid,
    )

    # cardiovascular / respiratory YJ code — previously downgraded to
    # NOCODED because the tx-server ships fragment 11xx/12xx only.
    cardio_code = "2149032F1099"  # カルベジロール１０ｍｇ錠
    assert _is_yj_code_valid(cardio_code)
    mr = _build_mr(cardio_code)
    coding = mr["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == _JP_YJ_CODE_URI, f"expected YJ URI, got {coding['system']}"
    assert coding["code"] == cardio_code
    assert coding["system"] != _JP_MEDICATION_CODE_NOCODED_CS

    # US path: YJ system 未使用、影響なし (regression guard)
    mr_us = _build_mr(cardio_code, country="US")
    assert mr_us["medicationCodeableConcept"]["coding"][0]["system"] != _JP_MEDICATION_CODE_NOCODED_CS


def test_medication_request_jp_nocoded_fallback_when_no_code_value() -> None:
    """#291:JP-CLINS eCS `medication[x].coding` min=1 を満たすため、
    code_mapping にヒットしない薬(ED 特異薬 等)は "nocoded" slice へ
    fallback する。system = MedicationCodeNocoded_CS, code = "NOCODED"。
    #305 session 60:display は "標準コードなし" 固定、薬剤名は text
    field で保持(1-code / 1-display required binding)。US 出力には
    影響しない。
    """
    from clinosim.modules.output.fhir_r4.medications.medications import (
        _JP_MEDICATION_CODE_NOCODED_CODE,
        _JP_MEDICATION_CODE_NOCODED_CS,
        _JP_MEDICATION_CODE_NOCODED_DISPLAY,
    )

    # JP:code_value 空 → nocoded fallback 発火
    mr_jp = _build_mr("")  # no order_code, unknown drug name
    coding = mr_jp["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == _JP_MEDICATION_CODE_NOCODED_CS
    assert coding["code"] == _JP_MEDICATION_CODE_NOCODED_CODE == "NOCODED"
    # #305 session 60:display は権威 CodeSystem 定義通り
    # "標準コードなし" 固定(1-code / 1-display required binding)。
    assert coding["display"] == _JP_MEDICATION_CODE_NOCODED_DISPLAY == "標準コードなし"
    assert mr_jp["medicationCodeableConcept"]["text"]  # text は常に emit(薬剤名)

    # US:code_value 空 → fallback 発火しない(US 出力は eCS profile 対象外)
    mr_us = _build_mr("", country="US")
    assert "coding" not in mr_us["medicationCodeableConcept"]

    # US:code_value 空 → fallback 発火しない(US 出力は eCS profile 対象外)
    mr_us = _build_mr("", country="US")
    assert "coding" not in mr_us["medicationCodeableConcept"]


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
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin

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
    """MA builder も 12-char YJ code → YJ URI。Issue #1220: MEDIS full CS
    導入により fragment 依存廃止、任意の real MHLW YJ code が gate 通過。"""
    ma = _build_ma("1112700X1038")  # ハロタン (MEDIS 医薬品HOTマスター収録)
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


# Issue #775 — medicationCodeableConcept.text は製剤名のみ、
# dose / route / frequency / duration / conditional expression の混入禁止。


def _build_mr_from_display(display_name: str, country: str = "JP") -> dict[str, Any]:
    """Helper: build MR from a raw disease-YAML `display_name` (drug + dose + usage)."""
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request

    order = {
        "order_id": "ORD-text-cleanup",
        "display_name": display_name,
        "order_type": "medication",
        "order_code": "",
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


@pytest.mark.parametrize(
    "display_name,expected_text",
    [
        # dose のみ
        ("Ondansetron 4mg", "オンダンセトロン"),
        # dose + route + freq
        ("Meropenem 1g IV q8h", "メロペネム"),
        # dose + route + freq + duration
        ("Prednisolone 40mg PO qd x5 days", "プレドニゾロン"),
        # dose + route + freq + prn + condition
        ("Acetaminophen 500mg PO q6h prn temp >= 38.5", "アセトアミノフェン"),
        # dose + route
        ("Mannitol 200mL IV q8h", "マンニトール"),
    ],
)
def test_mr_text_excludes_dose_and_usage_jp(display_name: str, expected_text: str) -> None:
    """Issue #775: `medicationCodeableConcept.text` は clean drug name のみ。
    dose / route / freq / duration / condition tokens は含まない。"""
    mr = _build_mr_from_display(display_name, country="JP")
    text = mr["medicationCodeableConcept"]["text"]
    assert text == expected_text, f"expected clean name only, got: {text!r}"


@pytest.mark.parametrize(
    "display_name,expected_text",
    [
        ("Ondansetron 4mg", "Ondansetron"),
        ("Meropenem 1g IV q8h", "Meropenem"),
        ("Prednisolone 40mg PO qd x5 days", "Prednisolone"),
    ],
)
def test_mr_text_excludes_dose_and_usage_us(display_name: str, expected_text: str) -> None:
    """Issue #775 US 側:同 policy を US で確認(dose/usage 混入禁止)。"""
    mr = _build_mr_from_display(display_name, country="US")
    text = mr["medicationCodeableConcept"]["text"]
    assert text == expected_text, f"expected clean name only, got: {text!r}"


def test_mar_text_excludes_dose_and_usage_jp() -> None:
    """MedicationAdministration も同 policy(text = 製剤名のみ)。"""
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin

    mar = {
        "mar_id": "MAR-x",
        "drug_name": "Ondansetron 4mg",
        "code_yj": "",
        "administration_datetime": "2026-06-01T10:00:00",
        "dose": "4mg PO qd",
        "route": "oral",
        "status": "given",
    }
    ma = _build_medication_admin(mar, patient_id="pt1", index=1, country="JP", encounter_id="enc1")
    assert ma["medicationCodeableConcept"]["text"] == "オンダンセトロン"


def test_mr_text_falls_back_to_full_name_when_no_match() -> None:
    """drug_codes 未登録の drug — base_name (先頭 token) を localize したものを text に
    使う。dose は落ちる。"""
    mr = _build_mr_from_display("UnknownDrug 10mg", country="JP")
    text = mr["medicationCodeableConcept"]["text"]
    # 先頭 token = "UnknownDrug"(_localize_drug_name は unknown token を素通し)
    assert text == "UnknownDrug"


def test_mr_text_multi_word_drug_name_preserved() -> None:
    """ "Normal saline" 型の multi-word drug 名は longest-match で全体が base_name。
    dose "500mL" は落ちる。"""
    mr = _build_mr_from_display("Normal saline 500mL IV", country="JP")
    text = mr["medicationCodeableConcept"]["text"]
    # Normal saline が drug_codes に登録されていれば "生理食塩水" 相当が返る。
    # 未登録なら "Normal" 単独が base_name になり localize される。
    # いずれにせよ "500mL" / "IV" は含まれてはいけない。
    assert "500mL" not in text
    assert " IV" not in text
    assert "500" not in text
