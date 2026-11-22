"""Issue #3562: JP prescription sig text reads as a prescription.

Frequency words match regardless of case (a stored ``weekly`` is as good as
``WEEKLY``), only the short upper-case abbreviations (PRN, PO, IV, ...) stay
case-sensitive; as-needed conditions, an auto-injector, an ODT and a central-line
infusion have whole Japanese phrases; and every dose / route / frequency string of
the encounter protocols localizes without English words.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.locale.free_text import localize_dose_text, localize_drug_name
from tests.unit.modules.document.narrative.test_jp_no_english_words_3034 import _english_words

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("freq", "ja"),
    [
        ("weekly", "週1回"),
        ("nightly", "就寝前"),
        ("monthly", "4週毎"),
        ("Weekly", "週1回"),
        ("TID PRN", "頓用（1日3回まで）"),
        ("BID PRN", "頓用（1日2回まで）"),
        ("PRN after each loose stool (max 4/day)", "下痢のたびに頓用（1日最大4回）"),
        ("PRN emergency (max 2/day)", "アナフィラキシー時 頓用（1日最大2回）"),
        ("PRN (max 2/day)", "頓用（1日最大2回）"),
        ("prn", "頓用"),
    ],
)
def test_frequency_reads_in_japanese(freq: str, ja: str) -> None:
    assert localize_dose_text(freq, "ja") == ja
    assert localize_dose_text(freq, "en") == freq


def test_a_lowercase_route_abbreviation_is_not_a_word_inside_a_drug_name() -> None:
    # "po" in "clopidogrel" must not become 経口; the short upper-case abbreviations stay case-sensitive.
    assert "経口" not in localize_dose_text("clopidogrel 75mg", "ja")
    assert "経口" in localize_dose_text("75mg PO", "ja")
    assert localize_dose_text("75mg po", "ja") == "75mg po"


@pytest.mark.parametrize(
    ("drug", "ja"),
    [
        ("Epinephrine auto-injector", "エピネフリン 自己注射薬"),
        ("Ondansetron 4mg ODT", "オンダンセトロン 4mg 口腔内崩壊錠"),
    ],
)
def test_drug_forms_read_in_japanese(drug: str, ja: str) -> None:
    assert localize_drug_name(drug, "ja") == ja


def test_a_central_line_infusion_reads_whole_without_a_repeated_strength() -> None:
    ja = localize_drug_name("Sodium Chloride 23.4% Injectable Solution 30mL IV over 15min via central line", "ja")
    assert ja == "塩化ナトリウム 23.4% 注射液 30mL 中心静脈ラインから15分かけて静注"
    # an order stored before the strength was removed from the dose text reads the same
    old = localize_drug_name(
        "Sodium Chloride 23.4% Injectable Solution 23.4% 30mL IV over 15min via central line", "ja"
    )
    assert old == ja


def test_the_bcg_dose_reads_in_japanese() -> None:
    ja = localize_dose_text("1 vial (81mg TICE / 27mg Connaught)", "ja")
    assert ja == "1バイアル（TICE株 81mg または Connaught株 27mg）"


def test_the_hypertonic_saline_protocol_dose_does_not_repeat_the_strength() -> None:
    text = (_REPO / "clinosim/modules/disease/reference_data/hemorrhagic_stroke.yaml").read_text(encoding="utf-8")
    assert '"23.4% 30mL IV' not in text


def _sig_strings() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"dose", "frequency"} and isinstance(value, str) and value.strip():
                    found.add((key, value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in sorted(glob.glob(str(_REPO / "clinosim/modules/encounter/reference_data/**/*.yaml"), recursive=True)):
        try:
            walk(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
    chemo = yaml.safe_load((_REPO / "clinosim/locale/shared/chemo_regimens.yaml").read_text(encoding="utf-8"))
    walk(chemo)
    return found


def test_sig_inventory_is_not_empty() -> None:
    assert len(_sig_strings()) > 25


def test_every_encounter_sig_string_reads_as_japanese() -> None:
    english = []
    for _key, text in sorted(_sig_strings()):
        ja = localize_dose_text(text, "ja")
        if _english_words(ja):
            english.append(f"{text!r} -> {ja}")
    assert not english, "English left in a JP sig:\n" + "\n".join(english)


def test_the_intravesical_route_reads_in_japanese() -> None:
    assert localize_dose_text("intravesical", "ja") == "膀胱内注入"
