"""P2-13 PR2a Task 1: jpfhir doc-typecodes + doc-section-codes lookup."""

from __future__ import annotations

import pytest

from clinosim.codes import get_system_uri, lookup


@pytest.mark.unit
def test_jpfhir_doc_typecodes_system_uri():
    assert get_system_uri("jpfhir-doc-typecodes") == ("http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes")


@pytest.mark.unit
def test_jpfhir_doc_section_system_uri():
    # session 53 iris4h-ai feedback D: URL は JP-CLINS spec `.url` fixedUri
    # に一致する。resource id (`jp-codeSystem-clins-document-section`) を
    # path segment に含めない。
    assert get_system_uri("jpfhir-doc-section") == "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,ja",
    [
        ("18842-5", "退院時サマリー"),
        ("57133-1", "診療情報提供書"),
        # session 47 PR3:JPGCHKUP01 は誤りで、JP-eCheckup が LOINC 53576-5 を使用
        ("53576-5", "検診・健診報告書"),
        ("57833-6", "処方箋"),
        ("56447-6", "計画書"),
    ],
)
def test_jpfhir_doc_typecodes_ja_lookup(code, ja):
    assert lookup("jpfhir-doc-typecodes", code, "ja") == ja


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,ja",
    [
        ("300", "構造情報セクション"),
        ("312", "入院理由セクション"),
        ("322", "入院時詳細セクション"),
        ("342", "入院時診断セクション"),
        ("352", "主訴セクション"),
        ("360", "現病歴セクション"),
        ("910", "紹介先情報セクション"),
        ("920", "紹介元情報セクション"),
        ("950", "紹介目的セクション"),
        ("422", "計画サマリーセクション"),
    ],
)
def test_jpfhir_doc_section_ja_lookup(code, ja):
    assert lookup("jpfhir-doc-section", code, "ja") == ja


@pytest.mark.unit
def test_jpfhir_doc_typecodes_en_fallback():
    assert lookup("jpfhir-doc-typecodes", "18842-5", "en") == "Discharge summary"


@pytest.mark.unit
def test_unknown_code_returns_code_itself():
    assert lookup("jpfhir-doc-typecodes", "UNKNOWN", "ja") == "UNKNOWN"
