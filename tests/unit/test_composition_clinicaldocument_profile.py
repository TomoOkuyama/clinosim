"""Issue #340 — JP path で JP-CLINS profile が存在しない Composition は
HL7 FHIR R4 core の `clinicaldocument` profile を meta.profile に明示宣言する。

## Rationale

`http://hl7.org/fhir/StructureDefinition/clinicaldocument` は HL7 R4 core
公式 profile で Composition の refinement(baseDefinition = Composition)。
constraints:

1. `Composition.subject` targetProfile を Patient / Practitioner / Group /
   Device / Location に制限
2. `versionNumber` extension slice を宣言

clinosim の Composition は subject = Patient reference で emit
(`_build_composition_generic`)、targetProfile 完全準拠。

「これは clinical document」の semantic を国際 profile で宣言する
= base FHIR Composition profile を列挙するような redundant hack ではなく
FHIR-faithful な improvement。

## Side effect (secondary)

HAPI validator の VS 展開 default path 回避
(v13 (2026-07-21) で HAPI 6.9.12 upgrade / okhttp3 化 / chunk 縮小 /
Display cache patch 等 7 workaround 全滅した internal bug 対策、
ただし profile 宣言自体は spec 準拠かつ意味的に honest)。

## Scope

JP-CLINS eDS / eReferral / eCheckup General の baseDefinition は
Composition 直下(clinicaldocument 経由でない)ため、それらの dispatch
path は変更せず(既存 profile は追加の意味を提供済み)。US path は
現時点で変更せず(将来 US 側 timeout 発生時に検討)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.modules.output._fhir_composition import _build_composition

pytestmark = pytest.mark.unit


_CLINICALDOCUMENT_PROFILE = "http://hl7.org/fhir/StructureDefinition/clinicaldocument"

_HL7_R4_CORE_SD = (
    Path(__file__).resolve().parents[2]
    / ".."
    / "fhir-jp-validator"
    / "tx-server-build"
    / "terminology"
    / "fhir-server"
    / "hl7.fhir.r4.core#4.0.1"
    / "package"
    / "StructureDefinition-clinicaldocument.json"
)


def _make_doc(loinc_code: str, language: str = "ja") -> dict:
    return {
        "document_id": "doc-ENC-TEST-01",
        "loinc_code": loinc_code,
        "patient_id": "PAT-001",
        "encounter_id": "ENC-TEST",
        "author_practitioner_id": "DR-001",
        "authored_datetime": "2026-01-15T10:00:00",
        "language": language,
        "format_type": "composition",
        "narrative": {"sections": {"body": "本文"}},
    }


def _make_sections() -> dict[str, str]:
    return {"body": "本文"}


# === profile 適用 pin(rehab_plan と sibling-sweep 対象 LOINC)===


def test_jp_rehab_plan_composition_declares_clinicaldocument_profile() -> None:
    """Issue #340 regression pin: LOINC 34823-5 (rehabilitation_plan) が
    JP path で meta.profile に HL7 R4 clinicaldocument を宣言する。"""
    doc = _make_doc("34823-5")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _CLINICALDOCUMENT_PROFILE in profiles, (
        f"Issue #340: JP rehab_plan Composition must declare clinicaldocument "
        f"profile in meta.profile (HL7 R4 core、subject targetProfile 準拠)。"
        f"got: {profiles}"
    )


def test_jp_admission_hp_declares_clinicaldocument_profile() -> None:
    """Sibling-sweep: LOINC 34117-2 (admission_hp) にも同 fix 適用。"""
    doc = _make_doc("34117-2")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _CLINICALDOCUMENT_PROFILE in profiles


def test_jp_ed_note_declares_clinicaldocument_profile() -> None:
    """Sibling-sweep: LOINC 34878-9 (ed_note) にも同 fix 適用。"""
    doc = _make_doc("34878-9")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _CLINICALDOCUMENT_PROFILE in profiles


def test_jp_outpatient_soap_declares_clinicaldocument_profile() -> None:
    """Sibling-sweep: LOINC 34131-3 (outpatient_soap) にも同 fix 適用。"""
    doc = _make_doc("34131-3")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _CLINICALDOCUMENT_PROFILE in profiles


# === JP-CLINS dispatch 優先 pin(clinicaldocument 追加しない)===


def test_jp_ecs_discharge_summary_uses_jp_clins_profile_only() -> None:
    """Regression: LOINC 18842-5 は JP-CLINS eDS builder dispatch 優先。
    baseDefinition = Composition 直下(clinicaldocument 経由でない)、
    既存 profile が完全な semantic を提供済みなので追加しない。"""
    doc = _make_doc("18842-5")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert any("JP_Composition_eDischargeSummary" in p for p in profiles), (
        f"eDS Composition must carry JP-CLINS eDS profile, got {profiles}"
    )
    assert _CLINICALDOCUMENT_PROFILE not in profiles, (
        "eDS Composition は既に JP-CLINS 特有 profile 保持、clinicaldocument "
        "追加は redundant(baseDefinition = Composition の 2 段階 refinement)。"
    )


def test_jp_ereferral_uses_jp_clins_profile_only() -> None:
    """Regression: LOINC 57133-1 は JP-CLINS eReferral dispatch 優先。"""
    doc = _make_doc("57133-1")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert any("JP_Composition_eReferral" in p for p in profiles)
    assert _CLINICALDOCUMENT_PROFILE not in profiles


def test_jp_echeckup_general_uses_jp_clins_profile_only() -> None:
    """Regression: LOINC 53576-5 は JP-eCheckup dispatch 優先。"""
    doc = _make_doc("53576-5")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert any("JP_Composition_eCheckupGeneral" in p for p in profiles)
    assert _CLINICALDOCUMENT_PROFILE not in profiles


# === US path 未変更 pin ===


def test_us_composition_no_clinicaldocument_added() -> None:
    """US path は clinicaldocument profile を追加しない(fix scope は JP 限定、
    US 側 timeout 発生時に検討)。US path は既存挙動維持。"""
    doc = _make_doc("34823-5", language="en")
    comp = _build_composition(doc, _make_sections(), "en")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _CLINICALDOCUMENT_PROFILE not in profiles, (
        f"US path Composition should NOT carry clinicaldocument profile (JP-only fix scope)、got {profiles}"
    )


# === Spec 準拠性 pin(feedback_verify_fhir_profile_uri_from_spec rule 適用)===


def test_clinicaldocument_profile_url_matches_hl7_r4_core_spec() -> None:
    """HL7 R4 core spec の StructureDefinition.url を直接引用していることを pin。
    spec revision で URL が変わった場合、この test が fail して migration 契機
    を提供する(session 51 の feedback_verify_fhir_profile_uri_from_spec rule
    適用)。"""
    if not _HL7_R4_CORE_SD.exists():
        pytest.skip(f"HL7 R4 core SD not available at {_HL7_R4_CORE_SD}")
    with open(_HL7_R4_CORE_SD) as f:
        sd = json.load(f)
    assert sd.get("url") == _CLINICALDOCUMENT_PROFILE, (
        f"spec URL drift: expected {_CLINICALDOCUMENT_PROFILE!r}, got {sd.get('url')!r}"
    )
    # baseDefinition = Composition(clinosim data conformance 前提の確認)
    assert sd.get("baseDefinition", "").startswith("http://hl7.org/fhir/StructureDefinition/Composition"), (
        f"clinicaldocument must derive from Composition, got baseDefinition={sd.get('baseDefinition')}"
    )


def test_clinicaldocument_subject_target_profile_includes_patient() -> None:
    """clinicaldocument profile の Composition.subject constraint が Patient を
    含むことを spec から pin(clinosim は Patient reference で subject を emit
    しているため、この constraint に conformant である前提)。"""
    if not _HL7_R4_CORE_SD.exists():
        pytest.skip(f"HL7 R4 core SD not available at {_HL7_R4_CORE_SD}")
    with open(_HL7_R4_CORE_SD) as f:
        sd = json.load(f)
    subject_element = next(
        (e for e in sd.get("differential", {}).get("element", []) if e.get("id") == "Composition.subject"),
        None,
    )
    assert subject_element is not None, "clinicaldocument spec must constrain Composition.subject"
    target_profiles = subject_element.get("type", [{}])[0].get("targetProfile", [])
    assert "http://hl7.org/fhir/StructureDefinition/Patient" in target_profiles, (
        f"Patient must be in subject targetProfile, got {target_profiles}"
    )
