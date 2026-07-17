"""Unit tests for _fhir_care_team builder (Tier 1 #3 α-min-2 Task 11)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.output._fhir_care_team import (
    CARE_TEAM_ID_PREFIX,
    _bb_care_teams,
)
from clinosim.types.encounter import Encounter, EncounterType

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_ctx(encounters, patient_id="pt1", country="us"):
    """Minimal BundleContext substitute."""
    return SimpleNamespace(
        record={
            "patient": {"patient_id": patient_id},
            "encounters": encounters,
            "extensions": {},
        },
        country=country,
        patient_id=patient_id,
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": patient_id},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )


def _inpatient_enc_dataclass(nurse_id: str = "nurse-001") -> Encounter:
    return Encounter(
        encounter_id="enc-inpt-1",
        patient_id="pt1",
        encounter_type=EncounterType.INPATIENT,
        attending_physician_id="dr-001",
        primary_nurse_id=nurse_id,
        admission_datetime=datetime(2026, 1, 10, 8, 0, 0),
        discharge_datetime=datetime(2026, 1, 15, 11, 0, 0),
    )


def _outpatient_enc_dataclass() -> Encounter:
    return Encounter(
        encounter_id="enc-outp-1",
        patient_id="pt1",
        encounter_type=EncounterType.OUTPATIENT,
        attending_physician_id="dr-002",
        primary_nurse_id="",
        admission_datetime=datetime(2026, 2, 5, 9, 0, 0),
        discharge_datetime=datetime(2026, 2, 5, 10, 30, 0),
    )


def _ed_enc_dataclass() -> Encounter:
    return Encounter(
        encounter_id="enc-ed-1",
        patient_id="pt1",
        encounter_type=EncounterType.EMERGENCY,
        attending_physician_id="dr-003",
        primary_nurse_id="",
        admission_datetime=datetime(2026, 3, 1, 22, 0, 0),
        discharge_datetime=datetime(2026, 3, 2, 4, 0, 0),
    )


def _inpatient_enc_dict(nurse_id: str = "nurse-001") -> dict:
    return {
        "encounter_id": "enc-inpt-2",
        "patient_id": "pt1",
        "encounter_type": "inpatient",
        "attending_physician_id": "dr-001",
        "primary_nurse_id": nurse_id,
        "admission_datetime": datetime(2026, 4, 10, 8, 0, 0),
        "discharge_datetime": datetime(2026, 4, 15, 11, 0, 0),
    }


# ---------------------------------------------------------------------------
# Shape tests
# ---------------------------------------------------------------------------


def test_care_team_has_required_fields():
    ctx = _make_ctx([_inpatient_enc_dataclass()])
    results = _bb_care_teams(ctx)
    assert len(results) == 1
    ct = results[0]
    assert ct["resourceType"] == "CareTeam"
    assert "id" in ct
    assert "status" in ct
    assert "subject" in ct


def test_care_team_id_uses_canonical_prefix():
    ctx = _make_ctx([_inpatient_enc_dataclass()])
    ct = _bb_care_teams(ctx)[0]
    assert ct["id"].startswith(CARE_TEAM_ID_PREFIX)
    assert ct["id"] == f"{CARE_TEAM_ID_PREFIX}enc-inpt-1"


def test_care_team_subject_references_patient():
    ctx = _make_ctx([_inpatient_enc_dataclass()], patient_id="patient-42")
    ct = _bb_care_teams(ctx)[0]
    assert ct["subject"]["reference"] == "Patient/patient-42"


def test_care_team_encounter_reference_populated():
    ctx = _make_ctx([_inpatient_enc_dataclass()])
    ct = _bb_care_teams(ctx)[0]
    assert ct["encounter"]["reference"] == "Encounter/enc-inpt-1"


# ---------------------------------------------------------------------------
# Status: active vs inactive
# ---------------------------------------------------------------------------


def test_discharged_encounter_status_is_inactive():
    enc = _inpatient_enc_dataclass()  # has discharge_datetime
    ctx = _make_ctx([enc])
    ct = _bb_care_teams(ctx)[0]
    assert ct["status"] == "inactive"


def test_in_progress_encounter_status_is_active():
    enc = Encounter(
        encounter_id="enc-ip-2",
        patient_id="pt1",
        encounter_type=EncounterType.INPATIENT,
        attending_physician_id="dr-001",
        primary_nurse_id="nurse-001",
        admission_datetime=datetime(2026, 5, 1, 8, 0, 0),
        discharge_datetime=None,
    )
    ctx = _make_ctx([enc])
    ct = _bb_care_teams(ctx)[0]
    assert ct["status"] == "active"


# ---------------------------------------------------------------------------
# Participant tests
# ---------------------------------------------------------------------------


def test_inpatient_encounter_emits_2_participants():
    ctx = _make_ctx([_inpatient_enc_dataclass(nurse_id="nurse-001")])
    ct = _bb_care_teams(ctx)[0]
    assert len(ct["participant"]) == 2


def test_outpatient_encounter_emits_1_participant():
    ctx = _make_ctx([_outpatient_enc_dataclass()])
    ct = _bb_care_teams(ctx)[0]
    assert len(ct["participant"]) == 1


def test_ed_encounter_emits_1_participant():
    ctx = _make_ctx([_ed_enc_dataclass()])
    ct = _bb_care_teams(ctx)[0]
    assert len(ct["participant"]) == 1


def test_participants_reference_practitioners():
    ctx = _make_ctx([_inpatient_enc_dataclass(nurse_id="nurse-99")])
    ct = _bb_care_teams(ctx)[0]
    refs = [p["member"]["reference"] for p in ct["participant"]]
    assert "Practitioner/dr-001" in refs
    assert "Practitioner/nurse-99" in refs


def test_empty_primary_nurse_id_no_orphan_participant():
    """primary_nurse_id='' must NOT produce a Practitioner/ reference."""
    ctx = _make_ctx([_outpatient_enc_dataclass()])
    ct = _bb_care_teams(ctx)[0]
    refs = [p["member"]["reference"] for p in ct["participant"]]
    # None of the refs should be "Practitioner/"
    assert all(r != "Practitioner/" for r in refs)
    assert len(refs) == 1


# ---------------------------------------------------------------------------
# Missing attending — UNKNOWN placeholder
# ---------------------------------------------------------------------------


def test_missing_attending_uses_UNKNOWN_placeholder():
    enc = Encounter(
        encounter_id="enc-nodr",
        patient_id="pt1",
        encounter_type=EncounterType.INPATIENT,
        attending_physician_id="",  # missing
        primary_nurse_id="nurse-1",
        admission_datetime=datetime(2026, 1, 1, 8, 0),
    )
    ctx = _make_ctx([enc])
    ct = _bb_care_teams(ctx)[0]
    refs = [p["member"]["reference"] for p in ct["participant"]]
    # UNKNOWN placeholder is used
    assert any("UNKNOWN" in r for r in refs), f"Expected UNKNOWN in {refs}"


# ---------------------------------------------------------------------------
# Period tests
# ---------------------------------------------------------------------------


def test_care_team_period_from_encounter_datetimes():
    enc = _inpatient_enc_dataclass()
    ctx = _make_ctx([enc])
    ct = _bb_care_teams(ctx)[0]
    assert "period" in ct
    assert "start" in ct["period"]
    assert "end" in ct["period"]
    assert "2026-01-10" in ct["period"]["start"]
    assert "2026-01-15" in ct["period"]["end"]


def test_in_progress_period_has_no_end():
    enc = Encounter(
        encounter_id="enc-ip-3",
        patient_id="pt1",
        encounter_type=EncounterType.INPATIENT,
        attending_physician_id="dr-001",
        primary_nurse_id="nurse-001",
        admission_datetime=datetime(2026, 6, 1, 8, 0, 0),
        discharge_datetime=None,
    )
    ctx = _make_ctx([enc])
    ct = _bb_care_teams(ctx)[0]
    assert "period" in ct
    assert "start" in ct["period"]
    assert "end" not in ct["period"]


# ---------------------------------------------------------------------------
# Empty encounters list
# ---------------------------------------------------------------------------


def test_empty_encounters_returns_empty_list():
    ctx = _make_ctx([])
    assert _bb_care_teams(ctx) == []


def test_missing_encounters_key_returns_empty_list():
    ctx = SimpleNamespace(
        record={"patient": {"patient_id": "pt1"}, "extensions": {}},
        country="us",
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )
    assert _bb_care_teams(ctx) == []


# ---------------------------------------------------------------------------
# JP locale
# ---------------------------------------------------------------------------


def test_jp_locale_category_display_in_ja():
    ctx = _make_ctx([_inpatient_enc_dataclass()], country="jp")
    ct = _bb_care_teams(ctx)[0]
    # category coding display should be Japanese
    display = ct["category"][0]["coding"][0]["display"]
    # Should contain Japanese characters (not just ASCII "Clinical team")
    assert any("　" <= ch <= "鿿" or "゠" <= ch <= "ヿ" for ch in display), (
        f"Expected Japanese characters in category display, got: {display!r}"
    )


# ---------------------------------------------------------------------------
# Category system + code pin. History:
#   - LA27976-8: unknown in LOINC 2.82 (v1 feedback 2026-07-16)
#   - 424535000: inactive in SNOMED CT International Edition
#   - 735320007: unknown in SNOMED International 2026-06-01 (v2 feedback
#     2026-07-17_full_v2, 3,788 rejections)
# Current authoritative value: 407484005 "Rehabilitation care team"
# — v2 feedback recommendation, verified present in the fhirserver's
# SNOMED International 2026-06-01 loadout.
# ---------------------------------------------------------------------------


def test_care_team_category_uses_active_snomed_code():
    ctx = _make_ctx([_inpatient_enc_dataclass()])
    ct = _bb_care_teams(ctx)[0]
    coding = ct["category"][0]["coding"][0]
    assert coding["system"] == "http://snomed.info/sct", (
        f"CareTeam.category.system must be SNOMED CT, got: {coding['system']!r}"
    )
    assert coding["code"] == "407484005", f"CareTeam.category.code must be 407484005, got: {coding['code']!r}"


# ---------------------------------------------------------------------------
# Dict path (PR-90 lesson: dual access)
# ---------------------------------------------------------------------------


def test_dict_path_records_work():
    """Dict-format encounter (production CIF) must produce valid CareTeam."""
    enc_dict = _inpatient_enc_dict(nurse_id="nurse-dict-1")
    ctx = _make_ctx([enc_dict])
    results = _bb_care_teams(ctx)
    assert len(results) == 1
    ct = results[0]
    assert ct["resourceType"] == "CareTeam"
    assert ct["id"] == f"{CARE_TEAM_ID_PREFIX}enc-inpt-2"
    refs = [p["member"]["reference"] for p in ct["participant"]]
    assert "Practitioner/dr-001" in refs
    assert "Practitioner/nurse-dict-1" in refs


def test_dataclass_path_records_work():
    """Dataclass-format encounter must also produce valid CareTeam."""
    enc = _inpatient_enc_dataclass(nurse_id="nurse-dc-1")
    ctx = _make_ctx([enc])
    results = _bb_care_teams(ctx)
    assert len(results) == 1
    ct = results[0]
    assert ct["resourceType"] == "CareTeam"
    refs = [p["member"]["reference"] for p in ct["participant"]]
    assert "Practitioner/dr-001" in refs
    assert "Practitioner/nurse-dc-1" in refs


# ---------------------------------------------------------------------------
# Multiple encounters
# ---------------------------------------------------------------------------


def test_multiple_encounters_emit_multiple_care_teams():
    encs = [_inpatient_enc_dataclass(), _outpatient_enc_dataclass()]
    ctx = _make_ctx(encs)
    results = _bb_care_teams(ctx)
    assert len(results) == 2
    ids = {ct["id"] for ct in results}
    assert f"{CARE_TEAM_ID_PREFIX}enc-inpt-1" in ids
    assert f"{CARE_TEAM_ID_PREFIX}enc-outp-1" in ids
