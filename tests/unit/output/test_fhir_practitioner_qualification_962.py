"""Practitioner qualification + regulatory-license identifier (Issue #962).

Guards the two gaps closed by Issue #962:

* Gap 1 — every JP Practitioner emits at least one
  ``qualification[]`` entry with the MHLW-coded ``code_system``
  (previously PH/PT/OT/ST/RD/MSW/TECH were text-only, blocking
  code-driven consumers). Physicians / radiologists additionally emit
  a second qualification entry for their specialty board
  (循環器専門医 / 消化器専門医 / …) derived from ``PractitionerRole.specialty``.
* Gap 2 — every JP MHLW-licensed Practitioner emits a
  ``JP_Practitioner_*LicenseNumber`` identifier entry alongside the
  internal ``urn:clinosim:staff`` key. Deterministic per-staff_id
  (SHA-256 salted), so re-runs are byte-identical.

US path is intentionally left untouched — its v2-0360 ``MD`` / ``RN``
codes remain, and no license identifier is added (no US-side
regulatory-license system is modeled). Test asserts the negative to
lock that boundary.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.practitioner import _build_practitioner

pytestmark = pytest.mark.unit

_JP_MHLW_QUAL_SYSTEM = "urn:oid:1.2.392.100495.20.1.75"
_JP_PHYSICIAN_LIC_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/JP_Practitioner_MedicalLicenseNumber"
_JP_NURSE_LIC_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/JP_Practitioner_NursingLicenseNumber"
_JP_PHARM_LIC_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/JP_Practitioner_PharmacistLicenseNumber"
_JP_TECH_LIC_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/JP_Practitioner_ClinicalLabTechnicianLicenseNumber"


def _staff(**overrides: object) -> dict:
    base: dict = {
        "name": "山田 太郎",
        "name_phonetic": "ヤマダ タロウ",
        "role": "physician",
        "department": "cardiology",
        "specialty": "cardiology",
        "qualification_year": 2001,
        "sex": "M",
        "phone": "03-1234-5678",
        "email": "test@hospital.example.org",
    }
    base.update(overrides)
    return base


def _first_qual_coding(resource: dict) -> dict:
    qualifications = resource.get("qualification") or []
    assert qualifications, f"missing qualification[]: {resource!r}"
    coding = (qualifications[0].get("code") or {}).get("coding") or []
    assert coding, f"first qualification[] entry has no coding: {qualifications[0]!r}"
    return coding[0]


def _license_identifier(resource: dict, system: str) -> dict | None:
    for ident in resource.get("identifier", []) or []:
        if ident.get("system") == system:
            return ident
    return None


# ---------------------------------------------------------------------------
# Gap 1 — qualification[] coded emit for JP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "expected_code", "expected_display"),
    [
        ("pharmacist", "Pharmacist", "薬剤師"),
        ("lab_technician", "ClinicalLabTechnician", "臨床検査技師"),
        ("physical_therapist", "PhysicalTherapist", "理学療法士"),
        ("occupational_therapist", "OccupationalTherapist", "作業療法士"),
        ("speech_therapist", "SpeechTherapist", "言語聴覚士"),
        ("dietitian", "RegisteredDietitian", "管理栄養士"),
        ("medical_social_worker", "MedicalSocialWorker", "医療ソーシャルワーカー"),
    ],
)
def test_jp_allied_health_qualification_is_coded(role: str, expected_code: str, expected_display: str) -> None:
    """Allied-health / pharmacy / lab-tech roles now emit MHLW-coded
    qualifications (previously text-only fallback per feedback FB-F7)."""
    staff_id = f"{role[:2].upper()}-001"
    roster = {staff_id: _staff(role=role, department="general", specialty="")}
    resource = _build_practitioner(staff_id, roster, country="JP")
    coding = _first_qual_coding(resource)
    assert coding["system"] == _JP_MHLW_QUAL_SYSTEM
    assert coding["code"] == expected_code
    assert coding["display"] == expected_display


def test_jp_physician_gets_specialty_board_as_second_qualification() -> None:
    """A cardiologist emits both MD and 循環器専門医 (Issue #962 Gap 1)."""
    roster = {"DR-CA-001": _staff(role="physician", department="cardiology", specialty="cardiology")}
    resource = _build_practitioner("DR-CA-001", roster, country="JP")
    quals = resource.get("qualification") or []
    assert len(quals) == 2, quals
    codes = [(q["code"]["coding"][0]["code"], q["code"]["coding"][0]["display"]) for q in quals]
    assert codes[0] == ("MedicalDoctor", "医師")
    assert codes[1] == ("CardiologySpecialist", "循環器専門医")


def test_jp_physician_without_board_mapping_still_gets_md() -> None:
    """A physician assigned to a department not in
    ``physician_specialty_boards`` still gets MHLW-coded MD but no
    second qualification entry — the emit degrades gracefully."""
    roster = {
        "DR-XX-001": _staff(role="physician", department="unmapped_dept", specialty="unmapped_dept"),
    }
    resource = _build_practitioner("DR-XX-001", roster, country="JP")
    quals = resource.get("qualification") or []
    assert len(quals) == 1
    assert quals[0]["code"]["coding"][0]["code"] == "MedicalDoctor"


# ---------------------------------------------------------------------------
# Gap 2 — regulatory-license identifier emit for JP
# ---------------------------------------------------------------------------


def test_jp_physician_emits_medical_license_identifier() -> None:
    roster = {"DR-CA-001": _staff(role="physician", department="cardiology", specialty="cardiology")}
    resource = _build_practitioner("DR-CA-001", roster, country="JP")
    lic = _license_identifier(resource, _JP_PHYSICIAN_LIC_SYSTEM)
    assert lic is not None, resource["identifier"]
    assert lic["use"] == "official"
    assert lic["type"]["text"] == "医籍番号"
    # "第<6-digit>号" per JP-CLINS 医籍番号 convention
    assert lic["value"].startswith("第") and lic["value"].endswith("号")
    assert lic["value"][1:-1].isdigit()
    assert len(lic["value"][1:-1]) == 6


def test_jp_nurse_emits_nursing_license_identifier() -> None:
    roster = {"NS-CA-001": _staff(role="nurse", department="cardiology", specialty="cardiology")}
    resource = _build_practitioner("NS-CA-001", roster, country="JP")
    lic = _license_identifier(resource, _JP_NURSE_LIC_SYSTEM)
    assert lic is not None
    assert lic["type"]["text"] == "看護師籍登録番号"
    assert lic["value"].isdigit() and len(lic["value"]) == 8


def test_jp_pharmacist_and_tech_emit_license_identifiers() -> None:
    roster = {
        "PH-001": _staff(role="pharmacist", department="pharmacy", specialty=""),
        "TECH-LAB-001": _staff(role="lab_technician", department="laboratory", specialty=""),
    }
    ph = _build_practitioner("PH-001", roster, country="JP")
    tech = _build_practitioner("TECH-LAB-001", roster, country="JP")
    assert _license_identifier(ph, _JP_PHARM_LIC_SYSTEM) is not None
    assert _license_identifier(tech, _JP_TECH_LIC_SYSTEM) is not None


def test_jp_msw_has_qualification_but_no_license_identifier() -> None:
    """MSW is not an MHLW-licensed profession — qualification stays,
    but no ``JP_Practitioner_*LicenseNumber`` identifier is emitted."""
    roster = {"MSW-001": _staff(role="medical_social_worker", department="social_services", specialty="")}
    resource = _build_practitioner("MSW-001", roster, country="JP")
    quals = resource.get("qualification") or []
    assert quals and quals[0]["code"]["coding"][0]["code"] == "MedicalSocialWorker"
    for ident in resource.get("identifier", []) or []:
        assert "JP_Practitioner_" not in (ident.get("system") or ""), ident


def test_jp_license_number_is_deterministic() -> None:
    """Regenerating the same staff_id gives byte-identical license
    numbers — RNG-neutral additive field per
    ``feedback_rng_neutral_additive_field.md``."""
    roster = {"DR-CA-001": _staff()}
    r1 = _build_practitioner("DR-CA-001", roster, country="JP")
    r2 = _build_practitioner("DR-CA-001", roster, country="JP")
    lic1 = _license_identifier(r1, _JP_PHYSICIAN_LIC_SYSTEM)
    lic2 = _license_identifier(r2, _JP_PHYSICIAN_LIC_SYSTEM)
    assert lic1 == lic2


# ---------------------------------------------------------------------------
# Cross-locale invariants
# ---------------------------------------------------------------------------


def test_us_practitioner_keeps_v2_0360_and_no_jp_license() -> None:
    """US locale unchanged — physician still emits v2-0360 ``MD`` and no
    JP-CLINS ``JP_Practitioner_*LicenseNumber`` identifier leaks in."""
    roster = {"DR-CA-001": _staff(name="John Smith", name_phonetic="")}
    resource = _build_practitioner("DR-CA-001", roster, country="US")
    quals = resource.get("qualification") or []
    assert len(quals) == 1
    coding = quals[0]["code"]["coding"][0]
    assert coding["system"] == "http://terminology.hl7.org/CodeSystem/v2-0360"
    assert coding["code"] == "MD"
    for ident in resource.get("identifier", []) or []:
        assert "JP_Practitioner_" not in (ident.get("system") or ""), ident
