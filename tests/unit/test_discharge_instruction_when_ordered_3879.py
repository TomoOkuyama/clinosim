"""A discharge instruction that states a treatment was given is printed only
when the visit ordered that treatment (Issue #3879)."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_disposition
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    discharge_instructions_for_age,
    load_encounter_condition,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_ENC = "ENC-ED-1"


def _order(index: int, display_name: str) -> SimpleNamespace:
    """An ED treatment order as the simulator writes it: ``ORD-<enc>-ED-T<i>``,
    ``i`` the index of the protocol ``treatment`` entry."""
    return SimpleNamespace(
        order_id=f"ORD-{_ENC}-ED-T{index}",
        encounter_id=_ENC,
        order_type="procedure",
        display_name=display_name,
        ordered_datetime="2026-05-01T10:00:00",
    )


def _disposition(condition: str, lang: str, orders: list[SimpleNamespace]) -> str:
    spec = load_encounter_condition(condition)
    country = "us" if lang == "en" else "jp"
    ctx = NarrativeContext(
        patient={"patient_id": "P1", "age": 40, "sex": "M"},
        encounter={
            "encounter_id": _ENC,
            "encounter_type": "emergency",
            "chief_complaint": spec["chief_complaint"][lang],
            "severity": "moderate",
            "discharge_disposition": "home",
            "triage_data": {"level": "4", "level_system": "ESI"},
        },
        encounter_type="emergency",
        disease_protocol=None,
        encounter_protocol=spec,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale=country,
        orders=orders,
    )
    return build_ed_disposition(_GEN, ctx)[0]


@pytest.mark.parametrize(
    ("lang", "stated"),
    [("en", ("packing", "cauterization")), ("ja", ("タンポン", "焼灼"))],
)
def test_epistaxis_without_packing_or_cautery_states_neither(lang: str, stated: tuple[str, ...]) -> None:
    text = _disposition("epistaxis", lang, [_order(2, "Oxymetazoline nasal spray")])
    assert not any(w in text for w in stated), text
    assert "48" in text  # the unconditional advice stays


def test_epistaxis_with_packing_says_packing_only() -> None:
    en = _disposition("epistaxis", "en", [_order(0, "Nasal packing (anterior)")])
    assert "Bleeding controlled with nasal packing" in en
    assert "cauterization" not in en
    ja = _disposition("epistaxis", "ja", [_order(0, "Nasal packing (anterior)")])
    assert "タンポン" in ja and "焼灼" not in ja


def test_epistaxis_with_cautery_says_cautery_only() -> None:
    en = _disposition("epistaxis", "en", [_order(1, "Silver nitrate cauterization")])
    assert "Bleeding controlled with silver nitrate cauterization" in en
    assert "packing" not in en


def test_a_locale_renamed_order_still_counts_as_the_protocol_treatment() -> None:
    """Migraine JP orders acetaminophen for the 'Ketorolac 30mg' entry: the order id index names the treatment."""
    ja = _disposition("migraine", "ja", [_order(0, "Acetaminophen 1000mg")])
    assert "点滴治療で頭痛発作は頓挫" in ja
    assert "点滴治療で頭痛発作は頓挫" not in _disposition("migraine", "ja", [_order(5, "Dark room rest")])


def test_instruction_without_a_gate_is_unchanged() -> None:
    spec = load_encounter_condition("epistaxis")
    texts = [i["en"] for i in discharge_instructions_for_age(spec, None, ordered=set())]
    assert any(t.startswith("Keep head elevated") for t in texts)


def test_when_ordered_must_name_treatments_of_the_protocol() -> None:
    data = copy.deepcopy(load_encounter_condition("epistaxis"))
    data["discharge_instructions"][0]["when_ordered"] = ["Not a treatment"]
    with pytest.raises(ValidationError, match="when_ordered"):
        EncounterConditionProtocol.model_validate(data)


def test_when_ordered_cannot_be_empty() -> None:
    data = copy.deepcopy(load_encounter_condition("epistaxis"))
    data["discharge_instructions"][0]["when_ordered"] = []
    with pytest.raises(ValidationError):
        EncounterConditionProtocol.model_validate(data)
