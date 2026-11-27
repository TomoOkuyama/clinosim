"""An unnamed newborn / unparsed staff name never emits an empty ``given`` (Issue #3920)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient
from clinosim.modules.output.fhir_r4.demographics.practitioner import _build_practitioner

pytestmark = pytest.mark.unit


def _baby(family: str = "Vega", given: str = "", phonetic: object = None) -> dict:
    name: dict = {"family_name": family, "given_name": given}
    if phonetic is not None:
        name["phonetic"] = phonetic
    return {
        "patient_id": "POP-000396-BABY",
        "sex": "F",
        "date_of_birth": "2026-06-21",
        "name": name,
    }


def _no_empty_parts(name: dict) -> None:
    for key, value in name.items():
        if key == "given":
            assert value and all(isinstance(g, str) and g for g in value), name
        elif isinstance(value, str):
            assert value, (key, name)


def test_us_unnamed_newborn_omits_given_and_texts_baby_family() -> None:
    name = _build_patient(_baby(), "US")["name"]
    assert len(name) == 1
    assert "given" not in name[0]
    assert name[0]["family"] == "Vega"
    assert name[0]["text"] == "Baby Vega"
    _no_empty_parts(name[0])


def test_us_named_patient_unchanged() -> None:
    p = _baby(given="Anna")
    p["patient_id"] = "POP-000001"
    name = _build_patient(p, "US")["name"][0]
    assert name["given"] == ["Anna"]
    assert "text" not in name


def test_jp_unnamed_newborn_omits_given_in_kanji_and_kana() -> None:
    p = _baby(family="佐々木", phonetic={"family_name": "ササキ", "given_name": ""})
    names = _build_patient(p, "JP")["name"]
    assert len(names) == 2
    for n in names:
        assert "given" not in n
        _no_empty_parts(n)
    assert names[0]["text"] == "佐々木"


def test_jp_kana_given_falls_back_only_to_a_non_empty_value() -> None:
    p = _baby(family="佐々木", given="", phonetic="ササキ")
    for n in _build_patient(p, "JP")["name"]:
        assert "given" not in n


def test_practitioner_without_given_part_omits_given() -> None:
    roster = {"S1": {"name": "Cher", "role": "nurse", "sex": "F", "name_phonetic": "シェア"}}
    for country in ("US", "JP"):
        for n in _build_practitioner("S1", roster, country)["name"]:
            assert "given" not in n, (country, n)
