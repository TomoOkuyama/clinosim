"""Internal slugs are shown by their display names (Issue #3025)."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.locale.free_text import localize_drug_name, localize_procedure_name
from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.output.fhir_r4.labs.service_request import _pick_reason_text
from clinosim.modules.output.fhir_r4.lib.localization import display_slugs_in_text

pytestmark = pytest.mark.unit

_SLUG = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+")


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Toilet use 10"), ("ja", "トイレ動作10")],
)
def test_the_adl_line_names_the_items_in_the_output_language(lang: str, expected: str) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.nursing import build_adl_assessment

    adl = SimpleNamespace(barthel_score=55, feeding=5, bathing=0, mobility=10, toilet_use=10)
    text, _ = build_adl_assessment(
        TemplateNarrativeGenerator(), SimpleNamespace(target_lang=lang, adl_assessments=[adl])
    )
    assert expected in text
    assert not _SLUG.search(text)


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize(
    "intent",
    [
        "Day 33 monitoring: PT_INR",
        "Screening: T_Bil",
        "Day 3 dip_then_recovery: additional workup",
        "ED imaging: Chest_Xray_PA_Lateral",
        "Admission workup: Blood_culture_set_1",
        "Day 2 monitoring: Anion_gap",
    ],
)
def test_an_order_reason_shows_no_slug(intent: str, lang: str) -> None:
    order = {"clinical_intent": intent, "clinical_intent_ja": ""}
    assert not _SLUG.search(_pick_reason_text(order, lang))


def test_slug_display_uses_the_tables() -> None:
    assert display_slugs_in_text("Day 3 dip_then_recovery: additional workup", "en") == (
        "Day 3 transient worsening then recovery: additional workup"
    )
    assert display_slugs_in_text("検診: T_Bil", "ja") == "検診: 総ビリルビン"
    assert display_slugs_in_text("0.5 mg/kg/h, no slug", "en") == "0.5 mg/kg/h, no slug"


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize(
    "name",
    [
        "urinary_catheter: Foley catheter",
        "compression_stocking: Graduated compression stockings",
        "cervical_immobilization: Collar",
        "wound_care: dressing",
        "Intubation_and_mechanical_ventilation (TV 6mL/kg, PEEP 5)",
    ],
)
def test_a_bedside_procedure_order_names_the_procedure(name: str, lang: str) -> None:
    assert not _SLUG.search(localize_procedure_name(name, lang))


@pytest.mark.parametrize(("lang", "note"), [("en", "increase rate by 20%"), ("ja", "注入速度を20%増量")])
def test_the_heparin_rate_notation_reads_as_an_instruction(lang: str, note: str) -> None:
    text = localize_drug_name("Unfractionated_Heparin increase_rate_by_20%", lang)
    assert text.endswith(note) and not _SLUG.search(text)


def test_the_interaction_note_author_is_named() -> None:
    assert t("order_intent.interaction_check_author", "en") == "Prescription safety check"
    assert t("order_intent.interaction_check_author", "ja") == "処方チェックシステム"
