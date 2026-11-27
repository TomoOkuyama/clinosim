"""Four complication tokens are coded by the disease their protocol describes (Issue #3907).

A token the disease protocols share can mean different diseases (``wound_infection``
is a surgical wound after an appendectomy and a burn wound in an electrical injury),
and a diabetic stay's hypoglycemia has its own combination code. The table
``reference_data/complication_diagnosis_codes.yaml`` gives a per-protocol code
(``protocol_codes``) beside the token's default.
"""

from __future__ import annotations

import pytest

from clinosim.codes import code_exists, lookup
from clinosim.locale.loader import map_diagnosis_code
from clinosim.simulator.complication_dx import (
    complication_diagnoses,
    complication_diagnosis_code,
    diagnosis_category,
    validate_protocol_codes,
)
from clinosim.simulator.complications import build_complication

pytestmark = pytest.mark.unit


def _event(token: str, day: int = 2) -> dict:
    return build_complication(token, day, f"2026-06-{10 + day:02d}T12:00:00", "daily_loop")


# (token, protocol) -> (US ICD-10-CM leaf, JP WHO ICD-10 code of the MHLW table)
_PROTOCOL_CODES = {
    ("stress_cardiomyopathy", "sepsis"): ("I42.89", "I42.8"),
    ("wound_infection", "electrical_injury"): ("L08.9", "L08.9"),
    ("rhabdomyolysis_aki", "electrical_injury"): ("T79.6XXA", "T79.6"),
}


@pytest.mark.parametrize(("key", "codes"), sorted(_PROTOCOL_CODES.items()))
def test_protocol_code_replaces_the_token_default(key: tuple[str, str], codes: tuple[str, str]) -> None:
    token, protocol = key
    us, jp = codes
    assert complication_diagnosis_code(token, disease_id=protocol) == us
    assert map_diagnosis_code(us, "US") == us
    assert map_diagnosis_code(us, "JP") == jp
    assert code_exists("icd-10-cm", us, exact=True)
    assert code_exists("icd-10", jp, exact=True)
    assert lookup("icd-10-cm", us, "en")
    assert lookup("icd-10", jp, "ja")


def test_the_token_default_stays_for_other_protocols() -> None:
    assert complication_diagnosis_code("stress_cardiomyopathy") == "I51.81"
    assert complication_diagnosis_code("stress_cardiomyopathy", disease_id="acute_mi") == "I51.81"
    assert complication_diagnosis_code("rhabdomyolysis_aki") == "M62.82"
    assert complication_diagnosis_code("rhabdomyolysis", disease_id="diabetic_ketoacidosis") == "M62.82"
    for surgical in ("acute_appendicitis", "acute_cholecystitis"):
        assert complication_diagnosis_code("wound_infection", disease_id=surgical) == "T81.49XA"
    assert complication_diagnosis_code("wound_infection") == "T81.49XA"


def test_an_unknown_disease_id_falls_back_to_the_default() -> None:
    assert complication_diagnosis_code("wound_infection", disease_id="no_such_protocol") == "T81.49XA"


@pytest.mark.parametrize(
    ("stay_code", "expected_us", "expected_jp"),
    [
        ("E10.10", "E10.649", "E10.6"),
        ("E10.11", "E10.649", "E10.6"),
        ("E11.10", "E11.649", "E11.6"),
        ("E11.11", "E11.649", "E11.6"),
    ],
)
def test_dka_hypoglycemia_is_the_combination_code_of_the_stays_diabetes_type(
    stay_code: str, expected_us: str, expected_jp: str
) -> None:
    code = complication_diagnosis_code("hypoglycemia", disease_id="diabetic_ketoacidosis", stay_codes=[stay_code])
    assert code == expected_us
    assert map_diagnosis_code(code, "US") == code
    assert map_diagnosis_code(code, "JP") == expected_jp
    assert code_exists("icd-10-cm", code, exact=True)
    assert code_exists("icd-10", expected_jp, exact=True)
    assert lookup("icd-10-cm", code, "en")
    assert lookup("icd-10", expected_jp, "ja")


def test_dka_hypoglycemia_without_a_diabetes_code_on_the_stay_uses_the_default_type() -> None:
    """The index's default type of "Diabetes, with hypoglycemia" is E11.649."""
    code = complication_diagnosis_code("hypoglycemia", disease_id="diabetic_ketoacidosis", stay_codes=["I10"])
    assert code == "E11.649"


def test_hypoglycemia_outside_the_dka_protocol_is_still_unspecified_hypoglycemia() -> None:
    assert complication_diagnosis_code("hypoglycemia") == "E16.2"


def test_the_stay_type_is_read_from_the_stays_diabetes_code_not_drawn() -> None:
    a = complication_diagnosis_code("hypoglycemia", disease_id="diabetic_ketoacidosis", stay_codes=["E10.10"])
    b = complication_diagnosis_code("hypoglycemia", disease_id="diabetic_ketoacidosis", stay_codes=["E10.10"])
    assert a == b == "E10.649"


def test_a_diabetic_stays_hypoglycemia_combination_code_is_not_dropped_by_the_category_rule() -> None:
    """E11.649 shares the 3-character category E11 with the principal E11.10 and the
    chronic E11.9; it is its own diagnosis and is added once."""
    entries, carried = complication_diagnoses(
        [_event("hypoglycemia")], ["E11.10"], ["E11.9"], disease_id="diabetic_ketoacidosis"
    )
    assert [e["disease_id"] for e in entries] == ["E11.649"]
    assert carried == []
    entries, _ = complication_diagnoses([_event("hypoglycemia")], ["E10.11"], [], disease_id="diabetic_ketoacidosis")
    assert [e["disease_id"] for e in entries] == ["E10.649"]


def test_a_stay_that_already_carries_the_combination_code_gets_no_duplicate() -> None:
    entries, carried = complication_diagnoses(
        [_event("hypoglycemia")], ["E11.10", "E11.649"], [], disease_id="diabetic_ketoacidosis"
    )
    assert entries == []
    assert carried == [{"name": "hypoglycemia", "carrying_code": "E11.649", "carrier": "stay"}]


def test_a_repeat_hypoglycemia_adds_one_entry() -> None:
    entries, _ = complication_diagnoses(
        [_event("hypoglycemia", 2), _event("hypoglycemia", 4)], ["E11.10"], [], disease_id="diabetic_ketoacidosis"
    )
    assert [e["disease_id"] for e in entries] == ["E11.649"]


def test_the_electrical_injury_muscle_and_compartment_diagnoses_both_show() -> None:
    """T79.6XXA (traumatic rhabdomyolysis) and T79.A0XA (compartment syndrome) are
    different diagnoses of the category T79."""
    entries, _ = complication_diagnoses(
        [_event("rhabdomyolysis_aki", 1), _event("compartment_syndrome", 2)], ["T75.4XXA"], [], "electrical_injury"
    )
    assert [e["disease_id"] for e in entries] == ["T79.6XXA", "T79.A0XA"]


def test_sepsis_cardiomyopathy_is_not_takotsubo() -> None:
    entries, _ = complication_diagnoses([_event("stress_cardiomyopathy")], ["A41.9"], [], disease_id="sepsis")
    assert [e["disease_id"] for e in entries] == ["I42.89"]


def test_diagnosis_category_is_the_first_onset_key() -> None:
    assert diagnosis_category("E11.649") == "E11.649"
    assert diagnosis_category("T79.6XXA") == "T79.6XXA"
    assert diagnosis_category("J98.11") == "J98"


# --- the load-time guard -------------------------------------------------------


def test_a_protocol_override_must_name_a_protocol_that_declares_the_token() -> None:
    declared = {"sepsis": {"stress_cardiomyopathy"}}
    validate_protocol_codes({"sepsis": {"stress_cardiomyopathy": "I42.89"}}, declared)
    with pytest.raises(ValueError, match="not_a_protocol"):
        validate_protocol_codes({"not_a_protocol": {"stress_cardiomyopathy": "I42.89"}}, declared)
    with pytest.raises(ValueError, match="wound_infection"):
        validate_protocol_codes({"sepsis": {"wound_infection": "L08.9"}}, declared)


def test_the_shipped_table_passes_the_guard() -> None:
    from clinosim.simulator.complication_dx import _table

    assert _table().protocol_codes  # loading validated every override


def test_the_sepsis_cardiomyopathy_label_names_septic_cardiomyopathy_not_takotsubo() -> None:
    """The token is declared by the sepsis protocol only, so its narrative label follows the code."""
    from clinosim.modules.document.narrative._localization import _localize_complication

    assert _localize_complication("stress_cardiomyopathy", "en") == "septic cardiomyopathy"
    assert _localize_complication("stress_cardiomyopathy", "ja") == "敗血症性心筋症"
