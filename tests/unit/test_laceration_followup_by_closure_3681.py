"""A laceration's follow-up depends on the closure placed (Issue #3681).

Suture or staple removal is advised only when sutures or staples were placed,
tissue adhesive needs no removal, and a wound with no closure gets wound-check
advice; the face has its own removal interval. The chief complaint does not
state a suture that may not have been placed.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_disposition
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    load_encounter_condition,
    visit_follow_up,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_SPEC = load_encounter_condition("minor_laceration")
_GEN = TemplateNarrativeGenerator()
_VARIANTS = _SPEC["diagnosis_variants"]
_SCALP = _VARIANTS[0]
_FACE = _VARIANTS[1]
_HAND = _VARIANTS[5]


def _orders(*names: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            encounter_id="ENC-ED-1",
            order_type="procedure",
            display_name=n,
            ordered_datetime="2026-05-01T10:00:00",
        )
        for n in names
    ]


def _ctx(lang: str, variant: dict, *closures: str) -> NarrativeContext:
    country = "us" if lang == "en" else "jp"
    return NarrativeContext(
        patient={"patient_id": "P1", "age": 30, "sex": "M"},
        encounter={
            "encounter_id": "ENC-ED-1",
            "encounter_type": "emergency",
            "chief_complaint": _SPEC["chief_complaint"][lang],
            "severity": "moderate",
            "discharge_disposition": "home",
            "triage_data": {"level": "4", "level_system": "ESI"},
        },
        encounter_type="emergency",
        disease_protocol=None,
        encounter_protocol=_SPEC,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[
            {
                "admission_diagnosis_code": variant["codes"][country[:2] if country == "us" else "jp"],
                "admission_diagnosis_system": "icd-10-cm" if lang == "en" else "icd-10-mhlw",
            }
        ],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale=country,
        orders=_orders(*closures),
    )


def _follow_up(lang: str, variant: dict, *closures: str) -> str:
    text, _ = build_ed_disposition(_GEN, _ctx(lang, variant, *closures))
    return text.rsplit("Follow-up:" if lang == "en" else "フォローアップ:", 1)[1]


@pytest.mark.parametrize(
    "closures",
    [(), ("Wound irrigation with normal saline",), ("Tissue adhesive (glue)",)],
)
def test_no_suture_or_staple_means_no_removal_advice(closures: tuple[str, ...]) -> None:
    for lang, words in (("en", ("suture", "staple")), ("ja", ("抜糸", "抜鉤"))):
        text = _follow_up(lang, _SCALP, *closures)
        assert not any(w in text for w in words), text


def test_adhesive_visit_says_no_removal_is_needed() -> None:
    assert "no removal" in _follow_up("en", _SCALP, "Tissue adhesive (glue)")
    assert "除去は不要" in _follow_up("ja", _SCALP, "Tissue adhesive (glue)")


@pytest.mark.parametrize("closure", ["Suture closure", "Skin staples"])
def test_sutured_or_stapled_visit_prints_removal(closure: str) -> None:
    assert "removal in 7-10 days" in _follow_up("en", _HAND, closure)
    assert "7〜10日後に抜糸・抜鉤" in _follow_up("ja", _HAND, closure)


def test_face_has_its_own_interval_and_only_for_a_face_wound() -> None:
    assert "removal in 5 days" in _follow_up("en", _FACE, "Suture closure")
    assert "5日後に抜糸・抜鉤" in _follow_up("ja", _FACE, "Suture closure")
    assert "5 days" not in _follow_up("en", _HAND, "Suture closure")
    assert "face" not in _follow_up("en", _FACE, "Suture closure")


def test_no_closure_fallback_is_a_wound_check() -> None:
    assert "wound check" in _follow_up("en", _HAND)
    assert "創部の確認" in _follow_up("ja", _HAND)


def test_chief_complaint_does_not_claim_sutures() -> None:
    assert _SPEC["chief_complaint"] == {"en": "Laceration", "ja": "裂傷"}


def test_visit_follow_up_resolution_is_first_match() -> None:
    assert visit_follow_up(_SPEC, {"Suture closure"}, "face")["en"].endswith("5 days")
    assert visit_follow_up(_SPEC, {"Suture closure"}, None)["en"].endswith("7-10 days")
    assert visit_follow_up(_SPEC, set(), "hand") == _SPEC["follow_up"]
    assert visit_follow_up({"follow_up": {"en": "x", "ja": "y"}}, {"Suture closure"}, None) == {"en": "x", "ja": "y"}


def test_validator_rejects_a_closure_the_protocol_never_orders() -> None:
    data = copy.deepcopy(_SPEC)
    data["follow_up_by_closure"][0]["treatments"] = ["Staple gun"]
    with pytest.raises(ValidationError, match="Staple gun"):
        EncounterConditionProtocol.model_validate(data)


def test_validator_rejects_an_unknown_site_and_a_missing_language() -> None:
    data = copy.deepcopy(_SPEC)
    data["follow_up_by_closure"][0]["sites"] = ["moon"]
    with pytest.raises(ValidationError, match="moon"):
        EncounterConditionProtocol.model_validate(data)
    data = copy.deepcopy(_SPEC)
    del data["follow_up_by_closure"][0]["ja"]
    with pytest.raises(ValidationError):
        EncounterConditionProtocol.model_validate(data)
