"""A drug skipped for the patient's allergy is worded as an allergy (Issue #2930).

The safety-skip line used one "avoid" phrase for every dropped drug, so a
penicillin-allergy skip read "avoided due to concurrent Penicillin allergy" /
「…との併用禁忌のため回避」 (併用禁忌 = a contraindication between two drugs).
The narrative now keys the phrase on the kind of rule that dropped the drug.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules import drug_safety
from clinosim.modules.document.narrative._safety_skips import safety_skip_line
from clinosim.modules.document.narrative.context import _build_safety_skips
from clinosim.simulator.medication_pipeline import allergy_blocked
from clinosim.types.allergy import Allergy
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 3, 1, 10, 0)
_PENICILLIN = "764146007"
_ENC = SimpleNamespace(id="ENC-1")


def _skip(kind: str | None, *, substituted: bool) -> dict:
    conflict = {
        "allergy": ("Penicillin allergy", "ペニシリンアレルギー"),
        "interaction": ("Warfarin", "ワルファリン"),
        "disease": ("Heart failure", "心不全"),
    }[kind or "interaction"]
    return {
        "considered": "Amoxicillin",
        "considered_ja": "アモキシシリン",
        "avoided_due_to": conflict[0],
        "avoided_due_to_ja": conflict[1],
        "substituted_with": "Azithromycin" if substituted else None,
        "substituted_with_ja": "アジスロマイシン" if substituted else None,
        "event_type": "avoid",
        "conflict_kind": kind,
    }


def test_rule_kind_classifies_each_rule_file() -> None:
    assert drug_safety.rule_kind("penicillin-allergy-penicillins") == "allergy"
    assert drug_safety.rule_kind("nsaid-in-heart-failure") == "disease"
    assert drug_safety.rule_kind("vka-plus-antiplatelet") == "interaction"
    assert drug_safety.rule_kind("medication-hold:aki") is None
    assert drug_safety.rule_kind(None) is None


@pytest.mark.parametrize(
    ("lang", "substituted", "expected"),
    [
        ("en", False, "- Amoxicillin not given: Penicillin allergy; no alternative selected."),
        ("en", True, "- Amoxicillin not given: Penicillin allergy; Azithromycin prescribed instead."),
        ("ja", False, "・ペニシリンアレルギーのためアモキシシリンは投与せず。"),
        ("ja", True, "・ペニシリンアレルギーのためアモキシシリンは投与せず、アジスロマイシンを処方。"),
    ],
)
def test_allergy_skip_template_line(lang: str, substituted: bool, expected: str) -> None:
    assert safety_skip_line(_skip("allergy", substituted=substituted), lang, prefix="safety_skips") == expected


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("substituted", [False, True])
def test_allergy_skip_has_no_interaction_wording(lang: str, substituted: bool) -> None:
    for prefix in ("safety_skips", "safety_skips_prompt"):
        line = safety_skip_line(_skip("allergy", substituted=substituted), lang, prefix=prefix)
        assert "併用" not in line and "concurrent" not in line, line
        assert ("Penicillin allergy" if lang == "en" else "ペニシリンアレルギー") in line


@pytest.mark.parametrize(
    ("kind", "lang", "expected"),
    [
        ("interaction", "en", "- Amoxicillin avoided due to concurrent Warfarin; no alternative selected."),
        ("interaction", "ja", "・アモキシシリン は ワルファリン との併用禁忌のため処方せず。"),
        ("disease", "en", "- Amoxicillin avoided due to concurrent Heart failure; no alternative selected."),
        ("disease", "ja", "・アモキシシリン は 心不全 との併用禁忌のため処方せず。"),
        (None, "en", "- Amoxicillin avoided due to concurrent Warfarin; no alternative selected."),
    ],
)
def test_interaction_and_disease_skips_keep_their_wording(kind: str | None, lang: str, expected: str) -> None:
    assert safety_skip_line(_skip(kind, substituted=False), lang, prefix="safety_skips") == expected


def test_logged_allergy_skip_reaches_the_narrative_as_an_allergy() -> None:
    patient = PatientProfile(patient_id="PT-1", age=40, sex="F")
    patient.allergies = [Allergy(allergy_id="1", allergen_code=_PENICILLIN, category="medication")]
    assert allergy_blocked(patient, "Amoxicillin", encounter_id="ENC-1", timestamp=_WHEN)
    [skip] = _build_safety_skips(patient, _ENC)
    assert skip["conflict_kind"] == "allergy"
    en = safety_skip_line(skip, "en", prefix="safety_skips")
    ja = safety_skip_line(skip, "ja", prefix="safety_skips")
    assert en.startswith("- Amoxicillin not given: ") and "allergy" in en
    assert "アレルギーのため" in ja and "投与せず" in ja and "併用禁忌" not in ja


def test_cif_hydrated_skip_reads_the_kind_from_the_verdict_dict() -> None:
    patient = {
        "safety_skip_log": [
            {
                "encounter_id": "ENC-1",
                "candidate_drug": "Amoxicillin",
                "active_conflict": "Penicillin allergy",
                "verdict": {"rule_id": "penicillin-allergy-penicillins", "severity": "contraindicated"},
            }
        ]
    }
    assert _build_safety_skips(patient, {"encounter_id": "ENC-1"})[0]["conflict_kind"] == "allergy"
