"""Issue #3428: JP drug dose instructions read as Japanese prescription phrases.

A dose string of a disease protocol with an annotation, condition or schedule has
a phrase of its own in the ``dose_phrases`` table, looked up whole before any word
substitution, so a JP record never carries "with food", "PRN agitation" or a raw
protocol slug.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.locale.free_text import localize_dose_text, localize_drug_name
from tests.unit.modules.document.narrative.test_jp_no_english_words_3034 import _english_words

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_LEFTOVER = re.compile(r"\bq\d|\bstat\b|_|\bx\s*\d")


def _dose_strings() -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "dose" and isinstance(value, str) and value.strip():
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in sorted(glob.glob(str(_REPO / "clinosim/modules/*/reference_data/**/*.yaml"), recursive=True)):
        try:
            walk(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
    return found


def test_inventory_is_not_empty() -> None:
    assert len(_dose_strings()) > 300


def test_every_disease_dose_reads_as_japanese() -> None:
    english = []
    for dose in sorted(_dose_strings()):
        ja = localize_dose_text(dose, "ja")
        if _english_words(ja) or _LEFTOVER.search(ja):
            english.append(f"{dose!r} -> {ja}")
    assert not english, "English left in the JP dose:\n" + "\n".join(english)


def test_every_disease_dose_reads_as_japanese_after_a_drug_name() -> None:
    english = []
    for dose in sorted(_dose_strings()):
        ja = localize_drug_name(f"Heparin {dose}", "ja")
        if _english_words(ja) or _LEFTOVER.search(ja):
            english.append(f"{dose!r} -> {ja}")
    assert not english, "English left in the JP order:\n" + "\n".join(english)


@pytest.mark.parametrize(
    ("dose", "ja"),
    [
        ("20mg PO daily with food", "20mg 経口 1日1回 食後"),
        ("5mg IM PRN agitation", "5mg 筋注 不穏時 頓用"),
        ("30mL PO TID (titrate to 2-3 soft stools/day)", "30mL 経口 1日3回 (軟便 2-3 回/日を目安に調節)"),
        ("500mg PO day1, then 250mg PO days 2-5", "1日目 500mg 経口、2-5日目 250mg 経口"),
        ("6-8g per liter removed", "排液 1 L あたり 6-8g"),
        ("increase_rate_by_20%", "注入速度を20%増量"),
    ],
)
def test_doses_are_prescription_japanese(dose: str, ja: str) -> None:
    assert localize_dose_text(dose, "ja") == ja


def test_a_dose_after_a_drug_name_keeps_the_drug_and_reads_the_dose_whole() -> None:
    assert localize_drug_name("Haloperidol 5mg IM PRN agitation", "ja").endswith("5mg 筋注 不穏時 頓用")
    assert localize_drug_name("Haloperidol 5mg IM PRN agitation", "ja").startswith("ハロペリドール")


def test_us_output_is_unchanged() -> None:
    assert localize_dose_text("20mg PO daily with food", "en") == "20mg PO daily with food"
    assert localize_drug_name("Haloperidol 5mg IM PRN agitation", "en") == "Haloperidol 5mg IM PRN agitation"
    assert localize_dose_text("increase_rate_by_20%", "en") == "increase rate by 20%"


def test_an_unlisted_dose_falls_back_to_term_substitution() -> None:
    assert localize_dose_text("500mg PO BID", "ja") == "500mg 経口 1日2回"


def test_a_duration_multiplier_is_written_in_japanese() -> None:
    # Issue #3473: "x 1h" / "x 7 days" must not survive in a JP dose.
    assert (
        localize_dose_text("1000mL/h x 1h, then 500mL/h x 4h, then 250mL/h", "ja")
        == "1000 mL/h で1時間、その後 500 mL/h で4時間、その後 250 mL/h"
    )
    assert localize_dose_text("1g IV daily x 7 days", "ja") == "1g 静注 1日1回 7日間"


def test_jp_golden_narratives_carry_no_multiplier() -> None:
    # Issue #3473: rendered JP narrative of every golden profile has no "x7日分" / "x 1h".
    bad = re.compile(r"\bx\s*\d+\s*(日分|h\b|日間)|mL/h x ")
    hits = []
    for path in sorted((_REPO / "tests/fixtures/patient_profiles").glob("jp_*.golden.json")):
        hits += [f"{path.name}: {m.group(0)}" for m in bad.finditer(path.read_text(encoding="utf-8"))]
    assert not hits, "\n".join(hits)
