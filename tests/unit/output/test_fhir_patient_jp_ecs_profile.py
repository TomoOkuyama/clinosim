"""Regression pin for Issue #378: Patient.meta.profile carries both
JP_Patient (JP Core) and JP_Patient_eCS (JP-CLINS).

Pre-fix, JP Patient only declared JP_Patient; JP-CLINS eCS Observations,
Conditions, and MedicationRequests referencing the patient via
`subject.reference` triggered validator errors because the referenced
Patient did not assert JP_Patient_eCS. In the v25 full-set report
(2026-07-23), this single omission accounted for 3,096 errors, including
100% (736/736) of Conditions failing validation.

Fix: declare both profile URIs (multi-profile assertion — FHIR R4
`Resource.meta.profile 0..*`). This test pins the URIs + ordering so
neither can silently be dropped nor reordered.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_patient import _build_patient

pytestmark = pytest.mark.unit

_JP_PATIENT = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"
_JP_PATIENT_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS"


def _sample_p() -> dict:
    return {
        "patient_id": "pt-1",
        "family_name_kanji": "田中",
        "given_name_kanji": "太郎",
        "family_name_kana": "タナカ",
        "given_name_kana": "タロウ",
        "sex": "male",
        "birthdate": "1970-01-01",
    }


def test_jp_patient_meta_profile_carries_both_jp_core_and_jp_clins_ecs() -> None:
    """Issue #378 core assertion: JP Patient carries JP_Patient AND
    JP_Patient_eCS in meta.profile."""
    p = _build_patient(_sample_p(), country="JP")
    profiles = p.get("meta", {}).get("profile", [])
    assert _JP_PATIENT in profiles, "JP_Patient (JP Core) missing"
    assert _JP_PATIENT_ECS in profiles, "JP_Patient_eCS (JP-CLINS) missing"


def test_jp_patient_meta_profile_order_pinned() -> None:
    """JP_Patient (Core) first, JP_Patient_eCS (CLINS) second. Ordering
    is not FHIR-significant but pinning it prevents a silent swap that
    would show up as a byte-diff regression in downstream test fixtures."""
    p = _build_patient(_sample_p(), country="JP")
    profiles = p["meta"]["profile"]
    assert profiles == [_JP_PATIENT, _JP_PATIENT_ECS]


def test_us_patient_omits_meta_profile_entirely() -> None:
    """US export intentionally omits meta.profile (no US Core profile is
    asserted — a separate roadmap item). Regression pin: adding
    JP_Patient_eCS must NOT leak the JP profile into US output."""
    p = _build_patient(_sample_p(), country="US")
    assert "meta" not in p or "profile" not in p.get("meta", {}), f"US Patient carries meta.profile: {p.get('meta')}"
