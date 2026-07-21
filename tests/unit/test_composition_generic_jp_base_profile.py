"""Issue #340 — JP path で JP-CLINS profile 未対応 LOINC の Composition は
base FHIR Composition profile を meta.profile に明示追加する。

v12 (2026-07-21、seed=300 p=1000 master 8b85ed45) validation で 6 件 HTTP
timeout が全 workaround で不変、真因確定:LOINC 34823-5 (rehabilitation_plan)
の Composition が meta.profile 未指定 → HAPI validator 内部 hang(VS 展開
default path で LOINC 全走査)。

Fix: `_build_composition` dispatch で JP path かつ JP-CLINS builder に該当
しない LOINC には base FHIR Composition profile
(`http://hl7.org/fhir/StructureDefinition/Composition`)を明示追加。
sibling-sweep で全 JP generic-fallback LOINC(admission_hp / ED / outpatient
SOAP 等)にも同 fix 適用 = predictive prevention。

US path + JP-CLINS 対応 LOINC(18842-5 / 57133-1 / 53576-5)は unchanged。
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_composition import _build_composition

pytestmark = pytest.mark.unit


_BASE_FHIR_COMPOSITION_PROFILE = "http://hl7.org/fhir/StructureDefinition/Composition"


def _make_doc(loinc_code: str, language: str = "ja") -> dict:
    """Minimal ClinicalDocument dict shape for _build_composition."""
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


def test_jp_rehab_plan_composition_carries_base_profile() -> None:
    """Issue #340 regression pin: LOINC 34823-5 (rehabilitation_plan) が
    JP path で meta.profile に base FHIR Composition を明示保持する。"""
    doc = _make_doc("34823-5")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _BASE_FHIR_COMPOSITION_PROFILE in profiles, (
        f"Issue #340: JP rehab_plan Composition must carry base FHIR Composition "
        f"profile in meta.profile (v12 HAPI timeout 対策)。got: {profiles}"
    )


def test_jp_admission_hp_composition_carries_base_profile() -> None:
    """Sibling-sweep: LOINC 34117-2 (admission_hp) にも同 fix 適用済。"""
    doc = _make_doc("34117-2")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _BASE_FHIR_COMPOSITION_PROFILE in profiles


def test_jp_ed_note_composition_carries_base_profile() -> None:
    """Sibling-sweep: LOINC 34878-9 (ed_note) にも同 fix 適用済。"""
    doc = _make_doc("34878-9")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _BASE_FHIR_COMPOSITION_PROFILE in profiles


def test_jp_ecs_discharge_summary_composition_uses_jp_clins_profile() -> None:
    """Regression: LOINC 18842-5 は JP-CLINS eDS builder が dispatch されて
    JP_Composition_eDischargeSummary profile を持つ(base FHIR profile は追加
    されない)。dispatch 優先の pin。"""
    doc = _make_doc("18842-5")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    # eDS profile が primary、base FHIR profile は追加されない(dispatch 優先)
    assert any("JP_Composition_eDischargeSummary" in p for p in profiles), (
        f"eDS Composition must carry JP-CLINS eDS profile, got {profiles}"
    )
    assert _BASE_FHIR_COMPOSITION_PROFILE not in profiles, (
        "eDS Composition should NOT carry base FHIR profile (dedicated JP-CLINS builder path、base の追加は無用)"
    )


def test_jp_ereferral_composition_uses_jp_clins_profile() -> None:
    """Regression: LOINC 57133-1 は JP-CLINS eReferral builder dispatch。"""
    doc = _make_doc("57133-1")
    comp = _build_composition(doc, _make_sections(), "ja")
    profiles = comp.get("meta", {}).get("profile", [])
    assert any("JP_Composition_eReferral" in p for p in profiles)
    assert _BASE_FHIR_COMPOSITION_PROFILE not in profiles


def test_us_rehab_composition_no_profile_added() -> None:
    """US path は base FHIR Composition profile を追加しない(fix は JP 限定)。
    US path は既存挙動維持(meta 未設定 or 空)。"""
    doc = _make_doc("34823-5", language="en")
    comp = _build_composition(doc, _make_sections(), "en")
    profiles = comp.get("meta", {}).get("profile", [])
    assert _BASE_FHIR_COMPOSITION_PROFILE not in profiles, (
        f"US path Composition should NOT carry base FHIR profile (JP-only fix)、got {profiles}"
    )
