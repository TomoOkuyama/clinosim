"""SNOMED CT and LOINC codes that meant another concept or did not exist are
replaced by verified codes of the intended concept, or omitted (Issue #3157).

Replacement codes: tx.fhir.org ``$lookup`` (SNOMED CT International Edition
2025-02-01, LOINC 2.83), recorded in ``clinosim/codes/authoritative/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from clinosim.codes import display
from clinosim.codes.loader import _load_system
from clinosim.locale.loader import department_specialty_snomed, load_code_mapping
from clinosim.modules.output.fhir_r4.labs.observations import lab_observation_coding
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_AUTH = _ROOT / "clinosim" / "codes" / "authoritative"

# The wrong or non-existent codes this issue removes.
_REMOVED_SNOMED = {
    "158965000",  # Medical practitioner, used for "Assistant surgeon"
    "158967008",  # Consultant physician, used for "Anaesthetist"
    "158972004",  # House officer, used for "Circulating nurse"
    "224549009",  # unknown to the International Edition ("Scrub nurse")
    "722414000",  # Vascular medicine, used for "Laboratory medicine"
    "405623001",  # Assigned practitioner, used for "Pharmacy"
    "394583003",  # unknown to the International Edition ("Endocrinology")
    "424535000",  # unknown (CareTeam category, emitted as text only)
    "735320007",  # unknown (CareTeam category, emitted as text only)
    "407484005",  # unknown (CareTeam category, emitted as text only)
}
_REMOVED_LOINC = {
    "93372-1",  # FDA product label Indexing - national clinical trial number, used for C-SSRS
    "27069-5",  # not in LOINC 2.83 (tacrolimus)
    "44805-4",  # not in LOINC 2.83 (PIVKA-II)
    "42346-6",  # not in LOINC 2.83
    "45391-8",  # not in LOINC 2.83
}


def _snapshot(name: str) -> dict:
    return json.loads((_AUTH / name).read_text(encoding="utf-8"))


def test_removed_codes_are_gone_from_the_code_tables() -> None:
    assert not _REMOVED_SNOMED & {str(c) for c in _load_system("snomed-ct").codes}
    assert not _REMOVED_LOINC & {str(c) for c in _load_system("loinc").codes}


def test_display_guard_exception_list_no_longer_names_them() -> None:
    allow = yaml.safe_load((_ROOT / "tests/unit/codes/authoritative_override_allowlist.yaml").read_text()) or {}
    assert not _REMOVED_SNOMED & set(allow.get("snomed-ct") or {})
    assert not _REMOVED_LOINC & set(allow.get("loinc") or {})


@pytest.mark.parametrize(
    ("snapshot", "system", "known_missing"),
    [
        # 303408005: legacy allergen entry kept for old CIF (allergens: Issue #3128).
        ("snomed_ct_tx.json", "snomed-ct", ["303408005"]),
        ("loinc_2_83_tx.json", "loinc", []),
    ],
)
def test_every_registered_code_is_in_the_authoritative_snapshot(
    snapshot: str, system: str, known_missing: list[str]
) -> None:
    snap = _snapshot(snapshot)
    in_snapshot = {c["code"] for c in snap["concept"]}
    registered = {str(c) for c in _load_system(system).codes}
    assert sorted(registered - in_snapshot) == known_missing
    assert snap["metadata"]["clinosim_codes_missing_from_source"] == known_missing
    assert snap["metadata"]["clinosim_codes_total"] == len(registered)
    assert in_snapshot <= registered


@pytest.mark.parametrize(
    ("dept", "code", "en"),
    [
        ("endocrinology", "394583002", "Endocrinology"),
        ("laboratory", "1255736009", "Clinical pathology"),
        ("pharmacy", "1258957008", "Hospital pharmacy specialization"),
    ],
)
def test_department_specialty_codes(dept: str, code: str, en: str) -> None:
    assert department_specialty_snomed(dept) == code
    assert display("snomed-ct", code, "en") == en


@pytest.mark.parametrize(
    ("code", "en", "ja"),
    [
        ("88189002", "Anesthesiologist", "麻酔科医"),
        ("415506007", "Scrub nurse", "器械出し看護師"),
        ("413854007", "Circulating nurse", "外回り看護師"),
    ],
)
def test_staff_role_codes(code: str, en: str, ja: str) -> None:
    assert display("snomed-ct", code, "en") == en
    assert display("snomed-ct", code, "ja") == ja


def test_anesthesiologist_performer_function() -> None:
    proc = {
        "procedure_id": "PROC-1",
        "procedure_code": "80146002",
        "procedure_name": "Appendectomy",
        "start_datetime": "2026-01-01T09:00:00",
        "end_datetime": "2026-01-01T10:00:00",
        "primary_surgeon_id": "DR-SU-001",
        "anesthesiologist_id": "DR-AN-001",
        "encounter_id": "ENC-1",
    }
    performers = _build_procedure(proc, "PAT-001", 0, "US")["performer"]
    anes = [p for p in performers if p["actor"]["reference"] == "Practitioner/DR-AN-001"][0]
    assert anes["function"]["coding"][0]["code"] == "88189002"
    assert anes["function"]["coding"][0]["display"] == "Anesthesiologist"


@pytest.mark.parametrize(
    ("analyte", "code", "en"),
    [
        ("Tacrolimus", "77348-1", "Tacrolimus [Mass/volume] in Blood --trough"),
        ("PIVKA_II", "93768-0", "Acarboxyprothrombin [Units/volume] in Serum or Plasma"),
        ("C-SSRS", "93293-9", "Most severe suicidal ideation 1 month"),
    ],
)
def test_lab_codes(analyte: str, code: str, en: str) -> None:
    assert load_code_mapping("lab", "US")[analyte] == code
    assert display("loinc", code, "en") == en


@pytest.mark.parametrize("country", ["US", "JP"])
def test_cssrs_observation_code(country: str) -> None:
    """The C-SSRS ideation-severity score is coded as the most severe
    suicidal ideation item (the 0-5 score is none plus its five answers)."""
    codings, _text = lab_observation_coding("C-SSRS", {}, {}, country)
    loinc = [c for c in codings if c.get("system") == "http://loinc.org"]
    assert loinc == [
        {"system": "http://loinc.org", "code": "93293-9", "display": "Most severe suicidal ideation 1 month"}
    ]
