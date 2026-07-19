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
        allergen_code="387458008",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 3, 15),
        reactions=[
            AllergyReaction(
                manifestation_snomed="271807003",
                severity="mild",
            ),
        ],
    )


def _sample_allergy_dict() -> dict:
    return {
        "allergy_id": "a01",
        "allergen_code": "387458008",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": date(2020, 3, 15),
        "reactions": [
            {
                "manifestation_snomed": "271807003",
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


def test_status_displays_resolve_via_codes_yaml():
    """Displays must come from codes/data/*.yaml + code_lookup, not hardcoded
    Python dicts (2026-07-02 grand design review, display-dict migration)."""
    from clinosim.codes import lookup

    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    clinical = r["clinicalStatus"]["coding"][0]
    verification = r["verificationStatus"]["coding"][0]
    assert clinical["display"] == lookup("hl7-allergyintolerance-clinical", "active", "en") == "Active"
    assert verification["display"] == lookup("hl7-allergyintolerance-verification", "confirmed", "en") == "Confirmed"


def test_category_medication():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["category"] == ["medication"]


def test_criticality_high():
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["criticality"] == "high"


def test_code_snomed_allergen():
    # allergen_code "387458008" = Aspirin in SNOMED. code_lookup resolves to "Aspirin".
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    coding = r["code"]["coding"][0]
    assert coding["code"] == "387458008"
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
    # Session 57 v3: the coding.display is looked up from the SNOMED yaml so it
    # reflects the canonical FSN ("Eruption of skin"); allergens.yaml's own
    # display_en ("Rash") is a friendly gloss that surfaces via text.
    assert manifestation["coding"][0]["display"] == "Eruption of skin"


# --- Dict path ---


def test_allergy_from_dict_path():
    """Production CIF is json.load() -> dict; verify _o() dict-access path."""
    ctx = _make_ctx([_sample_allergy_dict()])
    resources = _bb_allergy_intolerances(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "AllergyIntolerance"
    assert r["id"] == f"{ALLERGY_ID_PREFIX}pt1-a01"
    assert r["code"]["coding"][0]["code"] == "387458008"
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
    """JP cohort: allergen_code 373270004 (Penicillin) resolved to ペニシリン via code_lookup.
    Session 58 Issue #263: JP output prepends a JFAGY generic coding as
    code.coding[0] (satisfies JP Core AllergyIntolerance VS binding). The
    SNOMED coding with the ペニシリン display now sits at coding[1] but the
    `code.text` still carries the human-readable substance name."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "373270004"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    codings = r["code"]["coding"]
    # JFAGY primary (index 0)
    assert codings[0]["system"] == "http://jpfhir.jp/fhir/core/CodeSystem/YCM/JP_JfagyMedicationAllergen_CS"
    assert codings[0]["code"] == "00M"
    assert codings[0]["display"] == "医薬品"
    # SNOMED secondary (index 1) carries the locale-resolved substance display
    assert codings[1]["system"] == "http://snomed.info/sct"
    assert codings[1]["code"] == "373270004"
    assert codings[1]["display"] == "ペニシリン"
    assert r["code"]["text"] == "ペニシリン"


def test_jp_locale_resolves_reaction_manifestation_to_ja():
    """JP cohort: manifestation_snomed 247472004 (Rash) resolved to 発疹 via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "373270004"
    a.reactions = [
        AllergyReaction(
            manifestation_snomed="271807003",
            severity="moderate",
        )
    ]
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    rxn = r["reaction"][0]
    manifestation = rxn["manifestation"][0]
    assert manifestation["coding"][0]["display"] == "発疹"
    assert manifestation["text"] == "発疹"


# --- Session 58 Issue #263: JP Core AllergyIntolerance VS binding via JFAGY ---


def test_jp_medication_allergen_gets_jfagy_medication_cs_primary():
    """Medication category → JFAGY YCM medication allergen CS (00M / 医薬品)."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "373270004"
    a.category = "medication"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    primary = r["code"]["coding"][0]
    assert primary["system"] == "http://jpfhir.jp/fhir/core/CodeSystem/YCM/JP_JfagyMedicationAllergen_CS"
    assert primary["code"] == "00M"
    assert primary["display"] == "医薬品"


def test_jp_food_allergen_gets_jfagy_food_cs_primary():
    a = _sample_allergy_dataclass()
    a.allergen_code = "735038006"
    a.category = "food"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    primary = r["code"]["coding"][0]
    assert primary["system"] == "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyFoodAllergen_CS"
    assert primary["code"] == "00F"
    assert primary["display"] == "食品"


def test_jp_environment_allergen_gets_jfagy_non_food_non_medication_cs_primary():
    a = _sample_allergy_dataclass()
    a.allergen_code = "256262001"
    a.category = "environment"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    primary = r["code"]["coding"][0]
    assert primary["system"] == "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyNonFoodNonMedicationAllergen_CS"
    assert primary["code"] == "00N"
    assert primary["display"] == "非食品・非医薬品"


def test_us_output_keeps_snomed_primary_and_no_jfagy():
    """US output has no JP Core VS constraint. Continue emitting SNOMED alone."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "373270004"
    a.category = "medication"
    ctx = _make_ctx([a], country="US")
    r = _bb_allergy_intolerances(ctx)[0]
    codings = r["code"]["coding"]
    assert len(codings) == 1
    assert codings[0]["system"] == "http://snomed.info/sct"
    assert codings[0]["code"] == "373270004"


def test_jp_snomed_secondary_preserved_for_interop():
    """JP output keeps the SNOMED coding at index 1 so international
    consumers can still resolve the specific substance."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "115556009"  # Sulfonamide
    a.category = "medication"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    codings = r["code"]["coding"]
    assert len(codings) == 2
    assert codings[1]["system"] == "http://snomed.info/sct"
    assert codings[1]["code"] == "115556009"


# --- Multiple allergies ---


def test_multiple_allergies_all_emitted():
    a1 = _sample_allergy_dataclass()
    a2 = _sample_allergy_dataclass()
    a2.allergy_id = "a02"
    a2.allergen_code = "373270004"
    ctx = _make_ctx([a1, a2])
    resources = _bb_allergy_intolerances(ctx)
    assert len(resources) == 2
    ids = {r["id"] for r in resources}
    assert f"{ALLERGY_ID_PREFIX}pt1-a01" in ids
    assert f"{ALLERGY_ID_PREFIX}pt1-a02" in ids
