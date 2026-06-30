"""Unit tests for _fhir_allergy_intolerance builder (Tier 1 #3 α-min-1 Task 9)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from clinosim.modules.document import ALLERGY_ID_PREFIX
from clinosim.modules.output._fhir_allergy_intolerance import _bb_allergy_intolerances
from clinosim.types.allergy import Allergy, AllergyReaction


def _make_ctx(allergies, country="us"):
    return SimpleNamespace(
        record={"patient": {"allergies": allergies, "patient_id": "pt1"}, "extensions": {}},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={"allergies": allergies, "patient_id": "pt1"},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )


def _sample_allergy_dataclass() -> Allergy:
    return Allergy(
        allergy_id="a01",
        allergen_code="372687004",
        allergen_display="Amoxicillin",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 3, 15),
        reactions=[
            AllergyReaction(
                manifestation_snomed="271807003",
                manifestation_display="Rash",
                severity="mild",
            ),
        ],
    )


def _sample_allergy_dict() -> dict:
    return {
        "allergy_id": "a01",
        "allergen_code": "372687004",
        "allergen_display": "Amoxicillin",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": date(2020, 3, 15),
        "reactions": [
            {
                "manifestation_snomed": "271807003",
                "manifestation_display": "Rash",
                "severity": "mild",
            }
        ],
    }


# --- Empty / no allergies ---

def test_no_allergies_emits_nothing():
    ctx = _make_ctx([])
    assert _bb_allergy_intolerances(ctx) == []


def test_missing_allergies_key_emits_nothing():
    ctx = SimpleNamespace(
        record={"patient": {}, "extensions": {}},
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
    assert _bb_allergy_intolerances(ctx) == []


# --- Resource shape ---

def test_emits_one_allergy_intolerance_dataclass():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    resources = _bb_allergy_intolerances(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "AllergyIntolerance"


def test_allergy_id_uses_canonical_prefix():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["id"].startswith(ALLERGY_ID_PREFIX)
    assert r["id"] == f"{ALLERGY_ID_PREFIX}pt1-a01"


def test_clinical_status_active():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    coding = r["clinicalStatus"]["coding"][0]
    assert coding["code"] == "active"
    assert "allergyintolerance-clinical" in coding["system"]


def test_verification_status_confirmed():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    coding = r["verificationStatus"]["coding"][0]
    assert coding["code"] == "confirmed"
    assert "allergyintolerance-verification" in coding["system"]


def test_category_medication():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["category"] == ["medication"]


def test_criticality_high():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["criticality"] == "high"


def test_code_snomed_allergen():
    # allergen_code "372687004" = Aspirin in SNOMED. code_lookup resolves to "Aspirin"
    # (locale-aware, overrides the fixture's allergen_display "Amoxicillin").
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    coding = r["code"]["coding"][0]
    assert coding["code"] == "372687004"
    assert "snomed" in coding["system"].lower() or "snomed.info" in coding["system"]
    assert r["code"]["text"] == "Aspirin"


def test_patient_reference():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["patient"]["reference"] == "Patient/pt1"


def test_onset_datetime():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["onsetDateTime"] == "2020-03-15"


def test_reaction_manifestation_and_severity():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert "reaction" in r
    rxn = r["reaction"][0]
    assert rxn["severity"] == "mild"
    manifestation = rxn["manifestation"][0]
    assert manifestation["coding"][0]["code"] == "271807003"
    assert manifestation["text"] == "Rash"


# --- Dict path ---

def test_allergy_from_dict_path():
    """Production CIF is json.load() -> dict; verify _o() dict-access path."""
    ctx = _make_ctx([_sample_allergy_dict()])
    resources = _bb_allergy_intolerances(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "AllergyIntolerance"
    assert r["id"] == f"{ALLERGY_ID_PREFIX}pt1-a01"
    assert r["code"]["coding"][0]["code"] == "372687004"
    assert r["criticality"] == "high"
    assert r["onsetDateTime"] == "2020-03-15"


# --- Category fallback ---

def test_unknown_category_defaults_to_medication():
    a = _sample_allergy_dataclass()
    a.category = "unknown_xyz"
    ctx = _make_ctx([a])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["category"] == ["medication"]


def test_food_category():
    a = _sample_allergy_dataclass()
    a.category = "food"
    ctx = _make_ctx([a])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["category"] == ["food"]


# --- No onset date ---

def test_no_onset_date_omits_field():
    a = _sample_allergy_dataclass()
    a.onset_date = None
    ctx = _make_ctx([a])
    r = _bb_allergy_intolerances(ctx)[0]
    assert "onsetDateTime" not in r


# --- No reactions ---

def test_no_reactions_omits_reaction_field():
    a = _sample_allergy_dataclass()
    a.reactions = []
    ctx = _make_ctx([a])
    r = _bb_allergy_intolerances(ctx)[0]
    assert "reaction" not in r


# --- JP locale ---

def test_jp_locale_resolves_snomed_display_to_ja():
    """JP cohort: allergen_code 387207008 (Penicillin) resolved to ペニシリン via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "387207008"
    a.allergen_display = "Penicillin"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["code"]["coding"][0]["display"] == "ペニシリン"
    assert r["code"]["text"] == "ペニシリン"


def test_jp_locale_resolves_reaction_manifestation_to_ja():
    """JP cohort: manifestation_snomed 247472004 (Rash) resolved to 発疹 via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "387207008"
    a.allergen_display = "Penicillin"
    a.reactions = [
        AllergyReaction(
            manifestation_snomed="247472004",
            manifestation_display="Rash",
            severity="moderate",
        )
    ]
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    rxn = r["reaction"][0]
    manifestation = rxn["manifestation"][0]
    assert manifestation["coding"][0]["display"] == "発疹"
    assert manifestation["text"] == "発疹"


# --- Multiple allergies ---

def test_multiple_allergies_all_emitted():
    a1 = _sample_allergy_dataclass()
    a2 = _sample_allergy_dataclass()
    a2.allergy_id = "a02"
    a2.allergen_code = "70618"
    a2.allergen_display = "Penicillin"
    ctx = _make_ctx([a1, a2])
    resources = _bb_allergy_intolerances(ctx)
    assert len(resources) == 2
    ids = {r["id"] for r in resources}
    assert f"{ALLERGY_ID_PREFIX}pt1-a01" in ids
    assert f"{ALLERGY_ID_PREFIX}pt1-a02" in ids
