"""A JP newborn's kana is the reading of its own name (Issue #3017).

The newborn inherited the mother's whole phonetic, so a baby 佐藤 絹子 was
read サトウ ヨシコ (the mother 佐藤 芳子). The family reading is the
mother's; the given reading comes from the name-pool entry sampled for the
newborn.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from clinosim.modules.population.engine import _load_name_data
from clinosim.simulator.perinatal import _build_newborn_patient
from clinosim.types.patient import PatientProfile, PersonName

pytestmark = pytest.mark.unit

_BORN = date(2025, 4, 1)


def _mother(n: int) -> PatientProfile:
    return PatientProfile(
        patient_id=f"POP-{n:06d}",
        name=PersonName(family_name="佐藤", given_name="芳子", phonetic="サトウ ヨシコ"),
        sex="F",
        age=30,
        date_of_birth=date(1995, 1, 1),
    )


def _kana_of_given() -> dict[tuple[str, str], set[str]]:
    data = _load_name_data("JP")
    out: dict[tuple[str, str], set[str]] = {}
    for sex, key in (("M", "given_names_male"), ("F", "given_names_female")):
        for entry in data.get(key) or []:
            out.setdefault((sex, entry["kanji"]), set()).add(entry["kana"])
    return out


@pytest.mark.parametrize("sex", ["M", "F"])
def test_a_newborns_kana_given_name_matches_its_kanji_given_name(sex: str) -> None:
    readings = _kana_of_given()
    for n in range(40):
        baby = _build_newborn_patient(_mother(n), _BORN, sex, snapshot_date=_BORN + timedelta(days=60), country="JP")
        assert baby.name is not None and baby.name.given_name
        family, given = (baby.name.phonetic or "").split(" ")
        assert family == "サトウ"
        assert given in readings[(sex, baby.name.given_name)], (baby.name.given_name, given)


def test_an_unnamed_newborn_carries_only_the_family_reading() -> None:
    baby = _build_newborn_patient(_mother(1), _BORN, "F", snapshot_date=_BORN + timedelta(days=3), country="JP")
    assert baby.name is not None and baby.name.given_name == ""
    assert baby.name.phonetic == "サトウ"


def test_the_kanji_given_name_is_unchanged_by_the_reading() -> None:
    # The reading comes from the same pool entry as the kanji, so the
    # sampled given name stays what it was.
    from clinosim.simulator.perinatal import _sample_newborn_given

    baby = _build_newborn_patient(_mother(7), _BORN, "M", snapshot_date=_BORN + timedelta(days=60), country="JP")
    assert baby.name is not None
    entry = _sample_newborn_given(baby.patient_id, "M", "JP")
    assert baby.name.given_name == entry["kanji"]
    assert baby.name.phonetic == f"サトウ {entry['kana']}"
