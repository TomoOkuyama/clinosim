"""JP medication notes, routes and dose text are Japanese (Issue #3033)."""

from __future__ import annotations

import re

import pytest

from clinosim.locale.free_text import _localize_dosage_terms
from clinosim.modules.output.fhir_r4.lib.dosage import build_dosage_instruction, build_route_concept

pytestmark = pytest.mark.unit

_ENGLISH = re.compile(r"\b(?!mg\b|kg\b|mL\b|BCG\b|INR\b|CrCl\b|TICE\b|Connaught\b)[A-Za-z]{3,}\b")


def test_a_jp_intravesical_bcg_order_has_japanese_route_and_dose_text() -> None:
    assert build_route_concept("intravesical", "JP")["text"] == "膀胱内注入"
    text = _localize_dosage_terms("1 vial (81mg TICE / 27mg Connaught)", "ja")
    assert "バイアル" in text and not _ENGLISH.search(text), text


@pytest.mark.parametrize(
    ("dose", "expected"),
    [
        ("400mg/m2 bolus + 2400mg/m2/46h", "46時間"),
        ("150mg/m2 PO daily x 5 days", "5日間"),
        ("60mg PO daily (30mg if CrCl 15-50 or weight <= 60kg)", "体重"),
        ("Titrate to INR 2.0-3.0 (1.6-2.6 if age >= 70)", "70歳以上"),
    ],
)
def test_regimen_dose_text_reads_in_japanese(dose: str, expected: str) -> None:
    text = _localize_dosage_terms(dose, "ja")
    assert expected in text and not _ENGLISH.search(text), text
    assert _localize_dosage_terms(dose, "en") == dose


@pytest.mark.parametrize(("freq", "ja"), [("WEEKLY", "週1回"), ("MONTHLY", "4週毎"), ("NIGHTLY", "就寝前")])
def test_a_jp_dose_frequency_is_japanese(freq: str, ja: str) -> None:
    order = {"display_name": "X", "dose_quantity": 35.0, "dose_unit": "mg", "route": "PO", "frequency": freq}
    assert ja in build_dosage_instruction(order, "JP")["text"]
    assert ja in _localize_dosage_terms(f"35.0mg {freq}", "ja")


def test_topical_reads_in_japanese_on_an_administration() -> None:
    assert "外用" in _localize_dosage_terms("topical", "ja")


@pytest.mark.parametrize(("status", "ja"), [("active", "有効"), ("stopped", "中止"), ("cancelled", "取消")])
def test_the_jp_effective_status_note_is_japanese(status: str, ja: str) -> None:
    from clinosim.modules.output.fhir_r4.post_process.populate import _effective_status_note

    note = _effective_status_note(status)
    assert ja in note and not re.search(r"[A-Za-z]{4,}", note.replace("JP-CLINS", "")), note


def test_a_jp_chemotherapy_order_dose_text_is_japanese() -> None:
    order = {
        "display_name": "Fluorouracil",
        "dose_quantity": 400.0,
        "dose_unit": "mg/m2",
        "route": "IV",
        "frequency": "once",
        "dose_text_ja": "400mg/m2 bolus + 2400mg/m2/46h",
        "dose_text_en": "400mg/m2 bolus + 2400mg/m2/46h",
    }
    assert build_dosage_instruction(order, "JP")["text"] == "400mg/m² 急速静注後 2400mg/m² 46時間持続静注"
    assert build_dosage_instruction(order, "US")["text"] == "400mg/m2 bolus + 2400mg/m2/46h"
